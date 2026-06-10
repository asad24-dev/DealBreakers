from __future__ import annotations

import argparse
import json
import sys

from rich.console import Console
from rich.table import Table

from dealbreakers.agent import SellerAgent
from dealbreakers.config import get_settings
from dealbreakers.dealroom import DealRoomClient
from dealbreakers.mcp import TravelMcpRegistry


def main() -> None:
    # Buyers use emoji; the Windows console defaults to cp1252 and crashes mid-match.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="dealbreakers")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run a Deal Room negotiation.")
    mode = run_parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--practice", action="store_true", help="Use practice buyers.")
    mode.add_argument("--official", action="store_true", help="Use official scored buyers (LOCKED by default).")
    run_parser.add_argument("--persona", help="Practice persona id, e.g. practice-bob.")
    run_parser.add_argument(
        "--confirm-official",
        action="store_true",
        help="Second factor for official matches. Requires ALLOW_OFFICIAL_MATCHES=true in .env as well.",
    )

    subparsers.add_parser("discover-tools", help="List tools exposed by each travel MCP.")

    args = parser.parse_args()
    if args.command == "discover-tools":
        discover_tools()
    elif args.command == "run":
        if args.official and not args.confirm_official:
            parser.error(
                "Official matches are one-shot and scored. Pass --confirm-official AND set "
                "ALLOW_OFFICIAL_MATCHES=true in .env to deliberately unlock them."
            )
        run(practice=args.practice, persona_id=args.persona)


def discover_tools() -> None:
    console = Console()
    registry = TravelMcpRegistry()
    discovered = registry.discover_all()
    for server, tools in discovered.items():
        if isinstance(tools, str):
            console.print(f"[bold red]{server}:[/bold red] {tools}")
            continue
        table = Table(title=server)
        table.add_column("Tool")
        table.add_column("Description")
        table.add_column("Input Schema")
        for tool in tools:
            table.add_row(tool.name, tool.description, json.dumps(tool.input_schema)[:500])
        console.print(table)


def run(*, practice: bool, persona_id: str | None) -> None:
    settings = get_settings()
    console = Console()
    with DealRoomClient(settings) as dealroom:
        match = dealroom.start_match(practice=practice, persona_id=persona_id)
        if isinstance(match, dict) and match.get("done"):
            console.print("[bold]All official matches are complete.[/bold]")
            return
        SellerAgent(dealroom, console=console).run_match(match)


if __name__ == "__main__":
    main()
