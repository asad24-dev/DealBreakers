"""Graph runner — LangGraph when available, deterministic fallback otherwise (Phase 8E)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from dealbreakers.constants import MAX_ROUNDS, PRACTICE_PERSONAS
from dealbreakers.graph.context import GraphContext
from dealbreakers.graph.nodes import (
    analyze_node,
    check_end_node,
    counter_node,
    decide_action_node,
    generate_reply_node,
    route_after_check_end,
    route_after_decide,
    search_inventory_node,
    select_offer_node,
    send_turn_node,
    start_match_node,
    strategist_node,
    update_state_node,
)
from dealbreakers.graph.state import GraphState
from dealbreakers.learning.bandit import BanditPolicy
from dealbreakers.models.match import MatchStartResponse
from dealbreakers.negotiation.live_agent import MatchOutcome, assert_practice_match
from dealbreakers.models.transcript import TranscriptEvent

_LANGGRAPH_AVAILABLE: bool | None = None


def is_langgraph_available() -> bool:
    """Return True if langgraph can be imported."""
    global _LANGGRAPH_AVAILABLE
    if _LANGGRAPH_AVAILABLE is not None:
        return _LANGGRAPH_AVAILABLE
    try:
        import langgraph  # noqa: F401
        import langchain_core  # noqa: F401

        _LANGGRAPH_AVAILABLE = True
    except ImportError:
        _LANGGRAPH_AVAILABLE = False
    return _LANGGRAPH_AVAILABLE


PRACTICE_WHITELIST = frozenset(PRACTICE_PERSONAS)


@dataclass
class GraphRunResult:
    state: GraphState
    outcome: MatchOutcome
    used_langgraph: bool


def _assert_graph_safety(persona_id: str, start: MatchStartResponse) -> None:
    if persona_id not in PRACTICE_WHITELIST:
        raise RuntimeError(
            f"Graph runner is practice-only. Persona {persona_id!r} is not whitelisted."
        )
    assert_practice_match(start)


def _init_state(persona_id: str, start: MatchStartResponse) -> GraphState:
    return GraphState(
        persona_id=persona_id,
        match_id=start.match_id,
        latest_buyer_message=start.buyer.text,
    )


def _init_events(persona_id: str, start: MatchStartResponse) -> list[TranscriptEvent]:
    return [
        TranscriptEvent(
            match_id=start.match_id,
            persona_id=persona_id,
            scenario_name=start.scenario.name,
            round_number=None,
            role="buyer",
            text=start.buyer.text,
            action=start.buyer.action.value,
        )
    ]


def _run_wording_path(state: GraphState, ctx: GraphContext) -> GraphState:
    state = generate_reply_node(state, ctx)
    state = send_turn_node(state, ctx)
    return check_end_node(state, ctx)


def _run_search_path(state: GraphState, ctx: GraphContext) -> GraphState:
    state = search_inventory_node(state, ctx)
    state = select_offer_node(state, ctx)
    state = generate_reply_node(state, ctx)
    state = send_turn_node(state, ctx)
    return check_end_node(state, ctx)


def _run_offer_path(state: GraphState, ctx: GraphContext) -> GraphState:
    if not ctx.inventory.has_offerable:
        state = search_inventory_node(state, ctx)
    state = select_offer_node(state, ctx)
    state = generate_reply_node(state, ctx)
    state = send_turn_node(state, ctx)
    return check_end_node(state, ctx)


def _run_counter_path(state: GraphState, ctx: GraphContext) -> GraphState:
    state = counter_node(state, ctx)
    state = generate_reply_node(state, ctx)
    state = send_turn_node(state, ctx)
    return check_end_node(state, ctx)


_PATH_RUNNERS: dict[str, Callable[[GraphState, GraphContext], GraphState]] = {
    "wording_path": _run_wording_path,
    "search_path": _run_search_path,
    "offer_path": _run_offer_path,
    "counter_path": _run_counter_path,
}


def _run_round(state: GraphState, ctx: GraphContext) -> GraphState:
    state = analyze_node(state, ctx)
    state = strategist_node(state, ctx)
    state = update_state_node(state, ctx)
    state = decide_action_node(state, ctx)
    path = route_after_decide(state)
    runner = _PATH_RUNNERS[path]
    return runner(state, ctx)


def _run_fallback_loop(
    state: GraphState,
    ctx: GraphContext,
    *,
    max_rounds: int = MAX_ROUNDS,
) -> GraphState:
    state = start_match_node(state, ctx)
    while not state.ended and ctx.seller_rounds < max_rounds:
        state = _run_round(state, ctx)
        if route_after_check_end(state) == "end":
            break
    if not state.ended and ctx.seller_rounds >= max_rounds:
        state.ended = True
    return state


def _wrap_node(
    node_fn: Callable[[GraphState, GraphContext], GraphState],
    ctx: GraphContext,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def _inner(state_dict: dict[str, Any]) -> dict[str, Any]:
        gs = GraphState.from_dict(state_dict)
        gs = node_fn(gs, ctx)
        return gs.to_dict()

    return _inner


def _build_langgraph(ctx: GraphContext) -> Any:
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(dict)

    graph.add_node("start_match", _wrap_node(start_match_node, ctx))
    graph.add_node("analyze", _wrap_node(analyze_node, ctx))
    graph.add_node("strategist", _wrap_node(strategist_node, ctx))
    graph.add_node("update_state", _wrap_node(update_state_node, ctx))
    graph.add_node("decide_action", _wrap_node(decide_action_node, ctx))
    graph.add_node("search_inventory", _wrap_node(search_inventory_node, ctx))
    graph.add_node("select_offer", _wrap_node(select_offer_node, ctx))
    graph.add_node("counter", _wrap_node(counter_node, ctx))
    graph.add_node("generate_reply", _wrap_node(generate_reply_node, ctx))
    graph.add_node("send_turn", _wrap_node(send_turn_node, ctx))
    graph.add_node("check_end", _wrap_node(check_end_node, ctx))

    graph.add_edge(START, "start_match")
    graph.add_edge("start_match", "analyze")
    graph.add_edge("analyze", "strategist")
    graph.add_edge("strategist", "update_state")
    graph.add_edge("update_state", "decide_action")

    def _route_decide(state_dict: dict[str, Any]) -> str:
        gs = GraphState.from_dict(state_dict)
        return route_after_decide(gs)

    graph.add_conditional_edges(
        "decide_action",
        _route_decide,
        {
            "wording_path": "generate_reply",
            "search_path": "search_inventory",
            "offer_path": "select_offer",
            "counter_path": "counter",
        },
    )

    graph.add_edge("search_inventory", "select_offer")
    graph.add_edge("select_offer", "generate_reply")
    graph.add_edge("counter", "generate_reply")
    graph.add_edge("generate_reply", "send_turn")
    graph.add_edge("send_turn", "check_end")

    def _route_end(state_dict: dict[str, Any]) -> str:
        gs = GraphState.from_dict(state_dict)
        return route_after_check_end(gs)

    graph.add_conditional_edges(
        "check_end",
        _route_end,
        {"end": END, "analyze": "analyze"},
    )

    return graph.compile()


class GraphRunner:
    """Optional orchestration layer wrapping existing deterministic modules."""

    def __init__(self, ctx: GraphContext, *, prefer_langgraph: bool = True) -> None:
        self._ctx = ctx
        self._prefer_langgraph = prefer_langgraph

    def run(
        self,
        start: MatchStartResponse,
        *,
        persona_id: str,
        bandit_policy: BanditPolicy | None = None,
        bandit_epsilon: float = 0.0,
        log_path: str | Path | None = None,
    ) -> GraphRunResult:
        _assert_graph_safety(persona_id, start)

        self._ctx.start = start
        self._ctx.events = _init_events(persona_id, start)
        self._ctx.bandit_policy = bandit_policy
        self._ctx.bandit_epsilon = bandit_epsilon
        if bandit_policy is not None:
            self._ctx.markup_arm = bandit_policy.choose_arm(
                {"persona_id": persona_id},
                arm_type="markup",
                epsilon=bandit_epsilon,
            )
            self._ctx.search_arm = bandit_policy.choose_arm(
                arm_type="search",
                epsilon=bandit_epsilon,
            )
            self._ctx.counter_arm = bandit_policy.choose_arm(
                arm_type="counter",
                epsilon=bandit_epsilon,
            )

        state = _init_state(persona_id, start)
        used_langgraph = False

        if self._prefer_langgraph and is_langgraph_available():
            try:
                compiled = _build_langgraph(self._ctx)
                final_dict = compiled.invoke(state.to_dict())
                state = GraphState.from_dict(final_dict)
                used_langgraph = True
            except Exception as exc:  # noqa: BLE001
                state.error = f"LangGraph failed, using fallback: {exc}"
                state = _run_fallback_loop(state, self._ctx)
        else:
            state = _run_fallback_loop(state, self._ctx)

        if log_path:
            self._write_log(state, log_path)

        turn = self._ctx.turn_response
        result = turn.result if turn else None
        outcome = MatchOutcome(
            match_id=start.match_id,
            persona_id=persona_id,
            closed=bool(result and result.closed),
            walked=bool(result and result.end_reason == "walked"),
            rounds=result.rounds if result else self._ctx.seller_rounds,
            end_reason=result.end_reason if result else None,
            seller_rounds=self._ctx.seller_rounds,
        )
        return GraphRunResult(state=state, outcome=outcome, used_langgraph=used_langgraph)

    @staticmethod
    def _write_log(state: GraphState, log_path: str | Path) -> None:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for entry in state.logs:
                handle.write(json.dumps(entry, default=str) + "\n")
