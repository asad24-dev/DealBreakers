"""Offline tests for persona discovery helpers (Phase 8B)."""

from pathlib import Path

import pytest

from dealbreakers.experiments.persona_discovery import (
    DISCOVERY_QUESTIONS,
    TARGET_PERSONAS,
    assert_practice_match,
    profile_to_summary,
    profile_path_for,
    transcript_path_for,
)
from dealbreakers.constants import BuyerAction, MatchStatus
from dealbreakers.models.match import BuyerMessage, MatchStartResponse, Scenario


def make_start(*, brief: str = "PRACTICE buyer") -> MatchStartResponse:
    return MatchStartResponse(
        match_id="match-1",
        scenario=Scenario(name="Test", brief=brief),
        buyer=BuyerMessage(text="Hi", action=BuyerAction.CONTINUE),
        status=MatchStatus.AWAITING_SELLER,
    )


def test_target_personas_exclude_bob_and_toni() -> None:
    assert "practice-bob" not in TARGET_PERSONAS
    assert "practice-toni" not in TARGET_PERSONAS
    assert set(TARGET_PERSONAS) == {"practice-elon", "practice-gordon", "practice-cris"}


def test_each_persona_has_discovery_questions() -> None:
    for persona_id in TARGET_PERSONAS:
        assert len(DISCOVERY_QUESTIONS[persona_id]) >= 4


def test_assert_practice_match_rejects_official() -> None:
    with pytest.raises(RuntimeError, match="must never run an official match"):
        assert_practice_match(make_start(brief="Official buyer"))


def test_profile_paths() -> None:
    assert transcript_path_for("practice-elon") == Path("logs/persona_profiles/practice-elon.jsonl")
    assert profile_path_for("practice-gordon") == Path("logs/persona_profiles/practice-gordon.json")


def test_profile_to_summary_shape() -> None:
    profile = {
        "final_analysis": {
            "trip_type": "holiday",
            "luxury_preference": 0.9,
            "price_sensitivity": 0.1,
            "trust_sensitivity": 0.2,
            "destinations": ["Berlin"],
            "must_haves": ["wifi"],
            "confidence": 0.8,
            "objections": [],
        },
        "final_state": {
            "luxury_preference": 0.85,
            "price_sensitivity": 0.0,
            "trust_sensitivity": 0.3,
            "destinations": ["Berlin"],
            "must_haves": ["wifi", "central location"],
            "stated_budget_max": None,
            "confidence": 0.85,
            "estimate_safe_markup": 18.0,
            "estimate_aggressive_markup": 35.0,
            "objections": [],
        },
    }
    summary = profile_to_summary(profile)
    assert summary["product"] == "holiday"
    assert summary["luxury"] == 0.9
    assert summary["price_sensitivity"] == 0.1
    assert summary["trust_sensitivity"] == 0.3
    assert summary["must_haves"] == ["wifi", "central location"]
    assert summary["estimate_safe_markup"] == 18.0
