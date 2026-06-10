"""Offline tests for Kiwi flight MCP integration."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from dealbreakers.mcp.flight_normalizers import (
    FlightCandidate,
    extract_flight_listings,
    iso_to_kiwi_date,
    normalize_flight_listing,
)
from dealbreakers.mcp.kiwi import KiwiClient, city_to_iata

SAMPLE_FLIGHT = {
    "flyFrom": "LGW",
    "flyTo": "BER",
    "price": 176,
    "deepLink": "https://on.kiwi.com/test",
    "departure": {"local": "2026-07-10T06:40:00.000"},
    "return": {"departure": {"local": "2026-07-14T06:25:00.000"}},
}


def test_iso_to_kiwi_date():
    assert iso_to_kiwi_date("2026-07-10") == "10/07/2026"


def test_flight_candidate_is_offerable():
    flight = normalize_flight_listing(SAMPLE_FLIGHT)
    assert flight.is_offerable
    assert not FlightCandidate(url=None, price_total=100.0).is_offerable


def test_normalize_flight_listing():
    flight = normalize_flight_listing(SAMPLE_FLIGHT)
    assert flight.route == "LGW-BER"
    assert flight.price_total == 176.0
    assert flight.url == "https://on.kiwi.com/test"


def test_extract_flight_listings_from_content_text():
    payload = {
        "content": [{"type": "text", "text": json.dumps([SAMPLE_FLIGHT])}],
    }
    listings = extract_flight_listings(payload)
    assert len(listings) == 1


def test_malformed_flight_payloads_do_not_crash():
    assert extract_flight_listings({"unexpected": True}) == []
    assert normalize_flight_listing({}).price_total is None


def test_city_to_iata():
    assert city_to_iata("Berlin") == "BER"
    assert city_to_iata("STO") == "STO"


def test_kiwi_client_search_flights():
    mcp = MagicMock()
    mcp.request.return_value = {
        "content": [{"type": "text", "text": json.dumps([SAMPLE_FLIGHT])}],
    }
    client = KiwiClient(client=mcp)
    flights = client.search_flights("LON", "BER", "2026-07-10", "2026-07-14")
    assert len(flights) == 1
    assert flights[0].is_offerable
    args = mcp.request.call_args[0][1]["arguments"]
    assert args["departureDate"] == "10/07/2026"
    assert args["returnDate"] == "14/07/2026"
