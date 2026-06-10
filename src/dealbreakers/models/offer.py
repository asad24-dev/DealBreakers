"""Offer models matching the Deal Room API contract."""

from dataclasses import dataclass, field
from typing import Any


def _omit_none(data: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in data.items() if value is not None}


@dataclass
class Holiday:
    price_total: float
    hotel_name: str | None = None
    url: str | None = None
    star_rating: float | None = None
    review_score: float | None = None
    board_basis: str | None = None
    nights: int | None = None
    location: str | None = None
    country: str | None = None
    region: str | None = None
    amenities: list[str] = field(default_factory=list)

    def to_api_dict(self) -> dict[str, Any]:
        data = _omit_none({
            "priceTotal": self.price_total,
            "hotelName": self.hotel_name,
            "url": self.url,
            "starRating": self.star_rating,
            "reviewScore": self.review_score,
            "boardBasis": self.board_basis,
            "nights": self.nights,
            "location": self.location,
            "country": self.country,
            "region": self.region,
        })
        if self.amenities:
            data["amenities"] = self.amenities
        return data


@dataclass
class Tour:
    price_total: float
    name: str | None = None
    url: str | None = None
    operator: str | None = None
    region: str | None = None
    country: str | None = None
    duration_days: int | None = None
    location: str | None = None
    supplier: str | None = None

    def to_api_dict(self) -> dict[str, Any]:
        return _omit_none({
            "priceTotal": self.price_total,
            "name": self.name,
            "url": self.url,
            "operator": self.operator,
            "region": self.region,
            "country": self.country,
            "durationDays": self.duration_days,
            "location": self.location,
            "supplier": self.supplier,
        })


@dataclass
class Car:
    price_total: float
    vehicle_name: str | None = None
    url: str | None = None
    category: str | None = None
    transmission: str | None = None
    seats: int | None = None
    supplier: str | None = None

    def to_api_dict(self) -> dict[str, Any]:
        return _omit_none({
            "priceTotal": self.price_total,
            "vehicleName": self.vehicle_name,
            "url": self.url,
            "category": self.category,
            "transmission": self.transmission,
            "seats": self.seats,
            "supplier": self.supplier,
        })


@dataclass
class Source:
    mcp: str
    url: str
    price: float

    def to_api_dict(self) -> dict[str, Any]:
        return {"mcp": self.mcp, "url": self.url, "price": self.price}


@dataclass
class Offer:
    holiday: Holiday | None = None
    tour: Tour | None = None
    car: Car | None = None
    markup_pct: float = 0.0
    sources: list[Source] = field(default_factory=list)

    def to_api_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"markupPct": self.markup_pct}

        if self.holiday is not None:
            data["holiday"] = self.holiday.to_api_dict()
        if self.tour is not None:
            data["tour"] = self.tour.to_api_dict()
        if self.car is not None:
            data["car"] = self.car.to_api_dict()
        if self.sources:
            data["sources"] = [source.to_api_dict() for source in self.sources]

        return data
