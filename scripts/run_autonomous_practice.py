#!/usr/bin/env python3
"""Phase 7C: autonomous policy-driven practice matches.

PRACTICE MODE ONLY. Uses LiveNegotiationAgent — no hardcoded persona flows.
"""

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
from dealbreakers.logging import TranscriptRecorder
from dealbreakers.models.match import MatchStartResponse
from dealbreakers.negotiation.live_agent import LiveNegotiationAgent

ALLOWED_PERSONAS = frozenset(PRACTICE_PERSONAS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run autonomous practice negotiation.")
    parser.add_argument(
        "--persona",
        required=True,
        choices=sorted(ALLOWED_PERSONAS),
        help="Practice persona id (whitelist only).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    persona_id = args.persona

    print("PRACTICE MODE ONLY — AUTONOMOUS AGENT")
    print(f"Persona: {persona_id}\n")

    settings = load_settings()
    client = DealRoomClient(settings)
    log_dir = ROOT / "logs" / "autonomous"
    log_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = log_dir / f"{persona_id}.jsonl"

    agent = LiveNegotiationAgent(
        deal_room=client,
        recorder=TranscriptRecorder(path=transcript_path),
        log_path=transcript_path,
        verbose=True,
    )

    start = client.start_match(practice=True, persona_id=persona_id)
    if not isinstance(start, MatchStartResponse):
        print("Unexpected: match did not start.")
        return 1

    print(f"Match ID: {start.match_id}")
    print(f"Scenario: {start.scenario.name} — {start.scenario.brief}")
    print(f"\nBuyer: {start.buyer.text}\n")

    outcome = agent.run(start, persona_id=persona_id)

    print("\n" + "=" * 60)
    print("--- Result ---")
    print(f"Closed:       {outcome.closed}")
    print(f"Walked:       {outcome.walked}")
    print(f"Seller rounds: {outcome.seller_rounds}")
    print(f"End reason:   {outcome.end_reason}")
    print(f"Log:          {transcript_path}")
    print("=" * 60)
    return 0 if outcome.closed else 1


if __name__ == "__main__":
    raise SystemExit(main())
