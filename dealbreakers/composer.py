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
            f"I found a strong live option: {candidate.name}. It looks like a good fit because it {fit_bits}."
            f"{budget_line} I can offer it with a {markup_pct:.0f}% service margin and the real listing attached."
        )

    def no_listing_found(self, profile: BuyerProfile) -> str:
        if not profile.destination:
            return "I can search live deals, but I need a destination or region first. Where should I focus?"
        return (
            f"I am not seeing a clean live match for {profile.destination} with the details I have. "
            "Can you share your dates or one flexible alternative destination so I can widen the search?"
        )

    def concede(self, scored: ScoredCandidate, markup_pct: float) -> str:
        return (
            f"I hear you on price. I can sharpen this to a {markup_pct:.0f}% margin on "
            f"{scored.candidate.name}; that keeps the same real listing but gives you a better total."
        )
