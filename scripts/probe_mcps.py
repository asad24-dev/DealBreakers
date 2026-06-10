"""Dump tools/list schemas from all travel MCPs to mcp_tools.json for inspection."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dealbreakers.config import TRAVEL_MCP_ENDPOINTS
from dealbreakers.mcp_client import StreamableMCPClient

out: dict = {}
for name, url in TRAVEL_MCP_ENDPOINTS.items():
    client = StreamableMCPClient(name, url, timeout=30)
    try:
        client.initialize()
        tools = client.list_tools()
        out[name] = tools
        print(f"{name}: {len(tools)} tools -> {[t['name'] for t in tools]}")
    except Exception as exc:
        out[name] = {"error": str(exc)}
        print(f"{name}: FAILED {exc}")

Path("mcp_tools.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print("wrote mcp_tools.json")
