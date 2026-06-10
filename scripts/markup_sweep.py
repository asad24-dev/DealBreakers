#!/usr/bin/env python3
"""Phase 6B: practice-only markup sweep against practice-bob.

PRACTICE MODE ONLY — MARKUP SWEEP

Hardwired to practice-bob. Tests multiple markup percentages using the same
TravelSupermarket offer flow to learn Bob's acceptance threshold.

No --official, --practice, or persona flags exist by design.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dealbreakers.experiments.markup_sweep import (  # noqa: E402
    DEFAULT_MARKUPS,
    PERSONA_ID,
    first_rejected_or_walked_markup,
    format_results_table,
    highest_accepted_markup,
    parse_markup_list,
    run_and_report,
)

TRANSCRIPT_PATH = "logs/markup_sweep.jsonl"
SUMMARY_PATH = "logs/markup_sweep_summary.json"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Practice-only markup sweep vs practice-bob (hardcoded persona)."
    )
    parser.add_argument(
        "--markups",
        type=str,
        default=None,
        help="Comma-separated markup percentages, e.g. 5,10,15,20",
    )
    args = parser.parse_args()

    markups = parse_markup_list(args.markups) if args.markups else list(DEFAULT_MARKUPS)

    print("PRACTICE MODE ONLY — MARKUP SWEEP")
    print(f"Persona: {PERSONA_ID} (hardcoded)")
    print(f"Markups: {markups}\n")

    results = run_and_report(
        markups,
        transcript_path=TRANSCRIPT_PATH,
        summary_path=SUMMARY_PATH,
    )

    print(format_results_table(results))
    print()

    highest = highest_accepted_markup(results)
    if highest is not None:
        print(f"Highest accepted markup: {highest:g}%")
    else:
        print("Highest accepted markup: none")

    first_fail = first_rejected_or_walked_markup(results)
    if first_fail is not None:
        print(f"First rejected/walked markup: {first_fail:g}%")
    else:
        print("First rejected/walked markup: none (all accepted)")

    print(f"\nTranscript: {TRANSCRIPT_PATH}")
    print(f"Summary: {SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
