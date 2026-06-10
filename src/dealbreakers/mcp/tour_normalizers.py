"""Normalize TourRadar MCP payloads into offer-compatible TourCandidate objects."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from dealbreakers.mcp.normalizers import extract_price
from dealbreakers.models.offer import Tour

COUNTRY_CODE_TO_NAME: dict[str, str] = {
    "ES": "Spain",
    "PT": "Portugal",
    "FR": "France",
    "IT": "Italy",
    "DE": "Germany",
    "GB": "United Kingdom",
}

COUNTRY_NAME_TO_CODE: dict[str, str] = {
    name.lower(): code for code, name in COUNTRY_CODE_TO_NAME.items()
}

TOURRADAR_BASE_URL = "https://www.tourradar.com"


def country_to_code(country: str | None) -> str | None:
    if not country:
        return None
    stripped = country.strip()
    if len(stripped) == 2 and stripped.upper() in COUNTRY_CODE_TO_NAME:
        return stripped.upper()
    return COUNTRY_NAME_TO_CODE.get(stripped.lower())


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if data.get(key) is not None:
            return data[key]
    return None


def extract_tour_id(raw: dict[str, Any]) -> int | None:
    for key in ("tour_id", "tourId", "id"):
        value = raw.get(key)
        if isinstance(value, int) and value > 0:
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    tour = raw.get("tour")
    if isinstance(tour, dict):
        return extract_tour_id(tour)
    return None


def extract_duration(raw: dict[str, Any]) -> int | None:
    for key in ("tour_length_days", "durationDays", "duration_days", "duration", "days", "lengthDays"):
        value = raw.get(key)
        if isinstance(value, int) and value > 0:
            return value
        parsed = extract_price(value)
        if parsed is not None and parsed > 0:
            return int(parsed)
    match = re.search(r"(\d+)\s*-?\s*day", str(_first(raw, "tour_name", "name", "title") or "").lower())
    if match:
        return int(match.group(1))
    return None


def extract_url(raw: dict[str, Any]) -> str | None:
    for key in ("tour_url", "url", "tourUrl", "webUrl", "bookingUrl", "link", "href"):
        value = raw.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value

    links = raw.get("links")
    if isinstance(links, dict):
        for key in ("book-now", "tour-page", "bookingUrl", "url"):
            value = links.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value
    if isinstance(links, list):
        for item in links:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            if isinstance(url, str) and url.startswith("http"):
                return url

    slug = raw.get("slug")
    if isinstance(slug, str) and slug.startswith("/t/"):
        return f"{TOURRADAR_BASE_URL}{slug}"
    if isinstance(slug, str) and slug.isdigit():
        return f"{TOURRADAR_BASE_URL}/t/{slug}"

    tour_id = extract_tour_id(raw)
    if tour_id is not None:
        return f"{TOURRADAR_BASE_URL}/t/{tour_id}"
    return None


def extract_tour_price(raw: dict[str, Any]) -> float | None:
    prices = raw.get("prices")
    if isinstance(prices, dict):
        for key in (
            "price_total",
            "priceTotal",
            "price_total_upfront",
            "price_promotion",
            "price_base",
            "price",
            "amount",
            "total",
        ):
            parsed = extract_price(prices.get(key))
            if parsed is not None:
                return parsed
    for key in ("price_total", "priceTotal", "price", "amount", "total"):
        parsed = extract_price(raw.get(key))
        if parsed is not None:
            return parsed
    return None


def extract_country(raw: dict[str, Any], *, fallback: str | None = None) -> str | None:
    destinations = raw.get("destinations")
    if isinstance(destinations, dict):
        cities = destinations.get("cities")
        if isinstance(cities, list):
            codes = {
                city.get("country_code")
                for city in cities
                if isinstance(city, dict) and isinstance(city.get("country_code"), str)
            }
            if codes == {"ES"}:
                return "Spain"
            if len(codes) == 1:
                return COUNTRY_CODE_TO_NAME.get(next(iter(codes)))

    for key in ("start_city", "end_city", "start_point", "end_point"):
        point = raw.get(key)
        if isinstance(point, dict):
            code = point.get("country_code")
            if isinstance(code, str):
                return COUNTRY_CODE_TO_NAME.get(code.upper(), fallback)

    for key in ("country", "mainCountry"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return fallback


def extract_operator(raw: dict[str, Any]) -> str | None:
    operator = raw.get("operator")
    if isinstance(operator, dict):
        name = operator.get("name")
        return name if isinstance(name, str) else None
    if isinstance(operator, str):
        return operator
    return None


def extract_region(raw: dict[str, Any]) -> str | None:
    start_city = raw.get("start_city")
    if isinstance(start_city, dict):
        city_name = start_city.get("city_name")
        if isinstance(city_name, str):
            return city_name
    destinations = raw.get("destinations")
    if isinstance(destinations, dict):
        cities = destinations.get("cities")
        if isinstance(cities, list) and cities:
            first = cities[0]
            if isinstance(first, dict) and isinstance(first.get("city_name"), str):
                return first["city_name"]
    return _first(raw, "region", "location")


@dataclass
class TourCandidate:
    name: str | None = None
    url: str | None = None
    operator: str | None = None
    region: str | None = None
    country: str | None = None
    duration_days: int | None = None
    price_total: float | None = None
    departure_date: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def is_offerable(self) -> bool:
        return self.price_total is not None and bool(self.url)

    def to_tour(self) -> Tour:
        if self.price_total is None:
            raise ValueError("Cannot build a Tour without a numeric price_total")
        return Tour(
            price_total=self.price_total,
            name=self.name,
            url=self.url,
            operator=self.operator,
            region=self.region,
            country=self.country,
            duration_days=self.duration_days,
            location=self.region,
        )


def extract_tour_listings(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull tour listing arrays from an MCP tools/call result."""
    structured = result.get("structuredContent")
    if structured is not None:
        found = _find_tour_array(structured)
        if found:
            return found

    for item in result.get("content", []):
        if item.get("type") != "text":
            continue
        try:
            parsed = json.loads(item.get("text", ""))
        except (ValueError, TypeError):
            continue
        found = _find_tour_array(parsed)
        if found:
            return found

    return _find_tour_array(result) or []


def _find_tour_array(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []

    for key in ("tours", "items", "results", "data"):
        value = data.get(key)
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
        if isinstance(value, dict):
            nested = _find_tour_array(value)
            if nested:
                return nested

    tour = data.get("tour")
    if isinstance(tour, dict):
        return [tour]
    return []


def _best_departure(departures_payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(departures_payload, dict):
        return None
    items = departures_payload.get("items")
    if not isinstance(items, list) or not items:
        return None

    def departure_price(item: dict[str, Any]) -> float:
        prices = item.get("prices")
        if isinstance(prices, dict):
            parsed = extract_tour_price(prices)
            if parsed is not None:
                return parsed
        return float("inf")

    return min((item for item in items if isinstance(item, dict)), key=departure_price, default=None)


def merge_tour_candidate(
    search_raw: dict[str, Any] | None,
    details_raw: dict[str, Any] | None,
    departures_raw: dict[str, Any] | None,
    *,
    country_hint: str | None = None,
) -> TourCandidate:
    """Merge search, details, and departures into one TourCandidate."""
    merged: dict[str, Any] = {}
    for source in (search_raw, details_raw):
        if isinstance(source, dict):
            merged.update(source)

    raw = {
        "search": search_raw or {},
        "details": details_raw or {},
        "departures": departures_raw or {},
    }

    name = _first(merged, "tour_name", "name", "title")
    operator = extract_operator(merged)
    region = extract_region(merged)
    country = extract_country(merged, fallback=country_hint)
    duration_days = extract_duration(merged)

    url = extract_url(merged)
    price_total: float | None = None
    price_source: str | None = None
    departure_date: str | None = None

    best_departure = _best_departure(departures_raw)
    if isinstance(best_departure, dict):
        departure_prices = best_departure.get("prices")
        if isinstance(departure_prices, dict):
            price_total = extract_tour_price(departure_prices)
            if price_total is not None:
                price_source = "departure"
        if price_total is None:
            price_total = extract_tour_price(best_departure)
            if price_total is not None:
                price_source = "departure"
        date_value = best_departure.get("date")
        if isinstance(date_value, str):
            departure_date = date_value
        dep_url = extract_url(best_departure)
        if dep_url:
            url = dep_url

    if price_total is None and isinstance(details_raw, dict):
        price_total = extract_tour_price(details_raw)
        if price_total is not None:
            price_source = "details"
        details_url = extract_url(details_raw)
        if details_url:
            url = details_url

    if price_total is None and isinstance(search_raw, dict):
        price_total = extract_tour_price(search_raw)
        if price_total is not None:
            price_source = "search_result"

    if url is None and isinstance(details_raw, dict):
        url = extract_url(details_raw)
    if url is None and isinstance(search_raw, dict):
        url = extract_url(search_raw)

    if price_source:
        raw["price_source"] = price_source

    return TourCandidate(
        name=name if isinstance(name, str) else None,
        url=url,
        operator=operator,
        region=region,
        country=country,
        duration_days=duration_days,
        price_total=price_total,
        departure_date=departure_date,
        raw=raw,
    )
