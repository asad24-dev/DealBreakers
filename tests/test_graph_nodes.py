"""Tests for graph nodes and runner safety (Phase 8E)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dealbreakers.constants import BuyerAction, MatchStatus, MAX_ROUNDS
from dealbreakers.graph.context import GraphContext
from dealbreakers.graph.nodes import (
    check_end_node,
    decide_action_node,
    route_after_check_end,
    route_after_decide,
    start_match_node,
)
from dealbreakers.graph.runner import GraphRunner, PRACTICE_WHITELIST, is_langgraph_available
from dealbreakers.graph.state import GraphState
from dealbreakers.models.match import (
    BuyerMessage,
    MatchStartResponse,
    Scenario,
    TurnResponse,
)
from dealbreakers.negotiation.actions import NegotiationAction
from dealbreakers.negotiation.policy import decide_action


def make_start(*, brief: str = "PRACTICE buyer — Bob", persona: str = "practice-bob") -> MatchStartResponse:
    return MatchStartResponse(
        match_id="match-graph",
        scenario=Scenario(name="Test", brief=brief),
        buyer=BuyerMessage(
            text="I want a sunny week in Spain with a pool.",
            action=BuyerAction.CONTINUE,
        ),
        status=MatchStatus.AWAITING_SELLER,
    )


def test_graph_uses_practice_true_only() -> None:
    assert "practice-bob" in PRACTICE_WHITELIST
    with pytest.raises(RuntimeError, match="must never run an official match"):
        GraphRunner(GraphContext(deal_room=MagicMock())).run(
            make_start(brief="Official buyer"),
            persona_id="practice-bob",
        )


def test_no_official_persona_whitelist() -> None:
    with pytest.raises(RuntimeError, match="not whitelisted"):
        GraphRunner(GraphContext(deal_room=MagicMock())).run(
            make_start(),
            persona_id="official-gordon",
        )


def test_decide_node_calls_deterministic_policy() -> None:
    state = GraphState(
        latest_buyer_message="too expensive",
        analysis={"trip_type": "holiday", "destinations": ["Spain"], "must_haves": []},
    )
    ctx = GraphContext(deal_room=MagicMock())
    ctx.buyer_state.trip_type = "holiday"
    ctx.buyer_state.destinations = ["Spain"]
    ctx.buyer_state.last_offer_total = 1200.0
    ctx.buyer_state.last_markup_pct = 25.0

    direct = decide_action(
        ctx.buyer_state,
        ctx.analyzer.analyze([]),
        state.latest_buyer_message,
        inventory_ready=True,
    )
    state = decide_action_node(state, ctx)
    assert state.policy_decision is not None
    assert state.policy_decision["action"] in {a.value for a in NegotiationAction}


def test_route_after_decide_paths() -> None:
    state = GraphState(policy_decision={"action": "search"})
    assert route_after_decide(state) == "search_path"
    state.policy_decision = {"action": "counter"}
    assert route_after_decide(state) == "counter_path"


def test_graph_stops_at_round_cap() -> None:
    state = GraphState()
    ctx = GraphContext(deal_room=MagicMock())
    ctx.seller_rounds = MAX_ROUNDS
    state = check_end_node(state, ctx)
    assert state.ended is True


def test_graph_stops_on_accept() -> None:
    state = GraphState()
    ctx = GraphContext(deal_room=MagicMock())
    ctx.turn_response = TurnResponse(
        buyer=BuyerMessage(text="Book it", action=BuyerAction.ACCEPT),
        status=MatchStatus.ENDED,
        quote=None,
        result=None,
    )
    ctx.turn_response = TurnResponse(
        buyer=BuyerMessage(text="Done", action=BuyerAction.ACCEPT),
        status=MatchStatus.ENDED,
        quote=None,
        result=None,
    )
    state = check_end_node(state, ctx)
    assert state.ended is True


def test_start_match_records_opening() -> None:
    start = make_start()
    ctx = GraphContext(deal_room=MagicMock())
    ctx.start = start
    state = GraphState(persona_id="practice-bob")
    state = start_match_node(state, ctx)
    assert state.match_id == "match-graph"
    assert state.latest_buyer_message == start.buyer.text
    assert len(state.transcript) == 1


def test_langgraph_optional_does_not_break_import() -> None:
    """Project must work whether or not langgraph is installed."""
    assert isinstance(is_langgraph_available(), bool)


def test_check_end_loops_when_not_ended() -> None:
    state = GraphState(ended=False)
    ctx = GraphContext(deal_room=MagicMock())
    ctx.seller_rounds = 1
    state = check_end_node(state, ctx)
    assert state.ended is False
    assert route_after_check_end(state) == "analyze"
