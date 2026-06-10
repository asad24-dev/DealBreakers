"""Offline tests for car normalization and MCP car search."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from dealbreakers.mcp.car_normalizers import (
    CarCandidate,
    extract_car_category,
    extract_car_listings,
    extract_car_price,
    extract_car_url,
    extract_seats,
    extract_transmission,
    extract_vehicle_name,
    normalize_car_listing,
)
from dealbreakers.mcp.cars import CarSearchClient, build_economybookings_args
from dealbreakers.mcp.client import MCPError
from dealbreakers.offers.selection import (
    build_holiday_with_car_offer,
    pick_best_car_candidate,
    score_car_candidate,
)
from dealbreakers.mcp.normalizers import HolidayCandidate


def make_car(**overrides) -> CarCandidate:
    defaults = dict(
        vehicle_name="BMW 3 Series",
        url="https://example.com/car/1",
        price_total=280.0,
        category="Premium",
        transmission="Automatic",
        seats=5,
        supplier="Hertz",
        source_mcp="economybookings",
    )
    defaults.update(overrides)
    return CarCandidate(**defaults)


def make_holiday() -> HolidayCandidate:
    return HolidayCandidate(
        hotel_name="Luxury Resort",
        url="https://example.com/hotel",
        price_total=3130.0,
        star_rating=5.0,
        nights=7,
        location="Vilamoura",
        country="Portugal",
    )


def test_car_candidate_is_offerable_requires_price_url_and_identity():
    assert make_car().is_offerable
    assert not make_car(url=None).is_offerable
    assert not make_car(price_total=None).is_offerable
    assert not make_car(vehicle_name=None, category=None).is_offerable
    assert make_car(vehicle_name=None, category="SUV").is_offerable


def test_car_candidate_to_car_api_dict():
    payload = make_car().to_car().to_api_dict()
    assert payload["vehicleName"] == "BMW 3 Series"
    assert payload["priceTotal"] == 280.0
    assert payload["url"].startswith("https://")


def test_extract_car_price_from_strings_and_nested_dicts():
    assert extract_car_price("£112") == 112.0
    assert extract_car_price("from £1,240.50") == 1240.5
    assert extract_car_price({"pricing": {"total": 199}}) == 199.0
    assert extract_car_price({"prices": {"price_total": 150}}) == 150.0
    assert extract_car_price("not-a-price") is None


def test_extract_vehicle_name_and_url_and_category():
    raw = {
        "vehicle": {"name": "Mercedes C-Class"},
        "links": {"booking": "https://example.com/book"},
        "vehicleClass": "Executive",
    }
    assert extract_vehicle_name(raw) == "Mercedes C-Class"
    assert extract_car_url(raw) == "https://example.com/book"
    assert extract_car_category(raw) == "Executive"


def test_extract_transmission_and_seats():
    assert extract_transmission({"transmission": "automatic"}) == "Automatic"
    assert extract_transmission({"transmission": "manual"}) == "Manual"
    assert extract_seats({"seats": "5"}) == 5


def test_malformed_payloads_do_not_crash():
    assert extract_car_listings({"unexpected": True}) == []
    assert normalize_car_listing({}).price_total is None


def test_extract_car_listings_from_content_text_json():
    result = {
        "content": [
            {
                "type": "text",
                "text": json.dumps({
                    "cars": [
                        {
                            "vehicleName": "Audi A4",
                            "url": "https://example.com/audi",
                            "priceTotal": 320,
                        }
                    ]
                }),
            }
        ]
    }
    listings = extract_car_listings(result, source_mcp="economybookings")
    assert len(listings) == 1
    assert listings[0].vehicle_name == "Audi A4"


def test_car_search_client_calls_economybookings():
    mock = MagicMock()
    mock.call_tool.return_value = {
        "structuredContent": {
            "cars": [
                {
                    "vehicleName": "Fiat 500",
                    "url": "https://example.com/fiat",
                    "priceTotal": 90,
                }
            ]
        }
    }
    client = CarSearchClient(economy_client=mock, travelsupermarket_client=MagicMock())
    candidates = client.search_cars("Faro", "2026-07-10", "2026-07-17")
    mock.call_tool.assert_called_once()
    assert candidates[0].vehicle_name == "Fiat 500"


def test_car_search_falls_back_when_economybookings_fails():
    economy = MagicMock()
    economy.call_tool.side_effect = MCPError("down")
    tsm = MagicMock()
    tsm.call_tool.return_value = {
        "structuredContent": {
            "vehicles": [
                {
                    "carName": "VW Golf",
                    "bookingUrl": "https://example.com/golf",
                    "totalPrice": 110,
                }
            ]
        }
    }
    client = CarSearchClient(economy_client=economy, travelsupermarket_client=tsm)
    candidates = client.search_cars("Faro", "2026-07-10", "2026-07-17")
    assert len(client.last_errors) == 1
    assert candidates[0].vehicle_name == "VW Golf"
    assert candidates[0].source_mcp == "travelsupermarket"


def test_premium_tier_prefers_suv_category():
    from dealbreakers.offers.selection import pick_best_car_candidate

    economy = make_car(vehicle_name="Opel Corsa", category="Economy", price_total=75.0)
    suv = make_car(vehicle_name="VW T-Cross", category="SUV", price_total=79.0)
    picked = pick_best_car_candidate([economy, suv], premium=True)
    assert picked is not None
    assert picked.category == "SUV"


def test_premium_car_scoring_prefers_luxury_brand():
    economy = make_car(vehicle_name="Fiat 500", category="Economy", price_total=80.0)
    luxury = make_car(vehicle_name="Mercedes E-Class", category="Executive", price_total=350.0)
    assert score_car_candidate(luxury, premium=True) > score_car_candidate(economy, premium=True)
    assert pick_best_car_candidate([economy, luxury], premium=True) is luxury


def test_combined_offer_contains_holiday_and_car_sources():
    offer = build_holiday_with_car_offer(make_holiday(), make_car(), markup_pct=25.0)
    payload = offer.to_api_dict()
    assert "holiday" in payload
    assert "car" in payload
    assert len(payload["sources"]) == 2
    assert payload["sources"][0]["mcp"] == "travelsupermarket"
    assert payload["sources"][1]["mcp"] == "economybookings"


def test_combined_offer_omits_car_when_unofferable():
    offer = build_holiday_with_car_offer(
        make_holiday(),
        make_car(url=None),
        markup_pct=25.0,
    )
    payload = offer.to_api_dict()
    assert "car" not in payload
    assert len(payload["sources"]) == 1


def test_economybookings_args_shape():
    args = build_economybookings_args("Faro", "2026-07-10", "2026-07-17", 30, 10)
    assert args["pickupLocation"] == "Faro"
    assert args["driverAge"] == 30
