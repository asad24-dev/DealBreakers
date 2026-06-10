from __future__ import annotations

import re
from typing import Any

from .models import AMENITIES, BuyerProfile, Listing, OfferPlan
from .util import words


COUNTRIES = {
    "spain",
    "italy",
    "france",
    "greece",
    "portugal",
    "turkey",
    "morocco",
    "cyprus",
    "egypt",
    "malta",
    "croatia",
    "united kingdom",
    "uk",
}


class Negotiator:
    def __init__(self) -> None:
        self.profile = BuyerProfile()
        self.round_no = 0
        self.last_offer: OfferPlan | None = None
        self.price_pushback = 0

    def observe_opening(self, match: dict[str, Any]) -> None:
        scenario = match.get("scenario") or {}
        self.profile.persona = scenario.get("name", "")
        self.profile.brief = scenario.get("brief", "")
        buyer = (match.get("buyer") or {}).get("text", "")
        self.update_profile(" ".join([self.profile.brief, buyer]))

    def update_profile(self, text: str) -> None:
        lower = text.lower()
        self.profile.raw_notes.append(text)
        if any(token in lower for token in ("tour", "guided", "multi-day", "multiday")):
            self.profile.trip_type = "tour"
        elif any(token in lower for token in ("hotel", "beach", "city break", "holiday", "package")):
            self.profile.trip_type = "holiday"
        if any(token in lower for token in ("beach", "sunny", "pool", "warm")):
            self.profile.amenities.update({"pool", "close_to_beach"})
        if any(token in lower for token in ("kids", "children", "family")):
            self.profile.amenities.update({"kids_club", "family_friendly", "childrens_pool"})
        if "spa" in lower:
            self.profile.amenities.add("spa")
        if "wifi" in lower:
            self.profile.amenities.add("wifi")
        if "car" in lower and not any(token in lower for token in ("no car", "don't need a car", "dont need a car")):
            self.profile.wants_car = True
        if any(token in lower for token in ("no car", "without a car", "don't need a car", "dont need a car")):
            self.profile.wants_car = False
        if any(token in lower for token in ("too expensive", "over budget", "can't stretch", "too high", "pricey")):
            self.price_pushback += 1
        stars = re.search(r"([345])\s*(?:\+|-)?\s*star", lower)
        if stars:
            self.profile.min_stars = float(stars.group(1))
        nights = re.search(r"(\d{1,2})\s*(?:night|nights)", lower)
        if nights:
            self.profile.nights = int(nights.group(1))
        days = re.search(r"(\d{1,2})\s*(?:day|days)", lower)
        if days:
            self.profile.duration_days = int(days.group(1))
        money = re.findall(r"(?:£|gbp\s*)\s*(\d{3,6})", lower)
        if money:
            self.profile.budget_hint = max(float(value) for value in money)
        party = re.search(r"(family of|group of|party of|we are)\s+(\d+)", lower)
        if party:
            self.profile.party_size = int(party.group(2))
        for country in COUNTRIES:
            if country in lower:
                self.profile.country = "United Kingdom" if country == "uk" else country.title()
                self.profile.destination = self.profile.country
        self._infer_regions(lower)
        self.profile.amenities.update(AMENITIES & words(lower))

    def next_message(self, can_offer: bool) -> str:
        missing = []
        if not self.profile.trip_type:
            missing.append("whether you want a hotel holiday or a guided tour")
        if not (self.profile.destination or self.profile.country):
            missing.append("destination or vibe")
        if not (self.profile.nights or self.profile.duration_days):
            missing.append("trip length")
        if self.profile.wants_car is None:
            missing.append("whether you need a car")
        if self.round_no < 2 and missing:
            return "Thanks, I can help. To avoid wasting rounds, can you share your must-have destination or trip style, trip length, party size, and whether a car is useful?"
        if not can_offer:
            return "I am checking live availability against those priorities now. If there is a hard no-go, tell me before I price the package."
        return "I found a live option that matches the brief closely and keeps some room on price. I am sending it as a structured offer so you can judge the exact package."

    def choose_offer(self, listings: list[Listing]) -> OfferPlan | None:
        product_kind = "tour" if self.profile.trip_type == "tour" else "holiday"
        products = [item for item in listings if item.kind == product_kind]
        if not products and product_kind == "holiday":
            products = [item for item in listings if item.kind not in {"car", "flight"}]
        if not products:
            return None
        product = max(products, key=self._score_listing)
        car = None
        if self.profile.wants_car:
            cars = [item for item in listings if item.kind == "car"]
            if cars:
                car = min(cars, key=lambda item: item.price)
        markup = self._markup(product.price + (car.price if car else 0))
        return OfferPlan(product=product, car=car, markup_pct=markup, reason="best scored live listing")

    def offer_to_payload(self, plan: OfferPlan) -> dict[str, Any]:
        product = plan.product
        payload: dict[str, Any] = {"markupPct": plan.markup_pct, "sources": []}
        if product.kind == "tour":
            payload["tour"] = {
                "name": product.name,
                "url": product.url,
                "operator": product.operator or product.mcp,
                "region": product.region or product.location or product.country,
                "country": product.country or self.profile.country,
                "durationDays": product.duration_days or self.profile.duration_days or product.nights,
                "priceTotal": round(product.price, 2),
            }
        else:
            payload["holiday"] = {
                "hotelName": product.name,
                "url": product.url,
                "starRating": product.star_rating,
                "reviewScore": product.review_score,
                "boardBasis": product.board_basis,
                "nights": product.nights or self.profile.nights,
                "location": product.location or product.region or product.country,
                "region": product.region,
                "country": product.country or self.profile.country,
                "amenities": product.amenities,
                "priceTotal": round(product.price, 2),
            }
        payload["sources"].append({"mcp": product.mcp, "url": product.url, "price": round(product.price, 2)})
        if plan.car:
            payload["car"] = {
                "vehicleName": plan.car.vehicle_name or plan.car.name,
                "url": plan.car.url,
                "priceTotal": round(plan.car.price, 2),
                "transmission": plan.car.transmission,
                "seats": plan.car.seats,
            }
            payload["sources"].append({"mcp": plan.car.mcp, "url": plan.car.url, "price": round(plan.car.price, 2)})
        return _drop_none(payload)

    def _score_listing(self, listing: Listing) -> float:
        score = 0.0
        text = " ".join(filter(None, [listing.name, listing.location, listing.region, listing.country])).lower()
        if self.profile.country and self.profile.country.lower() in text:
            score += 10
        if self.profile.region and self.profile.region.lower() in text:
            score += 8
        if self.profile.min_stars and listing.star_rating:
            score += 6 if listing.star_rating >= self.profile.min_stars else -8
        if listing.review_score:
            score += min(listing.review_score, 10) / 2
        score += 2 * len(self.profile.amenities & set(listing.amenities))
        if self.profile.budget_hint and listing.price > self.profile.budget_hint:
            score -= (listing.price - self.profile.budget_hint) / 100
        score -= listing.price / 1000
        return score

    def _markup(self, cost: float) -> float:
        if self.profile.budget_hint:
            room_pct = max(0, (self.profile.budget_hint / cost - 1) * 100)
            target = min(18, max(2, room_pct * 0.72))
        else:
            target = 18
        target -= self.price_pushback * 4
        target -= max(0, self.round_no - 5) * 2
        return round(max(1, target), 2)

    def _infer_regions(self, lower: str) -> None:
        regions = {
            "majorca": "Majorca",
            "mallorca": "Majorca",
            "canary": "Canary Islands",
            "tenerife": "Tenerife",
            "amalfi": "Amalfi Coast",
            "rome": "Rome",
            "madrid": "Madrid",
            "barcelona": "Barcelona",
            "paris": "Paris",
            "lisbon": "Lisbon",
        }
        for token, region in regions.items():
            if token in lower:
                self.profile.region = region
                self.profile.destination = region


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _drop_none(v) for k, v in value.items() if v not in (None, [], {})}
    if isinstance(value, list):
        return [_drop_none(item) for item in value if item not in (None, {}, [])]
    return value

