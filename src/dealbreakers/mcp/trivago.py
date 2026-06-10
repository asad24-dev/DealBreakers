"""Typed wrapper around the Trivago MCP server."""

from __future__ import annotations

from typing import Any

from dealbreakers.constants import MCP_SOURCES
from dealbreakers.mcp.client import MCPClient, MCPError
from dealbreakers.mcp.hotel_normalizers import (
    HotelCandidate,
    extract_hotel_listings,
    normalize_hotel_listing,
)

TOOL_SUGGESTIONS = "trivago-search-suggestions"
TOOL_ACCOMMODATION_SEARCH = "trivago-accommodation-search"
TOOL_RADIUS_SEARCH = "trivago-accommodation-radius-search"

# Fallback coordinates for city-break targets when suggestions lack lat/lng.
_CITY_COORDS: dict[str, tuple[float, float]] = {
    "berlin": (52.52, 13.405),
    "stockholm": (59.3293, 18.0686),
    "amsterdam": (52.3676, 4.9041),
    "paris": (48.8566, 2.3522),
    "london": (51.5074, -0.1278),
}


def build_accommodation_args(
    *,
    suggestion_id: int,
    ns: int,
    arrival: str,
    departure: str,
    adults: int = 1,
    min_stars: int | None = None,
    required_amenities: list[str] | None = None,
) -> dict[str, Any]:
    args: dict[str, Any] = {
        "id": suggestion_id,
        "ns": ns,
        "arrival": arrival,
        "departure": departure,
        "adults": adults,
        "rooms": 1,
    }
    filters: dict[str, Any] = {}
    hotel_rating: dict[str, Any] = {}
    if required_amenities:
        if "wifi" in required_amenities:
            filters["freeWiFi"] = True
        if "gym" in required_amenities:
            filters["gym"] = True
    if min_stars is not None and min_stars >= 4:
        hotel_rating["4star"] = True
    elif min_stars is not None and min_stars >= 5:
        hotel_rating["5star"] = True
    if filters:
        args["filters"] = filters
    if hotel_rating:
        args["hotel_rating"] = hotel_rating
    return args


def build_radius_args(
    *,
    latitude: float,
    longitude: float,
    arrival: str,
    departure: str,
    adults: int = 1,
    radius: int = 5000,
    min_stars: int | None = None,
    required_amenities: list[str] | None = None,
) -> dict[str, Any]:
    args: dict[str, Any] = {
        "latitude": latitude,
        "longitude": longitude,
        "radius": radius,
        "arrival": arrival,
        "departure": departure,
        "adults": adults,
        "rooms": 1,
    }
    filters: dict[str, Any] = {}
    hotel_rating: dict[str, Any] = {}
    if required_amenities:
        if "wifi" in required_amenities:
            filters["freeWiFi"] = True
        if "gym" in required_amenities:
            filters["gym"] = True
    if min_stars is not None and min_stars >= 4:
        hotel_rating["4star"] = True
    if filters:
        args["filters"] = filters
    if hotel_rating:
        args["hotel_rating"] = hotel_rating
    return args


def pick_best_suggestion(
    suggestions: list[dict[str, Any]],
    *,
    city_query: str,
) -> dict[str, Any] | None:
    """Pick the best city suggestion (e.g. Berlin, Germany not Ohio)."""
    if not suggestions:
        return None
    query = city_query.strip().lower()
    best: dict[str, Any] | None = None
    best_score = -1
    for item in suggestions:
        if not isinstance(item, dict):
            continue
        label = str(item.get("location_label") or item.get("location") or "").lower()
        location_type = str(item.get("location_type") or "").lower()
        score = 0
        if query in label:
            score += 10
        if "germany" in label and query == "berlin":
            score += 20
        if "sweden" in label and query == "stockholm":
            score += 20
        if location_type == "city":
            score += 5
        if "usa" in label:
            score -= 15
        if score > best_score and item.get("id") is not None and item.get("ns") is not None:
            best_score = score
            best = item
    return best or (suggestions[0] if suggestions else None)


class TrivagoClient:
    def __init__(self, client: MCPClient | None = None, timeout: int = 90) -> None:
        self._client = client or MCPClient(MCP_SOURCES["trivago"], timeout=timeout)
        self.last_errors: list[str] = []

    def search_suggestions(self, city: str) -> list[dict[str, Any]]:
        try:
            result = self._client.request(
                "tools/call",
                {"name": TOOL_SUGGESTIONS, "arguments": {"query": city}},
            )
        except MCPError as exc:
            self.last_errors.append(str(exc))
            return []
        structured = result.get("structuredContent") or {}
        suggestions = structured.get("suggestions") or []
        return [item for item in suggestions if isinstance(item, dict)]

    def search_hotels(
        self,
        city: str,
        checkin_date: str,
        checkout_date: str,
        adults: int = 1,
        min_stars: int | None = None,
        required_amenities: list[str] | None = None,
        limit: int = 10,
    ) -> list[HotelCandidate]:
        """Two-step flow: suggestions → accommodation search."""
        self.last_errors = []
        suggestions = self.search_suggestions(city)
        picked = pick_best_suggestion(suggestions, city_query=city)

        candidates: list[HotelCandidate] = []
        if picked is not None:
            try:
                args = build_accommodation_args(
                    suggestion_id=int(picked["id"]),
                    ns=int(picked["ns"]),
                    arrival=checkin_date,
                    departure=checkout_date,
                    adults=adults,
                    min_stars=min_stars,
                    required_amenities=required_amenities,
                )
                result = self._client.request(
                    "tools/call",
                    {"name": TOOL_ACCOMMODATION_SEARCH, "arguments": args},
                )
                listings = extract_hotel_listings(result)
                candidates = [normalize_hotel_listing(item) for item in listings]
            except (MCPError, KeyError, TypeError, ValueError) as exc:
                self.last_errors.append(str(exc))

        if not candidates:
            coords = _CITY_COORDS.get(city.strip().lower())
            if coords is not None:
                try:
                    args = build_radius_args(
                        latitude=coords[0],
                        longitude=coords[1],
                        arrival=checkin_date,
                        departure=checkout_date,
                        adults=adults,
                        min_stars=min_stars,
                        required_amenities=required_amenities,
                    )
                    result = self._client.request(
                        "tools/call",
                        {"name": TOOL_RADIUS_SEARCH, "arguments": args},
                    )
                    listings = extract_hotel_listings(result)
                    candidates = [normalize_hotel_listing(item) for item in listings]
                except (MCPError, KeyError, TypeError, ValueError) as exc:
                    self.last_errors.append(str(exc))

        offerable_first = sorted(
            candidates,
            key=lambda c: (0 if c.is_offerable else 1, c.price_total or float("inf")),
        )
        return offerable_first[:limit]
