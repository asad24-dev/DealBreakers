"""Normalize car hire MCP listings into offer-compatible CarCandidate objects."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from dealbreakers.mcp.normalizers import extract_price
from dealbreakers.models.offer import Car

_PREMIUM_BRANDS = (
    "mercedes",
    "bmw",
    "audi",
    "range rover",
    "tesla",
    "jaguar",
    "lexus",
    "volvo",
    "porsche",
    "bentley",
)


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if data.get(key) is not None:
            return data[key]
    return None


def _nested_dict(data: dict[str, Any], *paths: tuple[str, ...]) -> dict[str, Any] | None:
    for path in paths:
        current: Any = data
        for key in path:
            if not isinstance(current, dict):
                current = None
                break
            current = current.get(key)
        if isinstance(current, dict):
            return current
    return None


def extract_car_price(raw: Any) -> float | None:
    """Extract numeric price from numbers, strings, or nested pricing dicts."""
    if isinstance(raw, dict):
        for key in ("priceTotal", "totalPrice", "price_total", "price", "amount", "total"):
            value = raw.get(key)
            parsed = extract_car_price(value)
            if parsed is not None:
                return parsed
        for nested in ("pricing", "prices", "price"):
            inner = raw.get(nested)
            if isinstance(inner, dict):
                parsed = extract_car_price(inner)
                if parsed is not None:
                    return parsed
        return None

    if isinstance(raw, str):
        cleaned = re.sub(r"[^0-9.]", "", raw.replace(",", ""))
        if cleaned and cleaned != ".":
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None

    return extract_price(raw)


def extract_vehicle_name(raw: dict[str, Any]) -> str | None:
    for key in ("vehicleName", "carName", "model", "name", "vehicle"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    vehicle = raw.get("vehicle")
    if isinstance(vehicle, dict):
        name = _first(vehicle, "name", "model", "vehicleName")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


def extract_car_url(raw: dict[str, Any]) -> str | None:
    for key in (
        "url",
        "bookingUrl",
        "deepLinkUrl",
        "redirectUrl",
        "bookingURL",
        "link",
        "href",
        "deeplink",
    ):
        value = raw.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    links = raw.get("links")
    if isinstance(links, dict):
        for key in ("booking", "deepLink", "book-now", "url"):
            value = links.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
    return None


def extract_car_category(raw: dict[str, Any]) -> str | None:
    for key in ("category", "categoryName", "class", "vehicleClass", "carClass"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    vehicle = raw.get("vehicle")
    if isinstance(vehicle, dict):
        category = _first(vehicle, "category", "class", "vehicleClass")
        if isinstance(category, str) and category.strip():
            return category.strip()
    return None


def extract_transmission(raw: dict[str, Any]) -> str | None:
    value = _first(raw, "transmission", "gearbox", "transmissionType")
    if isinstance(value, dict):
        value = _first(value, "name", "type", "value")
    if not isinstance(value, str):
        return None
    lowered = value.strip().lower()
    if "auto" in lowered:
        return "Automatic"
    if "manual" in lowered:
        return "Manual"
    return None


def extract_seats(raw: dict[str, Any]) -> int | None:
    value = _first(raw, "seats", "passengers", "passengerCount", "capacity")
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, float) and value > 0:
        return int(value)
    if isinstance(value, str):
        match = re.search(r"\d+", value)
        if match:
            return int(match.group())
    vehicle = raw.get("vehicle")
    if isinstance(vehicle, dict):
        return extract_seats(vehicle)
    return None


def extract_supplier(raw: dict[str, Any]) -> str | None:
    for key in ("supplier", "supplierName", "provider", "operator", "rentalCompany"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            name = _first(value, "name", "supplier")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return None


def normalize_car_listing(raw: dict[str, Any], source_mcp: str | None = None) -> CarCandidate:
    price_raw = _first(raw, "priceTotal", "totalPrice", "price", "amount", "leadInPrice")
    if price_raw is None:
        price_raw = raw
    return CarCandidate(
        vehicle_name=extract_vehicle_name(raw),
        url=extract_car_url(raw),
        price_total=extract_car_price(price_raw),
        category=extract_car_category(raw),
        transmission=extract_transmission(raw),
        seats=extract_seats(raw),
        supplier=extract_supplier(raw),
        source_mcp=source_mcp,
        raw=raw,
    )


def _find_car_listing_array(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []

    for key in ("cars", "vehicles", "results", "offers", "items", "data", "listings"):
        value = data.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
        if isinstance(value, dict):
            nested = _find_car_listing_array(value)
            if nested:
                return nested
    return []


def extract_car_listings(result: Any, source_mcp: str | None = None) -> list[CarCandidate]:
    """Pull car listings from MCP tools/call result shapes."""
    if isinstance(result, dict):
        structured = result.get("structuredContent")
        if structured is not None:
            found = _find_car_listing_array(structured)
            if found:
                return [normalize_car_listing(item, source_mcp) for item in found]

        for item in result.get("content", []):
            if item.get("type") != "text":
                continue
            try:
                parsed = json.loads(item.get("text", ""))
            except (ValueError, TypeError):
                continue
            found = _find_car_listing_array(parsed)
            if found:
                return [normalize_car_listing(item, source_mcp) for item in found]

        found = _find_car_listing_array(result)
        if found:
            return [normalize_car_listing(item, source_mcp) for item in found]

    if isinstance(result, list):
        return [normalize_car_listing(item, source_mcp) for item in result if isinstance(item, dict)]

    return []


def is_premium_looking(candidate: CarCandidate) -> bool:
    text = " ".join(
        part for part in (candidate.vehicle_name, candidate.category) if part
    ).lower()
    if any(word in text for word in ("premium", "luxury", "executive")):
        return True
    if "suv" in text:
        return True
    return any(brand in text for brand in _PREMIUM_BRANDS)


@dataclass
class CarCandidate:
    vehicle_name: str | None = None
    url: str | None = None
    price_total: float | None = None
    category: str | None = None
    transmission: str | None = None
    seats: int | None = None
    supplier: str | None = None
    source_mcp: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def is_offerable(self) -> bool:
        has_identity = bool(self.vehicle_name or self.category)
        return (
            self.price_total is not None
            and bool(self.url)
            and has_identity
        )

    def to_car(self) -> Car:
        if self.price_total is None:
            raise ValueError("Cannot build a Car without a numeric price_total")
        return Car(
            price_total=self.price_total,
            vehicle_name=self.vehicle_name,
            url=self.url,
            category=self.category,
            transmission=self.transmission,
            seats=self.seats,
            supplier=self.supplier,
        )
