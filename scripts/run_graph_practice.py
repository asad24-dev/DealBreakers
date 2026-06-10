#!/usr/bin/env python3
"""Phase 8E: practice matches via optional LangGraph orchestrator."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dealbreakers.api import DealRoomClient
from dealbreakers.config import load_settings
from dealbreakers.constants import PRACTICE_PERSONAS
from dealbreakers.graph.context import GraphContext
from dealbreakers.graph.runner import GraphRunner, is_langgraph_available
from dealbreakers.models.match import MatchStartResponse

ALLOWED_PERSONAS = frozenset(PRACTICE_PERSONAS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run graph-orchestrated practice negotiation.")
    parser.add_argument(
        "--persona",
        required=True,
        choices=sorted(ALLOWED_PERSONAS),
        help="Practice persona id (whitelist only).",
    )
    parser.add_argument(
        "--no-langgraph",
        action="store_true",
        help="Force fallback runner even if langgraph is installed.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    persona_id = args.persona

    print("PRACTICE MODE ONLY — GRAPH RUNNER")
    print(f"Persona: {persona_id}")
    print(f"LangGraph available: {is_langgraph_available()}")
    if args.no_langgraph:
        print("Using fallback runner (--no-langgraph)")
    print()

    settings = load_settings()
    client = DealRoomClient(settings)
    log_dir = ROOT / "logs" / "graph"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{persona_id}.jsonl"
    if log_path.exists():
        log_path.unlink()

    ctx = GraphContext(deal_room=client)
    runner = GraphRunner(ctx, prefer_langgraph=not args.no_langgraph)

    start = client.start_match(practice=True, persona_id=persona_id)
    if not isinstance(start, MatchStartResponse):
        print("Unexpected: match did not start.")
        return 1

    print(f"Match ID: {start.match_id}")
    print(f"Scenario: {start.scenario.name} — {start.scenario.brief}")
    print(f"\nBuyer: {start.buyer.text}\n")

    result = runner.run(start, persona_id=persona_id, log_path=log_path)
    outcome = result.outcome

    print("\n" + "=" * 60)
    print("--- Result ---")
    print(f"Closed:        {outcome.closed}")
    print(f"Walked:        {outcome.walked}")
    print(f"Seller rounds: {outcome.seller_rounds}")
    print(f"End reason:    {outcome.end_reason}")
    print(f"LangGraph:     {result.used_langgraph}")
    print(f"Log:           {log_path}")
    print("=" * 60)
    return 0 if outcome.closed else 1


if __name__ == "__main__":
    raise SystemExit(main())
