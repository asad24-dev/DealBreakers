from __future__ import annotations

from dataclasses import dataclass

from dealbreakers.profile import BuyerProfile


@dataclass(frozen=True)
class TurnDecision:
    action: str  # ask | search | offer | concede
    reason: str
    markup_pct: float
    question: str = ""


class NegotiationPolicy:
    def decide(self, profile: BuyerProfile, *, round_number: int, has_candidate_offer: bool) -> TurnDecision:
        missing = profile.missing_critical_fields()
        if missing and round_number <= 2:
            return TurnDecision(
                action="ask",
                reason=f"Need {', '.join(missing[:3])} before searching confidently.",
                markup_pct=self.markup_for(profile, round_number),
                question=self.qualifying_question(profile, missing),
            )

        if not has_candidate_offer:
            return TurnDecision(
                action="search",
                reason="Enough signal to search live MCP listings.",
                markup_pct=self.markup_for(profile, round_number),
            )

        if "price" in profile.objections or round_number >= 5:
            return TurnDecision(
                action="concede",
                reason="Buyer is price-resistant or rounds are running down.",
                markup_pct=self.concession_markup(profile, round_number),
            )

        return TurnDecision(
            action="offer",
            reason="Candidate can be presented while preserving margin.",
            markup_pct=self.markup_for(profile, round_number),
        )

    def markup_for(self, profile: BuyerProfile, round_number: int) -> float:
        base = 16.0
        if profile.luxury_weight >= 0.5:
            base += 5.0
        if profile.price_sensitivity >= 0.5:
            base -= 5.0
        if round_number >= 4:
            base -= 3.0
        return max(6.0, base)

    def concession_markup(self, profile: BuyerProfile, round_number: int) -> float:
        markup = self.markup_for(profile, round_number) - 5.0
        if round_number >= 8:
            markup = min(markup, 4.0)
        return max(2.0, markup)

    def qualifying_question(self, profile: BuyerProfile, missing: list[str]) -> str:
        if "trip style" in missing:
            return (
                "To make sure I pitch the right thing, are you looking for a hotel holiday, "
                "a city break, or a guided multi-day tour?"
            )
        if "budget" in missing and "destination" in missing:
            return "What destination or region are you leaning toward, and what total budget should I stay close to?"
        if "budget" in missing:
            return "What total budget would make this feel like a yes if the trip matches your must-haves?"
        if "party size" in missing:
            return "How many people am I pricing this for?"
        if "children ages" in missing:
            return "For accurate live package pricing, are any of the children under 2, or are they all aged 2-17?"
        if "duration" in missing:
            return "How many nights should I build the trip around?"
        return "What is the one must-have that would make this trip an easy yes?"
