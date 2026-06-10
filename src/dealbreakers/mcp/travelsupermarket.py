"""Typed wrapper around the TravelSupermarket MCP server."""

from __future__ import annotations

import json
from typing import Any

from dealbreakers.constants import MCP_SOURCES
from dealbreakers.mcp.client import MCPClient
from dealbreakers.mcp.normalizers import (
    AMENITY_TO_FACILITY_ID,
    HolidayCandidate,
    extract_price,
    normalize_amenities,
    normalize_board_basis,
)


class TravelSupermarketClient:
    def __init__(self, client: MCPClient | None = None, timeout: int = 60) -> None:
        self._client = client or MCPClient(MCP_SOURCES["travelsupermarket"], timeout=timeout)

    def search_holidays(
        self,
        destination: str,
        month: str | None = None,
        duration: int | None = 7,
        board: str | None = None,
        stars: int | None = None,
        facilities: list[str] | None = None,
        max_price: float | None = None,
        limit: int = 10,
    ) -> list[HolidayCandidate]:
        """Search package holidays and return normalized candidates.

        month: comma-separated month numbers ("7" or "6,7,8").
        facilities: canonical amenity words; translated to TSM facility IDs.
        max_price: per-person GBP cap (TSM prices are per person).
        """
        arguments: dict[str, Any] = {"destination": destination, "limit": limit}
        if month:
            arguments["departureMonth"] = month
        if duration is not None:
            arguments["duration"] = str(duration)
        if board:
            arguments["boardBasis"] = board
        if stars is not None:
            arguments["starRating"] = str(stars)
        if facilities:
            ids = [
                str(AMENITY_TO_FACILITY_ID[amenity])
                for amenity in facilities
                if amenity in AMENITY_TO_FACILITY_ID
            ]
            if ids:
                arguments["facilities"] = ",".join(ids)
        if max_price is not None:
            arguments["maxPrice"] = max_price

        result = self._client.request(
            "tools/call",
            {"name": "search-holidays", "arguments": arguments},
        )
        listings = extract_listings(result)
        return [normalize_holiday_listing(listing) for listing in listings]


def extract_listings(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull the listing array out of an MCP tools/call result.

    Handles structuredContent, content[].text JSON, and direct list/dict shapes.
    Returns [] rather than crashing on unknown shapes.
    """
    structured = result.get("structuredContent")
    if structured is not None:
        found = _find_listing_array(structured)
        if found:
            return found

    for item in result.get("content", []):
        if item.get("type") != "text":
            continue
        try:
            parsed = json.loads(item.get("text", ""))
        except (ValueError, TypeError):
            continue
        found = _find_listing_array(parsed)
        if found:
            return found

    return _find_listing_array(result) or []


def _find_listing_array(data: Any) -> list[dict[str, Any]]:
    """Find the most plausible array of holiday listings in a payload."""
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []

    for key in ("offers", "results", "holidays", "deals", "items", "data"):
        value = data.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
        if isinstance(value, dict):
            nested = _find_listing_array(value)
            if nested:
                return nested
    return []


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if data.get(key) is not None:
            return data[key]
    return None


def normalize_holiday_listing(listing: dict[str, Any]) -> HolidayCandidate:
    """Map one raw TravelSupermarket listing into a HolidayCandidate."""
    hotel = listing.get("hotel") if isinstance(listing.get("hotel"), dict) else {}

    name = _first(listing, "hotelName", "name", "title") or _first(hotel, "name")
    url = _first(
        listing, "deepLinkUrl", "bookingUrl", "bookingLink", "url", "deeplink", "link"
    )

    stars = _first(listing, "starRating", "stars") or _first(hotel, "starRating", "stars")
    star_rating = extract_price(stars)  # same digits-only extraction works for "4 stars"

    review = _first(listing, "reviewScore", "rating", "tripadvisorRating") or _first(
        hotel, "reviewScore", "rating"
    )
    review_score = extract_price(review)

    board_raw = _first(listing, "boardBasisCode", "boardBasis", "board", "boardType")
    board_basis = normalize_board_basis(board_raw if isinstance(board_raw, str) else None)

    nights_raw = _first(listing, "nights", "duration")
    nights: int | None = None
    nights_value = extract_price(nights_raw)
    if nights_value is not None:
        nights = int(nights_value)

    location = _first(listing, "location", "resort") or _first(hotel, "location")
    region = _first(listing, "region", "destinationName", "destination")
    country = _first(listing, "country") or _first(hotel, "country")

    amenities_raw = _first(listing, "facilities", "amenities") or _first(
        hotel, "facilities", "amenities"
    )
    amenities = normalize_amenities(amenities_raw) if isinstance(amenities_raw, list) else []

    price_raw = _first(
        listing, "totalPrice", "priceTotal", "price", "pricePerPerson", "leadInPrice"
    )
    if isinstance(price_raw, dict):
        price_raw = _first(price_raw, "total", "amount", "value", "perPerson")
    price_total = extract_price(price_raw)

    return HolidayCandidate(
        hotel_name=name if isinstance(name, str) else None,
        url=url if isinstance(url, str) else None,
        star_rating=star_rating,
        review_score=review_score,
        board_basis=board_basis,
        nights=nights,
        location=location if isinstance(location, str) else None,
        region=region if isinstance(region, str) else None,
        country=country if isinstance(country, str) else None,
        amenities=amenities,
        price_total=price_total,
        raw=listing,
    )
