"""Normalize Trivago hotel MCP listings into offer-compatible HotelCandidate objects."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from dealbreakers.mcp.normalizers import extract_price
from dealbreakers.models.offer import Holiday

_AMENITY_MAP: list[tuple[str, str]] = [
    ("wifi", "wifi"),
    ("wi-fi", "wifi"),
    ("gym", "gym"),
    ("fitness", "gym"),
    ("air conditioning", "air_conditioning"),
    ("bar", "bar"),
    ("spa", "spa"),
    ("restaurant", "restaurant"),
    ("balcony", "balcony"),
    ("jacuzzi", "jacuzzi"),
    ("hot tub", "jacuzzi"),
]


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if data.get(key) is not None:
            return data[key]
    return None


def map_hotel_amenities(raw: Any) -> list[str]:
    """Map hotel amenity text conservatively to canonical vocabulary."""
    if raw is None:
        return []
    if isinstance(raw, list):
        text = " ".join(str(item) for item in raw).lower()
    else:
        text = str(raw).lower()

    found: list[str] = []
    for phrase, canonical in _AMENITY_MAP:
        if phrase in text and canonical not in found:
            found.append(canonical)
    return found


def extract_hotel_price(raw: Any) -> float | None:
    if isinstance(raw, str):
        cleaned = re.sub(r"[^0-9.]", "", raw.replace(",", ""))
        if cleaned and cleaned != ".":
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None
    return extract_price(raw)


def _parse_nights(arrival: str | None, departure: str | None) -> int | None:
    if not arrival or not departure:
        return None
    try:
        start = date.fromisoformat(arrival[:10])
        end = date.fromisoformat(departure[:10])
        nights = (end - start).days
        return nights if nights > 0 else None
    except ValueError:
        return None


def _split_city_country(country_city: str | None) -> tuple[str | None, str | None]:
    if not country_city:
        return None, None
    if "," in country_city:
        city, country = country_city.rsplit(",", 1)
        return city.strip(), country.strip()
    return country_city.strip(), None


@dataclass
class HotelCandidate:
    hotel_name: str | None = None
    url: str | None = None
    star_rating: float | None = None
    review_score: float | None = None
    price_total: float | None = None
    location: str | None = None
    city: str | None = None
    country: str | None = None
    amenities: list[str] = field(default_factory=list)
    nights: int | None = None
    raw: dict = field(default_factory=dict)

    @property
    def is_offerable(self) -> bool:
        return (
            self.price_total is not None
            and self.price_total > 0
            and bool(self.url)
            and self.url.startswith("http")
        )

    def to_holiday(self, *, price_total: float | None = None) -> Holiday:
        """Convert standalone hotel to Deal Room Holiday product."""
        city = self.city or self.location
        return Holiday(
            price_total=price_total if price_total is not None else (self.price_total or 0.0),
            hotel_name=self.hotel_name,
            url=self.url,
            star_rating=self.star_rating,
            review_score=self.review_score,
            board_basis="RO",
            nights=self.nights,
            location=self.location or city,
            region=city,
            country=self.country,
            amenities=list(self.amenities),
        )


def extract_hotel_listings(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull accommodation arrays from Trivago MCP responses."""
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        for key in ("accommodations", "results", "hotels", "items", "data"):
            value = structured.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

    for item in result.get("content", []):
        if item.get("type") != "text":
            continue
        try:
            parsed = json.loads(item.get("text", ""))
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, list):
            return [entry for entry in parsed if isinstance(entry, dict)]
        if isinstance(parsed, dict):
            for key in ("accommodations", "results", "hotels", "items", "data"):
                value = parsed.get(key)
                if isinstance(value, list):
                    return [entry for entry in value if isinstance(entry, dict)]

    return []


def normalize_hotel_listing(raw: dict[str, Any]) -> HotelCandidate:
    """Map one Trivago accommodation into a HotelCandidate."""
    arrival = _first(raw, "arrival", "checkin", "check_in")
    departure = _first(raw, "departure", "checkout", "check_out")
    nights = _parse_nights(
        arrival if isinstance(arrival, str) else None,
        departure if isinstance(departure, str) else None,
    )

    country_city = _first(raw, "country_city", "location_label", "city")
    city, country = _split_city_country(country_city if isinstance(country_city, str) else None)

    url = _first(raw, "booking_url", "accommodation_url", "url", "deepLink")
    price = extract_hotel_price(_first(raw, "price_per_stay", "price_total", "price"))
    if price is None:
        price = extract_hotel_price(_first(raw, "price_per_night"))

    review_raw = _first(raw, "review_rating", "review_score", "rating")
    review_score = extract_hotel_price(review_raw)

    stars_raw = _first(raw, "hotel_rating", "star_rating", "stars")
    star_rating = extract_hotel_price(stars_raw)

    amenities = map_hotel_amenities(_first(raw, "top_amenities", "amenities", "facilities"))

    filters = raw.get("filters")
    if isinstance(filters, dict):
        if filters.get("freeWiFi") and "wifi" not in amenities:
            amenities.append("wifi")
        if filters.get("gym") and "gym" not in amenities:
            amenities.append("gym")

    name = _first(raw, "accommodation_name", "hotel_name", "name")
    address = _first(raw, "address")
    location = country_city if isinstance(country_city, str) else None
    if isinstance(address, str) and address.strip():
        location = address.strip()

    return HotelCandidate(
        hotel_name=name if isinstance(name, str) else None,
        url=url if isinstance(url, str) else None,
        star_rating=star_rating,
        review_score=review_score,
        price_total=price,
        location=location,
        city=city,
        country=country,
        amenities=amenities,
        nights=nights,
        raw=raw,
    )
