"""Offline tests for failure classification (Phase 8G)."""

from __future__ import annotations

from dealbreakers.evaluation.failure_classification import (
    FailureCategory,
    classify_failure,
    is_gordon_acceptable_failure,
)


def test_closed_classification() -> None:
    assert classify_failure({"closed": True}) == FailureCategory.CLOSED


def test_duration_mismatch_classification() -> None:
    row = {
        "closed": False,
        "walked": True,
        "duration_mismatch": True,
        "final_markup_pct": 12.0,
        "offer_sent": True,
    }
    assert classify_failure(row) == FailureCategory.DURATION_MISMATCH


def test_zero_percent_rejection_inventory_floor() -> None:
    row = {
        "closed": False,
        "walked": True,
        "duration_mismatch": False,
        "final_markup_pct": 0.0,
        "offer_sent": True,
    }
    assert classify_failure(row) == FailureCategory.INVENTORY_OR_PRICE_FLOOR


def test_inventory_unavailable_when_no_offer() -> None:
    row = {"closed": False, "walked": False, "offer_sent": False}
    assert classify_failure(row) == FailureCategory.INVENTORY_UNAVAILABLE


def test_gordon_acceptable_failures() -> None:
    assert is_gordon_acceptable_failure(FailureCategory.DURATION_MISMATCH)
    assert is_gordon_acceptable_failure(FailureCategory.INVENTORY_OR_PRICE_FLOOR)
    assert not is_gordon_acceptable_failure(FailureCategory.INVALID_OFFER)
