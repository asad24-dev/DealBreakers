"""Offline tests for evaluation metrics (Phase 8G)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

from dealbreakers.evaluation.scoring import compute_estimated_score, summarize_runs

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_all_personas.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("evaluate_all_personas", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(ROOT / "src"))
    spec.loader.exec_module(module)
    return module


def test_estimated_score_close_and_margin() -> None:
    score = compute_estimated_score(
        closed=True,
        walked=False,
        markup_pct=35.0,
        must_haves_matched=True,
        duration_matched=True,
        car_required=False,
        car_present=False,
        review_score=9.0,
    )
    assert score == 50.0 + 30.0 + 20.0


def test_estimated_score_duration_penalty() -> None:
    score = compute_estimated_score(
        closed=False,
        walked=False,
        markup_pct=10.0,
        duration_matched=False,
    )
    assert score < 20.0


def test_summarize_runs_shape() -> None:
    runs = [
        {
            "closed": True,
            "walked": False,
            "rounds": 2,
            "markup_pct": 30.0,
            "quote_total": 1300.0,
            "cost": 1000.0,
            "estimated_score": 80.0,
            "offer_sent": True,
        },
        {
            "closed": False,
            "walked": True,
            "rounds": 3,
            "markup_pct": 0.0,
            "quote_total": 3000.0,
            "cost": 3000.0,
            "estimated_score": 10.0,
            "offer_sent": True,
            "final_markup_pct": 0.0,
        },
    ]
    summary = summarize_runs(runs)
    assert summary["close_rate"] == 0.5
    assert summary["walk_rate"] == 0.5
    assert summary["avg_markup"] == 15.0
    assert summary["avg_profit"] == 150.0
    assert "common_failure_reason" in summary
    assert "failure_breakdown" in summary


def test_build_eval_row_includes_failure_category() -> None:
    mod = _load_module()
    row = mod._build_eval_row(
        persona_id="practice-bob",
        runner="live",
        run_idx=1,
        closed=True,
        walked=False,
        rounds=2,
        markup_pct=35.0,
        quote_total=1350.0,
        cost=1000.0,
        offer_sent=True,
    )
    assert row["failure_category"] == "closed"
    assert row["estimated_score"] > 0
