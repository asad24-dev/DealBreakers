#!/usr/bin/env python3
"""Search TourRadar guided tours and print normalized candidates.

Saves raw + normalized results to logs/tour_search.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dealbreakers.mcp import TourRadarClient

OUTPUT_PATH = ROOT / "logs" / "tour_search.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="guided tour of Spain")
    parser.add_argument("--country", default="Spain")
    parser.add_argument("--min-days", type=int, default=None)
    parser.add_argument("--max-days", type=int, default=None)
    parser.add_argument("--max-price", type=float, default=None)
    parser.add_argument("--limit", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(
        f"Searching TourRadar: query={args.query!r}, country={args.country}, "
        f"min_days={args.min_days}, max_days={args.max_days}, "
        f"max_price={args.max_price}, limit={args.limit}\n"
    )

    client = TourRadarClient()
    candidates = client.search_tours(
        query=args.query,
        country=args.country,
        min_days=args.min_days,
        max_days=args.max_days,
        max_price=args.max_price,
        limit=args.limit,
    )

    offerable = [candidate for candidate in candidates if candidate.is_offerable]
    print(f"Found {len(candidates)} candidates ({len(offerable)} offerable)\n")

    if not offerable:
        print("No offerable candidates.")
        if candidates:
            print("Top non-offerable reasons:")
            for candidate in candidates[:3]:
                missing = []
                if candidate.price_total is None:
                    missing.append("price_total")
                if not candidate.url:
                    missing.append("url")
                print(f"  - {candidate.name!r}: missing {', '.join(missing)}")

    for index, candidate in enumerate(candidates, 1):
        summary = {key: value for key, value in asdict(candidate).items() if key != "raw"}
        print(f"--- Candidate {index} {'(offerable)' if candidate.is_offerable else ''}")
        print(json.dumps(summary, indent=2, ensure_ascii=False))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "query": vars(args),
                "offerable_count": len(offerable),
                "candidates": [asdict(candidate) for candidate in candidates],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nSaved raw + normalized results to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
