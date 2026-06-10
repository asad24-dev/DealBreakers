#!/usr/bin/env python3
"""Run a single practice discovery turn against the live Deal Room API."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dealbreakers.api import DealRoomClient
from dealbreakers.config import load_settings
from dealbreakers.constants import PRACTICE_PERSONAS
from dealbreakers.logging import TranscriptRecorder
from dealbreakers.models.match import MatchStartResponse

DISCOVERY_QUESTION = (
    "Thanks for reaching out! To find the perfect trip for you, "
    "could you tell me when you're hoping to travel and how many people are going?"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--persona",
        default="practice-bob",
        choices=sorted(PRACTICE_PERSONAS),
        help="Practice persona to match against",
    )
    parser.add_argument(
        "--log",
        default="logs/runs.jsonl",
        help="Path to the JSONL transcript log",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = load_settings()
    client = DealRoomClient(settings)
    recorder = TranscriptRecorder(path=args.log)

    print(f"Starting practice match: {args.persona}")
    start = client.start_match(practice=True, persona_id=args.persona)

    if not isinstance(start, MatchStartResponse):
        print("All official matches are done.")
        return 0

    print(f"\nMatch ID: {start.match_id}")
    print(f"Scenario: {start.scenario.name}")
    print(f"Brief: {start.scenario.brief}")
    print(f"\nBuyer: {start.buyer.text}")

    recorder.record_match_started(start, practice=True, persona_id=args.persona)
    recorder.record_buyer_message(
        start.match_id,
        start.buyer,
        scenario_name=start.scenario.name,
        persona_id=args.persona,
    )

    print(f"\nSeller: {DISCOVERY_QUESTION}")
    turn = client.send_turn(start.match_id, DISCOVERY_QUESTION)

    recorder.record_seller_message(start.match_id, DISCOVERY_QUESTION, round_number=1)
    recorder.record_turn_response(start.match_id, turn)

    print(f"\nBuyer: {turn.buyer.text}")
    if turn.quote:
        print(
            f"\nQuote — cost: {turn.quote.cost}, "
            f"markup: {turn.quote.markup_pct}%, total: {turn.quote.total}"
        )

    print(f"\nTranscript saved to {args.log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
