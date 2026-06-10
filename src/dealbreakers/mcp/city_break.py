"""City-break search: Trivago hotels + optional Kiwi flights (Phase 8F)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from dealbreakers.mcp.flight_normalizers import FlightCandidate
from dealbreakers.mcp.hotel_normalizers import HotelCandidate
from dealbreakers.mcp.kiwi import KiwiClient, city_to_iata
from dealbreakers.mcp.trivago import TrivagoClient
from dealbreakers.models.offer import Holiday
from dealbreakers.state.buyer_state import BuyerState

_CITY_BREAK_CITIES = frozenset({"berlin", "stockholm", "amsterdam", "paris", "london"})
_FALLBACK_CITIES = ("Amsterdam", "Paris")

DEFAULT_CHECKIN = "2026-07-10"
DEFAULT_CHECKOUT_3N = "2026-07-13"
DEFAULT_CHECKOUT_4N = "2026-07-14"


def normalize_trip_type(trip_type: str | None) -> str | None:
    if trip_type is None:
        return None
    cleaned = trip_type.strip().lower().replace("-", "_").replace(" ", "_")
    if cleaned in {"city_break", "citybreak"}:
        return "city_break"
    return trip_type


def needs_city_break_path(state_destinations: list[str], trip_type: str | None) -> bool:
    normalized = normalize_trip_type(trip_type)
    if normalized == "city_break":
        return True
    text = " ".join(state_destinations).lower()
    return any(city in text for city in _CITY_BREAK_CITIES)


def pick_city_break_city(state: BuyerState) -> str | None:
    for destination in state.destinations:
        lowered = destination.strip().lower()
        for city in _CITY_BREAK_CITIES:
            if city in lowered:
                return destination.strip().title() if destination[0].isupper() else city.title()
    return None


def nights_between(checkin: str, checkout: str) -> int:
    try:
        start = date.fromisoformat(checkin[:10])
        end = date.fromisoformat(checkout[:10])
        return max((end - start).days, 1)
    except ValueError:
        return 4


@dataclass
class CityBreakCandidate:
    hotel: HotelCandidate
    flight: FlightCandidate | None
    price_total: float
    city: str
    country: str
    nights: int
    raw: dict = field(default_factory=dict)

    @property
    def is_offerable(self) -> bool:
        return self.hotel.is_offerable

    def to_holiday(self) -> Holiday:
        """Package cost = hotel + flight when flight exists."""
        return self.hotel.to_holiday(price_total=self.price_total)


class CityBreakSearchClient:
    def __init__(
        self,
        trivago: TrivagoClient | None = None,
        kiwi: KiwiClient | None = None,
    ) -> None:
        self._trivago = trivago or TrivagoClient()
        self._kiwi = kiwi or KiwiClient()
        self.last_errors: list[str] = []

    def search_city_break(
        self,
        city: str,
        checkin_date: str,
        checkout_date: str,
        adults: int = 1,
        require_flight: bool = False,
        limit: int = 10,
        *,
        min_stars: int | None = 4,
        required_amenities: list[str] | None = None,
    ) -> list[CityBreakCandidate]:
        amenities = required_amenities or ["wifi", "gym"]
        hotels = self._trivago.search_hotels(
            city,
            checkin_date,
            checkout_date,
            adults=adults,
            min_stars=min_stars,
            required_amenities=amenities,
            limit=limit,
        )
        self.last_errors.extend(self._trivago.last_errors)

        flights = self._kiwi.search_flights(
            fly_from="LON",
            fly_to=city_to_iata(city),
            departure_date=checkin_date,
            return_date=checkout_date,
            adults=adults,
            limit=5,
        )
        self.last_errors.extend(self._kiwi.last_errors)

        best_flight = next((f for f in flights if f.is_offerable), None)
        nights = nights_between(checkin_date, checkout_date)
        country = hotels[0].country if hotels and hotels[0].country else ""
        city_name = hotels[0].city if hotels and hotels[0].city else city

        combined: list[CityBreakCandidate] = []
        for hotel in hotels:
            if not hotel.is_offerable:
                continue
            flight = best_flight
            flight_missing = flight is None
            if require_flight and flight_missing:
                continue
            hotel_price = hotel.price_total or 0.0
            flight_price = flight.price_total if flight is not None else 0.0
            total = hotel_price + flight_price
            combined.append(
                CityBreakCandidate(
                    hotel=hotel,
                    flight=flight,
                    price_total=total,
                    city=city_name or city,
                    country=country or "",
                    nights=nights,
                    raw={
                        "hotel": hotel.raw,
                        "flight": flight.raw if flight else None,
                        "flight_missing": flight_missing,
                    },
                )
            )

        if not combined and hotels:
            for hotel in hotels:
                if hotel.is_offerable:
                    combined.append(
                        CityBreakCandidate(
                            hotel=hotel,
                            flight=None,
                            price_total=hotel.price_total or 0.0,
                            city=city_name or city,
                            country=country or "",
                            nights=nights,
                            raw={"hotel": hotel.raw, "flight": None, "flight_missing": True},
                        )
                    )

        return combined[:limit]


def city_break_date_pairs(nights: int) -> tuple[str, str]:
    checkin = DEFAULT_CHECKIN
    if nights == 3:
        return checkin, DEFAULT_CHECKOUT_3N
    return checkin, DEFAULT_CHECKOUT_4N


def search_city_breaks_for_state(
    state: BuyerState,
    client: CityBreakSearchClient,
    *,
    nights_options: tuple[int, ...] = (4, 3),
) -> tuple[list[CityBreakCandidate], str]:
    """Search city breaks for Elon-style buyers."""
    city = pick_city_break_city(state)
    if city is None:
        return [], "no city selected for city-break search"

    notes: list[str] = []
    all_candidates: list[CityBreakCandidate] = []
    for nights in nights_options:
        checkin, checkout = city_break_date_pairs(nights)
        candidates = client.search_city_break(
            city,
            checkin,
            checkout,
            min_stars=4,
            required_amenities=["wifi", "gym"],
            limit=10,
        )
        offerable = sum(1 for c in candidates if c.is_offerable)
        notes.append(f"{city} {nights}n: {len(candidates)} results, {offerable} offerable")
        all_candidates.extend(candidates)

    if not all_candidates:
        for fallback in _FALLBACK_CITIES:
            if fallback.lower() == (city or "").lower():
                continue
            for nights in nights_options:
                checkin, checkout = city_break_date_pairs(nights)
                candidates = client.search_city_break(
                    fallback,
                    checkin,
                    checkout,
                    min_stars=4,
                    required_amenities=["wifi", "gym"],
                    limit=5,
                )
                offerable = sum(1 for c in candidates if c.is_offerable)
                notes.append(
                    f"fallback {fallback} {nights}n: {len(candidates)} results, {offerable} offerable"
                )
                all_candidates.extend(candidates)

    return all_candidates, "; ".join(notes) if notes else "no city-break results"
