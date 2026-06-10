#!/usr/bin/env python3
"""Run the conversation analyzer on a JSONL transcript and save the result.

Example:
    python scripts/analyze_transcript.py --log logs/close_bob.jsonl --out logs/analysis.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dealbreakers.analysis import ConversationAnalyzer, events_from_log_records
from dealbreakers.logging import read_jsonl


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", default="logs/close_bob.jsonl", help="JSONL transcript to analyze")
    parser.add_argument("--out", default="logs/analysis.json", help="Where to save the analysis")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    records = read_jsonl(args.log)
    if not records:
        print(f"No records found in {args.log}")
        return 1

    events = events_from_log_records(records)
    print(f"Loaded {len(records)} log records -> {len(events)} transcript events\n")

    analysis = ConversationAnalyzer().analyze(events)
    result = analysis.to_dict()

    print(json.dumps(result, indent=2, ensure_ascii=False))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {"source_log": str(args.log), "events": len(events), "analysis": result},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved analysis to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
