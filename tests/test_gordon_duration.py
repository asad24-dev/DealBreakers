"""Tests for Gordon 14-night duration handling."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dealbreakers.mcp.normalizers import HolidayCandidate
from dealbreakers.negotiation.actions import NegotiationAction
from dealbreakers.negotiation.live_agent import (
    AgentSessionState,
    InventoryState,
    apply_policy_overrides,
    search_holidays,
)
from dealbreakers.negotiation.policy import PolicyDecision
from dealbreakers.offers.selection import (
    find_cheaper_equivalent_holiday,
    pick_best_holiday_for_duration,
)
from dealbreakers.state.buyer_state import (
    BuyerState,
    detect_shorter_stay_acceptance,
    detect_shorter_stay_rejection,
    extract_desired_nights,
)


def make_holiday(**overrides) -> HolidayCandidate:
    defaults = dict(
        hotel_name="Luxury Resort",
        url="https://example.com/hotel",
        price_total=3000.0,
        star_rating=5.0,
        review_score=9.0,
        nights=7,
        amenities=["spa", "close_to_beach", "pool"],
    )
    defaults.update(overrides)
    return HolidayCandidate(**defaults)


def test_extract_desired_nights_ten_and_fourteen():
    assert extract_desired_nights("I need ten nights minimum") == 10
    assert extract_desired_nights("two weeks in the sun") == 14


def test_search_holidays_logs_all_durations():
    state = BuyerState(destinations=["Spain"], desired_nights=14, luxury_preference=0.9)
    client = MagicMock()
    client.search_holidays.side_effect = [
        [],
        [make_holiday(nights=10, url="https://a.com")],
        [make_holiday(nights=7, url="https://b.com")],
    ]
    inventory = search_holidays(state, client)
    assert "14n" in inventory.search_note
    assert "10n" in inventory.search_note
    assert "7n" in inventory.search_note
    assert len(inventory.holiday_candidates) == 2


def test_pick_best_prefers_exact_duration():
    state = BuyerState(desired_nights=14)
    candidates = [
        make_holiday(nights=7, price_total=2500.0),
        make_holiday(nights=14, price_total=4000.0, url="https://14.com"),
    ]
    best = pick_best_holiday_for_duration(candidates, state)
    assert best is not None
    assert best.nights == 14


def test_pick_best_blocks_shorter_without_permission():
    state = BuyerState(desired_nights=14)
    candidates = [make_holiday(nights=7)]
    assert pick_best_holiday_for_duration(candidates, state, shorter_stay_accepted=None) is None
    assert pick_best_holiday_for_duration(candidates, state, shorter_stay_accepted=False) is None


def test_pick_best_allows_shorter_when_accepted():
    state = BuyerState(desired_nights=14)
    candidates = [make_holiday(nights=7)]
    best = pick_best_holiday_for_duration(candidates, state, shorter_stay_accepted=True)
    assert best is not None
    assert best.nights == 7


def test_duration_permission_refine_before_offer():
    state = BuyerState(desired_nights=14)
    session = AgentSessionState()
    inventory = InventoryState(holiday_candidates=[make_holiday(nights=7)])
    decision = PolicyDecision(
        action=NegotiationAction.OFFER,
        confidence=0.8,
        reasoning="inventory ready",
    )
    overridden = apply_policy_overrides(
        decision,
        state,
        "show me options",
        session=session,
        inventory_ready=True,
        inventory=inventory,
    )
    assert overridden.action is NegotiationAction.REFINE
    assert session.shorter_stay_permission_asked


def test_shorter_stay_acceptance_detection():
    assert detect_shorter_stay_acceptance("Yes, if the quality is strong")
    assert detect_shorter_stay_rejection("No — I need two weeks")


def test_find_cheaper_equivalent_holiday():
    state = BuyerState(luxury_preference=0.9, must_haves=["spa"])
    current = make_holiday(price_total=5000.0, url="https://current.com")
    cheaper = make_holiday(
        price_total=3500.0,
        url="https://cheaper.com",
        review_score=9.0,
    )
    result = find_cheaper_equivalent_holiday([current, cheaper], current, state)
    assert result is not None
    assert result.url == "https://cheaper.com"
