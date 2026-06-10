"""Structured output of conversation analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

TRIP_TYPES = {"holiday", "tour", "city_break"}


def _clamp01(value: Any, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _opt_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


@dataclass
class ConversationAnalysis:
    """Actionable buyer signals extracted from the conversation so far."""

    trip_type: str | None = None          # "holiday" | "tour" | None if unknown
    destinations: list[str] = field(default_factory=list)
    must_haves: list[str] = field(default_factory=list)
    nice_to_haves: list[str] = field(default_factory=list)

    budget_min: float | None = None
    budget_max: float | None = None

    price_sensitivity: float = 0.0
    trust_sensitivity: float = 0.0
    luxury_preference: float = 0.0

    objections: list[str] = field(default_factory=list)

    desired_nights: int | None = None

    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trip_type": self.trip_type,
            "destinations": list(self.destinations),
            "must_haves": list(self.must_haves),
            "nice_to_haves": list(self.nice_to_haves),
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
            "price_sensitivity": self.price_sensitivity,
            "trust_sensitivity": self.trust_sensitivity,
            "luxury_preference": self.luxury_preference,
            "objections": list(self.objections),
            "desired_nights": self.desired_nights,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationAnalysis":
        """Build from (possibly imperfect) LLM JSON. Every field always populated."""
        trip_type = data.get("trip_type")
        if isinstance(trip_type, str):
            trip_type = trip_type.strip().lower() or None
            if trip_type not in TRIP_TYPES:
                trip_type = None
        else:
            trip_type = None

        budget_min = _opt_float(data.get("budget_min"))
        budget_max = _opt_float(data.get("budget_max"))
        if budget_min is not None and budget_max is not None and budget_min > budget_max:
            budget_min, budget_max = budget_max, budget_min

        return cls(
            trip_type=trip_type,
            destinations=_str_list(data.get("destinations")),
            must_haves=_str_list(data.get("must_haves")),
            nice_to_haves=_str_list(data.get("nice_to_haves")),
            budget_min=budget_min,
            budget_max=budget_max,
            price_sensitivity=_clamp01(data.get("price_sensitivity")),
            trust_sensitivity=_clamp01(data.get("trust_sensitivity")),
            luxury_preference=_clamp01(data.get("luxury_preference")),
            objections=_str_list(data.get("objections")),
            desired_nights=_opt_int(data.get("desired_nights")),
            confidence=_clamp01(data.get("confidence")),
        )


def _opt_int(value: Any) -> int | None:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None
