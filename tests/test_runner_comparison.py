"""Tests for runner comparison metrics (Phase 8E)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "compare_runners.py"


def _load_compare_module():
    spec = importlib.util.spec_from_file_location("compare_runners", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(ROOT / "src"))
    spec.loader.exec_module(module)
    return module


def test_summary_json_shape() -> None:
    mod = _load_compare_module()
    rows = [
        {"closed": True, "walked": False, "rounds": 3, "markup": 12.0, "quote_total": 1100, "reward": 55.0},
        {"closed": False, "walked": True, "rounds": 5, "markup": 8.0, "quote_total": 900, "reward": -40.0},
    ]
    metrics = mod._metrics(rows)
    assert set(metrics.keys()) == {
        "close_rate",
        "walk_rate",
        "avg_markup",
        "avg_rounds",
        "avg_reward",
        "avg_quote_total",
    }


def test_metrics_computed_correctly() -> None:
    mod = _load_compare_module()
    rows = [
        {"closed": True, "walked": False, "rounds": 4, "markup": 10.0, "quote_total": 1000, "reward": 50.0},
        {"closed": True, "walked": False, "rounds": 6, "markup": 20.0, "quote_total": 2000, "reward": 60.0},
    ]
    metrics = mod._metrics(rows)
    assert metrics["close_rate"] == 1.0
    assert metrics["walk_rate"] == 0.0
    assert metrics["avg_markup"] == 15.0
    assert metrics["avg_rounds"] == 5.0
    assert metrics["avg_reward"] == 55.0
    assert metrics["avg_quote_total"] == 1500.0


def test_empty_metrics() -> None:
    mod = _load_compare_module()
    metrics = mod._metrics([])
    assert metrics["close_rate"] == 0.0
    assert metrics["avg_markup"] is None
