"""Car hire search across EconomyBookings and TravelSupermarket MCP servers."""

from __future__ import annotations

from typing import Any

from dealbreakers.constants import MCP_SOURCES
from dealbreakers.mcp.car_normalizers import CarCandidate, extract_car_listings, is_premium_looking
from dealbreakers.mcp.client import MCPClient, MCPError


def build_economybookings_args(
    location: str,
    pickup_date: str,
    dropoff_date: str,
    driver_age: int,
    limit: int,
) -> dict[str, Any]:
    return {
        "pickupLocation": location.strip(),
        "pickupDate": pickup_date,
        "dropoffDate": dropoff_date,
        "driverAge": driver_age,
        "limit": limit,
    }


def build_travelsupermarket_car_args(
    location: str,
    pickup_date: str,
    dropoff_date: str,
    driver_age: int,
    limit: int,
) -> dict[str, Any]:
    # TSM expects city or IATA — never append "Airport".
    clean_location = location.strip()
    if clean_location.lower().endswith(" airport"):
        clean_location = clean_location[: -len(" airport")].strip()
    return {
        "pickupLocation": clean_location,
        "pickupDate": pickup_date,
        "dropoffDate": dropoff_date,
        "driverAge": driver_age,
        "limit": limit,
    }


def _sort_candidates(candidates: list[CarCandidate], *, premium: bool) -> list[CarCandidate]:
    def sort_key(candidate: CarCandidate) -> tuple[int, int, float]:
        offerable = 0 if candidate.is_offerable else 1
        premium_rank = 0 if (premium and is_premium_looking(candidate)) else 1
        price = candidate.price_total if candidate.price_total is not None else float("inf")
        return (offerable, premium_rank, price)

    return sorted(candidates, key=sort_key)


class CarSearchClient:
    def __init__(
        self,
        economy_client: MCPClient | None = None,
        travelsupermarket_client: MCPClient | None = None,
        timeout: int = 60,
    ) -> None:
        self._economy = economy_client or MCPClient(
            MCP_SOURCES["economybookings"], timeout=timeout
        )
        self._tsm = travelsupermarket_client or MCPClient(
            MCP_SOURCES["travelsupermarket"], timeout=timeout
        )
        self.last_errors: list[str] = []

    def search_cars(
        self,
        location: str,
        pickup_date: str,
        dropoff_date: str,
        driver_age: int = 30,
        premium: bool = False,
        limit: int = 10,
    ) -> list[CarCandidate]:
        self.last_errors = []
        all_candidates: list[CarCandidate] = []

        providers = (
            ("economybookings", self._economy, build_economybookings_args),
            ("travelsupermarket", self._tsm, build_travelsupermarket_car_args),
        )
        for source_mcp, client, build_args in providers:
            args = build_args(location, pickup_date, dropoff_date, driver_age, limit)
            try:
                result = client.call_tool("search-car-hire", args)
                listings = extract_car_listings(result, source_mcp=source_mcp)
                all_candidates.extend(listings)
            except MCPError as exc:
                self.last_errors.append(f"{source_mcp}: {exc}")
                continue

        return _sort_candidates(all_candidates, premium=premium)[:limit]
