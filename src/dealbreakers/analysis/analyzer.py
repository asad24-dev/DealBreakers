"""LLM-backed conversation analyzer. Deterministic plumbing, inspectable output."""

from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv

from dealbreakers.analysis.models import ConversationAnalysis
from dealbreakers.analysis.prompts import SYSTEM_PROMPT, build_user_prompt
from dealbreakers.models.transcript import TranscriptEvent

DEFAULT_MODEL = "gpt-4o-mini"


class ConversationAnalyzer:
    """Extracts structured buyer signals from a transcript via OpenAI.

    The OpenAI client is injectable for offline tests. Extraction only:
    this class never produces seller-facing text.
    """

    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> None:
        load_dotenv()
        self._model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        self._temperature = temperature
        if client is None:
            from openai import OpenAI

            client = OpenAI()
        self._client = client

    def analyze(self, transcript: list[TranscriptEvent]) -> ConversationAnalysis:
        """Return a fully-populated ConversationAnalysis for the transcript."""
        response = self._client.chat.completions.create(
            model=self._model,
            temperature=self._temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(transcript)},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        try:
            data = json.loads(raw)
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        return ConversationAnalysis.from_dict(data)


def events_from_log_records(records: list[dict[str, Any]]) -> list[TranscriptEvent]:
    """Rebuild TranscriptEvents from JSONL log records (Phase 2 format)."""
    events: list[TranscriptEvent] = []
    for record in records:
        record_type = record.get("record_type")
        match_id = record.get("match_id") or ""

        if record_type == "buyer_message":
            events.append(
                TranscriptEvent(
                    match_id=match_id,
                    persona_id=record.get("persona_id"),
                    scenario_name=record.get("scenario_name"),
                    round_number=record.get("round_number"),
                    role="buyer",
                    text=record.get("text", ""),
                    action=record.get("action"),
                )
            )
        elif record_type == "seller_message":
            events.append(
                TranscriptEvent(
                    match_id=match_id,
                    persona_id=None,
                    scenario_name=None,
                    round_number=record.get("round_number"),
                    role="seller",
                    text=record.get("text", ""),
                    offer=record.get("offer"),
                )
            )
        elif record_type == "turn_response":
            events.append(
                TranscriptEvent(
                    match_id=match_id,
                    persona_id=None,
                    scenario_name=None,
                    round_number=None,
                    role="buyer",
                    text=record.get("buyer_text", ""),
                    action=record.get("buyer_action"),
                    quote=record.get("quote"),
                    result=record.get("result"),
                )
            )
    return events
