"""Deterministic negotiation policy engine (Phase 7A).

decide_action() chooses exactly one NegotiationAction per turn with an
inspectable reasoning string. No LLM involvement — business decisions
stay deterministic and testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dealbreakers.analysis.models import ConversationAnalysis
from dealbreakers.negotiation.actions import NegotiationAction
from dealbreakers.negotiation.pricing import (
    Aggressiveness,
    estimate_markup,
    generate_counter_markup,
    generate_luxury_counter_markup,
    generate_total_based_counter_markup,
    should_use_luxury_counter,
    should_use_total_based_counter,
)
from dealbreakers.negotiation.strategist import feels_overcharged
from dealbreakers.state.buyer_state import (
    BuyerState,
    detect_price_objection,
    detect_trust_objection,
)

# Buyer phrases signalling acceptance intent → CLOSE.
_CLOSE_PHRASES = (
    "book it",
    "let's do it",
    "lets do it",
    "sounds good",
    "i'll take it",
    "ill take it",
    "i will take it",
    "take it",
    "consider it booked",
    "make it mine",
    "i'm in",
    "sign me up",
)

# Buyer words signalling price pushback → COUNTER (only after an offer).
_COUNTER_WORDS = (
    "expensive",
    "budget",
    "cheaper",
    "cost",
    "price",
    "fee",
)

# Positive-sentiment words that reduce walk risk.
_POSITIVE_WORDS = (
    "sounds good",
    "love",
    "great",
    "wonderful",
    "perfect",
    "lovely",
    "beautiful",
    "happy",
    "delighted",
)


@dataclass
class PolicyDecision:
    action: NegotiationAction
    confidence: float
    reasoning: str
    target_markup: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "target_markup": self.target_markup,
        }


def _wants_to_close(text: str) -> bool:
    lowered = text.lower()
    return any(phrase in lowered for phrase in _CLOSE_PHRASES)


def _pushes_on_price(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in _COUNTER_WORDS)


def decide_action(
    buyer_state: BuyerState,
    conversation_analysis: ConversationAnalysis,
    latest_buyer_message: str,
    *,
    inventory_ready: bool = False,
) -> PolicyDecision:
    """Choose the next action. Deterministic: same inputs → same decision.

    Priority: CLOSE > COUNTER > DISCOVER > REFINE > SEARCH/OFFER.
    `inventory_ready` tells the policy whether offerable candidates are already
    in hand (OFFER) or a silent search is still needed first (SEARCH).
    """
    # Merge state with the latest analysis (state may lag a fresh analysis).
    trip_type = buyer_state.trip_type or conversation_analysis.trip_type
    destinations = buyer_state.destinations or conversation_analysis.destinations
    must_haves = buyer_state.must_haves or conversation_analysis.must_haves
    offer_sent = buyer_state.last_offer_total is not None

    # 1. CLOSE — buyer signals acceptance of an offer we actually sent.
    if offer_sent and _wants_to_close(latest_buyer_message):
        return PolicyDecision(
            action=NegotiationAction.CLOSE,
            confidence=0.95,
            reasoning="Buyer used acceptance language after an offer was presented.",
            target_markup=buyer_state.last_markup_pct,
        )

    # 2. COUNTER — buyer pushed back on price after an offer.
    if offer_sent and _pushes_on_price(latest_buyer_message):
        current = (
            buyer_state.last_markup_pct
            if buyer_state.last_markup_pct is not None
            else estimate_markup(buyer_state, Aggressiveness.BALANCED)
        )
        if should_use_total_based_counter(buyer_state):
            target = generate_total_based_counter_markup(
                current,
                buyer_state.last_offer_cost or 0.0,
                buyer_state.last_offer_total or 0.0,
                feels_overcharged=feels_overcharged(latest_buyer_message),
            )
            reasoning = "Luxury buyer price objection; total-based concession."
        elif should_use_luxury_counter(buyer_state):
            target = generate_luxury_counter_markup(current, buyer_state)
            reasoning = "Luxury buyer price objection on high-cost offer; aggressive concession."
        else:
            target = generate_counter_markup(current, buyer_state)
            reasoning = "Buyer raised a price concern after our offer; concede one rung."
        return PolicyDecision(
            action=NegotiationAction.COUNTER,
            confidence=0.85,
            reasoning=reasoning,
            target_markup=target,
        )

    # 3. DISCOVER — critical info missing.
    if trip_type is None or not destinations:
        missing = []
        if trip_type is None:
            missing.append("trip type")
        if not destinations:
            missing.append("destination")
        nothing_known = trip_type is None and not destinations and not must_haves
        return PolicyDecision(
            action=NegotiationAction.DISCOVER,
            confidence=0.9 if nothing_known else 0.75,
            reasoning=f"Missing critical info: {', '.join(missing)}.",
            target_markup=None,
        )

    # 4. REFINE — core info known but constraints unclear.
    if not must_haves:
        return PolicyDecision(
            action=NegotiationAction.REFINE,
            confidence=0.7,
            reasoning="Trip type and destination known but must-haves still unclear.",
            target_markup=None,
        )

    # 5. SEARCH / OFFER — enough information; no offer sent yet.
    if not offer_sent:
        if not inventory_ready:
            return PolicyDecision(
                action=NegotiationAction.SEARCH,
                confidence=0.8,
                reasoning="Enough buyer info; retrieve inventory before offering.",
                target_markup=None,
            )
        return PolicyDecision(
            action=NegotiationAction.OFFER,
            confidence=0.8,
            reasoning="Enough buyer info and candidates in hand; present first offer.",
            target_markup=estimate_markup(buyer_state, Aggressiveness.BALANCED),
        )

    # Fallback: offer sent, no clear accept or price pushback — refine the fit.
    return PolicyDecision(
        action=NegotiationAction.REFINE,
        confidence=0.6,
        reasoning="Offer sent but buyer gave no clear accept or price signal; clarify fit.",
        target_markup=buyer_state.last_markup_pct,
    )


def estimate_walk_risk(buyer_state: BuyerState, latest_buyer_message: str) -> float:
    """Deterministic walk-out risk in [0, 1]."""
    if buyer_state.walked:
        return 1.0

    risk = 0.1
    lowered = latest_buyer_message.lower()

    # --- risk increases ---
    risk += 0.15 * min(len(buyer_state.objections), 3)  # repeated objections
    if detect_trust_objection(latest_buyer_message):
        risk += 0.2
    # Repeated price pushback: an objection now on top of a previously rejected total.
    if detect_price_objection(latest_buyer_message) and buyer_state.rejected_total is not None:
        risk += 0.15

    # --- risk decreases ---
    if "?" in latest_buyer_message:  # engaged, asking follow-ups
        risk -= 0.1
    if any(word in lowered for word in _POSITIVE_WORDS):
        risk -= 0.1
    if buyer_state.known_affordable_total is not None:  # has accepted prices before
        risk -= 0.15

    return max(0.0, min(1.0, risk))
