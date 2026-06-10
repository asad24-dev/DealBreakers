from __future__ import annotations

import datetime
import re
from typing import Any

from dealbreakers.catalog import CandidateScorer, ListingCandidate, ScoredCandidate, extract_candidates
from dealbreakers.catalog import _extract_amenities  # shared amenity mapping
from dealbreakers.mcp import McpClient, McpTool, TRAVEL_MCPS
from dealbreakers.profile import BuyerProfile


class McpSearchEngine:
    def __init__(self, *, timeout_seconds: float = 45) -> None:
        self._timeout_seconds = timeout_seconds
        self._scorer = CandidateScorer()

    def find_best(self, profile: BuyerProfile) -> ScoredCandidate | None:
        shortlist = self.find_shortlist(profile, limit=1)
        return shortlist[0] if shortlist else None

    def find_shortlist(self, profile: BuyerProfile, *, limit: int = 5) -> list[ScoredCandidate]:
        candidates = self._collect(profile, minimal=False)
        if not candidates:
            # Broaden: drop optional filters (budget, months, party) and retry with the basics.
            candidates = self._collect(profile, minimal=True)

        scored = [self._scorer.score(candidate, profile) for candidate in candidates]
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:limit]

    def _collect(self, profile: BuyerProfile, *, minimal: bool) -> list[ListingCandidate]:
        candidates: list[ListingCandidate] = []

        # A committed tour buyer will never accept a hotel, so exhaust the tour source
        # (including a broadened retry) before falling back to accommodation MCPs.
        if profile.product_preference == "tour":
            tours = self._search_generic("tourradar", profile, minimal=minimal)
            if not tours and not minimal:
                tours = self._search_generic("tourradar", profile, minimal=True)
            if tours:
                return tours

        for server in self._rank_servers(profile):
            if server == "tourradar" and profile.product_preference == "tour":
                continue  # already tried above
            if server == "trivago":
                candidates.extend(self._search_trivago(profile))
            else:
                candidates.extend(self._search_generic(server, profile, minimal=minimal))
            if candidates:
                break  # The preferred source delivered; no need to hit lower-ranked MCPs.
        return candidates

    def _search_generic(self, server: str, profile: BuyerProfile, *, minimal: bool) -> list[ListingCandidate]:
        candidates: list[ListingCandidate] = []
        with McpClient(server, TRAVEL_MCPS[server], timeout_seconds=self._timeout_seconds) as client:
            try:
                tools = client.list_tools()
            except Exception:
                return candidates
            for tool in self._rank_tools(tools, profile):
                arguments = self._arguments_for(tool, profile, minimal=minimal)
                if arguments is None:
                    continue
                try:
                    result = client.call_tool(tool.name, arguments)
                except Exception:
                    continue
                candidates.extend(
                    extract_candidates(
                        server,
                        self._product_type_for(server, profile),
                        result,
                        hint_country=profile.destination,
                    )
                )
        return candidates

    def find_car(self, profile: BuyerProfile) -> ListingCandidate | None:
        """Car hire add-on from EconomyBookings (TravelSupermarket as fallback)."""
        location = profile.place or profile.destination
        if not location:
            return None
        pickup, dropoff = _stay_dates(profile)
        cars: list[dict] = []
        for server in ("economybookings", "travelsupermarket"):
            try:
                with McpClient(server, TRAVEL_MCPS[server], timeout_seconds=self._timeout_seconds) as client:
                    result = client.call_tool(
                        "search-car-hire",
                        {"pickupLocation": location, "pickupDate": pickup, "dropoffDate": dropoff},
                    )
            except Exception:
                continue
            structured = result.get("structuredContent") if isinstance(result, dict) else None
            found = structured.get("cars") if isinstance(structured, dict) else None
            if isinstance(found, list) and found:
                cars = [c for c in found if isinstance(c, dict)]
                source = server
                break
        if not cars:
            return None

        def usable(car: dict) -> bool:
            return isinstance(car.get("totalPrice"), int | float) and isinstance(
                car.get("redirectUrl") or car.get("url"), str
            )

        cars = [c for c in cars if usable(c)]
        if not cars:
            return None

        if "premium" in profile.car_preference or "luxury" in profile.car_preference:
            # Prefer genuinely premium categories; cheapest within the tier avoids a
            # price shock that blows up the package total. Within the tier, image matters:
            # a manual pickup truck categorised as "Luxury" reads as an insult to a
            # status-driven buyer, so elegance beats a small price saving.
            def elegance(c: dict) -> tuple[int, int, float]:
                name = str(c.get("vehicleName", "")).lower()
                is_truck = any(w in name for w in ("f150", "f-150", "pickup", "hilux", "ranger"))
                is_manual = str(c.get("transmission", "")).lower().startswith("man")
                return (int(is_truck), int(is_manual), float(c["totalPrice"]))

            for tier in ({"premium", "luxury"}, {"fullsize", "suv"}):
                tier_cars = [c for c in cars if str(c.get("categoryName", "")).lower() in tier]
                if tier_cars:
                    chosen = min(tier_cars, key=elegance)
                    break
            else:
                chosen = max(cars, key=lambda c: float(c["totalPrice"]))
        else:
            rated = [c for c in cars if (c.get("supplierRating") or 0) >= 7] or cars
            chosen = min(rated, key=lambda c: float(c["totalPrice"]))

        return ListingCandidate(
            source=source,
            product_type="car",
            name=str(chosen.get("vehicleName", "Car hire")),
            url=str(chosen.get("redirectUrl") or chosen.get("url")),
            price_total=float(chosen["totalPrice"]),
            location=location,
            operator=str(chosen.get("supplierName", "")),
            raw=chosen,
        )

    def _search_trivago(self, profile: BuyerProfile) -> list[ListingCandidate]:
        """Two-step trivago flow: city suggestion -> dated accommodation search."""
        query = profile.place or profile.destination
        if not query:
            return []
        arrival, departure = _stay_dates(profile)
        candidates: list[ListingCandidate] = []
        try:
            with McpClient("trivago", TRAVEL_MCPS["trivago"], timeout_seconds=self._timeout_seconds) as client:
                suggestions = client.call_tool("trivago-search-suggestions", {"query": query})
                target = _pick_suggestion(suggestions, profile.destination)
                if target is None:
                    return []
                result = client.call_tool(
                    "trivago-accommodation-search",
                    {"ns": target["ns"], "id": target["id"], "arrival": arrival, "departure": departure},
                )
        except Exception:
            return []

        structured = result.get("structuredContent") if isinstance(result, dict) else None
        accommodations = structured.get("accommodations") if isinstance(structured, dict) else None
        if not isinstance(accommodations, list):
            return []

        nights = max(1, (datetime.date.fromisoformat(departure) - datetime.date.fromisoformat(arrival)).days)
        for item in accommodations:
            if not isinstance(item, dict):
                continue
            name = item.get("accommodation_name")
            url = item.get("accommodation_url")
            price = _parse_money(str(item.get("price_per_stay", "")))
            if not (isinstance(name, str) and isinstance(url, str) and price):
                continue
            country_city = str(item.get("country_city", ""))
            country = country_city.split(",")[-1].strip() if "," in country_city else ""
            review = _parse_money(str(item.get("review_rating", "")))
            stars = item.get("hotel_rating")
            candidates.append(
                ListingCandidate(
                    source="trivago",
                    product_type="holiday",
                    name=name,
                    url=url,
                    price_total=price,
                    country=country,
                    region=country_city,
                    location=country_city,
                    nights=nights,
                    board_basis="RO",
                    star_rating=float(stars) if isinstance(stars, int | float) else None,
                    rating=review,
                    amenities=_extract_amenities({"amenities": item.get("top_amenities", "")}),
                    raw=item,
                )
            )
        return candidates

    def _rank_servers(self, profile: BuyerProfile) -> list[str]:
        if profile.product_preference == "tour":
            return ["tourradar", "travelsupermarket", "trivago"]
        if profile.product_preference == "city_break":
            return ["trivago", "travelsupermarket"]
        return ["travelsupermarket", "trivago", "tourradar"]

    def _rank_tools(self, tools: list[McpTool], profile: BuyerProfile) -> list[McpTool]:
        product_words = {
            "tour": ["tour", "trip", "itinerary"],
            "city_break": ["hotel", "stay", "accommodation", "city"],
            "holiday": ["holiday", "package", "hotel", "resort"],
            "unknown": ["search", "hotel", "holiday", "tour"],
        }[profile.product_preference]

        def score(tool: McpTool) -> int:
            text = f"{tool.name} {tool.description}".lower()
            return sum(1 for word in product_words if word in text)

        ranked = sorted(tools, key=score, reverse=True)
        return [tool for tool in ranked if score(tool) > 0][:3]

    _MINIMAL_FIELDS = {"textsearch", "q", "display_mode", "destination", "query", "limit"}

    def _arguments_for(self, tool: McpTool, profile: BuyerProfile, *, minimal: bool = False) -> dict[str, Any] | None:
        schema = tool.input_schema or {}
        properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
        required = set(schema.get("required", [])) if isinstance(schema, dict) else set()
        args: dict[str, Any] = {}

        for name, spec in properties.items():
            lowered = name.lower()
            if minimal and lowered not in self._MINIMAL_FIELDS and name not in required:
                continue
            value = self._value_for_field(lowered, spec, profile)
            if value is not None:
                args[name] = self._coerce_for_schema(value, spec)

        missing_required = [name for name in required if name not in args]
        # Avoid hallucinating required dates or airports. We would rather ask another question.
        if missing_required:
            return None
        return args

    def _coerce_for_schema(self, value: Any, spec: dict[str, Any]) -> Any:
        if spec.get("type") == "string" and not isinstance(value, str):
            return str(value)
        return value

    def _value_for_field(self, name: str, spec: dict[str, Any], profile: BuyerProfile) -> Any:
        if "textsearch" in name or name == "q":
            parts = ["guided tour"]
            if profile.destination:
                parts.append(f"in {profile.destination}")
            if profile.must_haves:
                parts.append("with " + ", ".join(sorted(profile.must_haves)))
            return " ".join(parts)
        if name == "display_mode":
            return "listing"
        if name in {"countries", "country_codes"} and profile.destination:
            country_code = _country_code(profile.destination)
            if country_code:
                return {"values": [country_code]} if spec.get("type") == "object" else [country_code]
        if any(token in name for token in ["destination", "country", "region", "location", "query"]):
            return profile.destination or None
        if any(token in name for token in ["nights", "duration"]):
            return profile.nights
        if "departuremonth" in name or "departure_month" in name:
            return profile.departure_months or None
        if name == "adults":
            return profile.adults
        if name == "children":
            return profile.children
        if name == "infants":
            return profile.infants
        if any(token in name for token in ["adults", "guests", "people", "passengers", "party"]):
            return profile.party_size
        if name == "price" and profile.budget:
            return {"max": profile.budget, "currency": "GBP"}
        if ("maxprice" in name or "max_price" in name) and profile.budget:
            divisor = profile.party_size or 1
            return round(profile.budget / divisor)
        if "budget" in name:
            return profile.budget
        if "limit" in name:
            return 10
        if spec.get("type") == "boolean" and "car" in name:
            return profile.wants_car
        return None

    def _product_type_for(self, server: str, profile: BuyerProfile) -> str:
        if server == "tourradar":
            return "tour"
        if profile.product_preference == "tour":
            return "tour"
        return "holiday"


def _stay_dates(profile: BuyerProfile) -> tuple[str, str]:
    today = datetime.date.today()
    nights = profile.nights or (4 if profile.product_preference == "city_break" else 7)
    arrival = today + datetime.timedelta(days=35)
    if profile.departure_months:
        try:
            month = int(profile.departure_months.split(",")[0])
            year = today.year if month > today.month else today.year + 1
            candidate = datetime.date(year, month, 15)
            if (candidate - today).days >= 21:
                arrival = candidate
        except ValueError:
            pass
    return arrival.isoformat(), (arrival + datetime.timedelta(days=nights)).isoformat()


def _pick_suggestion(result: Any, destination_country: str) -> dict | None:
    structured = result.get("structuredContent") if isinstance(result, dict) else None
    suggestions = structured.get("suggestions") if isinstance(structured, dict) else None
    if not isinstance(suggestions, list):
        return None
    usable = [
        s
        for s in suggestions
        if isinstance(s, dict) and isinstance(s.get("ns"), int) and isinstance(s.get("id"), int)
    ]
    if destination_country:
        for suggestion in usable:
            if destination_country.lower() in str(suggestion.get("location_label", "")).lower():
                return suggestion
    return usable[0] if usable else None


def _parse_money(text: str) -> float | None:
    match = re.search(r"(\d[\d,]*(?:\.\d+)?)", text.replace(",", ""))
    return float(match.group(1)) if match else None


def _country_code(country: str) -> str:
    return {
        "Spain": "ES",
        "Italy": "IT",
        "Greece": "GR",
        "Portugal": "PT",
        "France": "FR",
        "United Kingdom": "GB",
        "Germany": "DE",
        "Netherlands": "NL",
    }.get(country, "")
