"""Offline tests for city-break orchestration."""

from __future__ import annotations

from unittest.mock import MagicMock

from dealbreakers.mcp.city_break import (
    CityBreakCandidate,
    CityBreakSearchClient,
    needs_city_break_path,
    normalize_trip_type,
    pick_city_break_city,
)
from dealbreakers.mcp.flight_normalizers import FlightCandidate
from dealbreakers.mcp.hotel_normalizers import HotelCandidate
from dealbreakers.state.buyer_state import BuyerState


def make_hotel(**overrides) -> HotelCandidate:
    defaults = dict(
        hotel_name="Central Hotel",
        url="https://trivago.com/hotel/1",
        price_total=400.0,
        star_rating=4.0,
        review_score=8.6,
        city="Berlin",
        country="Germany",
        amenities=["wifi", "gym"],
        nights=4,
    )
    defaults.update(overrides)
    return HotelCandidate(**defaults)


def make_flight(**overrides) -> FlightCandidate:
    defaults = dict(
        route="LON-BER",
        url="https://kiwi.com/flight/1",
        price_total=180.0,
        origin="LON",
        destination="BER",
    )
    defaults.update(overrides)
    return FlightCandidate(**defaults)


def test_city_break_price_includes_hotel_and_flight():
    candidate = CityBreakCandidate(
        hotel=make_hotel(price_total=400.0),
        flight=make_flight(price_total=180.0),
        price_total=580.0,
        city="Berlin",
        country="Germany",
        nights=4,
    )
    holiday = candidate.to_holiday()
    assert holiday.price_total == 580.0


def test_city_break_does_not_invent_flight():
    candidate = CityBreakCandidate(
        hotel=make_hotel(),
        flight=None,
        price_total=400.0,
        city="Berlin",
        country="Germany",
        nights=4,
        raw={"flight_missing": True},
    )
    assert candidate.is_offerable
    assert candidate.flight is None
    assert candidate.to_holiday().price_total == 400.0


def test_needs_city_break_path():
    assert needs_city_break_path(["Berlin"], "city_break")
    assert needs_city_break_path(["Stockholm"], None)
    assert not needs_city_break_path(["Spain"], "holiday")


def test_normalize_trip_type():
    assert normalize_trip_type("city-break") == "city_break"
    assert normalize_trip_type("city break") == "city_break"


def test_pick_city_break_city():
    state = BuyerState(destinations=["Berlin"])
    assert pick_city_break_city(state) == "Berlin"


def test_city_break_search_client_combines_results():
    trivago = MagicMock()
    kiwi = MagicMock()
    trivago.search_hotels.return_value = [make_hotel()]
    trivago.last_errors = []
    kiwi.search_flights.return_value = [make_flight()]
    kiwi.last_errors = []

    client = CityBreakSearchClient(trivago=trivago, kiwi=kiwi)
    results = client.search_city_break(
        "Berlin", "2026-07-10", "2026-07-14", require_flight=False
    )
    assert len(results) == 1
    assert results[0].price_total == 580.0
    assert results[0].raw.get("flight_missing") is False


def test_city_break_flight_missing_flag():
    trivago = MagicMock()
    kiwi = MagicMock()
    trivago.search_hotels.return_value = [make_hotel()]
    trivago.last_errors = []
    kiwi.search_flights.return_value = []
    kiwi.last_errors = []

    client = CityBreakSearchClient(trivago=trivago, kiwi=kiwi)
    results = client.search_city_break("Berlin", "2026-07-10", "2026-07-14")
    assert results[0].raw.get("flight_missing") is True
