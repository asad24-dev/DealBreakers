"""Tests for official match safety guard (Phase 8G)."""

from __future__ import annotations

import pytest
import requests_mock

from dealbreakers.api import DealRoomClient
from dealbreakers.config import Settings

BASE_URL = "https://project-parley-production.up.railway.app"
TEAM_KEY = "tk_test_key"


@pytest.fixture
def client() -> DealRoomClient:
    return DealRoomClient(Settings(base_url=BASE_URL, team_key=TEAM_KEY))


def test_practice_match_works(client: DealRoomClient) -> None:
    with requests_mock.Mocker() as mock:
        mock.post(
            f"{BASE_URL}/match",
            json={
                "matchId": "practice1",
                "scenario": {"name": "Bob", "brief": "PRACTICE"},
                "buyer": {"text": "Hi", "action": "continue"},
                "status": "awaiting-seller",
            },
        )
        result = client.start_match(practice=True, persona_id="practice-bob")
        assert result.match_id == "practice1"
        assert mock.last_request.json() == {
            "practice": True,
            "personaId": "practice-bob",
        }


def test_official_without_flag_raises(client: DealRoomClient) -> None:
    with pytest.raises(RuntimeError, match="Official matches are disabled"):
        client.start_match(practice=False, official=True)


def test_official_without_env_raises(client: DealRoomClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOW_OFFICIAL_MATCHES", raising=False)
    with pytest.raises(RuntimeError, match="ALLOW_OFFICIAL_MATCHES"):
        client.start_match(practice=False, official=True)


def test_official_with_persona_id_raises(
    client: DealRoomClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOW_OFFICIAL_MATCHES", "true")
    with pytest.raises(RuntimeError, match="cannot target a practice persona"):
        client.start_match(practice=False, official=True, persona_id="practice-bob")


def test_official_with_env_and_flag_sends_empty_body(
    client: DealRoomClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALLOW_OFFICIAL_MATCHES", "true")
    with requests_mock.Mocker() as mock:
        mock.post(
            f"{BASE_URL}/match",
            json={
                "matchId": "official1",
                "scenario": {"name": "Real", "brief": "Official"},
                "buyer": {"text": "Hi", "action": "continue"},
                "status": "awaiting-seller",
            },
        )
        result = client.start_match(practice=False, official=True)
        assert result.match_id == "official1"
        assert mock.last_request.json() == {}
