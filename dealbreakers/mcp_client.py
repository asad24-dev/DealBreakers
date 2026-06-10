from __future__ import annotations

import itertools
from typing import Any

import httpx

from .util import compact_json, parse_sse_or_json


class StreamableMCPClient:
    def __init__(self, name: str, url: str, timeout: float = 30):
        self.name = name
        self.url = url
        self.timeout = timeout
        self._ids = itertools.count(1)
        self.session_id: str | None = None
        self.client = httpx.Client(
            timeout=timeout,
            headers={
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
            },
            follow_redirects=True,
        )

    def initialize(self) -> None:
        result = self.request(
            "initialize",
            {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "dealbreakers-seller", "version": "0.1.0"},
            },
            capture_session=True,
        )
        if result is not None:
            self.notify("notifications/initialized", {})

    def request(self, method: str, params: dict[str, Any] | None = None, capture_session: bool = False) -> Any:
        headers = {}
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": method}
        if params is not None:
            payload["params"] = params
        response = self.client.post(self.url, content=compact_json(payload), headers=headers)
        if capture_session:
            self.session_id = response.headers.get("mcp-session-id") or response.headers.get("Mcp-Session-Id")
        response.raise_for_status()
        data = parse_sse_or_json(response.text)
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"{self.name} MCP error calling {method}: {data['error']}")
        return data.get("result") if isinstance(data, dict) else data

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        headers = {}
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        payload = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        response = self.client.post(self.url, content=compact_json(payload), headers=headers)
        response.raise_for_status()

    def list_tools(self) -> list[dict[str, Any]]:
        result = self.request("tools/list", {})
        return result.get("tools", []) if isinstance(result, dict) else []

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        return self.request("tools/call", {"name": tool_name, "arguments": arguments})

