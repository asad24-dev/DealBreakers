"""Transcript models for match analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dealbreakers.logging.jsonl_logger import serialize_for_log

ROLE_SYSTEM = "system"
ROLE_BUYER = "buyer"
ROLE_SELLER = "seller"
ROLE_API = "api"


@dataclass
class TranscriptEvent:
    match_id: str
    persona_id: str | None
    scenario_name: str | None
    round_number: int | None
    role: str
    text: str
    action: str | None = None
    offer: dict | None = None
    quote: dict | None = None
    result: dict | None = None
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return serialize_for_log(self)


@dataclass
class MatchTranscript:
    match_id: str
    practice: bool
    persona_id: str | None
    scenario_name: str
    scenario_brief: str
    events: list[TranscriptEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return serialize_for_log(self)
