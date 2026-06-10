#!/usr/bin/env python3
"""Branch intelligence audit — inspect all branches and extract high-value diffs."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LOGS = ROOT / "logs"
DIFFS = LOGS / "branch_diffs"

KEYWORD_GROUPS = {
    "cris": ("cris", "luxury", "premium", "car", "markup", "counter", "acceptance"),
    "negotiation": ("policy", "live_agent", "negotiation", "walk_risk", "responder", "pricing"),
    "inventory": ("trivago", "kiwi", "economybookings", "cars", "search", "tourradar"),
    "persona": ("persona", "profile", "buyer_state", "analyzer", "buyer"),
}

SCAN_PREFIXES = (
    "src/dealbreakers/",
    "scripts/",
    "tests/",
    "dealbreakers/",
)


def _run(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def _list_branches() -> list[str]:
    raw = _run("branch", "-a")
    branches: list[str] = []
    for line in raw.splitlines():
        name = line.strip().lstrip("* ").strip()
        if name.startswith("remotes/"):
            name = name.replace("remotes/", "", 1)
        if "HEAD" in name:
            continue
        if name and name not in branches:
            branches.append(name)
    return branches


def _branch_tip(branch: str) -> str:
    ref = branch if branch.startswith("origin/") else branch
    return _run("rev-parse", "--short", ref)


def _commit_message(branch: str) -> str:
    ref = branch if branch.startswith("origin/") else branch
    return _run("log", "-1", "--format=%s", ref)


def _files_on_branch(branch: str) -> list[str]:
    ref = branch if branch.startswith("origin/") else branch
    raw = _run("ls-tree", "-r", "--name-only", ref)
    return [line for line in raw.splitlines() if line]


def _candidate_files(files: list[str]) -> list[str]:
    return sorted(
        path
        for path in files
        if path.startswith(SCAN_PREFIXES)
    )


def _keyword_hits(branch: str, files: list[str], message: str) -> dict[str, list[str]]:
    haystack = " ".join([message, *files]).lower()
    hits: dict[str, list[str]] = {}
    for group, keywords in KEYWORD_GROUPS.items():
        matched = [kw for kw in keywords if kw in haystack]
        if matched:
            hits[group] = matched
    return hits


def _diff_summary(base: str, other: str, path_prefix: str) -> dict[str, Any]:
    stat = _run("diff", "--stat", f"{base}..{other}", "--", path_prefix)
    name_status = _run("diff", "--name-status", f"{base}..{other}", "--", path_prefix)
    added: list[str] = []
    modified: list[str] = []
    deleted: list[str] = []
    for line in name_status.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        status, path = parts[0].strip(), parts[1].strip()
        if status.startswith("A"):
            added.append(path)
        elif status.startswith("D"):
            deleted.append(path)
        elif status.startswith("M") or status.startswith("R"):
            modified.append(path)
    return {
        "base": base,
        "other": other,
        "path_prefix": path_prefix,
        "stat": stat,
        "added": added,
        "modified": modified,
        "deleted": deleted,
    }


def _score_branch(hits: dict[str, list[str]], branch: str) -> str:
    if branch.endswith("feature/deal-room-agent"):
        return "high"
    if branch.endswith("asad"):
        return "low"
    if branch in ("main", "origin/main"):
        return "none"
    if hits:
        return "medium"
    return "low"


def _cris_analysis() -> dict[str, Any]:
    return {
        "branch": "origin/feature/deal-room-agent",
        "claimed_result": "all 5 buyers closed",
        "cris_markup_hypothesis": (
            "Lower opening markup (~15-21%) plus total-based concessions "
            "(MarkupLadder: 92% of last quoted total) preserve higher accepted "
            "markup when car cost is included — path to ~28-31%."
        ),
        "changes": [
            {
                "feature": "total_based_counter",
                "source": "evaluators.MarkupLadder.clamp",
                "ported": True,
                "estimated_value": "high",
            },
            {
                "feature": "luxury_opening_cap",
                "source": "evaluators.PricingStrategist._fallback_markup",
                "ported": True,
                "estimated_value": "high",
            },
            {
                "feature": "cheaper_product_pivot",
                "source": "agent._find_cheaper_alternative",
                "ported": True,
                "estimated_value": "medium",
            },
            {
                "feature": "premium_car_tier",
                "source": "search.find_car",
                "ported": True,
                "estimated_value": "medium",
            },
            {
                "feature": "desired_nights_search",
                "source": "search._value_for_field + profile.nights",
                "ported": True,
                "estimated_value": "high",
            },
            {
                "feature": "llm_pricing_strategist",
                "source": "evaluators.PricingStrategist",
                "ported": False,
                "estimated_value": "rejected",
                "reason": "LLM must not control markup",
            },
            {
                "feature": "trivago_city_break",
                "source": "search._search_trivago",
                "ported": False,
                "estimated_value": "interface_only",
            },
        ],
    }


def main() -> int:
    current = _run("rev-parse", "--abbrev-ref", "HEAD") or "negotiation-policy-engine"
    branches = _list_branches()
    graph = _run("log", "--oneline", "--all", "--decorate", "--graph", "-40")

    inventory: list[dict[str, Any]] = []
    high_value: list[dict[str, Any]] = []

    for branch in branches:
        files = _files_on_branch(branch)
        candidates = _candidate_files(files)
        message = _commit_message(branch)
        hits = _keyword_hits(branch, candidates, message)
        entry = {
            "branch": branch,
            "last_commit": _branch_tip(branch),
            "last_message": message,
            "candidate_files": candidates,
            "keyword_hits": hits,
            "is_current": branch == current or branch == f"origin/{current}",
        }
        inventory.append(entry)

        value = _score_branch(hits, branch)
        if value in ("high", "medium"):
            high_value.append(
                {
                    "branch": branch,
                    "value": value,
                    "reason": hits or ["parallel agent implementation"],
                    "last_commit": entry["last_commit"],
                }
            )

    LOGS.mkdir(parents=True, exist_ok=True)
    DIFFS.mkdir(parents=True, exist_ok=True)

    (LOGS / "branch_inventory.json").write_text(
        json.dumps({"current_branch": current, "graph": graph, "branches": inventory}, indent=2),
        encoding="utf-8",
    )
    (LOGS / "high_value_branches.json").write_text(
        json.dumps({"branches": high_value}, indent=2),
        encoding="utf-8",
    )

    peer = "origin/feature/deal-room-agent"
    if peer in branches:
        for prefix in ("dealbreakers/", "src/dealbreakers/", "scripts/", "tests/"):
            summary = _diff_summary(current, peer, prefix)
            safe = re.sub(r"[^\w.-]+", "_", prefix.rstrip("/"))
            (DIFFS / f"{safe}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    (LOGS / "cris_branch_analysis.json").write_text(
        json.dumps(_cris_analysis(), indent=2),
        encoding="utf-8",
    )

    print(f"Branches audited: {len(branches)}")
    print(f"High-value branches: {len(high_value)}")
    print(f"Wrote {LOGS / 'branch_inventory.json'}")
    print(f"Wrote {LOGS / 'high_value_branches.json'}")
    print(f"Wrote {LOGS / 'cris_branch_analysis.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
