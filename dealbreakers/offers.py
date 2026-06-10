"""Deterministic validation/sanitisation of offers before they reach the Deal Room."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from .prompts import AMENITY_VOCAB

BOARD_CODES = {"AI", "FB", "HB", "BB", "SC", "RO"}

_MCP_DOMAINS = {
    "travelsupermarket": "travelsupermarket",
    "trivago": "trivago",
    "kiwi": "kiwi",
    "economybookings": "economybookings",
    "tourradar": "tourradar",
}


def sanitize_offer(offer: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Return (clean_offer, None) or (None, reason) if the offer cannot be repaired."""
    if not isinstance(offer, dict):
        return None, "offer must be an object"
    clean: dict[str, Any] = {}

    holiday = offer.get("holiday")
    tour = offer.get("tour")
    if holiday and tour:
        return None, "offer must contain a holiday OR a tour, not both"
    if not holiday and not tour:
        return None, "offer must contain a holiday or a tour"

    if holiday:
        product, err = _sanitize_product(holiday, kind="holiday")
        if err:
            return None, err
        clean["holiday"] = product
    else:
        product, err = _sanitize_product(tour, kind="tour")
        if err:
            return None, err
        clean["tour"] = product

    car = offer.get("car")
    if isinstance(car, dict):
        car_price = _as_number(car.get("priceTotal"))
        if car_price is None:
            return None, "car.priceTotal must be a number (or drop the car)"
        clean_car = {k: v for k, v in car.items() if v not in (None, "", [], {})}
        clean_car["priceTotal"] = car_price
        clean["car"] = clean_car

    markup = _as_number(offer.get("markupPct"))
    if markup is None:
        markup = 10.0
    clean["markupPct"] = max(0.0, round(markup, 2))

    # Rebuild sources deterministically from the components so receipts always match
    # the offered URLs and prices exactly.
    sources = []
    for part in (clean.get("holiday"), clean.get("tour"), clean.get("car")):
        if part and part.get("url"):
            sources.append({
                "mcp": _mcp_from_url(part["url"]),
                "url": part["url"],
                "price": part["priceTotal"],
            })
    clean["sources"] = sources or offer.get("sources") or []
    return clean, None


def _looks_like_image(url: str) -> bool:
    path = urlparse(url.lower()).path
    host = urlparse(url.lower()).netloc
    return any(path.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")) or "img." in host


def _sanitize_product(product: Any, kind: str) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(product, dict):
        return None, f"{kind} must be an object"
    url = product.get("url")
    if isinstance(url, str) and _looks_like_image(url):
        return None, (
            f"{kind}.url is an IMAGE url, not the listing's booking link. Use the real booking URL "
            "from the tool result (e.g. deepLinkUrl for TravelSupermarket)."
        )
    price = _as_number(product.get("priceTotal"))
    if price is None:
        return None, f"{kind}.priceTotal must be a number"
    clean = {k: v for k, v in product.items() if v not in (None, "", [], {})}
    clean["priceTotal"] = price
    if kind == "holiday":
        amenities = clean.get("amenities")
        if isinstance(amenities, list):
            clean["amenities"] = [a for a in amenities if a in AMENITY_VOCAB]
        board = clean.get("boardBasis")
        if isinstance(board, str):
            board = board.strip().upper()
            clean["boardBasis"] = board if board in BOARD_CODES else None
            if clean["boardBasis"] is None:
                clean.pop("boardBasis")
        for key in ("starRating", "reviewScore", "nights"):
            if key in clean:
                value = _as_number(clean[key])
                if value is None:
                    clean.pop(key)
                else:
                    clean[key] = value
    else:
        if "durationDays" in clean:
            value = _as_number(clean["durationDays"])
            if value is None:
                clean.pop("durationDays")
            else:
                clean["durationDays"] = value
    return clean, None


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", "").replace("£", "").strip())
        except ValueError:
            return None
    return None


def _mcp_from_url(url: str) -> str:
    host = urlparse(str(url)).netloc.lower()
    for token, mcp in _MCP_DOMAINS.items():
        if token in host:
            return mcp
    return "travelsupermarket"
