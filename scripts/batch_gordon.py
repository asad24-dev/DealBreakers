"""Run N parallel practice-gordon matches and print a summary table."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / "venv" / "Scripts" / "python.exe"
LOGS = ROOT / "logs"


def run_one(run_id: int) -> tuple[int, int]:
    proc = subprocess.run(
        [str(PYTHON), "-m", "dealbreakers", "run", "--practice", "--persona", "practice-gordon"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "DEALBREAKERS_RUN_TAG": str(run_id)},
    )
    return run_id, proc.returncode


def parse_log(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    result = data.get("result") or {}
    turns = data.get("turns") or []

    quotes = [t["quote"] for t in turns if t.get("quote")]
    hotel = None
    for t in reversed(turns):
        offer = t.get("offer") or {}
        part = offer.get("holiday") or offer.get("tour") or {}
        if part.get("hotelName") or part.get("name"):
            hotel = part.get("hotelName") or part.get("name")
            break

    first = quotes[0] if quotes else {}
    last = quotes[-1] if quotes else {}
    closed = result.get("closed")
    end_reason = result.get("end_reason") or result.get("endReason") or "?"

    return {
        "run": path.stem[:15],
        "closed": "YES" if closed else "NO",
        "outcome": end_reason,
        "rounds": result.get("rounds") or len(turns),
        "hotel": (hotel or "?")[:28],
        "open_gbp": first.get("total"),
        "final_gbp": last.get("total"),
        "markup_pct": last.get("markup_pct"),
        "cost_gbp": last.get("cost"),
        "exit_code": 0,
    }


def main() -> None:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else n

    existing = {p.resolve() for p in LOGS.glob("*Gordon_Ramsay.json")}
    start = time.time()
    print(f"Launching {n} practice-gordon runs ({workers} parallel)...", flush=True)

    codes: list[int] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(run_one, i) for i in range(n)]
        for fut in as_completed(futures):
            run_id, code = fut.result()
            codes.append(code)
            print(f"  run {run_id + 1}/{n} finished (exit {code})", flush=True)

    elapsed = time.time() - start
    new_logs = sorted(
        [p for p in LOGS.glob("*Gordon_Ramsay.json") if p.resolve() not in existing],
        key=lambda p: p.stat().st_mtime,
    )
    if len(new_logs) > n:
        new_logs = new_logs[-n:]

    rows = [parse_log(p) for p in new_logs]
    closed = sum(1 for r in rows if r["closed"] == "YES")
    walks = sum(1 for r in rows if r["outcome"] == "walk")
    accepts = sum(1 for r in rows if r["outcome"] == "accept")
    avg_rounds = sum(r["rounds"] for r in rows) / len(rows) if rows else 0
    finals = [r["final_gbp"] for r in rows if r["final_gbp"]]
    markups = [r["markup_pct"] for r in rows if r["markup_pct"] is not None]

    print()
    print("=" * 100)
    print(f"BATCH SUMMARY  ({len(rows)} runs in {elapsed / 60:.1f} min, {sum(1 for c in codes if c)} non-zero exits)")
    print("=" * 100)
    print(f"{'Run':<18} {'Closed':<7} {'Outcome':<12} {'Rds':<4} {'Hotel':<28} {'Open':>8} {'Final':>8} {'Mk%':>6}")
    print("-" * 100)
    for i, r in enumerate(rows, 1):
        open_s = f"{r['open_gbp']:.0f}" if r["open_gbp"] else "-"
        final_s = f"{r['final_gbp']:.0f}" if r["final_gbp"] else "-"
        mk_s = f"{r['markup_pct']:.1f}" if r["markup_pct"] is not None else "-"
        print(
            f"{i:<18} {r['closed']:<7} {r['outcome']:<12} {r['rounds']:<4} "
            f"{r['hotel']:<28} {open_s:>8} {final_s:>8} {mk_s:>6}"
        )
    print("-" * 100)
    print(f"Close rate:     {closed}/{len(rows)} ({100 * closed / len(rows):.0f}%)" if rows else "No logs")
    print(f"Accept / Walk:  {accepts} / {walks}")
    print(f"Avg rounds:     {avg_rounds:.1f}")
    if finals:
        print(f"Final quote:    min GBP {min(finals):.0f}  max GBP {max(finals):.0f}  avg GBP {sum(finals)/len(finals):.0f}")
    if markups:
        print(f"Final markup:   min {min(markups):.1f}%  max {max(markups):.1f}%  avg {sum(markups)/len(markups):.1f}%")
    print("=" * 100)


if __name__ == "__main__":
    main()
