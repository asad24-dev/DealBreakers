from __future__ import annotations

import argparse

from .config import load_settings
from .runner import MatchRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the DealBreakers seller agent.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="start practice or official matches")
    mode = run.add_mutually_exclusive_group(required=True)
    mode.add_argument("--practice", action="store_true", help="start a practice match")
    mode.add_argument("--official", action="store_true", help="start official scored matches")
    run.add_argument("--persona", help="practice persona id, e.g. practice-bob")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = load_settings()
    runner = MatchRunner(settings)
    if args.command == "run":
        runner.run(practice=args.practice, persona_id=args.persona)

