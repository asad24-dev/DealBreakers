"""Structured per-turn transcript recording on top of the JSONL logger."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dealbreakers.logging.jsonl_logger import DEFAULT_LOG_PATH, append_run_log
from dealbreakers.models.match import BuyerMessage, MatchStartResponse, TurnResponse


class TranscriptRecorder:
    """Writes one structured JSONL record per match event."""

    def __init__(self, path: str | Path = DEFAULT_LOG_PATH) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def record_match_started(
        self,
        match_response: MatchStartResponse,
        *,
        practice: bool = True,
        persona_id: str | None = None,
    ) -> None:
        append_run_log(
            {
                "record_type": "match_started",
                "match_id": match_response.match_id,
                "practice": practice,
                "persona_id": persona_id,
                "scenario_name": match_response.scenario.name,
                "scenario_brief": match_response.scenario.brief,
                "status": match_response.status,
                "buyer_text": match_response.buyer.text,
                "buyer_action": match_response.buyer.action,
            },
            self._path,
        )

    def record_buyer_message(
        self,
        match_id: str,
        buyer: BuyerMessage,
        scenario_name: str | None = None,
        persona_id: str | None = None,
        round_number: int | None = None,
    ) -> None:
        append_run_log(
            {
                "record_type": "buyer_message",
                "match_id": match_id,
                "role": "buyer",
                "persona_id": persona_id,
                "scenario_name": scenario_name,
                "round_number": round_number,
                "text": buyer.text,
                "action": buyer.action,
            },
            self._path,
        )

    def record_seller_message(
        self,
        match_id: str,
        text: str,
        offer: dict | None = None,
        round_number: int | None = None,
    ) -> None:
        append_run_log(
            {
                "record_type": "seller_message",
                "match_id": match_id,
                "role": "seller",
                "round_number": round_number,
                "text": text,
                "offer": offer,
            },
            self._path,
        )

    def record_turn_response(self, match_id: str, turn_response: TurnResponse) -> None:
        append_run_log(
            {
                "record_type": "turn_response",
                "match_id": match_id,
                "status": turn_response.status,
                "buyer_text": turn_response.buyer.text,
                "buyer_action": turn_response.buyer.action,
                "quote": turn_response.quote,
                "result": turn_response.result,
            },
            self._path,
        )

    def record_error(
        self,
        match_id: str | None,
        error: Exception,
        context: dict[str, Any] | None = None,
    ) -> None:
        append_run_log(
            {
                "record_type": "error",
                "match_id": match_id,
                "error_type": type(error).__name__,
                "error_message": str(error),
                "context": context or {},
            },
            self._path,
        )
