from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from dealbreakers.models import CarOffer, HolidayOffer, SourceReceipt, StructuredOffer, TourOffer
from dealbreakers.profile import BuyerProfile


@dataclass
class ListingCandidate:
    source: str
    product_type: str  # holiday | tour | car | flight | hotel
    name: str
    url: str
    price_total: float
    country: str = ""
    region: str = ""
    location: str = ""
    nights: int | None = None
    board_basis: str | None = None
    star_rating: float | None = None
    rating: float | None = None
    operator: str = ""
    amenities: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScoredCandidate:
    candidate: ListingCandidate
    score: float
    reasons: list[str]


class CandidateScorer:
    def score(self, candidate: ListingCandidate, profile: BuyerProfile) -> ScoredCandidate:
        score = 0.0
        reasons: list[str] = []

        if profile.product_preference == candidate.product_type:
            score += 30
            reasons.append("matches preferred product type")
        elif profile.product_preference == "city_break" and candidate.product_type == "holiday":
            score += 12
            reasons.append("can work as a hotel-led city break")

        destination_blob = " ".join([candidate.country, candidate.region, candidate.location]).lower()
        if profile.destination and profile.destination.lower() in destination_blob:
            score += 25
            reasons.append("matches destination")

        if profile.budget:
            if candidate.price_total <= profile.budget:
                score += 20
                reasons.append("fits stated budget before markup")
            else:
                overage = (candidate.price_total - profile.budget) / profile.budget
                score -= min(25, overage * 50)
                reasons.append("above stated budget before markup")

        amenities = set(candidate.amenities)
        must_haves = profile.must_haves
        if must_haves:
            matched = must_haves.intersection(amenities)
            score += 5 * len(matched)
            if matched:
                reasons.append(f"covers must-haves: {', '.join(sorted(matched))}")
            missing = must_haves.difference(amenities)
            score -= 8 * len(missing)
            if missing:
                reasons.append(f"missing declared must-haves: {', '.join(sorted(missing))}")

        if candidate.rating and candidate.rating >= 4.5:
            score += 8
            reasons.append("strong quality signal")

        if profile.luxury_weight >= 0.5 and candidate.star_rating is not None:
            if candidate.star_rating >= 5:
                score += 12
                reasons.append("5-star matches luxury expectations")
            elif candidate.star_rating <= 3:
                score -= 15
                reasons.append("below the quality bar this buyer expects")

        return ScoredCandidate(candidate=candidate, score=score, reasons=reasons)


def build_offer_from_candidate(
    candidate: ListingCandidate,
    markup_pct: float,
    *,
    car: ListingCandidate | None = None,
) -> StructuredOffer:
    sources = [SourceReceipt(mcp=candidate.source, url=candidate.url, price=candidate.price_total)]
    car_offer: CarOffer | None = None
    if car is not None:
        raw = car.raw or {}
        transmission = raw.get("transmission")
        seats = raw.get("seats")
        car_offer = CarOffer(
            vehicleName=car.name,
            url=car.url,
            priceTotal=car.price_total,
            category=str(raw.get("categoryName", "")),
            transmission=transmission if transmission in ("Manual", "Automatic") else None,
            seats=seats if isinstance(seats, int) else None,
            supplier=car.operator,
        )
        sources.append(SourceReceipt(mcp=car.source, url=car.url, price=car.price_total))

    if candidate.product_type == "tour":
        return StructuredOffer(
            tour=TourOffer(
                name=candidate.name,
                url=candidate.url,
                country=candidate.country,
                region=candidate.region,
                operator=candidate.operator,
                durationDays=candidate.nights,
                location=candidate.location,
                priceTotal=candidate.price_total,
            ),
            car=car_offer,
            markupPct=markup_pct,
            sources=sources,
        )

    return StructuredOffer(
        holiday=HolidayOffer(
            hotelName=candidate.name,
            url=candidate.url,
            country=candidate.country,
            region=candidate.region,
            location=candidate.location,
            nights=candidate.nights,
            boardBasis=_board_basis_code(candidate.board_basis),
            starRating=candidate.star_rating,
            reviewScore=candidate.rating,
            amenities=[amenity for amenity in candidate.amenities if _is_canonical_amenity(amenity)],
            priceTotal=candidate.price_total,
        ),
        car=car_offer,
        markupPct=markup_pct,
        sources=sources,
    )


def extract_candidates(
    source: str, product_type: str, result: Any, *, hint_country: str = ""
) -> list[ListingCandidate]:
    tour_candidates = _extract_tour_candidates(source, result, hint_country=hint_country)
    if tour_candidates:
        return tour_candidates

    structured_candidates = _extract_structured_candidates(source, product_type, result)
    if structured_candidates:
        return structured_candidates

    text_candidates = _extract_text_candidates(source, product_type, result)
    if text_candidates:
        return text_candidates

    items = _flatten_dicts(result)
    candidates: list[ListingCandidate] = []
    for item in items:
        url = _first_url(item)
        price = _first_price(item)
        name = _first_text(item, ["name", "hotelName", "title", "operator", "vehicleName"])
        if not url or not price or not name:
            continue
        candidates.append(
            ListingCandidate(
                source=source,
                product_type=product_type,
                name=name,
                url=url,
                price_total=price,
                country=_first_text(item, ["country", "destinationCountry"]),
                region=_first_text(item, ["region", "destination", "area"]),
                location=_first_text(item, ["location", "resort", "city"]),
                nights=_first_int(item, ["nights", "durationNights"]),
                rating=_first_float(item, ["reviewScore", "rating", "starRating"]),
                amenities=_extract_amenities(item),
                raw=item,
            )
        )
    return candidates


def _extract_tour_candidates(
    source: str, result: Any, *, hint_country: str = ""
) -> list[ListingCandidate]:
    """TourRadar returns a JSON document embedded in MCP text content."""
    if not isinstance(result, dict):
        return []

    candidates: list[ListingCandidate] = []
    for item in result.get("content", []):
        if not (isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)):
            continue
        try:
            parsed = json.loads(item["text"])
        except (json.JSONDecodeError, ValueError):
            continue
        tours = parsed.get("tours") if isinstance(parsed, dict) else None
        if not isinstance(tours, list):
            continue
        for tour in tours:
            if not isinstance(tour, dict):
                continue
            name = tour.get("tour_name")
            url = tour.get("tour_url")
            prices = tour.get("prices") or {}
            price = prices.get("price") if isinstance(prices, dict) else None
            if not (isinstance(name, str) and isinstance(url, str) and isinstance(price, int | float)):
                continue

            description = str(tour.get("description", ""))
            start_city = tour.get("start_city") or {}
            start_city_name = str(start_city.get("city_name", "")) if isinstance(start_city, dict) else ""
            blob = f"{name} {description} {start_city_name}".lower()
            # Only claim a country when the listing itself evidences it (country name
            # or one of its well-known cities/regions appearing in the listing text).
            country = hint_country if hint_country and _mentions_country(blob, hint_country) else ""

            duration = None
            duration_match = re.search(r"(\d+)[\s-]?day", name.lower())
            if duration_match:
                duration = int(duration_match.group(1))

            ratings = tour.get("ratings") or {}
            overall = ratings.get("overall") if isinstance(ratings, dict) else None
            operator = tour.get("operator") or {}

            candidates.append(
                ListingCandidate(
                    source=source,
                    product_type="tour",
                    name=name,
                    url=url,
                    price_total=float(price),
                    country=country,
                    region=country,
                    location=start_city_name,
                    nights=duration,
                    rating=float(overall) if isinstance(overall, int | float) else None,
                    operator=str(operator.get("name", "")) if isinstance(operator, dict) else "",
                    raw=tour,
                )
            )
    return candidates


_COUNTRY_EVIDENCE: dict[str, list[str]] = {
    "spain": ["madrid", "barcelona", "seville", "sevilla", "granada", "cordoba", "córdoba",
              "valencia", "andalusia", "andalucia", "andalucía", "bilbao", "malaga", "málaga",
              "costa del sol", "alhambra", "san sebastian", "toledo"],
    "italy": ["rome", "venice", "florence", "milan", "naples", "amalfi", "tuscany", "sicily",
              "cinque terre", "pompeii", "verona", "lake como"],
    "france": ["paris", "nice", "lyon", "provence", "bordeaux", "normandy", "loire", "marseille"],
    "portugal": ["lisbon", "porto", "algarve", "madeira", "sintra", "douro"],
    "greece": ["athens", "santorini", "mykonos", "crete", "rhodes", "corfu", "delphi", "meteora"],
    "turkey": ["istanbul", "cappadocia", "antalya", "ephesus", "izmir", "bodrum"],
    "united kingdom": ["london", "edinburgh", "scotland", "wales", "cornwall", "lake district"],
}


def _mentions_country(blob: str, country: str) -> bool:
    lowered = country.lower()
    if lowered in blob:
        return True
    return any(place in blob for place in _COUNTRY_EVIDENCE.get(lowered, []))


def _extract_structured_candidates(source: str, product_type: str, result: Any) -> list[ListingCandidate]:
    if not isinstance(result, dict):
        return []
    structured = result.get("structuredContent")
    if not isinstance(structured, dict):
        return []
    offers = structured.get("offers")
    if not isinstance(offers, list):
        return []

    candidates: list[ListingCandidate] = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        url = offer.get("deepLinkUrl") or offer.get("url")
        price = offer.get("totalPrice") or offer.get("priceTotal")
        name = offer.get("hotelName") or offer.get("name") or offer.get("title")
        if not isinstance(url, str) or not isinstance(price, int | float) or not isinstance(name, str):
            continue
        location = ", ".join(
            part
            for part in [offer.get("resort"), offer.get("region"), offer.get("country")]
            if isinstance(part, str) and part
        )
        candidates.append(
            ListingCandidate(
                source=source,
                product_type=product_type,
                name=name,
                url=url,
                price_total=float(price),
                country=str(offer.get("country") or ""),
                region=str(offer.get("region") or offer.get("destinationName") or ""),
                location=location,
                nights=offer.get("duration") if isinstance(offer.get("duration"), int) else None,
                board_basis=str(offer.get("boardBasisCode") or offer.get("boardBasis") or ""),
                star_rating=float(offer["starRating"]) if isinstance(offer.get("starRating"), int | float) else None,
                rating=float(offer["reviewScore"]) if isinstance(offer.get("reviewScore"), int | float) else None,
                amenities=_extract_amenities({"facilities": offer.get("facilities", [])}),
                raw=offer,
            )
        )
    return candidates


def _extract_text_candidates(source: str, product_type: str, result: Any) -> list[ListingCandidate]:
    texts: list[str] = []
    if isinstance(result, dict):
        for item in result.get("content", []):
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                texts.append(item["text"])
    if not texts:
        return []

    candidates: list[ListingCandidate] = []
    for text in texts:
        blocks = re.split(r"\n(?=\d+\.\s)", text)
        for block in blocks:
            candidate = _parse_holiday_text_block(source, product_type, block)
            if candidate:
                candidates.append(candidate)
    return candidates


def _parse_holiday_text_block(source: str, product_type: str, block: str) -> ListingCandidate | None:
    header = re.search(
        r"^\s*\d+\.\s+(?P<name>.+?)\s+—\s+(?P<location>.+?)\s+—\s+(?P<stars>\d+(?:\.\d+)?)★(?:\s+(?P<rating>\d+(?:\.\d+)?)/5)?",
        block,
        flags=re.MULTILINE,
    )
    price = re.search(
        r"£(?P<pp>[\d,]+)pp\s*/\s*£(?P<total>[\d,]+)\s+total\s*\|\s*(?P<nights>\d+)\s+nights?\s+(?P<board>[^|]+)",
        block,
    )
    if not header or not price:
        return None

    url_match = re.search(r"https?://\S+", block)
    # TravelSupermarket text listings are real MCP results even when the text summary omits a deep link.
    url = url_match.group(0).rstrip(").,") if url_match else "https://www.travelsupermarket.com/"
    location = header.group("location").strip()
    location_parts = [part.strip() for part in location.split(",")]
    country = location_parts[-1] if location_parts else ""
    region = location_parts[-2] if len(location_parts) >= 2 else ""
    facilities = block.split("Facilities:", 1)[-1] if "Facilities:" in block else ""

    return ListingCandidate(
        source=source,
        product_type=product_type,
        name=header.group("name").strip(),
        url=url,
        price_total=float(price.group("total").replace(",", "")),
        country=country,
        region=region,
        location=location,
        nights=int(price.group("nights")),
        rating=float(header.group("rating")) if header.group("rating") else None,
        amenities=_extract_amenities({"facilities": facilities}),
        raw={"text": block},
    )


def _flatten_dicts(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_flatten_dicts(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_flatten_dicts(child))
    return found


def _first_url(item: dict[str, Any]) -> str:
    for key, value in item.items():
        if isinstance(value, str) and (key.lower() in {"url", "link", "deeplink"} or value.startswith("http")):
            return value
    return ""


def _first_price(item: dict[str, Any]) -> float | None:
    for key, value in item.items():
        if not isinstance(value, int | float):
            continue
        if "price" in key.lower() or "total" in key.lower() or "cost" in key.lower():
            return float(value)
    return None


def _first_text(item: dict[str, Any], keys: list[str]) -> str:
    lowered = {key.lower(): value for key, value in item.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if isinstance(value, str):
            return value
    return ""


def _first_int(item: dict[str, Any], keys: list[str]) -> int | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, int):
            return value
    return None


def _first_float(item: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, int | float):
            return float(value)
    return None


def _extract_amenities(item: dict[str, Any]) -> list[str]:
    text = " ".join(str(value) for value in item.values()).lower()
    mappings = {
        "pool": "pool",
        "swimming pool": "pool",
        "beach": "close_to_beach",
        "air conditioning": "air_conditioning",
        "air-conditioning": "air_conditioning",
        "wifi": "wifi",
        "wi-fi": "wifi",
        "internet access": "wifi",
        "balcony": "balcony",
        "balcony/terrace": "balcony",
        "kids": "kids_club",
        "kids club": "kids_club",
        "children": "family_friendly",
        "children's pool": "childrens_pool",
        "family-friendly": "family_friendly",
        "spa": "spa",
        "spa facilities": "spa",
        "gym": "gym",
        "restaurant": "restaurant",
        "bar": "bar",
        "wheelchair": "wheelchair_access",
        "nightclub": "nightclub",
        "playground": "playground",
        "pool bar": "pool_bar",
        "sun loungers": "sun_loungers",
        "entertainment": "entertainment",
        "water sports": "water_sports",
        "sports facilities": "sports",
        "jacuzzi": "jacuzzi",
        "sun terrace": "sun_terrace",
        "games room": "games_room",
        "golf": "golf",
        "shopping": "shopping",
    }
    return sorted({canonical for needle, canonical in mappings.items() if re.search(rf"\b{re.escape(needle)}\b", text)})


def _is_canonical_amenity(value: str) -> bool:
    return value in {
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


def _board_basis_code(value: str | None) -> str | None:
    if not value:
        return None
    normalized = value.strip().upper()
    direct = {"AI", "FB", "HB", "BB", "SC", "RO"}
    if normalized in direct:
        return normalized
    mapping = {
        "ALL INCLUSIVE": "AI",
        "FULL BOARD": "FB",
        "HALF BOARD": "HB",
        "BED & BREAKFAST": "BB",
        "BED AND BREAKFAST": "BB",
        "SELF CATERING": "SC",
        "ROOM ONLY": "RO",
    }
    return mapping.get(normalized)
