#!/usr/bin/env python3
"""Search TravelSupermarket package holidays and print normalized candidates.

Saves raw + normalized results to logs/holiday_search.json.
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

from dealbreakers.mcp import TravelSupermarketClient

MONTH_NUMBERS = {
    "january": "1", "february": "2", "march": "3", "april": "4",
    "may": "5", "june": "6", "july": "7", "august": "8",
    "september": "9", "october": "10", "november": "11", "december": "12",
}

OUTPUT_PATH = ROOT / "logs" / "holiday_search.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", default="Spain")
    parser.add_argument("--month", default="July", help="Month name or number(s), e.g. July or 7 or 6,7,8")
    parser.add_argument("--duration", type=int, default=7, help="Nights")
    parser.add_argument("--stars", type=int, default=None, help="Star rating, e.g. 4")
    parser.add_argument("--board", default=None, help="Board basis codes, e.g. AI or AI,HB")
    parser.add_argument("--max-price", type=float, default=None, help="Max per-person price (GBP)")
    parser.add_argument("--limit", type=int, default=10)
    return parser.parse_args()


def month_to_numbers(value: str) -> str:
    parts = [part.strip() for part in value.split(",")]
    return ",".join(MONTH_NUMBERS.get(part.lower(), part) for part in parts)


def main() -> int:
    args = parse_args()
    month = month_to_numbers(args.month)

    print(
        f"Searching TravelSupermarket: destination={args.destination}, "
        f"month={month}, duration={args.duration}, stars={args.stars}, "
        f"board={args.board}, max_price={args.max_price}, limit={args.limit}\n"
    )

    client = TravelSupermarketClient()
    candidates = client.search_holidays(
        destination=args.destination,
        month=month,
        duration=args.duration,
        board=args.board,
        stars=args.stars,
        max_price=args.max_price,
        limit=args.limit,
    )

    offerable = [candidate for candidate in candidates if candidate.is_offerable]
    print(f"Found {len(candidates)} candidates ({len(offerable)} offerable)\n")

    for index, candidate in enumerate(candidates, 1):
        summary = {key: value for key, value in asdict(candidate).items() if key != "raw"}
        print(f"--- Candidate {index} {'(offerable)' if candidate.is_offerable else ''}")
        print(json.dumps(summary, indent=2, ensure_ascii=False))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "query": vars(args),
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
