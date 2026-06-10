"""Tests for Elon city-break inventory routing."""

from __future__ import annotations

from unittest.mock import MagicMock

from dealbreakers.mcp.city_break import CityBreakCandidate
from dealbreakers.mcp.hotel_normalizers import HotelCandidate
from dealbreakers.mcp.normalizers import HolidayCandidate
from dealbreakers.negotiation.live_agent import run_inventory_search
from dealbreakers.state.buyer_state import BuyerState


def test_run_inventory_search_routes_city_break_not_tsm():
    state = BuyerState(
        trip_type="city_break",
        destinations=["Berlin"],
        must_haves=["wifi", "gym", "central"],
    )
    tsm = MagicMock()
    tourradar = MagicMock()
    city_break = MagicMock()
    hotel = HotelCandidate(
        hotel_name="Test Hotel",
        url="https://trivago.com/1",
        price_total=500.0,
        city="Berlin",
        country="Germany",
        amenities=["wifi", "gym"],
        nights=4,
    )
    city_break.search_city_break = MagicMock(return_value=[
        CityBreakCandidate(
            hotel=hotel,
            flight=None,
            price_total=500.0,
            city="Berlin",
            country="Germany",
            nights=4,
        )
    ])
    city_break.last_errors = []

    inventory = run_inventory_search(
        state, tsm=tsm, tourradar=tourradar, city_break=city_break
    )

    tsm.search_holidays.assert_not_called()
    assert city_break.search_city_break.called
    assert len(inventory.holiday_candidates) >= 1
    assert inventory.holiday_candidates[0].hotel_name == "Test Hotel"


def test_city_break_candidate_maps_to_holiday_candidate():
    from dealbreakers.negotiation.live_agent import city_break_to_holiday_candidate

    hotel = HotelCandidate(
        hotel_name="Central Berlin",
        url="https://trivago.com/2",
        price_total=600.0,
        nights=4,
        amenities=["wifi", "gym"],
    )
    cb = CityBreakCandidate(
        hotel=hotel,
        flight=None,
        price_total=680.0,
        city="Berlin",
        country="Germany",
        nights=4,
        raw={"flight_missing": True},
    )
    mapped = city_break_to_holiday_candidate(cb)
    assert isinstance(mapped, HolidayCandidate)
    assert mapped.price_total == 680.0
