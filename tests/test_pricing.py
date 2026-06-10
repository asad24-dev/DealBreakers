"""Offline tests for the deterministic pricing engine (Phase 7A)."""

from dealbreakers.negotiation.pricing import (
    Aggressiveness,
    estimate_markup,
    generate_counter_markup,
    generate_luxury_counter_markup,
)
from dealbreakers.state.buyer_state import BuyerState


# --- estimate_markup profiles ---


def test_trust_sensitive_profile() -> None:
    state = BuyerState(trust_sensitivity=0.8)
    assert estimate_markup(state, Aggressiveness.SAFE) == 5.0
    assert estimate_markup(state, Aggressiveness.BALANCED) == 8.0
    assert estimate_markup(state, Aggressiveness.AGGRESSIVE) == 10.0


def test_price_sensitive_profile() -> None:
    state = BuyerState(price_sensitivity=0.7)
    assert estimate_markup(state, Aggressiveness.SAFE) == 6.0
    assert estimate_markup(state, Aggressiveness.BALANCED) == 8.0
    assert estimate_markup(state, Aggressiveness.AGGRESSIVE) == 10.0


def test_luxury_profile() -> None:
    state = BuyerState(luxury_preference=0.9)
    assert estimate_markup(state, Aggressiveness.SAFE) == 18.0
    assert estimate_markup(state, Aggressiveness.BALANCED) == 25.0
    assert estimate_markup(state, Aggressiveness.AGGRESSIVE) == 35.0


def test_known_affordable_no_objections_profile() -> None:
    state = BuyerState(known_affordable_total=1056.24)
    assert estimate_markup(state, Aggressiveness.SAFE) == 15.0
    assert estimate_markup(state, Aggressiveness.BALANCED) == 25.0
    assert estimate_markup(state, Aggressiveness.AGGRESSIVE) == 35.0


def test_default_profile() -> None:
    state = BuyerState()
    assert estimate_markup(state, Aggressiveness.SAFE) == 10.0
    assert estimate_markup(state, Aggressiveness.BALANCED) == 12.0
    assert estimate_markup(state, Aggressiveness.AGGRESSIVE) == 15.0


def test_trust_beats_luxury_priority() -> None:
    state = BuyerState(trust_sensitivity=0.8, luxury_preference=0.9)
    assert estimate_markup(state, Aggressiveness.AGGRESSIVE) == 10.0


def test_objections_disable_affordable_profile() -> None:
    state = BuyerState(known_affordable_total=1000.0, objections=["price objection"])
    assert estimate_markup(state, Aggressiveness.SAFE) == 10.0  # falls to default


# --- generate_counter_markup ladder ---


def test_counter_ladder_steps() -> None:
    state = BuyerState()
    assert generate_counter_markup(40.0, state) == 35.0
    assert generate_counter_markup(35.0, state) == 30.0
    assert generate_counter_markup(30.0, state) == 25.0
    assert generate_counter_markup(25.0, state) == 20.0
    assert generate_counter_markup(20.0, state) == 15.0
    assert generate_counter_markup(15.0, state) == 10.0


def test_counter_never_increases() -> None:
    state = BuyerState()
    for current in (40.0, 27.0, 13.0, 6.0, 1.0):
        assert generate_counter_markup(current, state) < current


def test_counter_never_below_zero() -> None:
    state = BuyerState()
    assert generate_counter_markup(3.0, state) == 0.0
    assert generate_counter_markup(0.0, state) == 0.0
    assert generate_counter_markup(-5.0, state) == 0.0


def test_counter_off_ladder_values_snap_to_next_rung_down() -> None:
    state = BuyerState()
    assert generate_counter_markup(37.0, state) == 35.0
    assert generate_counter_markup(12.0, state) == 10.0
    assert generate_counter_markup(8.0, state) == 5.0


def test_counter_hypersensitive_buyer_concedes_two_rungs() -> None:
    state = BuyerState(price_sensitivity=0.9)
    assert generate_counter_markup(40.0, state) == 30.0
    assert generate_counter_markup(15.0, state) == 5.0


def test_counter_is_deterministic() -> None:
    state = BuyerState(price_sensitivity=0.5)
    results = {generate_counter_markup(30.0, state) for _ in range(5)}
    assert results == {25.0}


def test_luxury_counter_ladder() -> None:
    state = BuyerState(luxury_preference=1.0, last_offer_total=5000.0)
    assert generate_luxury_counter_markup(30.0, state) == 18.0
    assert generate_luxury_counter_markup(25.0, state) == 18.0
    assert generate_luxury_counter_markup(20.0, state) == 12.0
    assert generate_luxury_counter_markup(18.0, state) == 12.0
    assert generate_luxury_counter_markup(12.0, state) == 8.0


def test_total_based_counter_preserves_higher_markup_with_car_cost() -> None:
    from dealbreakers.negotiation.pricing import generate_total_based_counter_markup

    # Holiday 4704 + car 220 = 4924 cost; quoted total 6648 at ~35%
    result = generate_total_based_counter_markup(
        35.0,
        cost=4924.0,
        last_quoted_total=6648.0,
    )
    assert 24.0 <= result < 35.0


def test_cap_luxury_opening_markup() -> None:
    from dealbreakers.negotiation.pricing import cap_luxury_opening_markup

    state = BuyerState(luxury_preference=1.0)
    assert cap_luxury_opening_markup(35.0, state) == 25.0
    state.last_offer_total = 5000.0
    assert cap_luxury_opening_markup(35.0, state) == 35.0
