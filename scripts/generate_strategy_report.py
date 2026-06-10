#!/usr/bin/env python3
"""Generate final strategy report from evaluation and readiness artifacts (Phase 8G)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EVAL_LIVE = ROOT / "logs" / "final_eval" / "live_summary.json"
EVAL_GRAPH = ROOT / "logs" / "final_eval" / "graph_summary.json"
PROFILES_PATH = ROOT / "logs" / "persona_markup_profiles.json"
READINESS_PATH = ROOT / "logs" / "official_readiness.json"
OUT_PATH = ROOT / "logs" / "final_strategy_report.md"

PERSONAS = (
    "practice-bob",
    "practice-toni",
    "practice-cris",
    "practice-elon",
    "practice-gordon",
)

RISK_BY_PERSONA = {
    "practice-bob": "low",
    "practice-toni": "low",
    "practice-cris": "medium",
    "practice-elon": "medium",
    "practice-gordon": "high",
}


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _best_runner(live: dict | None, graph: dict | None) -> str:
    if live is None and graph is None:
        return "live"
    live_score = 0.0
    graph_score = 0.0
    if live:
        for persona in PERSONAS:
            row = live.get("personas_summary", {}).get(persona, {})
            live_score += float(row.get("close_rate", 0.0))
    if graph:
        for persona in PERSONAS:
            row = graph.get("personas_summary", {}).get(persona, {})
            graph_score += float(row.get("close_rate", 0.0))
    return "live" if live_score >= graph_score else "graph"


def _persona_section(
    persona_id: str,
    live: dict | None,
    profiles: dict | None,
    readiness: dict | None,
) -> list[str]:
    lines: list[str] = []
    live_row = (live or {}).get("personas_summary", {}).get(persona_id, {})
    profile_row = None
    if profiles:
        profile_row = profiles.get("profiles", profiles).get(persona_id)

    runner = _best_runner(live, None)
    opening = profile_row.get("aggressive") if profile_row else None
    fallback = profile_row.get("balanced") if profile_row else None
    close_rate = live_row.get("close_rate")
    failure = live_row.get("common_failure_reason", "unknown")

    lines.append(f"### {persona_id}")
    lines.append("")
    lines.append(f"- **runner:** {runner}")
    if opening is not None:
        lines.append(f"- **opening markup:** {opening:g}%")
    if fallback is not None:
        lines.append(f"- **fallback:** {fallback:g}%")
    if close_rate is not None:
        lines.append(f"- **close rate (live):** {close_rate}")
    lines.append(f"- **risk:** {RISK_BY_PERSONA.get(persona_id, 'medium')}")
    if persona_id == "practice-cris":
        lines.append("- **car required:** yes")
    if persona_id == "practice-gordon":
        lines.append("- **known inventory issue:** 14-night luxury stays often unavailable")
        lines.append(f"- **common failure:** {failure}")
    else:
        lines.append(f"- **common failure:** {failure}")
    lines.append("")
    return lines


def generate_report() -> str:
    live = _load_json(EVAL_LIVE)
    graph = _load_json(EVAL_GRAPH)
    profiles = _load_json(PROFILES_PATH)
    readiness = _load_json(READINESS_PATH)

    best_runner = _best_runner(live, graph)
    readiness_status = (readiness or {}).get("status", "UNKNOWN")
    blockers = (readiness or {}).get("blockers", [])

    lines = [
        "# DealBreakers Final Strategy Report",
        "",
        f"**Best runner:** {best_runner}",
        f"**Official readiness:** {readiness_status}",
        "",
    ]
    if blockers:
        lines.append("**Blockers:**")
        for blocker in blockers:
            lines.append(f"- {blocker}")
        lines.append("")

    lines.append("## Persona Summary")
    lines.append("")
    for persona_id in PERSONAS:
        lines.extend(_persona_section(persona_id, live, profiles, readiness))

    lines.extend(
        [
            "## Known Failure Modes",
            "",
            "- **practice-gordon:** duration mismatch or buyer walks at 0% on expensive inventory",
            "- **practice-cris:** car requirement unresolved if EconomyBookings has no match",
            "- **practice-elon:** city-break path depends on Trivago/Kiwi availability",
            "- **TSM intermittent 500:** search may return empty; agent retries shorter durations",
            "",
            "## Commands Before Official Attempt",
            "",
            "```bash",
            "pytest tests/ -v",
            "python scripts/evaluate_all_personas.py --runs 10 --runner live",
            "python scripts/official_readiness_check.py --run-tests",
            "python scripts/generate_strategy_report.py",
            "# Only when ready:",
            "# ALLOW_OFFICIAL_MATCHES=true python -c \"from dealbreakers.api import DealRoomClient; ...\"",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    report = generate_report()
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(report, encoding="utf-8")
    print(f"Report: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
