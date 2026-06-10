"""Offline tests for persona markup profiles (Phase 8G)."""

from __future__ import annotations

from dealbreakers.personas.markup_profiles import (
    PersonaMarkupProfile,
    get_profile,
    load_profiles,
    select_persona_markup,
)


def test_default_bob_profile_values() -> None:
    profile = get_profile("practice-bob")
    assert profile.safe == 25.0
    assert profile.balanced == 30.0
    assert profile.aggressive == 35.0
    assert profile.ceiling == 35.0
    assert profile.source == "measured"


def test_unknown_persona_falls_back() -> None:
    profile = get_profile("practice-unknown")
    assert profile.persona_id == "unknown"
    assert profile.safe == 8.0


def test_walk_risk_maps_to_markup_tier() -> None:
    assert select_persona_markup("practice-bob", 0.1) == 35.0
    assert select_persona_markup("practice-bob", 0.5) == 30.0
    assert select_persona_markup("practice-bob", 0.9) == 25.0


def test_ceiling_never_exceeded() -> None:
    profiles = load_profiles()
    profiles["practice-bob"] = PersonaMarkupProfile(
        persona_id="practice-bob",
        safe=25.0,
        balanced=30.0,
        aggressive=40.0,
        ceiling=35.0,
    )
    assert select_persona_markup("practice-bob", 0.1, profiles=profiles) == 35.0


def test_gordon_inventory_limited_profile() -> None:
    profile = get_profile("practice-gordon")
    assert profile.safe == 0.0
    assert profile.source == "inventory_limited"
