"""Registry of ideas cherry-picked from team branches (Phase 7E traceability)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PortedImprovement:
    source_branch: str
    feature: str
    ported: bool
    target_module: str
    notes: str


REGISTRY: list[PortedImprovement] = [
    PortedImprovement(
        source_branch="origin/feature/deal-room-agent",
        feature="total_based_counter",
        ported=True,
        target_module="negotiation.pricing",
        notes="MarkupLadder.clamp — concede on quoted total (92%/85%), not markup rungs.",
    ),
    PortedImprovement(
        source_branch="origin/feature/deal-room-agent",
        feature="luxury_opening_cap",
        ported=True,
        target_module="negotiation.pricing",
        notes="Cap first luxury offer at 25% even under aggressive walk-risk.",
    ),
    PortedImprovement(
        source_branch="origin/feature/deal-room-agent",
        feature="cheaper_product_pivot",
        ported=True,
        target_module="negotiation.live_agent",
        notes="Swap to 20%-cheaper hotel when price counters exhausted.",
    ),
    PortedImprovement(
        source_branch="origin/feature/deal-room-agent",
        feature="premium_car_tier",
        ported=True,
        target_module="offers.selection",
        notes="Prefer premium/luxury/suv/fullsize tier before brand scoring.",
    ),
    PortedImprovement(
        source_branch="origin/feature/deal-room-agent",
        feature="desired_nights_search",
        ported=True,
        target_module="negotiation.live_agent",
        notes="Search durations in order: desired → 10 → 7; disclose mismatch.",
    ),
    PortedImprovement(
        source_branch="origin/feature/deal-room-agent",
        feature="conversation_dead_stop",
        ported=True,
        target_module="negotiation.live_agent",
        notes="Stop burning rounds when buyer has clearly left.",
    ),
    PortedImprovement(
        source_branch="origin/feature/deal-room-agent",
        feature="negotiation_strategist",
        ported=True,
        target_module="negotiation.strategist",
        notes="Advisory brief for responder only — no policy/markup control.",
    ),
    PortedImprovement(
        source_branch="origin/feature/deal-room-agent",
        feature="trivago_city_break",
        ported=True,
        target_module="mcp.city_break",
        notes="Trivago + Kiwi city-break path wired in 8F.",
    ),
    PortedImprovement(
        source_branch="origin/feature/deal-room-agent",
        feature="llm_pricing_strategist",
        ported=False,
        target_module="negotiation.pricing",
        notes="Rejected — LLM must not set markup.",
    ),
]


def ported_features() -> list[str]:
    return [item.feature for item in REGISTRY if item.ported]


def registry_dict() -> list[dict[str, str | bool]]:
    return [
        {
            "source_branch": item.source_branch,
            "feature": item.feature,
            "ported": item.ported,
            "target_module": item.target_module,
            "notes": item.notes,
        }
        for item in REGISTRY
    ]
