#!/usr/bin/env python3
"""Build a BuyerState from a transcript log + saved analysis and print it.

Example:
    python scripts/build_state.py --log logs/close_bob.jsonl --analysis logs/analysis.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dealbreakers.analysis.models import ConversationAnalysis
from dealbreakers.logging import read_jsonl
from dealbreakers.state import build_buyer_state, estimate_aggressive_markup, estimate_safe_markup


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", default="logs/close_bob.jsonl")
    parser.add_argument("--analysis", default="logs/analysis.json")
    parser.add_argument("--out", default="logs/buyer_state.json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    records = read_jsonl(args.log)
    if not records:
        print(f"No records found in {args.log}")
        return 1

    analysis = None
    analysis_path = Path(args.analysis)
    if analysis_path.exists():
        saved = json.loads(analysis_path.read_text(encoding="utf-8"))
        analysis = ConversationAnalysis.from_dict(saved.get("analysis", saved))

    state = build_buyer_state(records, analysis)
    result = state.to_dict()
    result["estimate_safe_markup"] = estimate_safe_markup(state)
    result["estimate_aggressive_markup"] = estimate_aggressive_markup(state)

    print(json.dumps(result, indent=2, ensure_ascii=False))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved buyer state to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
