"""Offline tests for the autonomous negotiation loop (Phase 7C)."""

from __future__ import annotations

import json
from pathlib import Path
from itertools import chain, repeat
from unittest.mock import MagicMock

import pytest

from dealbreakers.analysis.models import ConversationAnalysis
from dealbreakers.constants import BuyerAction, MatchStatus, MAX_ROUNDS
from dealbreakers.models.match import (
    BuyerMessage,
    MatchResult,
    MatchStartResponse,
    Quote,
    Scenario,
    TurnResponse,
)
from dealbreakers.mcp.normalizers import HolidayCandidate
from dealbreakers.mcp.tour_normalizers import TourCandidate
from dealbreakers.negotiation.actions import NegotiationAction
from dealbreakers.negotiation.live_agent import (
    AgentSessionState,
    LiveNegotiationAgent,
    apply_policy_overrides,
    assert_practice_match,
    car_wrapper_available,
    markup_profile_from_walk_risk,
    run_inventory_search,
    search_holidays,
    search_tours,
    wants_car,
)
from dealbreakers.negotiation.pricing import Aggressiveness
from dealbreakers.negotiation.policy import decide_action
from dealbreakers.offers.selection import score_holiday_for_state
from dealbreakers.state.buyer_state import BuyerState


def make_start(*, brief: str = "PRACTICE buyer — Bob", persona: str = "practice-bob") -> MatchStartResponse:
    return MatchStartResponse(
        match_id="match-auto",
        scenario=Scenario(name="Test", brief=brief),
        buyer=BuyerMessage(
            text="I want a sunny week in Spain with a pool.",
            action=BuyerAction.CONTINUE,
        ),
        status=MatchStatus.AWAITING_SELLER,
    )


def make_holiday(**overrides) -> HolidayCandidate:
    defaults = dict(
        hotel_name="Be Live Tenerife",
        url="https://example.com/hotel",
        star_rating=4.0,
        review_score=9.0,
        board_basis="HB",
        nights=7,
        location="Tenerife",
        region="Tenerife",
        country="Spain",
        amenities=["pool", "close_to_beach"],
        price_total=978.0,
    )
    defaults.update(overrides)
    return HolidayCandidate(**defaults)


def make_tour(**overrides) -> TourCandidate:
    defaults = dict(
        name="Spain Cultural Tour",
        url="https://example.com/tour",
        operator="Europamundo",
        region="Andalusia",
        country="Spain",
        duration_days=8,
        price_total=1241.0,
    )
    defaults.update(overrides)
    return TourCandidate(**defaults)


def make_turn(
    text: str,
    *,
    action: BuyerAction = BuyerAction.CONTINUE,
    ended: bool = False,
    closed: bool = False,
    quote: Quote | None = None,
) -> TurnResponse:
    return TurnResponse(
        buyer=BuyerMessage(text=text, action=action),
        status=MatchStatus.ENDED if ended else MatchStatus.AWAITING_SELLER,
        quote=quote,
        result=(
            MatchResult(closed=closed, end_reason="accepted" if closed else None, rounds=3)
            if ended
            else None
        ),
    )


def test_practice_guard_rejects_official() -> None:
    with pytest.raises(RuntimeError, match="must never run an official match"):
        assert_practice_match(make_start(brief="Official buyer"))


def test_walk_risk_markup_profile() -> None:
    assert markup_profile_from_walk_risk(0.8) is Aggressiveness.SAFE
    assert markup_profile_from_walk_risk(0.1) is Aggressiveness.AGGRESSIVE
    assert markup_profile_from_walk_risk(0.5) is Aggressiveness.BALANCED


def test_wants_car_detects_must_haves() -> None:
    state = BuyerState(must_haves=["premium rental car"])
    assert wants_car(state, "I need a car included")


def test_car_pickup_location_prefers_holiday_over_vague_destination() -> None:
    from dealbreakers.negotiation.live_agent import car_pickup_location

    state = BuyerState(destinations=["Mediterranean"])
    holiday = make_holiday(location="Tenerife", region="Canary Islands")
    assert car_pickup_location(state, holiday) == "Tenerife"


def test_holiday_duration_plan_prefers_desired_nights() -> None:
    from dealbreakers.negotiation.live_agent import holiday_duration_plan

    state = BuyerState(desired_nights=14)
    assert holiday_duration_plan(state) == (14, 10, 7)


def test_conversation_is_dead_detects_departure() -> None:
    from dealbreakers.negotiation.live_agent import conversation_is_dead

    assert conversation_is_dead(["we're done", "goodbye"])
    assert not conversation_is_dead(["still thinking"])


def test_car_unresolved_triggers_refine_not_counter_loop() -> None:
    state = BuyerState(
        trip_type="holiday",
        destinations=["Algarve"],
        must_haves=["luxury car"],
        last_offer_total=4069.0,
        last_markup_pct=30.0,
    )
    session = AgentSessionState(unresolved_requirements=["car"], car_unresolved_notified=True)
    base = decide_action(state, ConversationAnalysis(), "Add a premium rental car", inventory_ready=True)
    overridden = apply_policy_overrides(
        base,
        state,
        "Add a premium rental car",
        session=session,
        inventory_ready=True,
    )
    assert overridden.action is NegotiationAction.REFINE


def test_state_scoring_prefers_luxury_over_cheap() -> None:
    luxury_state = BuyerState(luxury_preference=1.0, must_haves=["spa", "close_to_beach"])
    cheap = make_holiday(price_total=1200.0, star_rating=4.0, review_score=8.0, amenities=["spa"])
    premium = make_holiday(
        price_total=4500.0,
        star_rating=5.0,
        review_score=9.6,
        amenities=["spa", "close_to_beach", "pool"],
    )
    assert score_holiday_for_state(premium, luxury_state) > score_holiday_for_state(cheap, luxury_state)


def test_search_holidays_for_state_uses_destinations(monkeypatch) -> None:
    state = BuyerState(trip_type="holiday", destinations=["Spain"], must_haves=["pool"])
    calls: list[str] = []

    class FakeTSM:
        def search_holidays(self, destination: str, **kwargs):
            calls.append(destination)
            if destination == "Spain":
                return [make_holiday()]
            return []

    inventory = search_holidays(state, FakeTSM())  # type: ignore[arg-type]
    assert calls[0] == "Spain"
    assert inventory.holiday_candidates


def test_search_tours_for_tour_state(monkeypatch) -> None:
    state = BuyerState(trip_type="tour", destinations=["Spain"], must_haves=["guided tour"])

    class FakeTourRadar:
        def search_tours(self, **kwargs):
            assert kwargs["country"] == "Spain"
            return [make_tour()]

    inventory = search_tours(state, FakeTourRadar())  # type: ignore[arg-type]
    assert inventory.tour_candidates


def test_run_inventory_search_routes_by_trip_type() -> None:
    holiday_state = BuyerState(trip_type="holiday", destinations=["Spain"])
    tour_state = BuyerState(trip_type="tour", destinations=["Spain"])

    class FakeTSM:
        def search_holidays(self, **kwargs):
            return [make_holiday()]

    class FakeTourRadar:
        def search_tours(self, **kwargs):
            return [make_tour()]

    holiday_inv = run_inventory_search(holiday_state, tsm=FakeTSM(), tourradar=FakeTourRadar())  # type: ignore[arg-type]
    tour_inv = run_inventory_search(tour_state, tsm=FakeTSM(), tourradar=FakeTourRadar())  # type: ignore[arg-type]
    assert holiday_inv.holiday_candidates
    assert tour_inv.tour_candidates


def _mock_analyzer_sequence(analyses: list[ConversationAnalysis]) -> MagicMock:
    mock = MagicMock()
    mock.analyze.side_effect = analyses
    return mock


def test_autonomous_loop_closes_bob_with_mocks(tmp_path: Path) -> None:
    analysis = ConversationAnalysis(
        trip_type="holiday",
        destinations=["Spain"],
        must_haves=["pool"],
        confidence=0.8,
    )
    analyzer = _mock_analyzer_sequence([analysis] * 5)

    class FakeTSM:
        def search_holidays(self, **kwargs):
            return [make_holiday()]

    deal_room = MagicMock()
    deal_room.send_turn.side_effect = [
        make_turn("A pool is essential — show me options."),
        make_turn("I'll take it — let's book!", action=BuyerAction.ACCEPT, ended=True, closed=True),
    ]

    agent = LiveNegotiationAgent(
        deal_room=deal_room,
        analyzer=analyzer,
        tsm=FakeTSM(),  # type: ignore[arg-type]
        tourradar=MagicMock(),
        log_path=tmp_path / "bob.jsonl",
        reply_generator=lambda action, state, offer, msg: f"Seller {action.value}",
    )

    outcome = agent.run(make_start(), persona_id="practice-bob")
    assert outcome.closed
    assert deal_room.send_turn.call_count == 2
    second_call = deal_room.send_turn.call_args_list[1]
    assert second_call.kwargs["offer"] is not None
    assert second_call.kwargs["offer"].markup_pct is not None

    records = [json.loads(line) for line in (tmp_path / "bob.jsonl").read_text().splitlines()]
    agent_turns = [record for record in records if record.get("record_type") == "agent_turn"]
    assert agent_turns
    assert agent_turns[-1]["buyer_action"] == "accept"


def test_autonomous_loop_counters_gordon_price_objection(tmp_path: Path) -> None:
    analysis = ConversationAnalysis(
        trip_type="holiday",
        destinations=["Spain"],
        must_haves=["five-star", "spa", "close_to_beach"],
        luxury_preference=1.0,
        confidence=0.9,
    )
    analyzer = MagicMock()
    analyzer.analyze.return_value = analysis

    class FakeTSM:
        def search_holidays(self, **kwargs):
            return [make_holiday(star_rating=5.0, price_total=4356.0, amenities=["spa", "pool", "close_to_beach"])]

    deal_room = MagicMock()
    deal_room.send_turn.side_effect = chain(
        [
            make_turn("Five-star only — show me."),
            make_turn(
                "That price is absolutely outrageous — come down substantially.",
                quote=Quote(cost=4356, markup_pct=25, total=5445.0),
            ),
            make_turn("Better — still thinking."),
        ],
        repeat(make_turn("Keep going.")),
    )

    agent = LiveNegotiationAgent(
        deal_room=deal_room,
        analyzer=analyzer,
        tsm=FakeTSM(),  # type: ignore[arg-type]
        tourradar=MagicMock(),
        log_path=tmp_path / "gordon.jsonl",
        reply_generator=lambda action, state, offer, msg: f"Seller {action.value}",
    )

    agent.run(make_start(brief="PRACTICE — Gordon", persona="practice-gordon"), persona_id="practice-gordon")

    markups = [
        call.kwargs["offer"].markup_pct
        for call in deal_room.send_turn.call_args_list
        if call.kwargs.get("offer") is not None
    ]
    assert len(markups) >= 2
    assert markups[0] == 25.0  # luxury BALANCED profile
    # "outrageous" triggers total-based 85% concession (~6.25% on this package)
    assert markups[1] < markups[0]
    assert markups[1] <= 18.0


def test_autonomous_loop_counters_cris_without_car(tmp_path: Path) -> None:
    analysis = ConversationAnalysis(
        trip_type="holiday",
        destinations=["Algarve"],
        must_haves=["five-star", "spa", "luxury car"],
        luxury_preference=1.0,
        confidence=0.9,
    )
    analyzer = MagicMock()
    analyzer.analyze.return_value = analysis

    class FakeTSM:
        def search_holidays(self, **kwargs):
            return [make_holiday(star_rating=5.0, price_total=3130.0, amenities=["spa", "gym", "close_to_beach"])]

    class EmptyCarSearch:
        last_errors = ["economybookings: unavailable"]

        def search_cars(self, *args, **kwargs):
            return []

    deal_room = MagicMock()
    deal_room.send_turn.side_effect = chain(
        [
            make_turn("Show me something exceptional."),
            make_turn(
                "I need a premium rental car included in this package.",
                quote=Quote(cost=3130, markup_pct=25, total=3912.5),
            ),
            make_turn("Still waiting on the car."),
        ],
        repeat(make_turn("And the car?")),
    )

    agent = LiveNegotiationAgent(
        deal_room=deal_room,
        analyzer=analyzer,
        tsm=FakeTSM(),  # type: ignore[arg-type]
        tourradar=MagicMock(),
        car_search=EmptyCarSearch(),  # type: ignore[arg-type]
        log_path=tmp_path / "cris.jsonl",
        reply_generator=lambda action, state, offer, msg: f"Seller {action.value}",
    )

    agent.run(make_start(brief="PRACTICE — Cris", persona="practice-cris"), persona_id="practice-cris")

    offers = [
        call.kwargs["offer"]
        for call in deal_room.send_turn.call_args_list
        if call.kwargs.get("offer") is not None
    ]
    assert len(offers) == 1
    assert offers[0].markup_pct == 25.0
    assert offers[0].car is None
    records = (tmp_path / "cris.jsonl").read_text(encoding="utf-8")
    assert "unresolved_requirements" in records or "car" in records


def test_autonomous_loop_respects_max_rounds(tmp_path: Path) -> None:
    analysis = ConversationAnalysis(
        trip_type="holiday",
        destinations=["Spain"],
        must_haves=["pool"],
    )
    analyzer = _mock_analyzer_sequence([analysis] * (MAX_ROUNDS + 2))

    class FakeTSM:
        def search_holidays(self, **kwargs):
            return [make_holiday()]

    deal_room = MagicMock()
    deal_room.send_turn.return_value = make_turn("Still thinking.")

    agent = LiveNegotiationAgent(
        deal_room=deal_room,
        analyzer=analyzer,
        tsm=FakeTSM(),  # type: ignore[arg-type]
        tourradar=MagicMock(),
        log_path=tmp_path / "max.jsonl",
        reply_generator=lambda action, state, offer, msg: "Seller message",
    )

    outcome = agent.run(make_start(), persona_id="practice-bob")
    assert outcome.seller_rounds == MAX_ROUNDS
    assert deal_room.send_turn.call_count == MAX_ROUNDS


def test_run_autonomous_practice_script_is_practice_only() -> None:
    source = (Path(__file__).resolve().parents[1] / "scripts" / "run_autonomous_practice.py").read_text()
    assert 'start_match(practice=True, persona_id=persona_id)' in source
    assert 'start_match({})' not in source
    assert "--official" not in source
    assert "PRACTICE MODE ONLY" in source
