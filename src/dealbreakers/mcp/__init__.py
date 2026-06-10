"""MCP travel inventory access (Phase 5)."""

from dealbreakers.mcp.client import MCPClient, MCPError, MCPHTTPError, MCPProtocolError
from dealbreakers.mcp.discovery import discover_all, discover_provider
from dealbreakers.mcp.normalizers import HolidayCandidate
from dealbreakers.mcp.travelsupermarket import TravelSupermarketClient

__all__ = [
    "HolidayCandidate",
    "MCPClient",
    "MCPError",
    "MCPHTTPError",
    "MCPProtocolError",
    "TravelSupermarketClient",
    "discover_all",
    "discover_provider",
]
