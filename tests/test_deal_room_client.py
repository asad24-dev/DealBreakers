import json

import pytest
import requests_mock

from dealbreakers.api import (
    AuthenticationError,
    DealRoomClient,
    OfferValidationError,
)
from dealbreakers.config import Settings
from dealbreakers.models.match import AllMatchesDone, MatchStartResponse, TurnResponse
from dealbreakers.models.offer import Holiday, Offer, Source

BASE_URL = "https://project-parley-production.up.railway.app"
TEAM_KEY = "tk_test_key"


@pytest.fixture
def client() -> DealRoomClient:
    settings = Settings(base_url=BASE_URL, team_key=TEAM_KEY)
    return DealRoomClient(settings)


def test_start_match_official(client: DealRoomClient, monkeypatch) -> None:
    monkeypatch.setenv("ALLOW_OFFICIAL_MATCHES", "true")
    with requests_mock.Mocker() as mock:
        mock.post(
            f"{BASE_URL}/match",
            json={
                "matchId": "abc123",
                "scenario": {"name": "The Bennetts", "brief": "Family holiday"},
                "buyer": {"text": "Hi!", "action": "continue"},
                "status": "awaiting-seller",
            },
        )

        result = client.start_match(practice=False, official=True)

        assert isinstance(result, MatchStartResponse)
        assert result.match_id == "abc123"
        assert mock.last_request.headers["x-team-key"] == TEAM_KEY
        assert mock.last_request.json() == {}


def test_start_match_practice_with_persona(client: DealRoomClient) -> None:
    with requests_mock.Mocker() as mock:
        mock.post(
            f"{BASE_URL}/match",
            json={
                "matchId": "xyz789",
                "scenario": {"name": "Bob", "brief": "Beach week"},
                "buyer": {"text": "Hello", "action": "continue"},
                "status": "awaiting-seller",
            },
        )

        result = client.start_match(practice=True, persona_id="practice-bob")

        assert isinstance(result, MatchStartResponse)
        assert mock.last_request.json() == {
            "practice": True,
            "personaId": "practice-bob",
        }


def test_start_match_all_done(client: DealRoomClient) -> None:
    with requests_mock.Mocker() as mock:
        mock.post(f"{BASE_URL}/match", json={"done": True})

        result = client.start_match(practice=True)

        assert isinstance(result, AllMatchesDone)
        assert result.done is True
        assert mock.last_request.json() == {"practice": True}


def test_send_turn_without_offer(client: DealRoomClient) -> None:
    with requests_mock.Mocker() as mock:
        mock.post(
            f"{BASE_URL}/match/m1/turn",
            json={
                "buyer": {"text": "Sounds good", "action": "continue"},
                "status": "awaiting-seller",
                "result": None,
            },
        )

        turn = client.send_turn("m1", "Tell me more about dates.")

        assert isinstance(turn, TurnResponse)
        assert turn.buyer.text == "Sounds good"
        assert "offer" not in mock.last_request.json()


def test_send_turn_with_offer_serializes_numbers(client: DealRoomClient) -> None:
    with requests_mock.Mocker() as mock:
        mock.post(
            f"{BASE_URL}/match/m1/turn",
            json={
                "buyer": {"text": "Too expensive", "action": "continue"},
                "status": "awaiting-seller",
                "quote": {"cost": 2440, "markupPct": 12, "total": 2732.8},
                "result": None,
            },
        )

        offer = Offer(
            holiday=Holiday(
                price_total=2440,
                hotel_name="Test Hotel",
                country="Spain",
            ),
            markup_pct=12,
            sources=[Source(mcp="travelsupermarket", url="https://example.com", price=2440)],
        )
        turn = client.send_turn("m1", "Here is an option.", offer=offer)

        body = mock.last_request.json()
        assert body["offer"]["holiday"]["priceTotal"] == 2440
        assert isinstance(body["offer"]["holiday"]["priceTotal"], (int, float))
        assert turn.quote is not None
        assert turn.quote.total == 2732.8


def test_offer_validation_error_does_not_parse_json(client: DealRoomClient) -> None:
    with requests_mock.Mocker() as mock:
        mock.post(
            f"{BASE_URL}/match/m1/turn",
            status_code=400,
            text="priceTotal must be a number",
        )

        with pytest.raises(OfferValidationError) as exc_info:
            client.send_turn("m1", "Bad offer", offer=Offer())

        assert "priceTotal must be a number" in str(exc_info.value)
        assert exc_info.value.body == "priceTotal must be a number"


def test_authentication_error(client: DealRoomClient) -> None:
    with requests_mock.Mocker() as mock:
        mock.post(f"{BASE_URL}/match", status_code=401, text="Invalid key")

        with pytest.raises(AuthenticationError):
            client.start_match(practice=True, persona_id="practice-bob")


def test_turn_ended_accept(client: DealRoomClient) -> None:
    with requests_mock.Mocker() as mock:
        mock.post(
            f"{BASE_URL}/match/m1/turn",
            json={
                "buyer": {"text": "Deal!", "action": "accept"},
                "status": "ended",
                "result": {"closed": True, "endReason": "accept", "rounds": 4},
            },
        )

        turn = client.send_turn("m1", "Final offer", offer=Offer(
            holiday=Holiday(price_total=1000, country="Spain"),
            markup_pct=5,
        ))

        assert turn.is_ended
        assert turn.buyer_accepted
        assert turn.result is not None
        assert turn.result.closed is True
        assert json.loads(mock.last_request.body)["text"] == "Final offer"
