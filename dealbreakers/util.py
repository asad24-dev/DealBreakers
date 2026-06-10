from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any


PRICE_KEYS = ("priceTotal", "totalPrice", "price", "amount", "cost", "total")
URL_KEYS = ("url", "bookingUrl", "deepLink", "link", "href")
NAME_KEYS = ("hotelName", "name", "title", "vehicleName", "packageName")


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def parse_sse_or_json(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return None
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(stripped)
    events: list[str] = []
    for line in stripped.splitlines():
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload and payload != "[DONE]":
                events.append(payload)
    if not events:
        return None
    return json.loads(events[-1])


def first_value(data: dict[str, Any], keys: Iterable[str]) -> Any:
    lower = {str(k).lower(): v for k, v in data.items()}
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
        value = lower.get(key.lower())
        if value not in (None, ""):
            return value
    return None


def as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:[,.]\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def as_int(value: Any) -> int | None:
    number = as_float(value)
    return int(number) if number is not None else None


def walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z][a-zA-Z_-]+", text.lower()))

