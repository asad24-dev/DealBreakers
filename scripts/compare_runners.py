#!/usr/bin/env python3
"""Compare live agent, graph runner, and graph + bandit exploit (Phase 8F)."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dealbreakers.api import DealRoomClient
from dealbreakers.config import load_settings
from dealbreakers.graph.context import GraphContext
from dealbreakers.graph.runner import GraphRunner
from dealbreakers.learning.bandit import BanditPolicy, compute_reward
from dealbreakers.models.match import MatchStartResponse
from dealbreakers.evaluation.failure_classification import classify_failure
from dealbreakers.negotiation.live_agent import LiveNegotiationAgent, wants_car

PERSONAS = (
    "practice-bob",
    "practice-toni",
    "practice-cris",
    "practice-gordon",
    "practice-elon",
)
DEFAULT_OUT = ROOT / "logs" / "all_persona_comparison.json"
POLICY_PATH = ROOT / "logs" / "bandit_policy.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare negotiation runners.")
    parser.add_argument("--runs", type=int, default=3, help="Runs per persona per runner.")
    parser.add_argument("--personas", nargs="*", default=list(PERSONAS))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    return parser.parse_args()


def _failure_reason(row: dict) -> str:
    return classify_failure(row).value


def _metrics(rows: list[dict]) -> dict:
    if not rows:
        return {
            "close_rate": 0.0,
            "walk_rate": 0.0,
            "avg_markup": None,
            "avg_rounds": 0.0,
            "avg_reward": 0.0,
            "avg_quote_total": None,
        }
    markups = [r["markup"] for r in rows if r.get("markup") is not None]
    quotes = [r["quote_total"] for r in rows if r.get("quote_total") is not None]
    return {
        "close_rate": round(sum(1 for r in rows if r.get("closed")) / len(rows), 3),
        "walk_rate": round(sum(1 for r in rows if r.get("walked")) / len(rows), 3),
        "avg_markup": round(statistics.mean(markups), 2) if markups else None,
        "avg_rounds": round(statistics.mean(r.get("rounds", 0) for r in rows), 2),
        "avg_reward": round(statistics.mean(r.get("reward", 0) for r in rows), 2),
        "avg_quote_total": round(statistics.mean(quotes), 2) if quotes else None,
    }


def _failure_summary(rows: list[dict]) -> str:
    reasons = [_failure_reason(row) for row in rows]
    if not reasons:
        return "unknown"
    return max(set(reasons), key=reasons.count)


def _reward_row(
    outcome,
    buyer_state,
    session,
    inventory,
    latest_message: str,
    markup,
    quote_total,
) -> float:
    review_score = inventory.selected_holiday.review_score if inventory.selected_holiday else None
    return compute_reward(
        closed=outcome.closed,
        walked=outcome.walked,
        markup_pct=markup,
        offer_total=quote_total or buyer_state.last_offer_total,
        duration_matched=not session.duration_mismatch,
        car_required=wants_car(buyer_state, latest_message),
        car_present=inventory.selected_car is not None
        or (inventory.last_offer is not None and inventory.last_offer.car is not None),
        review_score=review_score,
    )


def _run_live(client: DealRoomClient, persona_id: str) -> dict:
    agent = LiveNegotiationAgent(deal_room=client, verbose=False)
    start = client.start_match(practice=True, persona_id=persona_id)
    if not isinstance(start, MatchStartResponse):
        return {"error": "start_failed", "failure_reason": "error"}
    outcome = agent.run(start, persona_id=persona_id)
    ctx = agent.last_run_context
    row = {
        "closed": outcome.closed,
        "walked": outcome.walked,
        "rounds": outcome.seller_rounds,
        "markup": ctx.get("final_markup_pct"),
        "quote_total": ctx.get("quote_total"),
        "offer_sent": bool(ctx.get("offer_sent")),
        "duration_mismatch": bool(ctx.get("duration_mismatch")),
        "final_markup_pct": ctx.get("final_markup_pct"),
        "unresolved_car": bool(ctx.get("unresolved_car")),
        "end_reason": outcome.end_reason,
    }
    row["failure_reason"] = _failure_reason(row)
    row["reward"] = 50.0 if outcome.closed else (-50.0 if outcome.walked else 0.0)
    return row


def _run_graph(
    client: DealRoomClient,
    persona_id: str,
    *,
    bandit: BanditPolicy | None = None,
) -> dict:
    ctx = GraphContext(deal_room=client)
    runner = GraphRunner(ctx, prefer_langgraph=False)
    start = client.start_match(practice=True, persona_id=persona_id)
    if not isinstance(start, MatchStartResponse):
        return {"error": "start_failed", "failure_reason": "error"}
    result = runner.run(
        start,
        persona_id=persona_id,
        bandit_policy=bandit,
        bandit_epsilon=0.0,
    )
    markup = result.state.markup_pct or ctx.buyer_state.last_markup_pct
    quote_total = ctx.buyer_state.last_offer_total
    reward = _reward_row(
        result.outcome,
        ctx.buyer_state,
        ctx.session,
        ctx.inventory,
        result.state.latest_buyer_message,
        markup,
        quote_total,
    )
    row = {
        "closed": result.outcome.closed,
        "walked": result.outcome.walked,
        "rounds": result.outcome.seller_rounds,
        "markup": markup,
        "quote_total": quote_total,
        "reward": reward,
        "offer_sent": bool(result.state.offer or ctx.inventory.last_offer),
        "duration_mismatch": ctx.session.duration_mismatch,
        "end_reason": result.outcome.end_reason,
    }
    row["failure_reason"] = _failure_reason(row)
    return row


def main() -> int:
    args = parse_args()
    settings = load_settings()
    client = DealRoomClient(settings)

    bandit = BanditPolicy.load(POLICY_PATH) if POLICY_PATH.exists() else BanditPolicy()

    comparison: dict[str, dict] = {}
    for persona_id in args.personas:
        live_rows: list[dict] = []
        graph_rows: list[dict] = []
        bandit_rows: list[dict] = []

        for _ in range(args.runs):
            live_rows.append(_run_live(client, persona_id))
            graph_rows.append(_run_graph(client, persona_id))
            bandit_rows.append(_run_graph(client, persona_id, bandit=bandit))

        comparison[persona_id] = {
            "live_agent": _metrics(live_rows),
            "graph_runner": _metrics(graph_rows),
            "graph_bandit_exploit": _metrics(bandit_rows),
            "failure_reason_summary": _failure_summary(live_rows),
            "runs": args.runs,
            "run_details": {
                "live_agent": live_rows,
                "graph_runner": graph_rows,
            },
        }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "personas": list(args.personas),
        "runs_per_persona": args.runs,
        "practice_only": True,
        "comparison": comparison,
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    alias = ROOT / "logs" / "runner_comparison.json"
    alias.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Comparison saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
