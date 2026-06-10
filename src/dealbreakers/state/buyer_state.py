"""Deterministic buyer state, updated from analyses, offers, and turn responses.

Key distinction this model enforces:
- stated_budget_max     — ONLY from explicit buyer budget language
- known_affordable_total — proven by an accepted offer (a floor, not a ceiling)
- rejected_total         — proven too expensive by a price objection
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from dealbreakers.analysis.models import ConversationAnalysis
from dealbreakers.models.match import Quote, TurnResponse
from dealbreakers.models.offer import Offer

# A "stated" budget within this relative distance of a price we quoted is
# treated as an echo of our own offer, not a genuine buyer-stated budget.
PRICE_ECHO_TOLERANCE = 0.10

_PRICE_OBJECTION_PHRASES = (
    "too expensive",
    "over budget",
    "over my budget",
    "can't afford",
    "cannot afford",
    "too much",
    "too pricey",
    "too steep",
    "out of my range",
    "out of our range",
    "cheaper",
    "lower the price",
    "bring the price down",
)

_TRUST_OBJECTION_PHRASES = (
    "rip me off",
    "ripped off",
    "rip-off",
    "hidden fees",
    "hidden charges",
    "be honest",
    "fair price",
    "is this legit",
    "scam",
    "don't trust",
    "do not trust",
    "trust you",
    "prove it",
)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _merge_unique(existing: list[str], incoming: list[str]) -> list[str]:
    """Merge preserving order; case-insensitive de-duplication."""
    seen = {item.lower() for item in existing}
    merged = list(existing)
    for item in incoming:
        if item.lower() not in seen:
            merged.append(item)
            seen.add(item.lower())
    return merged


def detect_price_objection(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _PRICE_OBJECTION_PHRASES)


def detect_trust_objection(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _TRUST_OBJECTION_PHRASES)


def detect_shorter_stay_acceptance(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in (
            "yes",
            "i'll consider",
            "ill consider",
            "open to",
            "if the quality",
            "if quality",
            "shorter stay",
            "7-night",
            "7 night",
            "that works",
            "go ahead",
        )
    )


def detect_shorter_stay_rejection(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in (
            "no",
            "two weeks",
            "2 weeks",
            "14 night",
            "14-night",
            "fortnight",
            "must be 14",
            "full two weeks",
        )
    )


def extract_desired_nights(text: str) -> int | None:
    """Parse duration from buyer language. 'two weeks' => 14, 'fortnight' => 14."""
    lowered = text.lower()
    if "ten nights" in lowered or "10 nights" in lowered or "10-night" in lowered:
        return 10
    if "fortnight" in lowered or "two weeks" in lowered or "2 weeks" in lowered:
        return 14
    if "three weeks" in lowered or "3 weeks" in lowered:
        return 21
    if re.search(r"\ba week\b", lowered) or "one week" in lowered or "1 week" in lowered:
        return 7
    match = re.search(r"\b(\d+)\s*(?:nights?|days?)\b", lowered)
    if match:
        value = int(match.group(1))
        return value if value > 0 else None
    return None


@dataclass
class BuyerState:
    trip_type: str | None = None

    destinations: list[str] = field(default_factory=list)
    must_haves: list[str] = field(default_factory=list)
    nice_to_haves: list[str] = field(default_factory=list)

    stated_budget_min: float | None = None
    stated_budget_max: float | None = None

    known_affordable_total: float | None = None
    rejected_total: float | None = None

    price_sensitivity: float = 0.0
    trust_sensitivity: float = 0.0
    luxury_preference: float = 0.0

    objections: list[str] = field(default_factory=list)
    confidence: float = 0.0

    desired_nights: int | None = None

    last_offer_total: float | None = None
    last_offer_cost: float | None = None
    last_markup_pct: float | None = None
    accepted: bool = False
    walked: bool = False

    # Every price the buyer has seen from us (costs and quoted totals);
    # used to filter analyzer "budgets" that merely echo our own offers.
    seen_offer_prices: list[float] = field(default_factory=list)

    # --- serialization ---

    def to_dict(self) -> dict[str, Any]:
        return {
            "trip_type": self.trip_type,
            "destinations": list(self.destinations),
            "must_haves": list(self.must_haves),
            "nice_to_haves": list(self.nice_to_haves),
            "stated_budget_min": self.stated_budget_min,
            "stated_budget_max": self.stated_budget_max,
            "known_affordable_total": self.known_affordable_total,
            "rejected_total": self.rejected_total,
            "price_sensitivity": self.price_sensitivity,
            "trust_sensitivity": self.trust_sensitivity,
            "luxury_preference": self.luxury_preference,
            "objections": list(self.objections),
            "confidence": self.confidence,
            "desired_nights": self.desired_nights,
            "last_offer_total": self.last_offer_total,
            "last_offer_cost": self.last_offer_cost,
            "last_markup_pct": self.last_markup_pct,
            "accepted": self.accepted,
            "walked": self.walked,
            "seen_offer_prices": list(self.seen_offer_prices),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BuyerState":
        state = cls()
        for key in state.to_dict():
            if key in data:
                setattr(state, key, data[key])
        state.price_sensitivity = _clamp01(float(state.price_sensitivity))
        state.trust_sensitivity = _clamp01(float(state.trust_sensitivity))
        state.luxury_preference = _clamp01(float(state.luxury_preference))
        state.confidence = _clamp01(float(state.confidence))
        return state

    # --- updates ---

    def update_from_analysis(self, analysis: ConversationAnalysis) -> None:
        if analysis.trip_type and self.trip_type is None:
            self.trip_type = analysis.trip_type

        self.destinations = _merge_unique(self.destinations, analysis.destinations)
        self.must_haves = _merge_unique(self.must_haves, analysis.must_haves)
        self.nice_to_haves = _merge_unique(self.nice_to_haves, analysis.nice_to_haves)
        self.objections = _merge_unique(self.objections, analysis.objections)

        # Rule 5 + rule 1: stated budgets only from genuine buyer language —
        # values that echo our own offer prices are NOT stated budgets.
        if analysis.budget_min is not None and not self._is_offer_echo(analysis.budget_min):
            self.stated_budget_min = analysis.budget_min
        if analysis.budget_max is not None and not self._is_offer_echo(analysis.budget_max):
            self.stated_budget_max = analysis.budget_max

        # Sensitivities only ratchet upward (monotonic evidence accumulation).
        self.price_sensitivity = _clamp01(max(self.price_sensitivity, analysis.price_sensitivity))
        self.trust_sensitivity = _clamp01(max(self.trust_sensitivity, analysis.trust_sensitivity))
        self.luxury_preference = _clamp01(max(self.luxury_preference, analysis.luxury_preference))

        self.confidence = _clamp01(max(self.confidence, analysis.confidence))

        if analysis.desired_nights is not None:
            if self.desired_nights is None or analysis.desired_nights > self.desired_nights:
                self.desired_nights = analysis.desired_nights

    def update_from_message(self, text: str) -> None:
        nights = extract_desired_nights(text)
        if nights is not None:
            if self.desired_nights is None or nights > self.desired_nights:
                self.desired_nights = nights

    def update_from_offer(self, quote_or_offer: Quote | Offer | dict[str, Any]) -> None:
        """Record the prices the buyer has seen. Accepts Quote, Offer, or dicts."""
        cost, total, markup = self._extract_prices(quote_or_offer)

        if cost is not None:
            self._remember_price(cost)
        if markup is not None:
            self.last_markup_pct = markup
        if total is None and cost is not None and markup is not None:
            total = round(cost * (1 + markup / 100), 2)
        if cost is not None:
            self.last_offer_cost = cost
        if total is not None:
            self._remember_price(total)
            self.last_offer_total = total

    def update_from_turn_response(self, turn_response: TurnResponse | dict[str, Any]) -> None:
        if isinstance(turn_response, TurnResponse):
            text = turn_response.buyer.text
            action = turn_response.buyer.action.value
            quote = turn_response.quote
        else:
            text = turn_response.get("buyer_text") or ""
            action = turn_response.get("buyer_action") or "continue"
            quote = turn_response.get("quote")

        if quote is not None:
            self.update_from_offer(quote)

        self.update_from_message(text)

        if detect_price_objection(text):
            if self.last_offer_total is not None:
                self.rejected_total = (
                    self.last_offer_total
                    if self.rejected_total is None
                    else min(self.rejected_total, self.last_offer_total)
                )
            self.price_sensitivity = _clamp01(max(self.price_sensitivity + 0.2, 0.7))
            self.objections = _merge_unique(self.objections, ["price objection"])
            self._bump_confidence()

        if detect_trust_objection(text):
            self.trust_sensitivity = _clamp01(max(self.trust_sensitivity + 0.2, 0.7))
            self.objections = _merge_unique(self.objections, ["trust objection"])
            self._bump_confidence()

        if action == "accept":
            self.accepted = True
            if self.last_offer_total is not None:
                self.known_affordable_total = max(
                    self.known_affordable_total or 0.0, self.last_offer_total
                )
            self._bump_confidence()
        elif action == "walk":
            self.walked = True
            self._bump_confidence()

    # --- internals ---

    def _extract_prices(
        self, quote_or_offer: Quote | Offer | dict[str, Any]
    ) -> tuple[float | None, float | None, float | None]:
        """Return (cost, total, markup_pct) from any supported shape."""
        if isinstance(quote_or_offer, Quote):
            return quote_or_offer.cost, quote_or_offer.total, quote_or_offer.markup_pct

        if isinstance(quote_or_offer, Offer):
            cost = 0.0
            if quote_or_offer.holiday:
                cost += quote_or_offer.holiday.price_total
            if quote_or_offer.tour:
                cost += quote_or_offer.tour.price_total
            if quote_or_offer.car:
                cost += quote_or_offer.car.price_total
            return (cost or None), None, quote_or_offer.markup_pct

        data = quote_or_offer
        # Quote dict — API camelCase or our snake_case logs.
        if "total" in data:
            markup = data.get("markupPct", data.get("markup_pct"))
            return data.get("cost"), data.get("total"), markup
        # Offer dict (API shape).
        cost = 0.0
        for product in ("holiday", "tour", "car"):
            part = data.get(product)
            if isinstance(part, dict) and isinstance(part.get("priceTotal"), (int, float)):
                cost += part["priceTotal"]
        markup = data.get("markupPct", data.get("markup_pct"))
        return (cost or None), None, markup

    def _is_offer_echo(self, value: float) -> bool:
        return any(
            abs(value - price) <= PRICE_ECHO_TOLERANCE * price
            for price in self.seen_offer_prices
            if price > 0
        )

    def _remember_price(self, price: float) -> None:
        if price not in self.seen_offer_prices:
            self.seen_offer_prices.append(price)

    def _bump_confidence(self) -> None:
        self.confidence = _clamp01(self.confidence + 0.05)


# --- markup heuristics ---


def estimate_safe_markup(state: BuyerState) -> float:
    if state.trust_sensitivity >= 0.7:
        return 5.0
    if state.price_sensitivity >= 0.7:
        return 6.0
    if state.luxury_preference >= 0.7:
        return 18.0
    if state.known_affordable_total is not None and not state.objections:
        return 15.0
    return 10.0


def estimate_aggressive_markup(state: BuyerState) -> float:
    if state.trust_sensitivity >= 0.7:
        return 8.0
    if state.price_sensitivity >= 0.7:
        return 10.0
    if state.luxury_preference >= 0.7:
        return 35.0
    if state.known_affordable_total is not None and not state.objections:
        return 25.0
    return 15.0
