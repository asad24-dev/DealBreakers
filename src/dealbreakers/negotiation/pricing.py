"""Deterministic pricing engine: markup estimation and counteroffer ladder (Phase 7A).

No LLM involvement — every number here is a pure function of BuyerState.
"""

from __future__ import annotations

from enum import Enum

from dealbreakers.state.buyer_state import BuyerState


class Aggressiveness(Enum):
    SAFE = "safe"
    BALANCED = "balanced"
    AGGRESSIVE = "aggressive"


# (safe, balanced, aggressive) markup percentages per buyer profile.
# Priority order mirrors Phase 4 estimators: trust > price > luxury > proven-affordable > default.
_TRUST_SENSITIVE = (5.0, 8.0, 10.0)
_PRICE_SENSITIVE = (6.0, 8.0, 10.0)
_LUXURY = (18.0, 25.0, 35.0)
_AFFORDABLE_NO_OBJECTIONS = (15.0, 25.0, 35.0)
_DEFAULT = (10.0, 12.0, 15.0)
_CITY_BREAK = (10.0, 12.0, 15.0)

# Counteroffer concession ladder. Always step DOWN to the next rung below
# the current markup; never increase, never go below 0.
COUNTER_LADDER = (35.0, 30.0, 25.0, 20.0, 15.0, 10.0, 5.0, 0.0)


def _is_city_break_state(state: BuyerState) -> bool:
    text = " ".join([state.trip_type or "", *state.destinations, *state.must_haves]).lower()
    return state.trip_type == "city_break" or any(
        token in text for token in ("city break", "city_break", "berlin", "stockholm", "wifi", "gym")
    )


def _profile_row(state: BuyerState) -> tuple[float, float, float]:
    if _is_city_break_state(state):
        return _CITY_BREAK
    if state.trust_sensitivity >= 0.7:
        return _TRUST_SENSITIVE
    if state.price_sensitivity >= 0.7:
        return _PRICE_SENSITIVE
    if state.luxury_preference >= 0.7:
        return _LUXURY
    if state.known_affordable_total is not None and not state.objections:
        return _AFFORDABLE_NO_OBJECTIONS
    return _DEFAULT


def estimate_markup(state: BuyerState, aggressiveness: Aggressiveness) -> float:
    """Recommended markup percentage for the buyer profile at the given posture."""
    safe, balanced, aggressive = _profile_row(state)
    if aggressiveness is Aggressiveness.SAFE:
        return safe
    if aggressiveness is Aggressiveness.BALANCED:
        return balanced
    return aggressive


def estimate_markup_for_persona(
    state: BuyerState,
    walk_risk: float,
    persona_id: str | None = None,
) -> float:
    """Persona profile markup when persona_id is known; otherwise state-based estimate."""
    if persona_id:
        from dealbreakers.personas.markup_profiles import select_persona_markup

        return select_persona_markup(persona_id, walk_risk)
    aggressiveness = (
        Aggressiveness.SAFE
        if walk_risk > 0.7
        else Aggressiveness.AGGRESSIVE
        if walk_risk < 0.3
        else Aggressiveness.BALANCED
    )
    return estimate_markup(state, aggressiveness)


def should_use_luxury_counter(state: BuyerState) -> bool:
    return state.luxury_preference >= 0.8 and (state.last_offer_total or 0) > 3000


def cap_luxury_opening_markup(markup: float, state: BuyerState) -> float:
    """First luxury offer: anchor lower to preserve accepted markup on counters."""
    if state.luxury_preference >= 0.8 and state.last_offer_total is None:
        return min(markup, 25.0)
    return markup


def cap_city_break_opening_markup(markup: float, state: BuyerState) -> float:
    """City-break opening cap — do not exceed 18% until sweep proves higher."""
    if _is_city_break_state(state) and state.last_offer_total is None:
        return min(markup, 18.0)
    return markup


def should_use_total_based_counter(state: BuyerState) -> bool:
    return (
        should_use_luxury_counter(state)
        and state.last_offer_total is not None
        and state.last_offer_cost is not None
        and state.last_offer_cost > 0
        and state.last_markup_pct is not None
    )


def generate_total_based_counter_markup(
    current_markup: float,
    cost: float,
    last_quoted_total: float,
    *,
    feels_overcharged: bool = False,
) -> float:
    """Concede on quoted total (ported from deal-room-agent MarkupLadder)."""
    if cost <= 0 or last_quoted_total <= 0:
        return max(0.0, current_markup - 4.0)
    multiplier = 0.85 if feels_overcharged else 0.92
    cap_total = last_quoted_total * multiplier
    new_markup = (cap_total / cost - 1.0) * 100.0
    new_markup = max(2.0, min(current_markup - 0.01, new_markup))
    return round(new_markup, 2)


def generate_luxury_counter_markup(current_markup: float, state: BuyerState) -> float:
    """Aggressive luxury concession ladder — avoids slow Bob-style steps."""
    if current_markup <= 0:
        return 0.0
    if current_markup > 30:
        return 18.0
    if current_markup >= 25:
        return 18.0
    if current_markup >= 20:
        return 12.0
    if current_markup >= 18:
        return 12.0
    if current_markup >= 12:
        return 8.0
    return 0.0


def generate_counter_markup(current_markup: float, state: BuyerState) -> float:
    """Next markup after a price objection: one ladder rung down.

    Guarantees: result < current_markup (unless already 0) and result >= 0.
    Price-hypersensitive buyers (>= 0.9) concede two rungs to protect the close.
    """
    if current_markup <= 0:
        return 0.0

    if should_use_luxury_counter(state):
        return generate_luxury_counter_markup(current_markup, state)

    rungs_below = [rung for rung in COUNTER_LADDER if rung < current_markup]
    if not rungs_below:
        return 0.0

    steps = 2 if state.price_sensitivity >= 0.9 else 1
    index = min(steps, len(rungs_below)) - 1
    return rungs_below[index]
