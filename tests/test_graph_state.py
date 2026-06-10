"""Tests for GraphState serialization (Phase 8E)."""

from __future__ import annotations

from dealbreakers.graph.state import GraphState


def test_graph_state_round_trip() -> None:
    original = GraphState(
        persona_id="practice-bob",
        match_id="match-1",
        round_number=2,
        latest_buyer_message="I want Spain",
        analysis={"trip_type": "holiday"},
        markup_pct=12.5,
        logs=[{"node": "analyze"}],
    )
    restored = GraphState.from_dict(original.to_dict())
    assert restored.persona_id == "practice-bob"
    assert restored.match_id == "match-1"
    assert restored.round_number == 2
    assert restored.latest_buyer_message == "I want Spain"
    assert restored.analysis == {"trip_type": "holiday"}
    assert restored.markup_pct == 12.5
    assert restored.logs == [{"node": "analyze"}]
