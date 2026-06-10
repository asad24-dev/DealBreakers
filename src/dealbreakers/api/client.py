"""Deal Room API client."""

from __future__ import annotations

import os
import time
from typing import Any

import requests

from dealbreakers.api.errors import (
    AuthenticationError,
    DealRoomError,
    NotFoundError,
    OfferValidationError,
    RateLimitError,
    ServerError,
)
from dealbreakers.config import Settings
from dealbreakers.models.match import AllMatchesDone, MatchStartResponse, TurnResponse
from dealbreakers.models.offer import Offer

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_RETRIES = 1
_RETRY_DELAY_SEC = 1.0


class DealRoomClient:
    def __init__(self, settings: Settings, *, timeout: float = 30.0) -> None:
        self._settings = settings
        self._timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "x-team-key": settings.team_key,
            "Content-Type": "application/json",
        })

    def start_match(
        self,
        *,
        practice: bool = True,
        persona_id: str | None = None,
        official: bool = False,
    ) -> MatchStartResponse | AllMatchesDone:
        if not practice:
            if not official:
                raise RuntimeError(
                    "Official matches are disabled. Set ALLOW_OFFICIAL_MATCHES=true "
                    "and pass official=True explicitly."
                )
            if os.environ.get("ALLOW_OFFICIAL_MATCHES", "").lower() not in {
                "1",
                "true",
                "yes",
            }:
                raise RuntimeError(
                    "Official matches are disabled. Set ALLOW_OFFICIAL_MATCHES=true "
                    "and pass official=True explicitly."
                )
            if persona_id is not None:
                raise RuntimeError(
                    "Official matches cannot target a practice persona. Omit persona_id."
                )
            body: dict[str, Any] = {}
        else:
            body = {"practice": True}
            if persona_id:
                body["personaId"] = persona_id

        data = self._post("/match", body)
        if data.get("done"):
            return AllMatchesDone.from_api(data)
        return MatchStartResponse.from_api(data)

    def send_turn(
        self,
        match_id: str,
        text: str,
        offer: Offer | None = None,
    ) -> TurnResponse:
        body: dict[str, Any] = {"text": text}
        if offer is not None:
            body["offer"] = offer.to_api_dict()

        data = self._post(f"/match/{match_id}/turn", body)
        return TurnResponse.from_api(data)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._settings.base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = self._session.post(
                    url,
                    json=body,
                    timeout=self._timeout,
                )
                return self._handle_response(response)
            except (RateLimitError, ServerError) as exc:
                last_error = exc
                if attempt < _MAX_RETRIES:
                    time.sleep(_RETRY_DELAY_SEC)
                    continue
                raise

        if last_error:
            raise last_error
        raise DealRoomError("Request failed with no response")

    def _handle_response(self, response: requests.Response) -> dict[str, Any]:
        status = response.status_code
        body = response.text

        if status == 400:
            raise OfferValidationError(
                f"Offer validation failed: {body}",
                body=body,
            )
        if status in {401, 403}:
            raise AuthenticationError(
                f"Authentication failed ({status}): {body}",
                status_code=status,
            )
        if status == 404:
            raise NotFoundError(
                f"Resource not found: {body}",
                status_code=status,
            )
        if status == 429:
            raise RateLimitError(
                f"Rate limit exceeded: {body}",
                status_code=status,
            )
        if status in _RETRYABLE_STATUS:
            raise ServerError(
                f"Server error ({status}): {body}",
                status_code=status,
            )
        if not response.ok:
            raise DealRoomError(
                f"Unexpected error ({status}): {body}",
                status_code=status,
            )

        return response.json()
