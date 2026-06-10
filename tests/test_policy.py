"""Offline tests for the deterministic policy engine and reply guardrails (Phase 7A/7B)."""

import json
from unittest.mock import MagicMock

from dealbreakers.analysis.models import ConversationAnalysis
from dealbreakers.negotiation import (
    NegotiationAction,
    decide_action,
    estimate_walk_risk,
    fallback_reply,
    generate_reply,
    validate_reply,
)
from dealbreakers.state.buyer_state import BuyerState


def informed_state(**overrides) -> BuyerState:
    """A buyer we know enough about to offer to."""
    defaults = dict(
        trip_type="holiday",
        destinations=["Spain"],
        must_haves=["pool"],
    )
    defaults.update(overrides)
    return BuyerState(**defaults)


EMPTY_ANALYSIS = ConversationAnalysis()


# --- DISCOVER / REFINE ---


def test_discover_when_trip_type_unknown() -> None:
    decision = decide_action(BuyerState(), EMPTY_ANALYSIS, "Hi, I want a trip!")
    assert decision.action is NegotiationAction.DISCOVER
    assert decision.confidence == 0.9
    assert decision.target_markup is None


def test_discover_when_destination_unknown() -> None:
    state = BuyerState(trip_type="holiday", must_haves=["pool"])
    decision = decide_action(state, EMPTY_ANALYSIS, "Somewhere sunny please")
    assert decision.action is NegotiationAction.DISCOVER
    assert "destination" in decision.reasoning


def test_analysis_fills_gaps_in_state() -> None:
    analysis = ConversationAnalysis(trip_type="holiday", destinations=["Spain"], must_haves=["pool"])
    decision = decide_action(BuyerState(), analysis, "A sunny week in Spain with a pool")
    assert decision.action is not NegotiationAction.DISCOVER


def test_refine_when_must_haves_unclear() -> None:
    state = BuyerState(trip_type="holiday", destinations=["Spain"])
    decision = decide_action(state, EMPTY_ANALYSIS, "Spain sounds nice")
    assert decision.action is NegotiationAction.REFINE


# --- SEARCH / OFFER ---


def test_search_when_informed_but_no_inventory() -> None:
    decision = decide_action(informed_state(), EMPTY_ANALYSIS, "A pool is essential")
    assert decision.action is NegotiationAction.SEARCH


def test_offer_when_informed_and_inventory_ready() -> None:
    decision = decide_action(
        informed_state(), EMPTY_ANALYSIS, "A pool is essential", inventory_ready=True
    )
    assert decision.action is NegotiationAction.OFFER
    assert decision.target_markup == 12.0  # BALANCED default profile


# --- COUNTER ---


def test_counter_on_price_pushback_after_offer() -> None:
    state = informed_state(last_offer_total=1369.20, last_markup_pct=40.0)
    decision = decide_action(state, EMPTY_ANALYSIS, "That fee seems quite expensive")
    assert decision.action is NegotiationAction.COUNTER
    assert decision.target_markup == 35.0  # one rung down from 40


def test_no_counter_before_any_offer() -> None:
    decision = decide_action(informed_state(), EMPTY_ANALYSIS, "What's the price like?")
    assert decision.action is not NegotiationAction.COUNTER


# --- CLOSE ---


def test_close_on_acceptance_language_after_offer() -> None:
    state = informed_state(last_offer_total=1124.70, last_markup_pct=15.0)
    decision = decide_action(state, EMPTY_ANALYSIS, "I'll take it — let's do it!")
    assert decision.action is NegotiationAction.CLOSE
    assert decision.confidence == 0.95
    assert decision.target_markup == 15.0


def test_no_close_without_offer() -> None:
    decision = decide_action(informed_state(), EMPTY_ANALYSIS, "Sounds good so far!")
    assert decision.action is not NegotiationAction.CLOSE


def test_close_beats_counter_when_both_signals_present() -> None:
    state = informed_state(last_offer_total=1000.0, last_markup_pct=20.0)
    decision = decide_action(state, EMPTY_ANALYSIS, "The price is fine — book it!")
    assert decision.action is NegotiationAction.CLOSE


def test_decisions_are_deterministic() -> None:
    state = informed_state(last_offer_total=1000.0, last_markup_pct=20.0)
    decisions = [
        decide_action(state, EMPTY_ANALYSIS, "too expensive for me").to_dict()
        for _ in range(5)
    ]
    assert all(decision == decisions[0] for decision in decisions)


# --- walk risk ---


def test_walk_risk_baseline_is_low() -> None:
    risk = estimate_walk_risk(BuyerState(), "Tell me more about the hotel")
    assert 0.0 <= risk <= 0.2


def test_walk_risk_increases_with_objections_and_trust_complaints() -> None:
    calm = estimate_walk_risk(BuyerState(), "Hmm, okay")
    objecting = estimate_walk_risk(
        BuyerState(objections=["price objection", "trust objection"]),
        "This feels like a rip-off, don't rip me off",
    )
    assert objecting > calm
    assert objecting >= 0.6


def test_walk_risk_repeated_price_objection_raises_risk() -> None:
    state = BuyerState(rejected_total=1300.0, last_offer_total=1300.0)
    risk = estimate_walk_risk(state, "Still too expensive")
    plain = estimate_walk_risk(BuyerState(), "Still too expensive")
    assert risk > plain


def test_walk_risk_decreases_with_engagement_and_history() -> None:
    engaged = estimate_walk_risk(
        BuyerState(known_affordable_total=1056.24),
        "That sounds wonderful — does it have a spa?",
    )
    assert engaged == 0.0


def test_walk_risk_clamped_and_walked_is_certain() -> None:
    assert estimate_walk_risk(BuyerState(walked=True), "bye") == 1.0
    many = BuyerState(objections=["a", "b", "c", "d", "e"], rejected_total=900.0)
    risk = estimate_walk_risk(many, "don't trust you, too expensive")
    assert 0.0 <= risk <= 1.0


# --- responder guardrails (OpenAI wording only) ---


def fake_openai(text: str) -> MagicMock:
    client = MagicMock()
    message = MagicMock()
    message.content = json.dumps({"text": text})
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=message)]
    )
    return client


OFFER_DICT = {
    "holiday": {
        "hotelName": "Be Live Adults Only Tenerife",
        "location": "Puerto De La Cruz",
        "nights": 7,
        "priceTotal": 978.0,
        "amenities": ["pool"],
    },
    "markupPct": 15.0,
}


def test_validate_reply_rejects_banned_phrases_and_length() -> None:
    assert validate_reply("Give me a moment, I'm searching for deals") is not None
    assert validate_reply("Let me look into that") is not None
    assert validate_reply("word " * 91) is not None
    assert validate_reply("") is not None
    assert validate_reply("A lovely 7-night stay with a pool. Shall we book it?") is None


def test_generate_reply_returns_model_text_when_valid() -> None:
    client = fake_openai("A lovely 7-night stay at Be Live Adults Only Tenerife. Book it?")
    text = generate_reply(
        NegotiationAction.OFFER, informed_state(), OFFER_DICT, "Sounds nice", client=client
    )
    assert "Be Live" in text


def test_generate_reply_falls_back_on_banned_phrase() -> None:
    client = fake_openai("Give me a moment, I'm checking availability...")
    text = generate_reply(
        NegotiationAction.OFFER, informed_state(), OFFER_DICT, "ok", client=client
    )
    assert text == fallback_reply(NegotiationAction.OFFER, OFFER_DICT)
    assert "checking" not in text.lower()


def test_generate_reply_falls_back_on_client_error() -> None:
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("api down")
    text = generate_reply(
        NegotiationAction.CLOSE, informed_state(), OFFER_DICT, "I'll take it", client=client
    )
    assert text == fallback_reply(NegotiationAction.CLOSE, OFFER_DICT)


def test_fallback_replies_pass_validation_for_all_actions() -> None:
    for action in NegotiationAction:
        assert validate_reply(fallback_reply(action, OFFER_DICT)) is None
