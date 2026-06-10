#!/usr/bin/env python3
"""Live car hire search CLI (read-only MCP)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dealbreakers.mcp.cars import CarSearchClient

DEFAULT_LOG = ROOT / "logs" / "car_search.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search car hire via MCP.")
    parser.add_argument("--location", required=True, help="City or IATA code (not 'Airport').")
    parser.add_argument("--pickup-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--dropoff-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--driver-age", type=int, default=30)
    parser.add_argument("--premium", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--out", default=str(DEFAULT_LOG))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    client = CarSearchClient()
    candidates = client.search_cars(
        args.location,
        args.pickup_date,
        args.dropoff_date,
        driver_age=args.driver_age,
        premium=args.premium,
        limit=args.limit,
    )
    offerable = [candidate for candidate in candidates if candidate.is_offerable]
    payload = {
        "location": args.location,
        "pickup_date": args.pickup_date,
        "dropoff_date": args.dropoff_date,
        "premium": args.premium,
        "total": len(candidates),
        "offerable": len(offerable),
        "errors": client.last_errors,
        "candidates": [
            {
                **{key: getattr(candidate, key) for key in (
                    "vehicle_name", "url", "price_total", "category",
                    "transmission", "seats", "supplier", "source_mcp",
                )},
                "is_offerable": candidate.is_offerable,
            }
            for candidate in candidates
        ],
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"Location: {args.location}")
    print(f"Results: {len(candidates)} total, {len(offerable)} offerable")
    if client.last_errors:
        print(f"Errors: {'; '.join(client.last_errors)}")
    for candidate in offerable[:5]:
        print(
            f"  - {candidate.vehicle_name or candidate.category} "
            f"({candidate.source_mcp}) £{candidate.price_total}"
        )
    print(f"\nSaved to {out_path}")
    return 0 if offerable else 1


if __name__ == "__main__":
    raise SystemExit(main())
