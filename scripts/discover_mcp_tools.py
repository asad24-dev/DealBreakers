#!/usr/bin/env python3
"""Discover and print the tools exposed by every live travel MCP server.

Saves the full discovery output (raw tool schemas) to logs/mcp_tools.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Windows consoles default to cp1252, which chokes on Unicode in tool descriptions.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dealbreakers.mcp import discover_all

OUTPUT_PATH = ROOT / "logs" / "mcp_tools.json"


def main() -> int:
    print("Discovering tools on all MCP servers...\n")
    results = discover_all()

    for name, result in results.items():
        print("=" * 70)
        print(f"Provider: {name}")
        print(f"URL: {result['url']}")

        if not result["ok"]:
            print(f"ERROR: {result['error']}")
            continue

        tools = result["tools"]
        print(f"Tools: {len(tools)}")
        for tool in tools:
            print(f"\n  - {tool.get('name', '<unnamed>')}")
            description = (tool.get("description") or "").strip()
            if description:
                print(f"    {description[:300]}")
            schema = tool.get("inputSchema")
            if schema:
                properties = schema.get("properties", {})
                required = set(schema.get("required", []))
                for prop, spec in properties.items():
                    marker = "*" if prop in required else " "
                    prop_type = spec.get("type", "?")
                    print(f"      {marker} {prop}: {prop_type}")
        print()

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print("=" * 70)
    reachable = sum(1 for result in results.values() if result["ok"])
    print(f"\n{reachable}/{len(results)} providers reachable.")
    print(f"Full discovery saved to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
