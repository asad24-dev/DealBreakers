"""Typed wrapper around the TourRadar MCP server."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from dealbreakers.constants import MCP_SOURCES
from dealbreakers.mcp.client import MCPClient
from dealbreakers.mcp.tour_normalizers import (
    TourCandidate,
    country_to_code,
    extract_tour_id,
    extract_tour_listings,
    merge_tour_candidate,
)


class TourRadarClient:
    def __init__(self, client: MCPClient | None = None, timeout: int = 90) -> None:
        self._client = client or MCPClient(MCP_SOURCES["tourradar"], timeout=timeout)

    def search_tours(
        self,
        query: str = "guided tour of Spain",
        country: str | None = "Spain",
        min_days: int | None = None,
        max_days: int | None = None,
        max_price: float | None = None,
        limit: int = 10,
    ) -> list[TourCandidate]:
        """Search guided tours and enrich top results with details + departures."""
        search_result = self._client.request(
            "tools/call",
            {"name": "vertex-tour-search", "arguments": self._build_search_arguments(
                query=query,
                country=country,
                min_days=min_days,
                max_days=max_days,
                max_price=max_price,
            )},
        )
        listings = extract_tour_listings(search_result)[:limit]

        candidates: list[TourCandidate] = []
        for listing in listings:
            tour_id = extract_tour_id(listing)
            details_raw = self._fetch_details(tour_id) if tour_id else None
            departures_raw = self._fetch_departures(tour_id) if tour_id else None
            candidates.append(
                merge_tour_candidate(
                    listing,
                    details_raw,
                    departures_raw,
                    country_hint=country,
                )
            )

        offerable = [candidate for candidate in candidates if candidate.is_offerable]
        non_offerable = [candidate for candidate in candidates if not candidate.is_offerable]
        return offerable + non_offerable

    def _build_search_arguments(
        self,
        *,
        query: str,
        country: str | None,
        min_days: int | None,
        max_days: int | None,
        max_price: float | None,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {
            "textSearch": query,
            "display_mode": "listing",
            "currency": "GBP",
        }
        country_code = country_to_code(country)
        if country_code:
            arguments["countries"] = {"values": [country_code], "operator": "OR"}
        if min_days is not None or max_days is not None:
            duration: dict[str, int] = {}
            if min_days is not None:
                duration["min"] = min_days
            if max_days is not None:
                duration["max"] = max_days
            arguments["duration"] = duration
        if max_price is not None:
            arguments["price"] = {"min": 0, "max": max_price, "currency": "GBP"}
        return arguments

    def _fetch_details(self, tour_id: int) -> dict[str, Any] | None:
        try:
            result = self._client.request(
                "tools/call",
                {"name": "b2b-tour-details", "arguments": {"tourId": tour_id, "currency": "GBP"}},
            )
            structured = result.get("structuredContent", result)
            if isinstance(structured, dict) and isinstance(structured.get("tour"), dict):
                return structured["tour"]
        except Exception:
            return None
        return None

    def _fetch_departures(self, tour_id: int) -> dict[str, Any] | None:
        today = date.today()
        try:
            result = self._client.request(
                "tools/call",
                {
                    "name": "b2b-tour-departures",
                    "arguments": {
                        "tourId": tour_id,
                        "dateRange": {
                            "start": today.isoformat(),
                            "end": (today + timedelta(days=365)).isoformat(),
                        },
                    },
                },
            )
            structured = result.get("structuredContent", result)
            return structured if isinstance(structured, dict) else None
        except Exception:
            return None
