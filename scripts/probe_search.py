"""Read-only probe: dump one raw search-holidays result to inspect field names."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dealbreakers.mcp_client import StreamableMCPClient

client = StreamableMCPClient("tsm", "https://travel-supermarket-integration-dev-test.up.railway.app/mcp", timeout=120)
client.initialize()
result = client.call_tool(
    "search-holidays",
    {"destination": "Spain", "departureMonth": "7", "duration": "7", "adults": "1", "limit": 2},
)
Path("tsm_sample.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
print("wrote tsm_sample.json")
