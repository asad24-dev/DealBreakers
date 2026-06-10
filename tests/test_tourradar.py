"""Offline tests for TourRadar normalization and client."""

import json
from unittest.mock import MagicMock

from dealbreakers.mcp.tour_normalizers import (
    TourCandidate,
    country_to_code,
    extract_duration,
    extract_tour_id,
    extract_tour_listings,
    extract_tour_price,
    extract_url,
    merge_tour_candidate,
)
from dealbreakers.mcp.tourradar import TourRadarClient

SEARCH_TOUR = {
    "tour_id": 51327,
    "tour_name": "The Best of Spain",
    "operator": {"id": 1907, "name": "Globus"},
    "tour_url": "https://www.tourradar.com/t/51327",
    "start_city": {"city_name": "Madrid", "country_code": "ES"},
    "prices": {"currency": "USD", "price": 2979},
}

DETAILS_TOUR = {
    "tour_id": 51327,
    "tour_name": "The Best of Spain",
    "tour_length_days": 9,
    "operator": {"name": "Globus"},
    "destinations": {
        "cities": [
            {"city_name": "Madrid", "country_code": "ES"},
            {"city_name": "Seville", "country_code": "ES"},
        ]
    },
    "links": {
        "tour-page": "https://www.tourradar.com/t/51327",
        "book-now": "https://www.tourradar.com/book-now/51327",
    },
    "prices": {"price_total": 2245, "currency": "GBP"},
}

DEPARTURES = {
    "items": [
        {
            "date": "2026-09-03",
            "prices": {"price_total": 2100, "currency": "GBP"},
            "links": [
                {"type": "book-now", "url": "https://www.tourradar.com/book-now/51327?date=03.09.2026"},
            ],
        },
        {
            "date": "2026-10-01",
            "prices": {"price_total": 2300, "currency": "GBP"},
        },
    ]
}


def make_client_with_search(search_payload: dict) -> TourRadarClient:
    mcp = MagicMock()

    def request(method, params):
        name = params["name"]
        if name == "vertex-tour-search":
            return search_payload
        if name == "b2b-tour-details":
            return {"structuredContent": {"tour": DETAILS_TOUR}}
        if name == "b2b-tour-departures":
            return {"structuredContent": DEPARTURES}
        raise AssertionError(f"unexpected tool {name}")

    mcp.request.side_effect = request
    return TourRadarClient(client=mcp)


# --- TourCandidate ---


def test_tour_candidate_is_offerable_requires_price_and_url() -> None:
    assert TourCandidate(name="Tour", price_total=1000.0, url="https://example.com").is_offerable
    assert not TourCandidate(name="Tour", price_total=1000.0).is_offerable
    assert not TourCandidate(name="Tour", url="https://example.com").is_offerable


def test_tour_candidate_to_tour_api_dict_shape() -> None:
    candidate = TourCandidate(
        name="The Best of Spain",
        url="https://www.tourradar.com/t/51327",
        operator="Globus",
        region="Madrid",
        country="Spain",
        duration_days=9,
        price_total=2100.0,
    )
    payload = candidate.to_tour().to_api_dict()
    assert payload["name"] == "The Best of Spain"
    assert payload["priceTotal"] == 2100.0
    assert isinstance(payload["priceTotal"], float)
    assert payload["country"] == "Spain"
    assert payload["durationDays"] == 9
    assert payload["url"].startswith("https://")


# --- extract helpers ---


def test_extract_tour_price_parses_currency_strings() -> None:
    assert extract_tour_price({"prices": {"price_total": "£1,250"}}) == 1250.0
    assert extract_tour_price({"price": "$1,250.50"}) == 1250.50
    assert extract_tour_price({"prices": {"price": "from £1,250"}}) == 1250.0


def test_extract_url_supports_common_fields_and_links() -> None:
    assert extract_url({"tour_url": "https://www.tourradar.com/t/1"}) == "https://www.tourradar.com/t/1"
    assert extract_url({"links": {"book-now": "https://www.tourradar.com/book-now/1"}}) == (
        "https://www.tourradar.com/book-now/1"
    )
    assert extract_url({"slug": "51327"}) == "https://www.tourradar.com/t/51327"


def test_extract_duration_from_days_field_and_name() -> None:
    assert extract_duration({"tour_length_days": 9}) == 9
    assert extract_duration({"tour_name": "Spain in 10 days"}) == 10


def test_country_to_code_maps_spain() -> None:
    assert country_to_code("Spain") == "ES"
    assert country_to_code("ES") == "ES"


# --- extraction from MCP payloads ---


def test_extract_tour_listings_from_structured_content() -> None:
    result = {"structuredContent": {"tours": [SEARCH_TOUR]}}
    assert extract_tour_listings(result) == [SEARCH_TOUR]


def test_extract_tour_listings_from_content_text_json() -> None:
    result = {"content": [{"type": "text", "text": json.dumps({"tours": [SEARCH_TOUR]})}]}
    assert extract_tour_listings(result) == [SEARCH_TOUR]


def test_extract_tour_listings_unknown_shape_returns_empty() -> None:
    assert extract_tour_listings({"unexpected": True}) == []


# --- merge / price priority ---


def test_merge_prefers_departure_price_over_details_and_search() -> None:
    candidate = merge_tour_candidate(SEARCH_TOUR, DETAILS_TOUR, DEPARTURES, country_hint="Spain")
    assert candidate.price_total == 2100.0
    assert candidate.raw["price_source"] == "departure"
    assert candidate.departure_date == "2026-09-03"
    assert candidate.country == "Spain"
    assert candidate.is_offerable


def test_merge_falls_back_to_details_then_search_price() -> None:
    details_only = merge_tour_candidate(SEARCH_TOUR, DETAILS_TOUR, None, country_hint="Spain")
    assert details_only.price_total == 2245.0
    assert details_only.raw["price_source"] == "details"

    search_only = merge_tour_candidate(SEARCH_TOUR, None, None, country_hint="Spain")
    assert search_only.price_total == 2979.0
    assert search_only.raw["price_source"] == "search_result"


# --- TourRadarClient tools/call shape ---


def test_search_tours_builds_vertex_tour_search_call() -> None:
    mcp = MagicMock()
    mcp.request.return_value = {"structuredContent": {"tours": []}}
    client = TourRadarClient(client=mcp)

    client.search_tours(
        query="guided tour of Spain",
        country="Spain",
        min_days=5,
        max_days=12,
        max_price=3000,
        limit=3,
    )

    first_call = mcp.request.call_args_list[0]
    assert first_call.args[0] == "tools/call"
    assert first_call.args[1]["name"] == "vertex-tour-search"
    arguments = first_call.args[1]["arguments"]
    assert arguments["textSearch"] == "guided tour of Spain"
    assert arguments["countries"] == {"values": ["ES"], "operator": "OR"}
    assert arguments["duration"] == {"min": 5, "max": 12}
    assert arguments["price"] == {"min": 0, "max": 3000, "currency": "GBP"}


def test_search_tours_returns_offerable_first() -> None:
    client = make_client_with_search({"structuredContent": {"tours": [SEARCH_TOUR]}})
    candidates = client.search_tours(limit=1)
    assert len(candidates) == 1
    assert candidates[0].is_offerable
    assert candidates[0].name == "The Best of Spain"
