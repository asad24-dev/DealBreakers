"""Replay logged evidence into a BuyerState. Deterministic and inspectable."""

from __future__ import annotations

from typing import Any

from dealbreakers.analysis.models import ConversationAnalysis
from dealbreakers.state.buyer_state import BuyerState


def apply_log_records(state: BuyerState, records: list[dict[str, Any]]) -> BuyerState:
    """Replay Phase 2 JSONL records (in order) into the state."""
    for record in records:
        record_type = record.get("record_type")
        if record_type == "seller_message" and record.get("offer"):
            state.update_from_offer(record["offer"])
        elif record_type == "turn_response":
            state.update_from_turn_response(record)
    return state


def build_buyer_state(
    records: list[dict[str, Any]],
    analysis: ConversationAnalysis | None = None,
) -> BuyerState:
    """Build a fresh BuyerState from a transcript log and optional analysis.

    Offers and turn responses are replayed FIRST so that seen offer prices are
    known before the analysis is applied — this is what lets the state reject
    analyzer "budgets" that merely echo our own quoted prices.
    """
    state = BuyerState()
    apply_log_records(state, records)
    if analysis is not None:
        state.update_from_analysis(analysis)
    return state
