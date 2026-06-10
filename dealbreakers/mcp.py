from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import count
from typing import Any

import httpx


TRAVEL_MCPS: dict[str, str] = {
    "travelsupermarket": "https://travel-supermarket-integration-dev-test.up.railway.app/mcp",
    "trivago": "https://mcp.trivago.com/mcp",
    "kiwi": "https://mcp.kiwi.com/mcp",
    "economybookings": "https://economybookings-integration-dev.up.railway.app/mcp",
    "tourradar": "https://ai.tourradar.com/mcp/main",
}


@dataclass(frozen=True)
class McpTool:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]


class McpClient:
    def __init__(self, server_name: str, url: str, *, timeout_seconds: float = 45) -> None:
        self.server_name = server_name
        self.url = url
        self._ids = count(1)
        self._initialized = False
        self._session_id: str | None = None
        self._client = httpx.Client(timeout=timeout_seconds, headers={"accept": "application/json, text/event-stream"})

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> McpClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def list_tools(self) -> list[McpTool]:
        result = self._rpc("tools/list", {})
        tools = result.get("tools", []) if isinstance(result, dict) else []
        return [
            McpTool(
                server=self.server_name,
                name=str(tool.get("name", "")),
                description=str(tool.get("description", "")),
                input_schema=tool.get("inputSchema") or {},
            )
            for tool in tools
            if tool.get("name")
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return self._rpc("tools/call", {"name": name, "arguments": arguments})

    def _ensure_initialized(self) -> None:
        """Spec-compliant MCP servers (kiwi, trivago) reject requests without an
        initialize handshake and session id; lenient ones tolerate the extra call."""
        if self._initialized:
            return
        self._initialized = True
        try:
            response = self._client.post(
                self.url,
                json={
                    "jsonrpc": "2.0",
                    "id": next(self._ids),
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "dealbreakers", "version": "0.1"},
                    },
                },
            )
            self._session_id = response.headers.get("mcp-session-id")
            self._client.post(
                self.url,
                json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                headers=self._session_headers(),
            )
        except httpx.HTTPError:
            self._session_id = None

    def _session_headers(self) -> dict[str, str]:
        return {"mcp-session-id": self._session_id} if self._session_id else {}

    def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        self._ensure_initialized()
        payload = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": method,
            "params": params,
        }
        response = self._client.post(self.url, json=payload, headers=self._session_headers())
        response.raise_for_status()
        data = _decode_mcp_response(response)
        if "error" in data:
            raise RuntimeError(f"{self.server_name} MCP error: {data['error']}")
        result = data.get("result", data)
        if isinstance(result, dict) and result.get("isError"):
            raise RuntimeError(f"{self.server_name} MCP tool error: {result}")
        return result


class TravelMcpRegistry:
    def __init__(self, urls: dict[str, str] | None = None, *, timeout_seconds: float = 45) -> None:
        self._urls = urls or TRAVEL_MCPS
        self._timeout_seconds = timeout_seconds

    def clients(self) -> list[McpClient]:
        return [
            McpClient(name, url, timeout_seconds=self._timeout_seconds)
            for name, url in self._urls.items()
        ]

    def discover_all(self) -> dict[str, list[McpTool] | str]:
        discovered: dict[str, list[McpTool] | str] = {}
        for client in self.clients():
            with client:
                try:
                    discovered[client.server_name] = client.list_tools()
                except Exception as exc:
                    discovered[client.server_name] = f"{type(exc).__name__}: {exc}"
        return discovered


def _decode_mcp_response(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" not in content_type:
        return response.json()

    for line in response.text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line.removeprefix("data:").strip()
        if not data or data == "[DONE]":
            continue
        parsed = json.loads(data)
        if isinstance(parsed, dict) and ("result" in parsed or "error" in parsed):
            return parsed
    raise RuntimeError("MCP stream ended without a JSON-RPC result.")
