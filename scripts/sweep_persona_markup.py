#!/usr/bin/env python3
"""Practice-only markup sweep for a single persona (Phase 8G)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dealbreakers.api import DealRoomClient
from dealbreakers.config import load_settings
from dealbreakers.models.match import MatchStartResponse
from dealbreakers.negotiation.live_agent import LiveNegotiationAgent
from dealbreakers.personas.markup_profiles import load_profiles, save_profiles

SWEEP_DIR = ROOT / "logs" / "markup_sweeps"
DEFAULT_MARKUPS = {
    "practice-cris": [18, 22, 25, 28, 30, 31, 32, 35],
    "practice-toni": [12, 15, 18, 20, 25, 30],
    "practice-elon": [10, 12, 15, 18, 20, 25],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sweep markup for one practice persona.")
    parser.add_argument("--persona", required=True, help="Practice persona id.")
    parser.add_argument(
        "--markups",
        default="",
        help="Comma-separated markup percentages.",
    )
    return parser.parse_args()


def parse_markup_list(value: str) -> list[float]:
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not parts:
        raise ValueError("Empty markup list")
    return [float(part) for part in parts]


@dataclass
class SweepResult:
    persona_id: str
    opening_markup_pct: float
    accepted_markup_pct: float | None
    closed: bool
    walked: bool
    buyer_action: str | None
    rounds: int | None
    quote_total: float | None
    cost: float | None
    counter_used: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _run_single(
    client: DealRoomClient,
    persona_id: str,
    markup_pct: float,
) -> SweepResult:
    result = SweepResult(
        persona_id=persona_id,
        opening_markup_pct=markup_pct,
        accepted_markup_pct=None,
        closed=False,
        walked=False,
        buyer_action=None,
        rounds=None,
        quote_total=None,
        cost=None,
    )
    try:
        agent = LiveNegotiationAgent(deal_room=client, verbose=False)
        start = client.start_match(practice=True, persona_id=persona_id)
        if not isinstance(start, MatchStartResponse):
            result.error = "start_failed"
            return result
        outcome = agent.run(
            start,
            persona_id=persona_id,
            forced_opening_markup=markup_pct,
        )
        ctx = agent.last_run_context
        result.closed = outcome.closed
        result.walked = outcome.walked
        result.rounds = outcome.seller_rounds
        result.quote_total = ctx.get("quote_total")
        result.cost = ctx.get("cost")
        final_markup = ctx.get("final_markup_pct")
        result.accepted_markup_pct = final_markup if outcome.closed else None
        result.counter_used = (
            final_markup is not None
            and final_markup < markup_pct
            and outcome.closed
        )
        return result
    except Exception as exc:  # noqa: BLE001
        result.error = str(exc)
        return result


def _build_summary(results: list[SweepResult]) -> dict:
    valid = [r for r in results if r.error is None]
    direct = [r.opening_markup_pct for r in valid if r.closed and not r.counter_used]
    after_counter = [r.accepted_markup_pct for r in valid if r.closed and r.counter_used and r.accepted_markup_pct is not None]
    first_objection = next(
        (r.opening_markup_pct for r in valid if not r.closed and not r.walked),
        None,
    )
    first_walk = next((r.opening_markup_pct for r in valid if r.walked), None)
    highest_direct = max(direct) if direct else None
    highest_counter = max(after_counter) if after_counter else None
    recommended_opening = highest_direct or highest_counter
    recommended_floor = min(
        [r.accepted_markup_pct for r in valid if r.closed and r.accepted_markup_pct is not None],
        default=None,
    )
    return {
        "persona_id": results[0].persona_id if results else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "highest_direct_accept": highest_direct,
        "highest_after_counter_accept": highest_counter,
        "first_price_objection": first_objection,
        "first_walk": first_walk,
        "recommended_opening": recommended_opening,
        "recommended_floor": recommended_floor,
        "runs": [r.to_dict() for r in results],
    }


def _update_profiles(persona_id: str, summary: dict) -> None:
    profiles = load_profiles()
    if persona_id not in profiles:
        return
    profile = profiles[persona_id]
    opening = summary.get("recommended_opening")
    floor = summary.get("recommended_floor")
    if opening is not None:
        profile.aggressive = max(profile.aggressive, float(opening))
        profile.balanced = max(profile.balanced, min(float(opening), profile.aggressive))
    if floor is not None:
        profile.safe = min(profile.safe, float(floor))
    profile.notes.append(
        f"Sweep {datetime.now(timezone.utc).date()}: opening={opening}, floor={floor}"
    )
    save_profiles(profiles)


def main() -> int:
    args = parse_args()
    persona_id = args.persona
    if not persona_id.startswith("practice-"):
        print("Only practice personas are allowed.", file=sys.stderr)
        return 1

    markups = (
        parse_markup_list(args.markups)
        if args.markups
        else DEFAULT_MARKUPS.get(persona_id, [10, 12, 15, 18, 20, 25])
    )

    settings = load_settings()
    client = DealRoomClient(settings)
    SWEEP_DIR.mkdir(parents=True, exist_ok=True)

    results = [_run_single(client, persona_id, markup) for markup in markups]
    jsonl_path = SWEEP_DIR / f"{persona_id}.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result.to_dict()) + "\n")

    summary = _build_summary(results)
    summary_path = SWEEP_DIR / f"{persona_id}_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _update_profiles(persona_id, summary)

    print(f"Sweep saved: {jsonl_path}")
    print(f"Summary: {summary_path}")
    print(
        f"highest_direct={summary['highest_direct_accept']} "
        f"recommended_opening={summary['recommended_opening']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
