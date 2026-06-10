"""Offline tests for hard-persona agent behaviour (Phase 7D)."""

from __future__ import annotations

from itertools import chain, repeat
from unittest.mock import MagicMock

from dealbreakers.analysis.models import ConversationAnalysis
from dealbreakers.constants import BuyerAction, MatchStatus
from dealbreakers.models.match import BuyerMessage, MatchStartResponse, Quote, Scenario, TurnResponse
from dealbreakers.mcp.car_normalizers import CarCandidate
from dealbreakers.mcp.normalizers import HolidayCandidate
from dealbreakers.negotiation.actions import NegotiationAction
from dealbreakers.negotiation.live_agent import (
    AgentSessionState,
    LiveNegotiationAgent,
    apply_impatience_override,
    apply_policy_overrides,
    is_impatient,
    wants_car,
)
from dealbreakers.negotiation.policy import decide_action
from dealbreakers.negotiation.pricing import generate_luxury_counter_markup
from dealbreakers.state.buyer_state import BuyerState


def make_start() -> MatchStartResponse:
    return MatchStartResponse(
        match_id="match-hard",
        scenario=Scenario(name="Cris", brief="PRACTICE buyer"),
        buyer=BuyerMessage(text="I want something exceptional.", action=BuyerAction.CONTINUE),
        status=MatchStatus.AWAITING_SELLER,
    )


def make_holiday() -> HolidayCandidate:
    return HolidayCandidate(
        hotel_name="Tivoli Marina",
        url="https://example.com/hotel",
        star_rating=5.0,
        price_total=3130.0,
        nights=7,
        location="Vilamoura",
        country="Portugal",
        amenities=["spa", "gym", "close_to_beach"],
    )


def make_car() -> CarCandidate:
    return CarCandidate(
        vehicle_name="Mercedes E-Class",
        url="https://example.com/mercedes",
        price_total=280.0,
        category="Executive",
        transmission="Automatic",
        seats=5,
        source_mcp="economybookings",
    )


def make_turn(text: str, **kwargs):
    action = kwargs.pop("action", BuyerAction.CONTINUE)
    ended = kwargs.pop("ended", False)
    closed = kwargs.pop("closed", False)
    return TurnResponse(
        buyer=BuyerMessage(text=text, action=action),
        status=MatchStatus.ENDED if ended else MatchStatus.AWAITING_SELLER,
        quote=kwargs.get("quote"),
        result=None,
    )


def test_impatience_message_detected():
    assert is_impatient("stop asking questions and show me what you've got", BuyerState())


def test_impatience_forces_search_not_discover():
    decision = decide_action(
        BuyerState(trip_type="holiday"),
        ConversationAnalysis(),
        "stop asking and show me",
    )
    overridden = apply_impatience_override(
        decision,
        latest_message="stop asking and show me",
        state=BuyerState(trip_type="holiday"),
        inventory_ready=False,
        session=AgentSessionState(),
    )
    assert overridden.action is NegotiationAction.SEARCH


def test_gordon_luxury_counter_jumps_30_to_18():
    state = BuyerState(luxury_preference=1.0, last_offer_total=5662.0)
    assert generate_luxury_counter_markup(30.0, state) == 18.0
    assert generate_luxury_counter_markup(25.0, state) == 18.0
    assert generate_luxury_counter_markup(20.0, state) == 12.0


def test_max_price_counters_enforced():
    state = BuyerState(last_offer_total=5000.0, last_markup_pct=18.0)
    session = AgentSessionState(price_counter_count=2)
    decision = decide_action(state, ConversationAnalysis(), "still too expensive", inventory_ready=True)
    overridden = apply_policy_overrides(
        decision,
        state,
        "still too expensive",
        session=session,
        inventory_ready=True,
    )
    assert overridden.action is NegotiationAction.OFFER
    assert overridden.target_markup == 8.0


def test_cris_car_search_triggers_combined_offer(tmp_path):
    analysis = ConversationAnalysis(
        trip_type="holiday",
        destinations=["Algarve"],
        must_haves=["premium rental car", "five-star"],
        luxury_preference=1.0,
    )
    analyzer = MagicMock()
    analyzer.analyze.return_value = analysis

    class FakeTSM:
        def search_holidays(self, **kwargs):
            return [make_holiday()]

    class FakeCarSearch:
        last_errors: list[str] = []

        def search_cars(self, *args, **kwargs):
            return [make_car()]

    deal_room = MagicMock()
    deal_room.send_turn.side_effect = chain(
        [
            make_turn("Show me something exceptional."),
            make_turn("I'll take it.", action=BuyerAction.ACCEPT, ended=True, closed=True),
        ],
        repeat(make_turn("ok")),
    )

    agent = LiveNegotiationAgent(
        deal_room=deal_room,
        analyzer=analyzer,
        tsm=FakeTSM(),  # type: ignore[arg-type]
        tourradar=MagicMock(),
        car_search=FakeCarSearch(),  # type: ignore[arg-type]
        log_path=tmp_path / "cris.jsonl",
        reply_generator=lambda action, state, offer, msg: f"{action.value}",
    )
    agent.run(make_start(), persona_id="practice-cris")

    offer = deal_room.send_turn.call_args_list[1].kwargs["offer"]
    assert offer is not None
    assert offer.car is not None
    assert offer.holiday is not None


def test_cris_no_car_records_unresolved_and_avoids_car_counter_loop(tmp_path):
    analysis = ConversationAnalysis(
        trip_type="holiday",
        destinations=["Algarve"],
        must_haves=["premium rental car"],
        luxury_preference=1.0,
    )
    analyzer = MagicMock()
    analyzer.analyze.return_value = analysis

    class FakeTSM:
        def search_holidays(self, **kwargs):
            return [make_holiday()]

    class EmptyCarSearch:
        last_errors = ["economybookings: down"]

        def search_cars(self, *args, **kwargs):
            return []

    deal_room = MagicMock()
    deal_room.send_turn.side_effect = chain(
        [
            make_turn("Show me a concrete package right now."),
            make_turn("I need a premium rental car included."),
            make_turn("Where is the car?"),
        ],
        repeat(make_turn("still waiting")),
    )

    agent = LiveNegotiationAgent(
        deal_room=deal_room,
        analyzer=analyzer,
        tsm=FakeTSM(),  # type: ignore[arg-type]
        tourradar=MagicMock(),
        car_search=EmptyCarSearch(),  # type: ignore[arg-type]
        log_path=tmp_path / "cris_no_car.jsonl",
        reply_generator=lambda action, state, offer, msg: "seller",
    )
    agent.run(make_start(), persona_id="practice-cris")

    offers = [
        call.kwargs["offer"]
        for call in deal_room.send_turn.call_args_list
        if call.kwargs.get("offer") is not None
    ]
    assert offers
    assert all(offer.car is None for offer in offers)
    records = (tmp_path / "cris_no_car.jsonl").read_text(encoding="utf-8")
    assert "unresolved_requirements" in records
    assert '"car"' in records


def test_wants_car_from_must_haves():
    state = BuyerState(must_haves=["premium rental car"])
    assert wants_car(state, "package please")
