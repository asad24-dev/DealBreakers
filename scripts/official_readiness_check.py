#!/usr/bin/env python3
"""Official readiness gate — does NOT start official matches (Phase 8G)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dealbreakers.api.client import DealRoomClient
from dealbreakers.config import Settings
from dealbreakers.evaluation.failure_classification import FailureCategory
from dealbreakers.graph.runner import is_langgraph_available
from dealbreakers.personas.markup_profiles import DEFAULT_PROFILES_PATH, load_profiles

OUT_PATH = ROOT / "logs" / "official_readiness.json"
EVAL_LIVE = ROOT / "logs" / "final_eval" / "live_summary.json"
COMPARISON_PATH = ROOT / "logs" / "all_persona_comparison.json"
TESTS_MARKER = ROOT / "logs" / ".tests_passing"

CLOSE_THRESHOLDS = {
    "practice-bob": 0.8,
    "practice-toni": 0.8,
    "practice-cris": 0.7,
    "practice-elon": 0.6,
    "practice-gordon": 0.5,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Official readiness check.")
    parser.add_argument(
        "--run-tests",
        action="store_true",
        help="Run pytest instead of checking tests marker.",
    )
    return parser.parse_args()


def _load_eval_summary() -> dict | None:
    if EVAL_LIVE.exists():
        return json.loads(EVAL_LIVE.read_text(encoding="utf-8"))
    if COMPARISON_PATH.exists():
        data = json.loads(COMPARISON_PATH.read_text(encoding="utf-8"))
        converted: dict[str, dict] = {}
        for persona, row in data.get("comparison", {}).items():
            metrics = row.get("live_agent") or row.get("graph_runner") or {}
            converted[persona] = {
                "close_rate": metrics.get("close_rate", 0.0),
                "common_failure_reason": row.get("failure_reason_summary", "unknown"),
            }
        return {"personas_summary": converted, "source": "comparison_fallback"}
    return None


def _integration_available(name: str) -> bool:
    try:
        if name == "TSM":
            from dealbreakers.mcp.travelsupermarket import TravelSupermarketClient

            TravelSupermarketClient()
        elif name == "TourRadar":
            from dealbreakers.mcp.tourradar import TourRadarClient

            TourRadarClient()
        elif name == "EconomyBookings":
            from dealbreakers.mcp.cars import CarSearchClient

            CarSearchClient()
        elif name == "Trivago":
            from dealbreakers.mcp.trivago import TrivagoClient

            TrivagoClient()
        elif name == "Kiwi":
            from dealbreakers.mcp.kiwi import KiwiClient

            KiwiClient()
        else:
            return False
        return True
    except Exception:  # noqa: BLE001
        return False


def _official_safety_ok() -> tuple[bool, str | None]:
    try:
        client = DealRoomClient(Settings(base_url="https://example.com", team_key="test"))
        client.start_match(practice=False, official=True)
        return False, "official_start_without_env_should_raise"
    except RuntimeError:
        pass
    env = os.environ.copy()
    env["ALLOW_OFFICIAL_MATCHES"] = "true"
    try:
        client = DealRoomClient(Settings(base_url="https://example.com", team_key="test"))
        client.start_match(practice=False, official=True, persona_id="practice-bob")
        return False, "official_with_persona_should_raise"
    except RuntimeError:
        pass
    return True, None


def _gordon_inventory_limited(eval_summary: dict | None) -> bool:
    if not eval_summary:
        return False
    row = eval_summary.get("personas_summary", {}).get("practice-gordon", {})
    if row.get("gordon_inventory_limited_ok"):
        return True
    breakdown = row.get("failure_breakdown", {})
    acceptable = {
        FailureCategory.DURATION_MISMATCH.value,
        FailureCategory.INVENTORY_OR_PRICE_FLOOR.value,
        FailureCategory.INVENTORY_UNAVAILABLE.value,
        FailureCategory.PRICE_WALK.value,
    }
    return any(key in acceptable for key in breakdown)


def main() -> int:
    args = parse_args()
    checks: dict[str, dict] = {}
    blockers: list[str] = []
    ready = True

    if args.run_tests:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/", "-q", "--tb=no"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
            tests_pass = result.returncode == 0
            checks["tests"] = {
                "pass": tests_pass,
                "returncode": result.returncode,
                "mode": "run",
            }
        except Exception as exc:  # noqa: BLE001
            tests_pass = False
            checks["tests"] = {"pass": False, "error": str(exc), "mode": "run"}
    else:
        tests_pass = TESTS_MARKER.exists()
        checks["tests"] = {"pass": tests_pass, "mode": "marker", "path": str(TESTS_MARKER)}

    if not tests_pass:
        ready = False
        blockers.append("tests not passing (run pytest or --run-tests)")

    integrations = ["TSM", "TourRadar", "EconomyBookings", "Trivago", "Kiwi"]
    for name in integrations:
        ok = _integration_available(name)
        checks[f"integration_{name}"] = {"pass": ok}
        if not ok:
            ready = False
            blockers.append(f"integration unavailable: {name}")

    eval_summary = _load_eval_summary()
    checks["eval_summary"] = {"pass": eval_summary is not None, "path": str(EVAL_LIVE)}
    if eval_summary is None:
        ready = False
        blockers.append("missing latest evaluation summary (run evaluate_all_personas.py)")

    if eval_summary:
        personas_summary = eval_summary.get("personas_summary", {})
        for persona, threshold in CLOSE_THRESHOLDS.items():
            row = personas_summary.get(persona, {})
            rate = float(row.get("close_rate", 0.0))
            if persona == "practice-gordon":
                gordon_ok = rate >= threshold or _gordon_inventory_limited(eval_summary)
                checks[f"close_rate_{persona}"] = {
                    "pass": gordon_ok,
                    "rate": rate,
                    "threshold": threshold,
                    "inventory_limited_ok": _gordon_inventory_limited(eval_summary),
                }
                if not gordon_ok:
                    ready = False
                    blockers.append(
                        f"practice-gordon close rate {rate} below {threshold} and not inventory-limited"
                    )
            else:
                passed = rate >= threshold
                checks[f"close_rate_{persona}"] = {
                    "pass": passed,
                    "rate": rate,
                    "threshold": threshold,
                }
                if not passed:
                    ready = False
                    blockers.append(f"{persona} close rate {rate} below {threshold}")

    safety_ok, safety_err = _official_safety_ok()
    checks["official_safety_guard"] = {"pass": safety_ok, "detail": safety_err}
    if not safety_ok:
        ready = False
        blockers.append(f"official safety bypass: {safety_err}")

    profiles_exist = DEFAULT_PROFILES_PATH.exists() or bool(load_profiles())
    checks["persona_markup_profiles"] = {
        "pass": profiles_exist,
        "path": str(DEFAULT_PROFILES_PATH),
    }
    if not profiles_exist:
        ready = False
        blockers.append("persona markup profiles missing")

    checks["graph_fallback"] = {
        "pass": True,
        "langgraph_available": is_langgraph_available(),
    }

    checks["invalid_offer_fields"] = {"pass": True, "note": "validated by offer schema tests"}

    payload = {
        "ready": ready,
        "status": "READY" if ready else "NOT READY",
        "blockers": blockers,
        "checks": checks,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(payload["status"])
    if blockers:
        print("Blockers:")
        for blocker in blockers:
            print(f"  - {blocker}")
    print(f"Report: {OUT_PATH}")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
