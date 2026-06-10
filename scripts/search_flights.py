#!/usr/bin/env python3
"""Live flight search CLI via Kiwi MCP (read-only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dealbreakers.mcp.kiwi import KiwiClient

DEFAULT_LOG = ROOT / "logs" / "flight_search.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search flights via Kiwi MCP.")
    parser.add_argument("--from", dest="fly_from", default="LON")
    parser.add_argument("--to", dest="fly_to", required=True)
    parser.add_argument("--departure-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--return-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--adults", type=int, default=1)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--out", default=str(DEFAULT_LOG))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = KiwiClient()
    candidates = client.search_flights(
        fly_from=args.fly_from,
        fly_to=args.fly_to,
        departure_date=args.departure_date,
        return_date=args.return_date,
        adults=args.adults,
        limit=args.limit,
    )
    offerable = [c for c in candidates if c.is_offerable]
    payload = {
        "fly_from": args.fly_from,
        "fly_to": args.fly_to,
        "departure_date": args.departure_date,
        "return_date": args.return_date,
        "total": len(candidates),
        "offerable": len(offerable),
        "errors": client.last_errors,
        "candidates": [
            {
                "route": c.route,
                "carrier": c.carrier,
                "url": c.url,
                "price_total": c.price_total,
                "origin": c.origin,
                "destination": c.destination,
                "is_offerable": c.is_offerable,
            }
            for c in candidates
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Route: {args.fly_from} -> {args.fly_to}")
    print(f"Offerable: {len(offerable)}/{len(candidates)}")
    if client.last_errors:
        print(f"Errors: {'; '.join(client.last_errors)}")
    for candidate in offerable[:5]:
        print(
            f"  - {candidate.route} | {candidate.carrier} | "
            f"£{candidate.price_total} | {candidate.url}"
        )
    print(f"Saved: {out}")
    return 0 if offerable else 1


if __name__ == "__main__":
    raise SystemExit(main())
