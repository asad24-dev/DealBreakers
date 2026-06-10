"""Typed wrapper around the Kiwi MCP flight search server."""

from __future__ import annotations

from typing import Any

from dealbreakers.constants import MCP_SOURCES
from dealbreakers.mcp.client import MCPClient, MCPError
from dealbreakers.mcp.flight_normalizers import (
    FlightCandidate,
    extract_flight_listings,
    iso_to_kiwi_date,
    normalize_flight_listing,
)

TOOL_SEARCH_FLIGHT = "search-flight"

_CITY_IATA: dict[str, str] = {
    "london": "LON",
    "berlin": "BER",
    "stockholm": "STO",
    "amsterdam": "AMS",
    "paris": "PAR",
}


def city_to_iata(city_or_code: str) -> str:
    cleaned = city_or_code.strip().upper()
    if len(cleaned) == 3 and cleaned.isalpha():
        return cleaned
    return _CITY_IATA.get(city_or_code.strip().lower(), cleaned[:3] if cleaned else "LON")


class KiwiClient:
    def __init__(self, client: MCPClient | None = None, timeout: int = 90) -> None:
        self._client = client or MCPClient(MCP_SOURCES["kiwi"], timeout=timeout)
        self.last_errors: list[str] = []

    def search_flights(
        self,
        fly_from: str = "LON",
        fly_to: str = "BER",
        departure_date: str = "2026-07-10",
        return_date: str = "2026-07-14",
        adults: int = 1,
        limit: int = 10,
    ) -> list[FlightCandidate]:
        args: dict[str, Any] = {
            "flyFrom": city_to_iata(fly_from),
            "flyTo": city_to_iata(fly_to),
            "departureDate": iso_to_kiwi_date(departure_date),
            "returnDate": iso_to_kiwi_date(return_date),
            "passengers": {"adults": adults},
            "curr": "GBP",
        }
        try:
            result = self._client.request(
                "tools/call",
                {"name": TOOL_SEARCH_FLIGHT, "arguments": args},
            )
        except MCPError as exc:
            self.last_errors = [str(exc)]
            return []

        listings = extract_flight_listings(result)
        candidates = [normalize_flight_listing(item) for item in listings]
        offerable_first = sorted(
            candidates,
            key=lambda c: (0 if c.is_offerable else 1, c.price_total or float("inf")),
        )
        return offerable_first[:limit]
