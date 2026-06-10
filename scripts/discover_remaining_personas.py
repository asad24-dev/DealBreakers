#!/usr/bin/env python3
"""Phase 8B: multi-turn discovery for practice-elon, practice-gordon, practice-cris.

PRACTICE MODE ONLY — PERSONA DISCOVERY

Runs 3-5 discovery turns per persona. Uses ConversationAnalyzer and BuyerState
after every turn. No offers sent — information gathering only.

Does NOT touch practice-bob or practice-toni (already closed).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dealbreakers.analysis import ConversationAnalyzer  # noqa: E402
from dealbreakers.api import DealRoomClient  # noqa: E402
from dealbreakers.config import load_settings  # noqa: E402
from dealbreakers.experiments.persona_discovery import (  # noqa: E402
    TARGET_PERSONAS,
    discover_remaining_personas,
    profile_to_summary,
    run_discovery_session,
)

PROFILES_DIR = "logs/persona_profiles"
SUMMARY_PATH = "logs/persona_summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Discover unknown practice personas (no offers).")
    parser.add_argument(
        "--persona",
        choices=list(TARGET_PERSONAS),
        default=None,
        help="Run discovery for one persona only (default: all three)",
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=4,
        help="Discovery turns per persona (3-5 recommended)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.turns < 1 or args.turns > 5:
        print("--turns must be between 1 and 5")
        return 1

    print("PRACTICE MODE ONLY — PERSONA DISCOVERY")
    print(f"Targets: {', '.join(TARGET_PERSONAS)}")
    print(f"Turns per persona: {args.turns}\n")

    settings = load_settings()
    client = DealRoomClient(settings)
    analyzer = ConversationAnalyzer()

    if args.persona:
        profile = run_discovery_session(
            args.persona,
            client=client,
            analyzer=analyzer,
            profiles_dir=PROFILES_DIR,
            num_turns=args.turns,
        )
        summary = {args.persona: profile_to_summary(profile)}
        Path(SUMMARY_PATH).write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        print(f"\nProfile: {PROFILES_DIR}/{args.persona}.json")
        print(f"Transcript: {PROFILES_DIR}/{args.persona}.jsonl")
        print(f"Summary: {SUMMARY_PATH}")
        return 0

    summary = discover_remaining_personas(
        client=client,
        analyzer=analyzer,
        profiles_dir=PROFILES_DIR,
        summary_path=SUMMARY_PATH,
        num_turns=args.turns,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nProfiles saved under {PROFILES_DIR}/")
    print(f"Summary: {SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
