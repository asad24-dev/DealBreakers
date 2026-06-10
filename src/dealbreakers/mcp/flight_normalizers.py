"""Normalize Kiwi flight MCP listings into FlightCandidate objects."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from dealbreakers.mcp.normalizers import extract_price


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if data.get(key) is not None:
            return data[key]
    return None


def iso_to_kiwi_date(iso_date: str) -> str:
    """Convert YYYY-MM-DD to Kiwi dd/mm/yyyy format."""
    parts = iso_date.strip()[:10].split("-")
    if len(parts) != 3:
        return iso_date
    year, month, day = parts
    return f"{day}/{month}/{year}"


@dataclass
class FlightCandidate:
    carrier: str | None = None
    route: str | None = None
    url: str | None = None
    price_total: float | None = None
    departure_date: str | None = None
    return_date: str | None = None
    origin: str | None = None
    destination: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def is_offerable(self) -> bool:
        return (
            self.price_total is not None
            and self.price_total > 0
            and bool(self.url)
            and self.url.startswith("http")
        )


def extract_flight_listings(result: dict[str, Any]) -> list[dict[str, Any]]:
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        for key in ("flights", "results", "data", "items"):
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
            for key in ("flights", "results", "data", "items"):
                value = parsed.get(key)
                if isinstance(value, list):
                    return [entry for entry in value if isinstance(entry, dict)]
    return []


def normalize_flight_listing(raw: dict[str, Any]) -> FlightCandidate:
    fly_from = _first(raw, "flyFrom", "origin", "from")
    fly_to = _first(raw, "flyTo", "destination", "to")
    route = None
    if fly_from and fly_to:
        route = f"{fly_from}-{fly_to}"

    url = _first(raw, "deepLink", "url", "bookingUrl", "booking_url")
    price = extract_price(_first(raw, "price", "price_total", "priceTotal"))

    departure = _first(raw, "departureDate", "departure_date")
    if departure is None and isinstance(raw.get("departure"), dict):
        local = raw["departure"].get("local")
        if isinstance(local, str):
            departure = local[:10]

    return_date = _first(raw, "returnDate", "return_date")
    ret = raw.get("return")
    if return_date is None and isinstance(ret, dict):
        dep = ret.get("departure")
        if isinstance(dep, dict) and isinstance(dep.get("local"), str):
            return_date = dep["local"][:10]

    carrier = _first(raw, "airline", "carrier", "airlines")
    if isinstance(carrier, list) and carrier:
        carrier = carrier[0]

    return FlightCandidate(
        carrier=carrier if isinstance(carrier, str) else None,
        route=route,
        url=url if isinstance(url, str) else None,
        price_total=price,
        departure_date=departure if isinstance(departure, str) else None,
        return_date=return_date if isinstance(return_date, str) else None,
        origin=fly_from if isinstance(fly_from, str) else None,
        destination=fly_to if isinstance(fly_to, str) else None,
        raw=raw,
    )
