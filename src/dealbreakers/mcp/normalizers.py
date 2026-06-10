"""Normalize raw MCP listings into offer-compatible structures.

Conservative by design: we only map amenities and board basis when the source
clearly states them. Misrepresentation is disqualification.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from dealbreakers.constants import AMENITY_VOCABULARY
from dealbreakers.models.offer import Holiday

# TravelSupermarket facility IDs (from the search-holidays input schema) map
# 1:1 onto the canonical amenity vocabulary.
FACILITY_ID_TO_AMENITY: dict[int, str] = {
    1: "pool",
    2: "close_to_beach",
    3: "air_conditioning",
    4: "wifi",
    5: "balcony",
    6: "kids_club",
    7: "restaurant",
    8: "childrens_pool",
    9: "wheelchair_access",
    10: "nightclub",
    11: "bar",
    12: "spa",
    13: "playground",
    14: "pool_bar",
    15: "sun_loungers",
    16: "entertainment",
    17: "water_sports",
    18: "sports",
    19: "gym",
    20: "jacuzzi",
    21: "sun_terrace",
    22: "games_room",
    23: "golf",
    24: "shopping",
}

AMENITY_TO_FACILITY_ID: dict[str, int] = {
    amenity: facility_id for facility_id, amenity in FACILITY_ID_TO_AMENITY.items()
}

# Ordered: more specific phrases first so "children's pool" never matches "pool".
_AMENITY_PHRASES: list[tuple[str, str]] = [
    ("children's pool", "childrens_pool"),
    ("childrens pool", "childrens_pool"),
    ("kids pool", "childrens_pool"),
    ("pool bar", "pool_bar"),
    ("swimming pool", "pool"),
    ("outdoor pool", "pool"),
    ("indoor pool", "pool"),
    ("pool", "pool"),
    ("close to beach", "close_to_beach"),
    ("close to the beach", "close_to_beach"),
    ("near beach", "close_to_beach"),
    ("near the beach", "close_to_beach"),
    ("beachfront", "close_to_beach"),
    ("beach front", "close_to_beach"),
    ("kids club", "kids_club"),
    ("kids' club", "kids_club"),
    ("children club", "kids_club"),
    ("children's club", "kids_club"),
    ("air conditioning", "air_conditioning"),
    ("air-conditioning", "air_conditioning"),
    ("air con", "air_conditioning"),
    ("wifi", "wifi"),
    ("wi-fi", "wifi"),
    ("internet access", "wifi"),
    ("balcony", "balcony"),
    ("terrace", "sun_terrace"),
    ("sun terrace", "sun_terrace"),
    ("sun lounger", "sun_loungers"),
    ("spa", "spa"),
    ("wellness", "spa"),
    ("jacuzzi", "jacuzzi"),
    ("hot tub", "jacuzzi"),
    ("gym", "gym"),
    ("fitness", "gym"),
    ("restaurant", "restaurant"),
    ("bar", "bar"),
    ("nightclub", "nightclub"),
    ("playground", "playground"),
    ("entertainment", "entertainment"),
    ("water sport", "water_sports"),
    ("sports facilities", "sports"),
    ("games room", "games_room"),
    ("golf", "golf"),
    ("shopping", "shopping"),
    ("wheelchair access", "wheelchair_access"),
    ("wheelchair", "wheelchair_access"),
    ("family friendly", "family_friendly"),
    ("family-friendly", "family_friendly"),
]

_BOARD_BASIS_MAP: dict[str, str] = {
    "ai": "AI",
    "all inclusive": "AI",
    "all-inclusive": "AI",
    "all incl": "AI",
    "fb": "FB",
    "full board": "FB",
    "hb": "HB",
    "half board": "HB",
    "bb": "BB",
    "b&b": "BB",
    "bed & breakfast": "BB",
    "bed and breakfast": "BB",
    "breakfast": "BB",
    "sc": "SC",
    "self catering": "SC",
    "self-catering": "SC",
    "ro": "RO",
    "room only": "RO",
}


def normalize_amenity(text: str) -> str | None:
    """Map one free-text amenity to a canonical word, or None if unclear."""
    lowered = text.strip().lower()
    if not lowered:
        return None
    if lowered in AMENITY_VOCABULARY:
        return lowered
    for phrase, canonical in _AMENITY_PHRASES:
        # Word boundaries so e.g. "bar" never matches "barbecue".
        if re.search(rf"\b{re.escape(phrase)}\b", lowered):
            return canonical
    return None


def normalize_amenities(values: list[Any]) -> list[str]:
    """Map a mixed list of amenity strings / facility IDs to canonical words."""
    seen: list[str] = []
    for value in values:
        canonical: str | None = None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            canonical = FACILITY_ID_TO_AMENITY.get(int(value))
        elif isinstance(value, str):
            if value.strip().isdigit():
                canonical = FACILITY_ID_TO_AMENITY.get(int(value.strip()))
            else:
                canonical = normalize_amenity(value)
        if canonical and canonical not in seen:
            seen.append(canonical)
    return seen


def normalize_board_basis(value: str | None) -> str | None:
    """Map free-text board basis to AI/FB/HB/BB/SC/RO, or None if unclear."""
    if not value:
        return None
    return _BOARD_BASIS_MAP.get(value.strip().lower())


def extract_price(value: Any) -> float | None:
    """Extract a numeric price from a number or a string like '£1,234.56'."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = re.sub(r"[^0-9.]", "", value)
        if cleaned.count(".") <= 1 and cleaned not in ("", "."):
            return float(cleaned)
    return None


@dataclass
class HolidayCandidate:
    """A normalized holiday listing, convertible into an offer Holiday."""

    hotel_name: str | None = None
    url: str | None = None
    star_rating: float | None = None
    review_score: float | None = None
    board_basis: str | None = None
    nights: int | None = None
    location: str | None = None
    region: str | None = None
    country: str | None = None
    amenities: list[str] = field(default_factory=list)
    price_total: float | None = None
    raw: dict = field(default_factory=dict)

    @property
    def is_offerable(self) -> bool:
        """True when this candidate has the minimum needed for a valid offer."""
        return self.price_total is not None and bool(self.url)

    def to_holiday(self) -> Holiday:
        if self.price_total is None:
            raise ValueError("Cannot build a Holiday without a numeric price_total")
        return Holiday(
            price_total=self.price_total,
            hotel_name=self.hotel_name,
            url=self.url,
            star_rating=self.star_rating,
            review_score=self.review_score,
            board_basis=self.board_basis,
            nights=self.nights,
            location=self.location,
            country=self.country,
            region=self.region,
            amenities=list(self.amenities),
        )
