#!/usr/bin/env python3
"""Phase 8E: practice-only bandit training over graph runner."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dealbreakers.api import DealRoomClient
from dealbreakers.config import load_settings
from dealbreakers.constants import PRACTICE_PERSONAS
from dealbreakers.graph.context import GraphContext
from dealbreakers.graph.runner import GraphRunner
from dealbreakers.learning.bandit import BanditPolicy, compute_reward
from dealbreakers.models.match import MatchStartResponse
from dealbreakers.negotiation.live_agent import wants_car

LOG_DIR = ROOT / "logs"
POLICY_PATH = LOG_DIR / "bandit_policy.json"
RUNS_PATH = LOG_DIR / "bandit_runs.jsonl"
SUMMARY_PATH = LOG_DIR / "bandit_summary.json"

DEFAULT_PERSONAS = ("practice-bob", "practice-toni", "practice-cris", "practice-gordon")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train bandit policy on practice matches only.")
    parser.add_argument(
        "--personas",
        default=",".join(DEFAULT_PERSONAS),
        help="Comma-separated practice persona ids.",
    )
    parser.add_argument("--runs", type=int, default=20, help="Total training runs.")
    parser.add_argument("--epsilon", type=float, default=0.1, help="Exploration rate.")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def _validate_personas(personas: list[str]) -> list[str]:
    allowed = set(PRACTICE_PERSONAS)
    for persona in personas:
        if persona not in allowed:
            raise SystemExit(f"Persona {persona!r} is not in practice whitelist.")
    return personas


def _reward_from_run(outcome, state, ctx) -> float:
    offer_total = ctx.buyer_state.last_offer_total
    markup = state.markup_pct or ctx.buyer_state.last_markup_pct
    review_score = None
    if ctx.inventory.selected_holiday:
        review_score = ctx.inventory.selected_holiday.review_score
    duration_matched = not ctx.session.duration_mismatch
    car_required = wants_car(ctx.buyer_state, state.latest_buyer_message)
    car_present = ctx.inventory.selected_car is not None or (
        ctx.inventory.last_offer is not None and ctx.inventory.last_offer.car is not None
    )
    return compute_reward(
        closed=outcome.closed,
        walked=outcome.walked,
        markup_pct=markup,
        offer_total=offer_total,
        must_haves_matched=True,
        review_score=review_score,
        duration_matched=duration_matched,
        car_required=car_required,
        car_present=car_present,
    )


def main() -> int:
    args = parse_args()
    personas = _validate_personas([p.strip() for p in args.personas.split(",") if p.strip()])

    print("PRACTICE-ONLY BANDIT TRAINING")
    print(f"Personas: {personas}")
    print(f"Runs: {args.runs}, epsilon: {args.epsilon}\n")

    settings = load_settings()
    client = DealRoomClient(settings)
    policy = BanditPolicy()
    policy._rng.seed(args.seed)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if RUNS_PATH.exists():
        RUNS_PATH.unlink()

    run_records: list[dict] = []

    for run_idx in range(1, args.runs + 1):
        persona_id = personas[(run_idx - 1) % len(personas)]
        ctx = GraphContext(deal_room=client)
        runner = GraphRunner(ctx, prefer_langgraph=False)

        start = client.start_match(practice=True, persona_id=persona_id)
        if not isinstance(start, MatchStartResponse):
            run_records.append({"run": run_idx, "persona": persona_id, "error": "start_failed"})
            continue

        result = runner.run(
            start,
            persona_id=persona_id,
            bandit_policy=policy,
            bandit_epsilon=args.epsilon,
        )
        reward = _reward_from_run(result.outcome, result.state, ctx)

        chosen_arms = [ctx.markup_arm, ctx.search_arm, ctx.counter_arm]
        for arm in chosen_arms:
            if arm is not None:
                policy.update_arm(arm, reward)

        record = {
            "run": run_idx,
            "persona": persona_id,
            "closed": result.outcome.closed,
            "walked": result.outcome.walked,
            "rounds": result.outcome.seller_rounds,
            "reward": reward,
            "markup_arm": ctx.markup_arm.name if ctx.markup_arm else None,
            "search_arm": ctx.search_arm.name if ctx.search_arm else None,
            "counter_arm": ctx.counter_arm.name if ctx.counter_arm else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        run_records.append(record)
        with RUNS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")

        print(
            f"Run {run_idx}/{args.runs} {persona_id}: "
            f"closed={result.outcome.closed} reward={reward:.1f}"
        )

    policy.save(POLICY_PATH)

    summary = {
        "runs": args.runs,
        "epsilon": args.epsilon,
        "personas": personas,
        "practice_only": True,
        "avg_reward": round(
            sum(r["reward"] for r in run_records if "reward" in r) / max(len(run_records), 1),
            2,
        ),
        "close_rate": round(
            sum(1 for r in run_records if r.get("closed")) / max(len(run_records), 1),
            3,
        ),
        "policy_path": str(POLICY_PATH),
        "arms": policy.to_dict()["arms"],
    }
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\nPolicy saved: {POLICY_PATH}")
    print(f"Runs log:     {RUNS_PATH}")
    print(f"Summary:      {SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
