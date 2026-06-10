from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


AMENITIES = {
    "pool",
    "close_to_beach",
    "air_conditioning",
    "wifi",
    "balcony",
    "kids_club",
    "restaurant",
    "childrens_pool",
    "wheelchair_access",
    "nightclub",
    "bar",
    "spa",
    "playground",
    "pool_bar",
    "sun_loungers",
    "entertainment",
    "water_sports",
    "sports",
    "gym",
    "jacuzzi",
    "sun_terrace",
    "games_room",
    "golf",
    "shopping",
    "family_friendly",
}


@dataclass
class BuyerProfile:
    persona: str = ""
    brief: str = ""
    trip_type: str | None = None
    destination: str | None = None
    country: str | None = None
    region: str | None = None
    city: str | None = None
    nights: int | None = None
    duration_days: int | None = None
    party_size: int | None = None
    wants_car: bool | None = None
    min_stars: float | None = None
    budget_hint: float | None = None
    amenities: set[str] = field(default_factory=set)
    dislikes: set[str] = field(default_factory=set)
    raw_notes: list[str] = field(default_factory=list)


@dataclass
class Listing:
    mcp: str
    kind: str
    name: str
    url: str
    price: float
    raw: dict[str, Any]
    country: str | None = None
    region: str | None = None
    location: str | None = None
    star_rating: float | None = None
    review_score: float | None = None
    board_basis: str | None = None
    nights: int | None = None
    amenities: list[str] = field(default_factory=list)
    operator: str | None = None
    duration_days: int | None = None
    vehicle_name: str | None = None
    transmission: str | None = None
    seats: int | None = None


@dataclass
class OfferPlan:
    product: Listing
    car: Listing | None
    markup_pct: float
    reason: str

