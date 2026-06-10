"""Serializable graph state for the orchestration layer (Phase 8E)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class GraphState:
    persona_id: str = ""
    match_id: str = ""
    round_number: int = 0
    transcript: list[dict[str, Any]] = field(default_factory=list)
    latest_buyer_message: str = ""
    analysis: dict[str, Any] | None = None
    buyer_state: dict[str, Any] | None = None
    insights: dict[str, Any] | None = None
    policy_decision: dict[str, Any] | None = None
    inventory_candidates: dict[str, Any] | None = None
    selected_inventory: dict[str, Any] | None = None
    selected_car: dict[str, Any] | None = None
    offer: dict[str, Any] | None = None
    markup_pct: float | None = None
    seller_text: str = ""
    turn_response: dict[str, Any] | None = None
    ended: bool = False
    error: str | None = None
    logs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GraphState:
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{key: value for key, value in data.items() if key in known})
