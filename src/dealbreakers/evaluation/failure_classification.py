"""Failure classification for practice evaluation (Phase 8G)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class FailureCategory(StrEnum):
    CLOSED = "closed"
    PRICE_WALK = "price_walk"
    INVENTORY_UNAVAILABLE = "inventory_unavailable"
    DURATION_MISMATCH = "duration_mismatch"
    INVENTORY_OR_PRICE_FLOOR = "inventory_or_price_floor"
    UNRESOLVED_REQUIREMENT = "unresolved_requirement"
    INVALID_OFFER = "invalid_offer"
    API_ERROR = "api_error"
    ROUND_CAP = "round_cap"
    UNKNOWN = "unknown"


def classify_failure(run: dict[str, Any]) -> FailureCategory:
    """Classify a single practice run outcome."""
    if run.get("error"):
        err = str(run.get("error", "")).lower()
        if "offer" in err or "validation" in err or "400" in err:
            return FailureCategory.INVALID_OFFER
        return FailureCategory.API_ERROR

    if run.get("closed"):
        return FailureCategory.CLOSED

    if run.get("walked"):
        if run.get("duration_mismatch"):
            if run.get("final_markup_pct") is not None and float(run["final_markup_pct"]) <= 0:
                return FailureCategory.INVENTORY_OR_PRICE_FLOOR
            return FailureCategory.DURATION_MISMATCH
        if run.get("final_markup_pct") is not None and float(run["final_markup_pct"]) <= 0:
            return FailureCategory.INVENTORY_OR_PRICE_FLOOR
        if run.get("offer_sent") is False:
            return FailureCategory.INVENTORY_UNAVAILABLE
        return FailureCategory.PRICE_WALK

    if run.get("duration_mismatch") and not run.get("closed"):
        return FailureCategory.DURATION_MISMATCH

    if run.get("unresolved_car") or run.get("unresolved_requirement"):
        return FailureCategory.UNRESOLVED_REQUIREMENT

    if run.get("offer_sent") is False:
        return FailureCategory.INVENTORY_UNAVAILABLE

    if run.get("end_reason") == "round_cap" or run.get("round_cap"):
        return FailureCategory.ROUND_CAP

    return FailureCategory.UNKNOWN


def is_gordon_acceptable_failure(category: FailureCategory) -> bool:
    """Gordon may be inventory-limited rather than a policy failure."""
    return category in (
        FailureCategory.DURATION_MISMATCH,
        FailureCategory.INVENTORY_OR_PRICE_FLOOR,
        FailureCategory.INVENTORY_UNAVAILABLE,
        FailureCategory.PRICE_WALK,
    )
