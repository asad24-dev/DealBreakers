#!/usr/bin/env python3
"""Multi-run practice evaluation after porting improvements (Phase 7E)."""

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
from dealbreakers.logging import TranscriptRecorder
from dealbreakers.models.match import MatchStartResponse
from dealbreakers.negotiation.live_agent import LiveNegotiationAgent

PERSONAS = ("practice-bob", "practice-toni", "practice-cris", "practice-gordon")
DEFAULT_OUT = ROOT / "logs" / "post_port_summary.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate personas over multiple runs.")
    parser.add_argument("--runs", type=int, default=5, help="Runs per persona.")
    parser.add_argument("--personas", nargs="*", default=list(PERSONAS))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    return parser.parse_args()


def _final_markup(log_path: Path) -> float | None:
    if not log_path.exists():
        return None
    markup = None
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("record_type") == "agent_turn" and record.get("offer_sent"):
            if record.get("markup") is not None:
                markup = float(record["markup"])
    return markup


def main() -> int:
    args = parse_args()
    settings = load_settings()
    client = DealRoomClient(settings)
    log_dir = ROOT / "logs" / "autonomous" / "eval"
    log_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, dict] = {}

    for persona_id in args.personas:
        runs: list[dict] = []
        for run_idx in range(1, args.runs + 1):
            log_path = log_dir / f"{persona_id}-run{run_idx}.jsonl"
            agent = LiveNegotiationAgent(
                deal_room=client,
                recorder=TranscriptRecorder(path=log_path),
                log_path=log_path,
                verbose=False,
            )
            start = client.start_match(practice=True, persona_id=persona_id)
            if not isinstance(start, MatchStartResponse):
                runs.append({"run": run_idx, "error": "match_start_failed"})
                continue
            outcome = agent.run(start, persona_id=persona_id)
            runs.append(
                {
                    "run": run_idx,
                    "closed": outcome.closed,
                    "walked": outcome.walked,
                    "rounds": outcome.seller_rounds,
                    "end_reason": outcome.end_reason,
                    "final_markup_pct": _final_markup(log_path),
                }
            )
            print(
                f"{persona_id} run {run_idx}: closed={outcome.closed} "
                f"rounds={outcome.seller_rounds} end={outcome.end_reason}"
            )

        closed = [run for run in runs if run.get("closed")]
        walked = [run for run in runs if run.get("walked")]
        markups = [
            run["final_markup_pct"]
            for run in runs
            if run.get("final_markup_pct") is not None
        ]
        rounds = [run["rounds"] for run in runs if run.get("rounds") is not None]

        summary[persona_id] = {
            "runs": runs,
            "close_rate": len(closed) / len(runs) if runs else 0.0,
            "walk_rate": len(walked) / len(runs) if runs else 0.0,
            "average_rounds": statistics.mean(rounds) if rounds else None,
            "average_markup": statistics.mean(markups) if markups else None,
            "median_markup": statistics.median(markups) if markups else None,
        }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nSaved summary to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
