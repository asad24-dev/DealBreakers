from dealbreakers.analysis.models import ConversationAnalysis
from dealbreakers.constants import BuyerAction, MatchStatus
from dealbreakers.models.match import BuyerMessage, Quote, TurnResponse
from dealbreakers.state import (
    BuyerState,
    build_buyer_state,
    estimate_aggressive_markup,
    estimate_safe_markup,
)


def make_turn(text: str, action: str = "continue", quote: Quote | None = None) -> TurnResponse:
    return TurnResponse(
        buyer=BuyerMessage(text=text, action=BuyerAction(action)),
        status=MatchStatus.AWAITING_SELLER,
        quote=quote,
    )


# --- Rule 1 + 2: acceptance proves affordability, never a stated budget ---


def test_accept_updates_known_affordable_not_stated_budget() -> None:
    state = BuyerState()
    state.update_from_offer({"holiday": {"priceTotal": 978.0}, "markupPct": 8})
    state.update_from_turn_response(
        make_turn("I'll take it!", "accept", quote=Quote(cost=978, markup_pct=8, total=1056.24))
    )

    assert state.accepted is True
    assert state.known_affordable_total == 1056.24
    assert state.stated_budget_max is None


def test_accept_keeps_highest_affordable_total() -> None:
    state = BuyerState(known_affordable_total=2000.0)
    state.update_from_offer(Quote(cost=900, markup_pct=10, total=990))
    state.update_from_turn_response(make_turn("Deal", "accept"))

    assert state.known_affordable_total == 2000.0


# --- Rule 3: price objections ---


def test_too_expensive_updates_rejected_total_and_price_sensitivity() -> None:
    state = BuyerState()
    state.update_from_offer(Quote(cost=2000, markup_pct=15, total=2300))
    state.update_from_turn_response(make_turn("That's too expensive for us"))

    assert state.rejected_total == 2300
    assert state.price_sensitivity >= 0.7
    assert "price objection" in state.objections


def test_rejected_total_takes_minimum() -> None:
    state = BuyerState(rejected_total=1800.0)
    state.update_from_offer(Quote(cost=2000, markup_pct=15, total=2300))
    state.update_from_turn_response(make_turn("Still over budget I'm afraid"))

    assert state.rejected_total == 1800.0


# --- Rule 4: trust objections ---


def test_trust_objection_updates_trust_sensitivity() -> None:
    state = BuyerState()
    state.update_from_turn_response(make_turn("Don't rip me off, I want a fair price"))

    assert state.trust_sensitivity >= 0.7
    assert "trust objection" in state.objections


# --- Rule 5: stated budgets only from genuine buyer language ---


def test_analysis_budget_echoing_offer_price_is_ignored() -> None:
    state = BuyerState()
    state.update_from_offer({"holiday": {"priceTotal": 978.0}, "markupPct": 8})

    analysis = ConversationAnalysis.from_dict({"budget_max": 978.0, "confidence": 0.8})
    state.update_from_analysis(analysis)

    assert state.stated_budget_max is None


def test_analysis_genuine_budget_is_kept() -> None:
    state = BuyerState()
    state.update_from_offer({"holiday": {"priceTotal": 978.0}, "markupPct": 8})

    analysis = ConversationAnalysis.from_dict({"budget_max": 2500.0, "budget_min": 1500.0})
    state.update_from_analysis(analysis)

    assert state.stated_budget_max == 2500.0
    assert state.stated_budget_min == 1500.0


# --- Rule 6: list merging ---


def test_analysis_lists_merge_without_duplicates_preserving_order() -> None:
    state = BuyerState(must_haves=["pool"], destinations=["Spain"])
    analysis = ConversationAnalysis.from_dict({
        "must_haves": ["Pool", "close to beach"],
        "destinations": ["Greece", "spain"],
    })
    state.update_from_analysis(analysis)

    assert state.must_haves == ["pool", "close to beach"]
    assert state.destinations == ["Spain", "Greece"]


# --- Rule 7: clamping ---


def test_sensitivities_clamp_to_unit_interval() -> None:
    state = BuyerState(price_sensitivity=0.95)
    state.update_from_turn_response(make_turn("way too expensive"))
    assert state.price_sensitivity == 1.0

    rebuilt = BuyerState.from_dict({"trust_sensitivity": 9.0, "confidence": -2.0})
    assert rebuilt.trust_sensitivity == 1.0
    assert rebuilt.confidence == 0.0


# --- Rule 8: monotonic confidence ---


def test_confidence_never_decreases() -> None:
    state = BuyerState(confidence=0.6)
    state.update_from_analysis(ConversationAnalysis.from_dict({"confidence": 0.3}))
    assert state.confidence == 0.6

    state.update_from_turn_response(make_turn("Deal!", "accept"))
    assert state.confidence > 0.6


# --- markup estimators ---


def test_estimate_safe_markup_priority_order() -> None:
    assert estimate_safe_markup(BuyerState(trust_sensitivity=0.8, luxury_preference=0.9)) == 5.0
    assert estimate_safe_markup(BuyerState(price_sensitivity=0.8)) == 6.0
    assert estimate_safe_markup(BuyerState(luxury_preference=0.8)) == 18.0
    assert estimate_safe_markup(BuyerState(known_affordable_total=1000.0)) == 15.0
    assert estimate_safe_markup(BuyerState()) == 10.0


def test_estimate_safe_markup_objections_disable_affordable_boost() -> None:
    state = BuyerState(known_affordable_total=1000.0, objections=["price objection"])
    assert estimate_safe_markup(state) == 10.0


def test_estimate_aggressive_markup_priority_order() -> None:
    assert estimate_aggressive_markup(BuyerState(trust_sensitivity=0.8)) == 8.0
    assert estimate_aggressive_markup(BuyerState(price_sensitivity=0.8)) == 10.0
    assert estimate_aggressive_markup(BuyerState(luxury_preference=0.8)) == 35.0
    assert estimate_aggressive_markup(BuyerState(known_affordable_total=1000.0)) == 25.0
    assert estimate_aggressive_markup(BuyerState()) == 15.0


# --- round trip ---


def test_state_round_trips_through_dict() -> None:
    state = BuyerState(
        trip_type="holiday",
        destinations=["Spain"],
        must_haves=["pool"],
        known_affordable_total=1056.24,
        price_sensitivity=0.3,
        accepted=True,
        seen_offer_prices=[978.0, 1056.24],
    )
    rebuilt = BuyerState.from_dict(state.to_dict())
    assert rebuilt == state


# --- full replay from log records (Bob-shaped) ---


def test_extract_desired_nights_two_weeks() -> None:
    from dealbreakers.state.buyer_state import extract_desired_nights

    assert extract_desired_nights("I want two weeks in the sun") == 14
    assert extract_desired_nights("14 nights minimum") == 14


def test_update_from_message_sets_desired_nights() -> None:
    from dealbreakers.state.buyer_state import BuyerState

    state = BuyerState()
    state.update_from_message("We need a fortnight away")
    assert state.desired_nights == 14


def test_build_buyer_state_from_bob_shaped_records() -> None:
    records = [
        {"record_type": "match_started", "match_id": "m1", "practice": True},
        {"record_type": "buyer_message", "match_id": "m1", "text": "Sunny week please"},
        {"record_type": "seller_message", "match_id": "m1", "round_number": 1,
         "text": "Spain or Greece — pool a must?", "offer": None},
        {"record_type": "turn_response", "match_id": "m1",
         "buyer_text": "Any! And yes a pool is essential.", "buyer_action": "continue",
         "quote": None, "result": None},
        {"record_type": "seller_message", "match_id": "m1", "round_number": 2,
         "text": "Here's the deal",
         "offer": {"holiday": {"priceTotal": 978.0}, "markupPct": 8,
                   "sources": [{"mcp": "travelsupermarket", "url": "https://x", "price": 978.0}]}},
        {"record_type": "turn_response", "match_id": "m1",
         "buyer_text": "I'll take it!", "buyer_action": "accept",
         "quote": {"cost": 978, "markup_pct": 8, "total": 1056.24},
         "result": {"closed": True, "end_reason": "accept", "rounds": 2}},
    ]
    analysis = ConversationAnalysis.from_dict({
        "trip_type": "holiday",
        "destinations": ["Spain", "Greece", "Portugal"],
        "must_haves": ["pool"],
        "budget_max": 978.0,   # analyzer echo of our own price — must be ignored
        "confidence": 0.8,
    })

    state = build_buyer_state(records, analysis)

    assert state.trip_type == "holiday"
    assert "pool" in state.must_haves
    assert state.known_affordable_total == 1056.24
    assert state.stated_budget_max is None
    assert state.accepted is True
    assert state.walked is False
    assert state.last_markup_pct == 8
    assert state.confidence >= 0.8
