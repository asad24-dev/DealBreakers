"""Offline tests for strategy report generation (Phase 8G)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "generate_strategy_report.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_strategy_report", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.path.insert(0, str(ROOT / "src"))
    spec.loader.exec_module(module)
    return module


def test_strategy_report_contains_all_personas(tmp_path: Path, monkeypatch) -> None:
    mod = _load_module()
    eval_path = tmp_path / "live_summary.json"
    eval_path.write_text(
        json.dumps(
            {
                "personas_summary": {
                    "practice-bob": {"close_rate": 1.0, "common_failure_reason": "closed"},
                    "practice-toni": {"close_rate": 1.0, "common_failure_reason": "closed"},
                    "practice-cris": {"close_rate": 0.8, "common_failure_reason": "closed"},
                    "practice-elon": {"close_rate": 0.7, "common_failure_reason": "closed"},
                    "practice-gordon": {
                        "close_rate": 0.0,
                        "common_failure_reason": "inventory_or_price_floor",
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    profiles_path = tmp_path / "persona_markup_profiles.json"
    profiles_path.write_text(
        json.dumps(
            {
                "profiles": {
                    "practice-bob": {
                        "persona_id": "practice-bob",
                        "safe": 25,
                        "balanced": 30,
                        "aggressive": 35,
                        "ceiling": 35,
                        "source": "measured",
                        "notes": [],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    readiness_path = tmp_path / "official_readiness.json"
    readiness_path.write_text(
        json.dumps({"status": "NOT READY", "blockers": ["tests"]}),
        encoding="utf-8",
    )

    monkeypatch.setattr(mod, "EVAL_LIVE", eval_path)
    monkeypatch.setattr(mod, "PROFILES_PATH", profiles_path)
    monkeypatch.setattr(mod, "READINESS_PATH", readiness_path)
    monkeypatch.setattr(mod, "OUT_PATH", tmp_path / "report.md")

    report = mod.generate_report()
    for persona in mod.PERSONAS:
        assert persona in report
    assert "Official readiness" in report
    assert "Commands Before Official" in report
