from __future__ import annotations

from dealbreakers.catalog import ScoredCandidate
from dealbreakers.profile import BuyerProfile


class MessageComposer:
    def ask(self, question: str) -> str:
        return question

    def present_offer(self, profile: BuyerProfile, scored: ScoredCandidate, markup_pct: float) -> str:
        candidate = scored.candidate
        fit_bits = ", ".join(scored.reasons[:3]) or "matches what you asked for"
        budget_line = ""
        if profile.budget:
            budget_line = f" It keeps the base package around GBP {candidate.price_total:,.0f} before my service fee."

        return (
            f"{candidate.name} is a strong live option — {fit_bits}."
            f"{budget_line} Total around GBP {candidate.price_total * (1 + markup_pct / 100):,.0f}; listing attached."
        )

    def no_listing_found(self, profile: BuyerProfile) -> str:
        if not profile.destination:
            return "I can search live deals, but I need a destination or region first. Where should I focus?"
        return (
            f"I am not seeing a clean live match for {profile.destination} with the details I have. "
            "Can you share your dates or one flexible alternative destination so I can widen the search?"
        )

    def concede(self, scored: ScoredCandidate, markup_pct: float) -> str:
        total = scored.candidate.price_total * (1 + markup_pct / 100)
        return (
            f"Same {scored.candidate.name}, better number: GBP {total:,.0f}. "
            "That's me stretching on my side — worth locking in."
        )
