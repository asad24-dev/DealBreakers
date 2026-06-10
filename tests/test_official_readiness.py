"""Tests for official readiness check summary."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "official_readiness_check.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("official_readiness_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(ROOT / "src"))
    spec.loader.exec_module(module)
    return module


def test_readiness_summary_shape(tmp_path: Path):
    comparison = {
        "personas_summary": {
            "practice-bob": {"close_rate": 1.0, "walk_rate": 0.0},
            "practice-toni": {"close_rate": 1.0, "walk_rate": 0.0},
            "practice-cris": {"close_rate": 0.8, "walk_rate": 0.0},
            "practice-gordon": {
                "close_rate": 0.0,
                "walk_rate": 1.0,
                "common_failure_reason": "duration_mismatch",
            },
            "practice-elon": {"close_rate": 1.0, "walk_rate": 0.0},
        }
    }
    path = tmp_path / "comparison.json"
    path.write_text(json.dumps(comparison), encoding="utf-8")

    mod = _load_module()
    original = mod.EVAL_LIVE
    mod.EVAL_LIVE = path
    try:
        loaded = mod._load_eval_summary()
        assert loaded is not None
        rate = loaded["personas_summary"]["practice-bob"]["close_rate"]
        assert rate == 1.0
    finally:
        mod.EVAL_LIVE = original
