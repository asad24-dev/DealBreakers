#!/usr/bin/env python3
"""Live hotel search CLI via Trivago MCP (read-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dealbreakers.mcp.trivago import TrivagoClient

DEFAULT_LOG = ROOT / "logs" / "hotel_search.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search hotels via Trivago MCP.")
    parser.add_argument("--city", required=True)
    parser.add_argument("--checkin-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--checkout-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--adults", type=int, default=1)
    parser.add_argument("--min-stars", type=int, default=None)
    parser.add_argument("--amenities", nargs="*", default=["wifi", "gym"])
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--out", default=str(DEFAULT_LOG))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = TrivagoClient()
    candidates = client.search_hotels(
        args.city,
        args.checkin_date,
        args.checkout_date,
        adults=args.adults,
        min_stars=args.min_stars,
        required_amenities=args.amenities or None,
        limit=args.limit,
    )
    offerable = [c for c in candidates if c.is_offerable]
    payload = {
        "city": args.city,
        "checkin_date": args.checkin_date,
        "checkout_date": args.checkout_date,
        "total": len(candidates),
        "offerable": len(offerable),
        "errors": client.last_errors,
        "candidates": [
            {
                "hotel_name": c.hotel_name,
                "url": c.url,
                "star_rating": c.star_rating,
                "review_score": c.review_score,
                "price_total": c.price_total,
                "city": c.city,
                "amenities": c.amenities,
                "is_offerable": c.is_offerable,
            }
            for c in candidates
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"City: {args.city}")
    print(f"Offerable: {len(offerable)}/{len(candidates)}")
    if client.last_errors:
        print(f"Errors: {'; '.join(client.last_errors)}")
    for candidate in offerable[:5]:
        print(
            f"  - {candidate.hotel_name} | {candidate.star_rating}* | "
            f"review {candidate.review_score} | £{candidate.price_total} | {candidate.url}"
        )
    print(f"Saved: {out}")
    return 0 if offerable else 1


if __name__ == "__main__":
    raise SystemExit(main())
