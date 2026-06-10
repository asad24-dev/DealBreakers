"""Offline tests for Trivago hotel MCP integration."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from dealbreakers.mcp.hotel_normalizers import (
    HotelCandidate,
    extract_hotel_listings,
    map_hotel_amenities,
    normalize_hotel_listing,
)
from dealbreakers.mcp.trivago import TrivagoClient, pick_best_suggestion


SAMPLE_ACCOMMODATION = {
    "accommodation_name": "Test Hotel Berlin",
    "accommodation_url": "https://www.trivago.com/hotel/1",
    "price_per_stay": "€446",
    "hotel_rating": 4,
    "review_rating": "8.5",
    "country_city": "Berlin, Germany",
    "arrival": "2026-07-10",
    "departure": "2026-07-14",
    "top_amenities": "WiFi, Gym, Spa, Restaurant",
}

SAMPLE_SUGGESTIONS = [
    {"id": 3848, "ns": 200, "location_label": "Berlin, Germany", "location_type": "City"},
    {"id": 343951, "ns": 200, "location_label": "Ohio, USA", "location_type": "City"},
]


def test_hotel_candidate_is_offerable():
    hotel = normalize_hotel_listing(SAMPLE_ACCOMMODATION)
    assert hotel.is_offerable
    assert not HotelCandidate(url=None, price_total=100.0).is_offerable


def test_hotel_to_holiday():
    hotel = normalize_hotel_listing(SAMPLE_ACCOMMODATION)
    holiday = hotel.to_holiday()
    assert holiday.hotel_name == "Test Hotel Berlin"
    assert holiday.board_basis == "RO"
    assert holiday.nights == 4
    assert "wifi" in holiday.amenities
    assert "gym" in holiday.amenities


def test_amenity_mapping():
    amenities = map_hotel_amenities("WiFi in public areas, Gym, Hot tub, Bar")
    assert "wifi" in amenities
    assert "gym" in amenities
    assert "jacuzzi" in amenities
    assert "bar" in amenities
    assert "central" not in amenities


def test_extract_hotel_listings_structured():
    payload = {"structuredContent": {"accommodations": [SAMPLE_ACCOMMODATION]}}
    listings = extract_hotel_listings(payload)
    assert len(listings) == 1


def test_extract_hotel_listings_malformed():
    assert extract_hotel_listings({"unexpected": True}) == []
    assert normalize_hotel_listing({}).price_total is None


def test_pick_best_suggestion_prefers_berlin_germany():
    picked = pick_best_suggestion(SAMPLE_SUGGESTIONS, city_query="Berlin")
    assert picked is not None
    assert picked["id"] == 3848


def test_trivago_client_suggestions_to_search_chain():
    mcp = MagicMock()

    def request(method, params):
        name = params["name"]
        if name == "trivago-search-suggestions":
            return {"structuredContent": {"suggestions": SAMPLE_SUGGESTIONS}}
        if name == "trivago-accommodation-search":
            return {"structuredContent": {"accommodations": [SAMPLE_ACCOMMODATION]}}
        raise AssertionError(name)

    mcp.request.side_effect = request
    client = TrivagoClient(client=mcp)
    hotels = client.search_hotels(
        "Berlin",
        "2026-07-10",
        "2026-07-14",
        min_stars=4,
        required_amenities=["wifi", "gym"],
    )
    assert len(hotels) == 1
    assert hotels[0].is_offerable
    assert mcp.request.call_count == 2
