from __future__ import annotations

from typing import Any

import httpx

from dealbreakers.config import Settings
from dealbreakers.models import MatchStart, SellerTurn, TurnResponse


class OfficialMatchLockedError(RuntimeError):
    """Raised when an official (scored) match is requested while locked out."""


class DealRoomClient:
    def __init__(self, settings: Settings) -> None:
        settings.require_dealroom()
        self._allow_official = settings.allow_official_matches
        self._client = httpx.Client(
            base_url=settings.dealroom_base_url.rstrip("/"),
            headers={"x-team-key": settings.team_key},
            timeout=settings.request_timeout_seconds,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> DealRoomClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def start_match(self, *, practice: bool, persona_id: str | None = None) -> MatchStart | dict:
        if not practice and not self._allow_official:
            raise OfficialMatchLockedError(
                "Official matches are LOCKED. Each official buyer is a one-shot scored "
                "attempt. To unlock at submission time, set ALLOW_OFFICIAL_MATCHES=true "
                "in .env and pass --confirm-official on the CLI."
            )

        body: dict[str, Any] = {}
        if practice:
            body["practice"] = True
            if persona_id:
                body["personaId"] = persona_id
        # Defensive: never let a non-practice body slip through while locked.
        assert practice or self._allow_official

        response = self._client.post("/match", json=body)
        response.raise_for_status()
        data = response.json()
        if data.get("done"):
            return data
        return MatchStart.model_validate(data)

    def take_turn(self, match_id: str, turn: SellerTurn) -> TurnResponse:
        response = self._client.post(f"/match/{match_id}/turn", json=turn.api_payload())
        response.raise_for_status()
        return TurnResponse.model_validate(response.json())
