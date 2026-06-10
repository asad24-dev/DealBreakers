#!/usr/bin/env python3
"""Full persona evaluation across live, graph, and graph+bandit runners (Phase 8G)."""

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
from dealbreakers.evaluation.failure_classification import FailureCategory, classify_failure
from dealbreakers.evaluation.scoring import compute_estimated_score, summarize_runs
from dealbreakers.graph.context import GraphContext
from dealbreakers.graph.runner import GraphRunner
from dealbreakers.learning.bandit import BanditPolicy
from dealbreakers.models.match import MatchStartResponse
from dealbreakers.negotiation.live_agent import LiveNegotiationAgent, wants_car
from dealbreakers.personas.markup_profiles import save_profiles, load_profiles

PERSONAS = (
    "practice-bob",
    "practice-toni",
    "practice-cris",
    "practice-elon",
    "practice-gordon",
)
EVAL_DIR = ROOT / "logs" / "final_eval"
POLICY_PATH = ROOT / "logs" / "bandit_policy.json"
RUNNER_SUMMARY = {
    "live": "live_summary.json",
    "graph": "graph_summary.json",
    "graph-bandit": "graph_bandit_summary.json",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate all practice personas.")
    parser.add_argument("--runs", type=int, default=10, help="Runs per persona.")
    parser.add_argument(
        "--runner",
        choices=["live", "graph", "graph-bandit"],
        default="live",
        help="Runner to evaluate.",
    )
    parser.add_argument("--personas", nargs="*", default=list(PERSONAS))
    return parser.parse_args()


def _build_eval_row(
    *,
    persona_id: str,
    runner: str,
    run_idx: int,
    closed: bool,
    walked: bool,
    rounds: int,
    markup_pct: float | None,
    quote_total: float | None,
    cost: float | None,
    duration_mismatch: bool = False,
    offer_sent: bool = False,
    unresolved_car: bool = False,
    unresolved_requirement: bool = False,
    end_reason: str | None = None,
    error: str | None = None,
    review_score: float | None = None,
    car_required: bool = False,
    car_present: bool = False,
    duration_matched: bool = True,
    must_haves_matched: bool = True,
    luxury_satisfied: bool = False,
) -> dict:
    estimated = compute_estimated_score(
        closed=closed,
        walked=walked,
        markup_pct=markup_pct,
        must_haves_matched=must_haves_matched,
        duration_matched=duration_matched,
        car_required=car_required,
        car_present=car_present,
        review_score=review_score,
        luxury_satisfied=luxury_satisfied,
    )
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "persona_id": persona_id,
        "runner": runner,
        "run": run_idx,
        "closed": closed,
        "walked": walked,
        "rounds": rounds,
        "markup_pct": markup_pct,
        "quote_total": quote_total,
        "cost": cost,
        "duration_mismatch": duration_mismatch,
        "offer_sent": offer_sent,
        "unresolved_car": unresolved_car,
        "unresolved_requirement": unresolved_requirement,
        "end_reason": end_reason,
        "error": error,
        "estimated_score": estimated,
    }
    row["failure_category"] = classify_failure(row).value
    return row


def _run_live(client: DealRoomClient, persona_id: str, run_idx: int) -> dict:
    agent = LiveNegotiationAgent(deal_room=client, verbose=False)
    start = client.start_match(practice=True, persona_id=persona_id)
    if not isinstance(start, MatchStartResponse):
        return _build_eval_row(
            persona_id=persona_id,
            runner="live",
            run_idx=run_idx,
            closed=False,
            walked=False,
            rounds=0,
            markup_pct=None,
            quote_total=None,
            cost=None,
            error="start_failed",
        )
    outcome = agent.run(start, persona_id=persona_id)
    ctx = agent.last_run_context
    return _build_eval_row(
        persona_id=persona_id,
        runner="live",
        run_idx=run_idx,
        closed=outcome.closed,
        walked=outcome.walked,
        rounds=outcome.seller_rounds,
        markup_pct=ctx.get("final_markup_pct"),
        quote_total=ctx.get("quote_total"),
        cost=ctx.get("cost"),
        duration_mismatch=bool(ctx.get("duration_mismatch")),
        offer_sent=bool(ctx.get("offer_sent")),
        unresolved_car=bool(ctx.get("unresolved_car")),
        unresolved_requirement=bool(ctx.get("unresolved_requirement")),
        end_reason=outcome.end_reason,
        duration_matched=not bool(ctx.get("duration_mismatch")),
        car_required=False,
    )


def _run_graph(
    client: DealRoomClient,
    persona_id: str,
    run_idx: int,
    *,
    bandit: BanditPolicy | None = None,
    runner_name: str,
) -> dict:
    ctx = GraphContext(deal_room=client)
    graph_runner = GraphRunner(ctx, prefer_langgraph=False)
    start = client.start_match(practice=True, persona_id=persona_id)
    if not isinstance(start, MatchStartResponse):
        return _build_eval_row(
            persona_id=persona_id,
            runner=runner_name,
            run_idx=run_idx,
            closed=False,
            walked=False,
            rounds=0,
            markup_pct=None,
            quote_total=None,
            cost=None,
            error="start_failed",
        )
    result = graph_runner.run(
        start,
        persona_id=persona_id,
        bandit_policy=bandit,
        bandit_epsilon=0.0,
    )
    markup = result.state.markup_pct or ctx.buyer_state.last_markup_pct
    review_score = (
        ctx.inventory.selected_holiday.review_score
        if ctx.inventory.selected_holiday
        else None
    )
    car_required = wants_car(ctx.buyer_state, result.state.latest_buyer_message)
    car_present = (
        ctx.inventory.selected_car is not None
        or (
            ctx.inventory.last_offer is not None
            and ctx.inventory.last_offer.car is not None
        )
    )
    return _build_eval_row(
        persona_id=persona_id,
        runner=runner_name,
        run_idx=run_idx,
        closed=result.outcome.closed,
        walked=result.outcome.walked,
        rounds=result.outcome.seller_rounds,
        markup_pct=markup,
        quote_total=ctx.buyer_state.last_offer_total,
        cost=ctx.buyer_state.last_offer_cost,
        duration_mismatch=ctx.session.duration_mismatch,
        offer_sent=bool(result.state.offer or ctx.inventory.last_offer),
        unresolved_car="car" in ctx.session.unresolved_requirements and car_required,
        unresolved_requirement=bool(ctx.session.unresolved_requirements),
        end_reason=result.outcome.end_reason,
        review_score=review_score,
        car_required=car_required,
        car_present=car_present,
        duration_matched=not ctx.session.duration_mismatch,
    )


def main() -> int:
    args = parse_args()
    settings = load_settings()
    client = DealRoomClient(settings)
    EVAL_DIR.mkdir(parents=True, exist_ok=True)

    profiles = load_profiles()
    save_profiles(profiles)

    bandit = BanditPolicy.load(POLICY_PATH) if POLICY_PATH.exists() else BanditPolicy()
    all_runs_path = EVAL_DIR / "all_runs.jsonl"

    summary: dict[str, dict] = {}
    new_rows: list[dict] = []

    for persona_id in args.personas:
        runs: list[dict] = []
        for run_idx in range(1, args.runs + 1):
            if args.runner == "live":
                row = _run_live(client, persona_id, run_idx)
            elif args.runner == "graph":
                row = _run_graph(client, persona_id, run_idx, runner_name="graph")
            else:
                row = _run_graph(
                    client,
                    persona_id,
                    run_idx,
                    bandit=bandit,
                    runner_name="graph-bandit",
                )
            runs.append(row)
            new_rows.append(row)
            print(
                f"{persona_id} run {run_idx}: closed={row['closed']} "
                f"walked={row['walked']} score={row['estimated_score']} "
                f"fail={row['failure_category']}"
            )

        metrics = summarize_runs(runs)
        gordon_ok = persona_id == "practice-gordon" and any(
            classify_failure(r) in (
                FailureCategory.CLOSED,
                FailureCategory.DURATION_MISMATCH,
                FailureCategory.INVENTORY_OR_PRICE_FLOOR,
                FailureCategory.INVENTORY_UNAVAILABLE,
            )
            for r in runs
        )
        metrics["gordon_inventory_limited_ok"] = gordon_ok
        summary[persona_id] = metrics

    summary_payload = {
        "runner": args.runner,
        "runs_per_persona": args.runs,
        "personas": list(args.personas),
        "practice_only": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "personas_summary": summary,
    }

    out_name = RUNNER_SUMMARY[args.runner]
    summary_path = EVAL_DIR / out_name
    summary_path.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")

    with all_runs_path.open("a", encoding="utf-8") as handle:
        for row in new_rows:
            handle.write(json.dumps(row) + "\n")

    print(f"\nSummary: {summary_path}")
    print(f"All runs: {all_runs_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
