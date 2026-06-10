"""Scoring and metrics for practice evaluation (Phase 8G)."""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass
from typing import Any

from dealbreakers.evaluation.failure_classification import FailureCategory, classify_failure


@dataclass
class RunMetrics:
    closed: bool = False
    walked: bool = False
    rounds: int = 0
    markup_pct: float | None = None
    quote_total: float | None = None
    cost: float | None = None
    estimated_score: float = 0.0
    failure_category: str = "unknown"


def compute_estimated_score(
    *,
    closed: bool,
    walked: bool = False,
    markup_pct: float | None = None,
    must_haves_matched: bool = True,
    duration_matched: bool = True,
    car_required: bool = False,
    car_present: bool = False,
    review_score: float | None = None,
    luxury_satisfied: bool = False,
) -> float:
    """Competition-style estimated score per Phase 8G spec."""
    close_points = 50.0 if closed else 0.0
    margin_proxy = 0.0
    if markup_pct is not None and markup_pct > 0:
        margin_proxy = min(30.0, (markup_pct / 35.0) * 30.0)

    satisfaction = 0.0
    if must_haves_matched:
        satisfaction += 8.0
    if duration_matched:
        satisfaction += 4.0
    if car_required:
        if car_present:
            satisfaction += 4.0
    else:
        satisfaction += 4.0
    if (review_score is not None and review_score >= 8.5) or luxury_satisfied:
        satisfaction += 4.0
    if not duration_matched:
        satisfaction -= 10.0
    if car_required and not car_present:
        satisfaction -= 10.0

    satisfaction = max(-20.0, min(20.0, satisfaction))
    return round(close_points + margin_proxy + satisfaction, 2)


def summarize_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate metrics for a persona's runs."""
    if not runs:
        return {
            "close_rate": 0.0,
            "walk_rate": 0.0,
            "continue_or_round_cap_rate": 0.0,
            "avg_rounds": 0.0,
            "avg_markup": None,
            "median_markup": None,
            "avg_quote_total": None,
            "avg_cost": None,
            "avg_profit": None,
            "avg_estimated_score": 0.0,
            "common_failure_reason": "unknown",
        }

    categories = [classify_failure(run).value for run in runs]
    common_failure = Counter(categories).most_common(1)[0][0]

    markups = [r["markup_pct"] for r in runs if r.get("markup_pct") is not None]
    quotes = [r["quote_total"] for r in runs if r.get("quote_total") is not None]
    costs = [r["cost"] for r in runs if r.get("cost") is not None]
    profits = [
        r["quote_total"] - r["cost"]
        for r in runs
        if r.get("quote_total") is not None and r.get("cost") is not None
    ]
    scores = [r.get("estimated_score", 0.0) for r in runs]
    rounds = [r.get("rounds", 0) for r in runs]

    closed_count = sum(1 for r in runs if r.get("closed"))
    walked_count = sum(1 for r in runs if r.get("walked"))
    round_cap_count = sum(
        1 for r in runs if classify_failure(r) == FailureCategory.ROUND_CAP
    )
    continue_count = len(runs) - closed_count - walked_count - round_cap_count

    return {
        "close_rate": round(closed_count / len(runs), 3),
        "walk_rate": round(walked_count / len(runs), 3),
        "continue_or_round_cap_rate": round(
            (continue_count + round_cap_count) / len(runs), 3
        ),
        "avg_rounds": round(statistics.mean(rounds), 2) if rounds else 0.0,
        "avg_markup": round(statistics.mean(markups), 2) if markups else None,
        "median_markup": round(statistics.median(markups), 2) if markups else None,
        "avg_quote_total": round(statistics.mean(quotes), 2) if quotes else None,
        "avg_cost": round(statistics.mean(costs), 2) if costs else None,
        "avg_profit": round(statistics.mean(profits), 2) if profits else None,
        "avg_estimated_score": round(statistics.mean(scores), 2) if scores else 0.0,
        "common_failure_reason": common_failure,
        "failure_breakdown": dict(Counter(categories)),
    }
