"""Offline tests for Phase 8C remaining persona close scripts."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from dealbreakers.constants import BuyerAction, MatchStatus
from dealbreakers.models.match import BuyerMessage, MatchStartResponse, Scenario, TurnResponse
from dealbreakers.mcp.normalizers import HolidayCandidate
from dealbreakers.offers import (
    build_holiday_offer,
    pick_best_cris_candidate,
    pick_best_elon_candidate,
    pick_best_gordon_candidate,
    score_cris_candidate,
    score_elon_candidate,
    score_gordon_candidate,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load_script_module(name: str):
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def make_start(*, brief: str = "PRACTICE buyer — test") -> MatchStartResponse:
    return MatchStartResponse(
        match_id="match-test",
        scenario=Scenario(name="Test Buyer", brief=brief),
        buyer=BuyerMessage(text="I want a trip.", action=BuyerAction.CONTINUE),
        status=MatchStatus.AWAITING_SELLER,
    )


def make_candidate(
    *,
    hotel_name: str = "Hotel",
    price: float = 2000.0,
    stars: float = 4.0,
    review: float = 8.5,
    amenities: list[str] | None = None,
    location: str = "Resort",
    url: str = "https://example.com/hotel",
) -> HolidayCandidate:
    return HolidayCandidate(
        hotel_name=hotel_name,
        url=url,
        star_rating=stars,
        review_score=review,
        board_basis="HB",
        nights=7,
        location=location,
        region="Region",
        country="Country",
        amenities=amenities or [],
        price_total=price,
    )


@pytest.mark.parametrize(
    ("script_name", "persona_id", "banner"),
    [
        ("close_elon", "practice-elon", "CLOSE ELON"),
        ("close_gordon", "practice-gordon", "CLOSE GORDON"),
        ("close_cris", "practice-cris", "CLOSE CRIS"),
    ],
)
def test_script_hardcodes_persona_and_practice(script_name: str, persona_id: str, banner: str):
    source = (SCRIPTS / f"{script_name}.py").read_text(encoding="utf-8")
    assert f'PERSONA_ID = "{persona_id}"' in source
    assert "start_match(practice=True, persona_id=PERSONA_ID)" in source
    assert 'start_match({})' not in source
    assert "--official" not in source
    assert "--practice" not in source
    assert f"PRACTICE MODE ONLY — {banner}" in source


@pytest.mark.parametrize("script_name", ["close_elon", "close_gordon", "close_cris"])
def test_assert_practice_match_rejects_official(script_name: str):
    module = load_script_module(script_name)
    with pytest.raises(RuntimeError, match="must never run an official match"):
        module.assert_practice_match(make_start(brief="Official buyer — Gordon Ramsay"))


def test_elon_scoring_prefers_wifi_gym_central_four_star():
    basic = make_candidate(
        hotel_name="Budget Inn",
        price=1500.0,
        stars=3.0,
        review=7.5,
        amenities=["pool"],
        location="Outskirts",
    )
    ideal = make_candidate(
        hotel_name="Central Business Hotel",
        price=1800.0,
        stars=4.0,
        review=9.2,
        amenities=["wifi", "gym"],
        location="Berlin city centre",
    )
    assert score_elon_candidate(ideal) > score_elon_candidate(basic)
    assert pick_best_elon_candidate([basic, ideal]) is ideal


def test_gordon_scoring_prefers_five_star_spa_beach_over_cheaper_four_star():
    cheap_four = make_candidate(
        hotel_name="Cheap Beach",
        price=1200.0,
        stars=4.0,
        review=8.0,
        amenities=["spa"],
        location="Costa",
    )
    luxury_five = make_candidate(
        hotel_name="Grand Spa Resort",
        price=4500.0,
        stars=5.0,
        review=9.6,
        amenities=["spa", "close_to_beach", "pool"],
        location="Marbella",
    )
    assert score_gordon_candidate(luxury_five) > score_gordon_candidate(cheap_four)
    assert pick_best_gordon_candidate([cheap_four, luxury_five]) is luxury_five


def test_cris_scoring_prefers_spa_gym_beach_terrace_quality():
    cheaper = make_candidate(
        hotel_name="Value Resort",
        price=1100.0,
        stars=4.0,
        review=8.0,
        amenities=["spa"],
        location="Algarve",
    )
    premium = make_candidate(
        hotel_name="Palace Algarve",
        price=4200.0,
        stars=5.0,
        review=9.5,
        amenities=["spa", "gym", "close_to_beach", "sun_terrace"],
        location="Algarve beachfront",
    )
    assert score_cris_candidate(premium) > score_cris_candidate(cheaper)
    assert pick_best_cris_candidate([cheaper, premium]) is premium


def test_no_car_invented_when_wrapper_unavailable():
    cris = load_script_module("close_cris")
    assert cris.car_wrapper_available() is False
    offer = build_holiday_offer(make_candidate(), markup_pct=30.0)
    assert offer.car is None
    payload = offer.to_api_dict()
    assert "car" not in payload


@pytest.mark.parametrize("script_name", ["close_elon", "close_gordon", "close_cris"])
def test_no_offer_sent_when_no_offerable_candidate(script_name: str):
    module = load_script_module(script_name)
    unofferable = HolidayCandidate(
        hotel_name="Ghost Hotel",
        url=None,
        price_total=None,
    )
    search_patchers = {
        "close_elon": ("search_elon_candidates",),
        "close_gordon": ("search_gordon_candidates",),
        "close_cris": ("search_cris_candidates",),
    }
    search_fn = search_patchers[script_name][0]

    with (
        patch.object(module, "load_settings"),
        patch.object(module, "DealRoomClient") as mock_client_cls,
        patch.object(module, "TranscriptRecorder") as mock_recorder_cls,
        patch.object(module, search_fn, return_value=([unofferable], "none")),
    ):
        mock_client = mock_client_cls.return_value
        mock_client.start_match.return_value = make_start()
        mock_client.send_turn.return_value = TurnResponse(
            status=MatchStatus.AWAITING_SELLER,
            buyer=BuyerMessage(text="Sounds good.", action=BuyerAction.CONTINUE),
        )
        mock_recorder = mock_recorder_cls.return_value
        exit_code = module.main()

    assert exit_code == 1
    mock_client.send_turn.assert_called_once()
    mock_recorder.record_error.assert_called()
