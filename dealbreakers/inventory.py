from __future__ import annotations

import re
from typing import Any

from .config import TRAVEL_MCP_ENDPOINTS
from .mcp_client import StreamableMCPClient
from .models import AMENITIES, BuyerProfile, Listing
from .util import NAME_KEYS, PRICE_KEYS, URL_KEYS, as_float, as_int, first_value, walk_dicts, words


class InventoryBroker:
    def __init__(self, timeout: float = 30):
        self.clients = {
            name: StreamableMCPClient(name, url, timeout=timeout)
            for name, url in TRAVEL_MCP_ENDPOINTS.items()
        }
        self.tools: dict[str, list[dict[str, Any]]] = {}

    def connect(self) -> None:
        for name, client in self.clients.items():
            try:
                client.initialize()
                self.tools[name] = client.list_tools()
                print(f"[mcp] {name}: {len(self.tools[name])} tools")
            except Exception as exc:
                self.tools[name] = []
                print(f"[mcp] {name}: unavailable ({exc})")

    def search(self, profile: BuyerProfile) -> list[Listing]:
        candidates: list[Listing] = []
        if profile.trip_type == "tour":
            candidates.extend(self._search_server("tourradar", profile, "tour"))
        else:
            candidates.extend(self._search_server("travelsupermarket", profile, "holiday"))
            candidates.extend(self._search_server("trivago", profile, "holiday"))
            candidates.extend(self._search_server("kiwi", profile, "flight"))
        if profile.wants_car is not False:
            candidates.extend(self._search_server("economybookings", profile, "car"))
            candidates.extend(self._search_server("travelsupermarket", profile, "car"))
        return self._dedupe(candidates)

    def _search_server(self, server: str, profile: BuyerProfile, kind: str) -> list[Listing]:
        tools = self.tools.get(server, [])
        if not tools:
            return []
        selected = self._select_tools(tools, kind)
        results: list[Listing] = []
        for tool in selected[:4]:
            for args in self._argument_attempts(tool, profile, kind):
                try:
                    data = self.clients[server].call_tool(tool["name"], args)
                except Exception as exc:
                    print(f"[mcp] {server}.{tool['name']} failed with {args}: {exc}")
                    continue
                results.extend(self._normalize(server, kind, data))
                if results:
                    break
        return results

    def _select_tools(self, tools: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
        wanted = {
            "holiday": ("search", "hotel", "holiday", "package", "deal"),
            "flight": ("search", "flight"),
            "car": ("search", "car", "vehicle", "rental"),
            "tour": ("search", "tour", "trip"),
        }[kind]
        scored = []
        for tool in tools:
            text = f"{tool.get('name', '')} {tool.get('description', '')}".lower()
            score = sum(1 for token in wanted if token in text)
            if score:
                scored.append((score, tool))
        return [tool for _, tool in sorted(scored, key=lambda item: item[0], reverse=True)] or tools

    def _argument_attempts(self, tool: dict[str, Any], profile: BuyerProfile, kind: str) -> list[dict[str, Any]]:
        schema = tool.get("inputSchema") or {}
        properties = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        destination = profile.destination or profile.city or profile.region or profile.country or "Spain"
        args: dict[str, Any] = {}
        for key, spec in properties.items():
            low = key.lower()
            if "destination" in low or low in {"to", "city", "location", "region"}:
                args[key] = destination
            elif "country" in low:
                args[key] = profile.country or destination
            elif "origin" in low or low in {"from", "departure"}:
                args[key] = "London"
            elif "night" in low:
                args[key] = profile.nights or 7
            elif "duration" in low or "days" in low:
                args[key] = profile.duration_days or profile.nights or 7
            elif "adult" in low or "people" in low or "guest" in low or "passenger" in low:
                args[key] = profile.party_size or 2
            elif "child" in low:
                args[key] = 0
            elif "star" in low:
                args[key] = profile.min_stars or 4
            elif "query" in low or "search" in low or "keyword" in low:
                args[key] = self._query(profile, kind)
            elif "currency" in low:
                args[key] = "GBP"
            elif "limit" in low or "size" in low:
                args[key] = 10
            elif key in required:
                args[key] = self._default_for(spec)
        attempts = [args]
        if args:
            attempts.append({k: v for k, v in args.items() if k in required})
        attempts.append({"query": self._query(profile, kind)})
        attempts.append({})
        return attempts

    def _query(self, profile: BuyerProfile, kind: str) -> str:
        parts = [profile.destination or profile.country or profile.region or "Spain", kind]
        if profile.amenities:
            parts.extend(sorted(profile.amenities)[:4])
        if profile.min_stars:
            parts.append(f"{int(profile.min_stars)} star")
        return " ".join(str(part).replace("_", " ") for part in parts if part)

    def _default_for(self, spec: dict[str, Any]) -> Any:
        typ = spec.get("type")
        if typ == "number":
            return 1
        if typ == "integer":
            return 1
        if typ == "boolean":
            return False
        if typ == "array":
            return []
        return ""

    def _normalize(self, server: str, fallback_kind: str, data: Any) -> list[Listing]:
        listings: list[Listing] = []
        for item in walk_dicts(data):
            price = as_float(first_value(item, PRICE_KEYS))
            url = first_value(item, URL_KEYS)
            name = first_value(item, NAME_KEYS)
            if price is None or not url or not name:
                continue
            text = " ".join(str(v) for v in item.values() if isinstance(v, (str, int, float))).lower()
            kind = self._kind_from(server, fallback_kind, text)
            amenities = [amenity for amenity in AMENITIES if amenity.replace("_", " ") in text or amenity in text]
            listings.append(
                Listing(
                    mcp=server,
                    kind=kind,
                    name=str(name)[:120],
                    url=str(url),
                    price=price,
                    raw=item,
                    country=_clean(first_value(item, ("country", "destinationCountry"))),
                    region=_clean(first_value(item, ("region", "destinationRegion", "area"))),
                    location=_clean(first_value(item, ("location", "address", "city", "destination"))),
                    star_rating=as_float(first_value(item, ("starRating", "stars", "rating"))),
                    review_score=as_float(first_value(item, ("reviewScore", "guestRating", "score"))),
                    board_basis=_board_basis(text),
                    nights=as_int(first_value(item, ("nights", "durationNights"))),
                    amenities=amenities,
                    operator=_clean(first_value(item, ("operator", "supplier"))),
                    duration_days=as_int(first_value(item, ("durationDays", "days", "duration"))),
                    vehicle_name=_clean(first_value(item, ("vehicleName", "carName", "model", "name"))),
                    transmission=_clean(first_value(item, ("transmission",))),
                    seats=as_int(first_value(item, ("seats", "passengers"))),
                )
            )
        return listings

    def _kind_from(self, server: str, fallback_kind: str, text: str) -> str:
        if server == "tourradar" or "tour" in text:
            return "tour"
        if server == "economybookings" or "car" in text or "vehicle" in text:
            return "car"
        return fallback_kind

    def _dedupe(self, listings: list[Listing]) -> list[Listing]:
        seen: set[tuple[str, str, int]] = set()
        unique: list[Listing] = []
        for listing in listings:
            key = (listing.kind, listing.url, round(listing.price))
            if key not in seen:
                unique.append(listing)
                seen.add(key)
        return unique


def _clean(value: Any) -> str | None:
    return str(value).strip() if value not in (None, "") else None


def _board_basis(text: str) -> str | None:
    for code in ("AI", "FB", "HB", "BB", "SC", "RO"):
        if re.search(rf"\b{code.lower()}\b", text):
            return code
    if "all inclusive" in text:
        return "AI"
    if "breakfast" in text:
        return "BB"
    return None

