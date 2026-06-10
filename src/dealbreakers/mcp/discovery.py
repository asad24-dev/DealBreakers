"""Discover the tools exposed by each live MCP server."""

from __future__ import annotations

from typing import Any

from dealbreakers.constants import MCP_SOURCES
from dealbreakers.mcp.client import MCPClient, MCPError


def discover_provider(name: str, url: str, timeout: int = 30) -> dict[str, Any]:
    """Run tools/list against one provider. Errors are captured, not raised."""
    try:
        tools = MCPClient(url, timeout=timeout).list_tools()
        return {"provider": name, "url": url, "ok": True, "tools": tools}
    except MCPError as exc:
        return {"provider": name, "url": url, "ok": False, "error": str(exc), "tools": []}


def discover_all(
    servers: dict[str, str] | None = None,
    timeout: int = 30,
) -> dict[str, dict[str, Any]]:
    """Discover tools for every provider. Returns {provider: discovery_result}."""
    servers = servers if servers is not None else MCP_SOURCES
    return {name: discover_provider(name, url, timeout=timeout) for name, url in servers.items()}
