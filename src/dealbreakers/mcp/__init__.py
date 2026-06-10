"""MCP travel inventory access (Phase 5)."""

from dealbreakers.mcp.car_normalizers import CarCandidate
from dealbreakers.mcp.cars import CarSearchClient
from dealbreakers.mcp.city_break import CityBreakCandidate, CityBreakSearchClient
from dealbreakers.mcp.client import MCPClient, MCPError, MCPHTTPError, MCPProtocolError
from dealbreakers.mcp.discovery import discover_all, discover_provider
from dealbreakers.mcp.flight_normalizers import FlightCandidate
from dealbreakers.mcp.hotel_normalizers import HotelCandidate
from dealbreakers.mcp.kiwi import KiwiClient
from dealbreakers.mcp.normalizers import HolidayCandidate
from dealbreakers.mcp.tour_normalizers import TourCandidate
from dealbreakers.mcp.tourradar import TourRadarClient
from dealbreakers.mcp.travelsupermarket import TravelSupermarketClient
from dealbreakers.mcp.trivago import TrivagoClient

__all__ = [
    "CarCandidate",
    "CarSearchClient",
    "CityBreakCandidate",
    "CityBreakSearchClient",
    "FlightCandidate",
    "HolidayCandidate",
    "HotelCandidate",
    "KiwiClient",
    "MCPClient",
    "MCPError",
    "MCPHTTPError",
    "MCPProtocolError",
    "TourCandidate",
    "TourRadarClient",
    "TravelSupermarketClient",
    "TrivagoClient",
    "discover_all",
    "discover_provider",
]
