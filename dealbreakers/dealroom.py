from __future__ import annotations

from typing import Any

import httpx


class DealRoomClient:
    def __init__(self, base_url: str, team_key: str, timeout: float = 30):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            timeout=timeout,
            headers={
                "x-team-key": team_key,
                "content-type": "application/json",
                "accept": "application/json",
            },
        )

    def start_match(self, practice: bool, persona_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {}
        if practice:
            body["practice"] = True
        if persona_id:
            body["personaId"] = persona_id
        response = self.client.post(f"{self.base_url}/match", json=body)
        response.raise_for_status()
        return response.json()

    def take_turn(self, match_id: str, text: str, offer: dict[str, Any] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"text": text}
        if offer:
            body["offer"] = offer
        response = self.client.post(f"{self.base_url}/match/{match_id}/turn", json=body)
        response.raise_for_status()
        return response.json()

