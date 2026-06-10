#!/usr/bin/env python3
"""Phase 7B: binary-search markup ceiling discovery for practice personas.

PRACTICE MODE ONLY — MARKUP CEILING SEARCH

Probes markups between a known-accepted floor and a known-rejected ceiling
using the same valid TravelSupermarket offer flow as the markup sweep.
Persists per-persona markup profiles to logs/persona_markup_profiles.json.

No --official or --practice flags exist. Personas are restricted to the
practice whitelist and every match start is practice=True.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dealbreakers.api import DealRoomClient  # noqa: E402
from dealbreakers.config import load_settings  # noqa: E402
from dealbreakers.constants import PRACTICE_PERSONAS  # noqa: E402
from dealbreakers.experiments.markup_sweep import run_single_markup  # noqa: E402
from dealbreakers.logging import TranscriptRecorder  # noqa: E402
from dealbreakers.mcp import TravelSupermarketClient  # noqa: E402

TRANSCRIPT_PATH = "logs/markup_ceiling.jsonl"
PROFILES_PATH = "logs/persona_markup_profiles.json"


def derive_profile(ceiling: float) -> dict[str, float]:
    """Markup profile from a confirmed acceptance ceiling.

    aggressive = highest multiple of 5 at or below the ceiling,
    balanced = aggressive - 5, safe = aggressive - 10 (floored at 0).
    Example: ceiling 38 → safe 25, balanced 30, aggressive 35.
    """
    aggressive = max(0.0, 5.0 * (ceiling // 5))
    return {
        "safe": max(0.0, aggressive - 10),
        "balanced": max(0.0, aggressive - 5),
        "aggressive": aggressive,
        "ceiling": ceiling,
    }


def load_profiles(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {}


def save_profiles(profiles: dict, path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profiles, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Binary-search a practice persona's markup acceptance ceiling."
    )
    parser.add_argument(
        "--persona",
        choices=sorted(PRACTICE_PERSONAS),
        default="practice-bob",
        help="Practice persona to probe (practice whitelist only).",
    )
    parser.add_argument(
        "--lo", type=int, default=35,
        help="Known-accepted markup (search floor). Default 35 (Bob, Phase 6B).",
    )
    parser.add_argument(
        "--hi", type=int, default=50,
        help="Known-rejected markup (search ceiling). Default 50.",
    )
    parser.add_argument(
        "--max-probes", type=int, default=6,
        help="Max live matches to spend on the search.",
    )
    args = parser.parse_args()

    if args.lo >= args.hi:
        print(f"--lo ({args.lo}) must be below --hi ({args.hi})")
        return 1

    print("PRACTICE MODE ONLY — MARKUP CEILING SEARCH")
    print(f"Persona: {args.persona}")
    print(f"Bounds: accepted={args.lo}, rejected={args.hi}\n")

    settings = load_settings()
    client = DealRoomClient(settings)
    tsm_client = TravelSupermarketClient()
    recorder = TranscriptRecorder(path=TRANSCRIPT_PATH)

    lo, hi = args.lo, args.hi
    probes = 0
    history: list[dict] = []

    while hi - lo > 1 and probes < args.max_probes:
        mid = (lo + hi) // 2
        probes += 1
        print(f"Probe {probes}: markup {mid}% ... ", end="", flush=True)

        result = run_single_markup(
            float(mid),
            client=client,
            tsm_client=tsm_client,
            recorder=recorder,
            persona_id=args.persona,
        )
        history.append(result.to_dict())

        if result.error is not None:
            print(f"ERROR ({result.error}) — stopping search")
            break
        if result.closed:
            print(f"accepted (quote £{result.quote_total})")
            lo = mid
        else:
            print(f"rejected ({result.buyer_action})")
            hi = mid

    ceiling = float(lo)
    profile = derive_profile(ceiling)

    profiles = load_profiles(PROFILES_PATH)
    profiles[args.persona] = profile
    save_profiles(profiles, PROFILES_PATH)

    print(f"\n--- Result for {args.persona} ---")
    print(f"Accepted up to: {lo}%   First rejected: {hi}%")
    print(f"Profile: {json.dumps(profile)}")
    print(f"\nProfiles saved to {PROFILES_PATH}")
    print(f"Transcript: {TRANSCRIPT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
