from __future__ import annotations

"""Internal evaluator agents. Each one is a single structured LLM call with a
deterministic fallback, so the negotiation loop never blocks on a model error."""

import typing
from dataclasses import dataclass

from pydantic import BaseModel, Field

from dealbreakers import llm
from dealbreakers.catalog import ScoredCandidate
from dealbreakers.models import Amenity
from dealbreakers.profile import BuyerProfile

CANONICAL_AMENITIES = list(typing.get_args(Amenity))


# ---------------------------------------------------------------- profile agent


class ProfileExtraction(BaseModel):
    """What the buyer has revealed so far. Leave fields null when not stated."""

    product_preference: str | None = Field(
        default=None, description="One of: holiday, tour, city_break, unknown"
    )
    destination_country: str | None = Field(
        default=None, description="Country name in English, e.g. 'Spain'"
    )
    destination_place: str | None = Field(
        default=None, description="More specific place if mentioned, e.g. 'Majorca'"
    )
    destination_flexible: bool = Field(
        default=False,
        description="True if the buyer says they are open/flexible about where to go",
    )
    adults: int | None = None
    children: int | None = Field(default=None, description="Children aged 2-17")
    infants: int | None = Field(default=None, description="Children under 2")
    children_ages_unclear: bool = Field(
        default=False, description="True if kids are mentioned but under-2 status is unknown"
    )
    nights: int | None = None
    departure_months: str | None = Field(
        default=None, description="Comma-separated month numbers, e.g. '7' or '6,7,8'"
    )
    budget_total: float | None = Field(
        default=None, description="Total GBP budget for the whole party if stated or strongly implied"
    )
    wants_car: bool | None = None
    car_preference: str | None = Field(
        default=None, description="If they want a car: 'premium', 'automatic', 'suv', 'small', etc."
    )
    must_have_amenities: list[str] = Field(
        default_factory=list,
        description=f"Only canonical words from: {', '.join(CANONICAL_AMENITIES)}",
    )
    luxury_level: float = Field(default=0.0, ge=0, le=1, description="0 = budget, 1 = ultra luxury")
    price_sensitivity: float = Field(default=0.0, ge=0, le=1)


class BuyerRead(BaseModel):
    """Psychological read of the buyer's LAST message only."""

    mood: str = Field(default="neutral", description="e.g. excited, hesitant, annoyed, suspicious")
    tone: str = Field(default="casual", description="How the buyer writes: formal, casual, blunt, chatty")
    resistance: float = Field(default=0.3, ge=0, le=1, description="Price pushback level right now")
    feels_overcharged: bool = Field(
        default=False, description="True if buyer implies we are greedy / robbing them"
    )
    close_signal: float = Field(
        default=0.0, ge=0, le=1, description="How close the buyer sounds to accepting"
    )
    impatience: float = Field(
        default=0.2,
        ge=0,
        le=1,
        description="How much the buyer wants to wrap up fast (grumpy, terse, 'just show me something')",
    )
    main_objection: str = Field(default="", description="price, fit, trust, or empty")


class ProfileEvaluator:
    def extract(self, scenario: str, transcript: str) -> ProfileExtraction | None:
        prompt = (
            "You are a buyer-intake analyst for a travel seller in a negotiation game.\n"
            f"Scenario brief: {scenario}\n"
            "Conversation so far (Buyer/Seller turns):\n"
            f"{transcript}\n\n"
            "Extract ONLY what the buyer actually said or strongly implied. Do not guess "
            "budgets or destinations that were never mentioned. budget_total is for the whole "
            "party in GBP. product_preference is 'tour' only if they want a guided multi-day "
            "tour; 'city_break' for city trips; 'holiday' for beach/resort/lakes hotel stays."
        )
        return llm.structured(prompt, ProfileExtraction)

    def read_buyer(self, last_buyer_message: str, quote_context: str) -> BuyerRead | None:
        prompt = (
            "You are reading the buyer's psychology in a price negotiation.\n"
            f"Buyer's last message: {last_buyer_message}\n"
            f"Context: {quote_context}\n"
            "Assess their mood, writing tone, price resistance, whether they feel overcharged, "
            "how close they sound to accepting, and how impatient they are to wrap up "
            "(terse or grumpy buyers want an offer NOW, not more questions)."
        )
        return llm.structured(prompt, BuyerRead)


def merge_extraction(profile: BuyerProfile, extraction: ProfileExtraction | None) -> BuyerProfile:
    if extraction is None:
        return profile
    if extraction.product_preference in {"holiday", "tour", "city_break"}:
        profile.product_preference = extraction.product_preference
    if extraction.destination_country:
        profile.destination = extraction.destination_country
    if extraction.destination_place:
        profile.place = extraction.destination_place
        if not profile.destination:
            profile.destination = extraction.destination_place
    if extraction.destination_flexible:
        profile.destination_flexible = True
    if extraction.adults is not None:
        profile.adults = extraction.adults
    if extraction.children is not None:
        profile.children = extraction.children
    if extraction.infants is not None:
        profile.infants = extraction.infants
        profile.child_ages_unknown = False
    if extraction.children_ages_unclear and extraction.infants is None:
        profile.child_ages_unknown = True
    if profile.adults is not None:
        profile.party_size = profile.adults + (profile.children or 0) + (profile.infants or 0)
    if extraction.nights is not None:
        profile.nights = extraction.nights
    if extraction.departure_months:
        profile.departure_months = extraction.departure_months
    if extraction.budget_total is not None:
        profile.budget = extraction.budget_total
    if extraction.wants_car is not None:
        profile.wants_car = extraction.wants_car
    if extraction.car_preference:
        profile.car_preference = extraction.car_preference
    for amenity in extraction.must_have_amenities:
        if amenity in CANONICAL_AMENITIES:
            profile.must_haves.add(amenity)
    profile.luxury_weight = max(profile.luxury_weight, extraction.luxury_level)
    profile.price_sensitivity = max(profile.price_sensitivity, extraction.price_sensitivity)
    return profile


# -------------------------------------------------------------- shortlist agent


class ShortlistVerdict(BaseModel):
    best_index: int = Field(description="Index of the single best candidate for this buyer")
    ruled_out_indices: list[int] = Field(default_factory=list)
    rationale: str = ""


class ShortlistEvaluator:
    def pick(self, profile: BuyerProfile, shortlist: list[ScoredCandidate]) -> int | None:
        if not shortlist:
            return None
        if len(shortlist) == 1:
            return 0
        lines = []
        for i, scored in enumerate(shortlist):
            c = scored.candidate
            lines.append(
                f"[{i}] {c.name} | {c.location or c.region or c.country} | "
                f"GBP {c.price_total:.0f} total | {c.nights or '?'} nights | "
                f"stars={c.star_rating or '?'} review={c.rating or '?'} | "
                f"amenities: {', '.join(c.amenities[:12]) or 'unknown'}"
            )
        prompt = (
            "Pick the best travel listing for this buyer and rule out poor fits.\n"
            f"Buyer: {profile.scenario_brief}\n"
            f"Wants: {profile.product_preference}, destination={profile.destination or 'flexible'}, "
            f"nights={profile.nights}, party={profile.party_size}, "
            f"budget GBP {profile.budget or 'unknown'} TOTAL (our markup goes on top, so leave headroom), "
            f"must-haves: {', '.join(sorted(profile.must_haves)) or 'none stated'}, "
            f"luxury={profile.luxury_weight:.1f}, price_sensitivity={profile.price_sensitivity:.1f}\n"
            "Candidates:\n" + "\n".join(lines) + "\n"
            "Prefer listings that cover every must-have, fit the budget with 10-20% headroom "
            "below it, and match the quality level the buyer expects. If the budget is unknown "
            "and the buyer is price-sensitive or values 'good value', pick a mid-priced option "
            "with excellent reviews — NOT the most expensive one."
        )
        verdict = llm.structured(prompt, ShortlistVerdict)
        if verdict is None or not (0 <= verdict.best_index < len(shortlist)):
            return None
        return verdict.best_index


# ---------------------------------------------------------------- pricing agent


class PricingAdvice(BaseModel):
    estimated_ceiling_total: float | None = Field(
        default=None, description="Best estimate of the max total GBP the buyer will accept"
    )
    recommended_markup_pct: float = Field(ge=0, le=30)
    rationale: str = ""


@dataclass
class PricingDecision:
    markup_pct: float
    rationale: str
    ceiling_estimate: float | None = None


@dataclass
class MarkupLadder:
    """Deterministic guard rails around the LLM's pricing advice.

    Buyers react to the TOTAL they pay, not our percentage. So concessions are
    enforced on the quoted total: every follow-up quote must be meaningfully
    cheaper than the last when the buyer pushes back. That lets us keep a healthy
    percentage when we pivot to a cheaper base package."""

    last_total: float | None = None

    def clamp(
        self,
        advised: float,
        *,
        round_number: int,
        max_rounds: int,
        read: BuyerRead | None,
        cost: float,
        budget: float | None,
        pivots_available: bool = False,
    ) -> float:
        total = cost * (1 + advised / 100.0)

        if self.last_total is not None:
            # Never quote higher than we already did: it destroys trust.
            cap = self.last_total
            if read is not None:
                if read.feels_overcharged:
                    cap = self.last_total * 0.85
                elif read.main_objection == "price" or read.resistance >= 0.6:
                    cap = self.last_total * 0.92
            total = min(total, cap)

        # Once the buyer objects on price and we know their budget, land inside it.
        if budget and read is not None and (read.main_objection == "price" or read.feels_overcharged):
            total = min(total, budget)

        markup = (total / cost - 1.0) * 100.0 if cost > 0 else advised

        # Endgame: closing beats margin (close=50pts, margin=30pts).
        remaining = max_rounds - round_number

        # While a base-product pivot is still available, don't burn the markup lever
        # to the floor — a pivot delivers the "substantial" drop the buyer wants
        # without giving away margin on the current package.
        if pivots_available and remaining > 3:
            markup = max(markup, 8.0)
            if self.last_total is not None and cost > 0:
                never_higher = (self.last_total / cost - 1.0) * 100.0
                markup = min(markup, max(2.0, never_higher))

        if remaining <= 3:
            markup = min(markup, 6.0)
        if remaining <= 1:
            markup = min(markup, 3.0)

        markup = max(2.0, min(25.0, markup))
        self.last_total = cost * (1 + markup / 100.0)
        return markup


class PricingStrategist:
    def __init__(self) -> None:
        self.ladder = MarkupLadder()

    def decide(
        self,
        profile: BuyerProfile,
        read: BuyerRead | None,
        *,
        cost: float,
        round_number: int,
        max_rounds: int,
        quote_history: str,
        pivots_available: bool = False,
    ) -> PricingDecision:
        advice = llm.structured(self._prompt(profile, read, cost, round_number, quote_history), PricingAdvice)
        if advice is not None:
            advised = advice.recommended_markup_pct
            rationale = advice.rationale
            ceiling = advice.estimated_ceiling_total
        else:
            advised = self._fallback_markup(profile, round_number)
            rationale = "deterministic fallback"
            ceiling = profile.budget
        markup = self.ladder.clamp(
            advised,
            round_number=round_number,
            max_rounds=max_rounds,
            read=read,
            cost=cost,
            budget=profile.budget,
            pivots_available=pivots_available,
        )
        return PricingDecision(markup_pct=markup, rationale=rationale, ceiling_estimate=ceiling)

    def _prompt(
        self,
        profile: BuyerProfile,
        read: BuyerRead | None,
        cost: float,
        round_number: int,
        quote_history: str,
    ) -> str:
        read_text = (
            f"mood={read.mood}, resistance={read.resistance:.1f}, feels_overcharged={read.feels_overcharged}, "
            f"close_signal={read.close_signal:.1f}, objection={read.main_objection or 'none'}"
            if read
            else "no read yet"
        )
        return (
            "You set the markup percentage for a travel seller in a negotiation game.\n"
            "Scoring: closing the deal = 50 pts, margin captured = 30 pts, buyer satisfaction = 20 pts. "
            "A blown deal is catastrophic; squeezing 2 extra points of margin is not worth a walk-away.\n"
            f"Our real cost: GBP {cost:.0f}. Buyer budget: {profile.budget or 'unknown'} GBP total. "
            f"Buyer price sensitivity: {profile.price_sensitivity:.1f}, luxury: {profile.luxury_weight:.1f}.\n"
            f"Buyer read: {read_text}\n"
            f"Round {round_number} of 15. Quote history: {quote_history or 'none yet'}\n"
            "Recommend a markup percent (0-30). Anchor high early when resistance is low; concede "
            "decisively when the buyer pushes back; keep the final total within their ceiling. "
            "Buyers get angry when the total is far above their budget and may accuse us of robbery."
        )

    def _fallback_markup(self, profile: BuyerProfile, round_number: int) -> float:
        base = 15.0
        if profile.luxury_weight >= 0.5:
            base += 4.0
        if profile.price_sensitivity >= 0.5:
            base -= 4.0
        return max(4.0, base - 1.5 * max(0, round_number - 2))


# --------------------------------------------------------------- message agent


class MessageComposerLLM:
    def compose(
        self,
        *,
        intent: str,
        profile: BuyerProfile,
        read: BuyerRead | None,
        candidate_summary: str,
        fallback: str,
        last_buyer_message: str,
    ) -> str:
        tone = read.tone if read else "casual"
        mood = read.mood if read else "neutral"
        prompt = (
            "You write the seller's next message in a travel deal negotiation.\n"
            f"Intent of this turn: {intent}\n"
            f"Buyer's last message: {last_buyer_message}\n"
            f"Buyer tone: {tone}; mood: {mood}; brief: {profile.scenario_brief}\n"
            f"Package details you may reference (do NOT invent anything beyond this): {candidate_summary or 'none'}\n"
            "Rules: 1-3 sentences, mirror the buyer's tone, be warm and confident, reference their "
            "specific must-haves when relevant, never mention markup/cost/margins/percentages, never "
            "claim the trip is booked, never invent amenities or prices, no emojis unless the buyer uses them. "
            "CRITICAL: if package details are 'none', you must NOT describe any specific trip, hotel, tour, "
            "itinerary, city list, duration or price — doing so would be misrepresentation. In that case "
            "just respond to the buyer and ask the single question in the intent. "
            "Never contradict or embellish the listed package details: if the buyer dislikes a listed "
            "feature, acknowledge it honestly instead of inventing claims about exclusivity, quietness, "
            "or anything else not in the details."
        )
        text = llm.freeform(prompt)
        return text or fallback
