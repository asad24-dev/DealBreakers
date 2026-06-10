"""Practice-only multi-turn discovery for unknown personas (Phase 8B)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from dealbreakers.analysis.analyzer import ConversationAnalyzer, events_from_log_records
from dealbreakers.api.client import DealRoomClient
from dealbreakers.logging.jsonl_logger import read_jsonl
from dealbreakers.logging.transcript_recorder import TranscriptRecorder
from dealbreakers.models.match import MatchStartResponse
from dealbreakers.state.buyer_state import (
    BuyerState,
    estimate_aggressive_markup,
    estimate_safe_markup,
)
from dealbreakers.state.updater import build_buyer_state

TARGET_PERSONAS = ("practice-elon", "practice-gordon", "practice-cris")

DISCOVERY_QUESTIONS: dict[str, list[str]] = {
    "practice-elon": [
        (
            "Great to meet you. Are you picturing a tech-and-culture city break in a European "
            "capital, or would you rather a beach week or guided tour?"
        ),
        (
            "Which cities are on your radar — Berlin, London, Amsterdam, Lisbon, or somewhere "
            "else — and what matters most on the ground: museums, food, walkability, or nightlife?"
        ),
        (
            "Any must-haves I should treat as non-negotiable — central location, great Wi-Fi, "
            "design hotels, specific neighborhoods?"
        ),
        (
            "Solo trip or traveling with others, and how flexible are your dates?"
        ),
        (
            "On budget: are you optimizing hard for value, or is a premium stay worth it for "
            "the right city experience?"
        ),
    ],
    "practice-gordon": [
        (
            "To calibrate properly — are you after a beach holiday, a city escape, or a "
            "structured tour?"
        ),
        (
            "Which destinations are on your shortlist, and what does five-star actually mean "
            "to you — service, dining, spa, location?"
        ),
        (
            "Non-negotiables: pool, beach, fine dining, private transfer — what must be perfect?"
        ),
        (
            "Traveling solo or with family, and any fixed dates I should work around?"
        ),
        (
            "When a package falls short, do you push back on price, quality, or trust — "
            "what should I watch for?"
        ),
    ],
    "practice-cris": [
        (
            "Sounds like you want the full luxury package — holiday plus premium wheels. "
            "Beach base or city base, and is a high-end car non-negotiable?"
        ),
        (
            "Which country or region first — Spain, Portugal, Italy — and how important are "
            "airport pickup, luxury brand, or a convertible?"
        ),
        (
            "Hotel-wise: minimum star rating, spa, beachfront — what are the hard requirements?"
        ),
        (
            "Solo, couple, or family — and are your dates fixed or flexible?"
        ),
        (
            "On spend: do you care more about total value, or is premium pricing expected "
            "for the right experience?"
        ),
    ],
}


def _merge_lists(*values: list[str] | None) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in value or []:
            key = item.lower()
            if key not in seen:
                merged.append(item)
                seen.add(key)
    return merged


def assert_practice_match(start: MatchStartResponse) -> None:
    if "PRACTICE" not in start.scenario.brief.upper():
        raise RuntimeError(
            "Safety stop: persona discovery must never run an official match. "
            f"Scenario brief was: {start.scenario.brief!r}"
        )


def transcript_path_for(persona_id: str, profiles_dir: str | Path = "logs/persona_profiles") -> Path:
    return Path(profiles_dir) / f"{persona_id}.jsonl"


def profile_path_for(persona_id: str, profiles_dir: str | Path = "logs/persona_profiles") -> Path:
    return Path(profiles_dir) / f"{persona_id}.json"


def profile_to_summary(profile: dict[str, Any]) -> dict[str, Any]:
    """Compact summary row for persona_summary.json."""
    analysis = profile.get("final_analysis") or {}
    state = profile.get("final_state") or {}
    return {
        "product": analysis.get("trip_type"),
        "luxury": max(
            float(analysis.get("luxury_preference") or 0.0),
            float(state.get("luxury_preference") or 0.0),
        ),
        "price_sensitivity": max(
            float(analysis.get("price_sensitivity") or 0.0),
            float(state.get("price_sensitivity") or 0.0),
        ),
        "trust_sensitivity": max(
            float(analysis.get("trust_sensitivity") or 0.0),
            float(state.get("trust_sensitivity") or 0.0),
        ),
        "destinations": _merge_lists(
            analysis.get("destinations"),
            state.get("destinations"),
        ),
        "must_haves": _merge_lists(
            analysis.get("must_haves"),
            state.get("must_haves"),
        ),
        "stated_budget_max": state.get("stated_budget_max"),
        "confidence": max(
            float(analysis.get("confidence") or 0.0),
            float(state.get("confidence") or 0.0),
        ),
        "estimate_safe_markup": state.get("estimate_safe_markup"),
        "estimate_aggressive_markup": state.get("estimate_aggressive_markup"),
        "objections": state.get("objections") or analysis.get("objections") or [],
    }


def _state_dict(state: BuyerState) -> dict[str, Any]:
    data = state.to_dict()
    data["estimate_safe_markup"] = estimate_safe_markup(state)
    data["estimate_aggressive_markup"] = estimate_aggressive_markup(state)
    return data


def run_discovery_session(
    persona_id: str,
    *,
    client: DealRoomClient,
    analyzer: ConversationAnalyzer,
    profiles_dir: str | Path = "logs/persona_profiles",
    num_turns: int = 4,
) -> dict[str, Any]:
    """Run a practice-only discovery session. No offers sent."""
    if persona_id not in TARGET_PERSONAS:
        raise ValueError(f"Persona {persona_id!r} is not in discovery target list")

    questions = DISCOVERY_QUESTIONS[persona_id][:num_turns]
    transcript_path = transcript_path_for(persona_id, profiles_dir)
    transcript_path.parent.mkdir(parents=True, exist_ok=True)
    recorder = TranscriptRecorder(path=transcript_path)

    start = client.start_match(practice=True, persona_id=persona_id)
    if not isinstance(start, MatchStartResponse):
        raise RuntimeError("Unexpected: match did not start")
    assert_practice_match(start)

    recorder.record_match_started(start, practice=True, persona_id=persona_id)
    recorder.record_buyer_message(
        start.match_id,
        start.buyer,
        scenario_name=start.scenario.name,
        persona_id=persona_id,
    )

    turn_snapshots: list[dict[str, Any]] = []

    for round_number, question in enumerate(questions, start=1):
        turn = client.send_turn(start.match_id, question)
        recorder.record_seller_message(start.match_id, question, round_number=round_number)
        recorder.record_turn_response(start.match_id, turn)

        records = read_jsonl(transcript_path)
        events = events_from_log_records(records)
        analysis = analyzer.analyze(events)
        state = build_buyer_state(records, analysis)

        turn_snapshots.append(
            {
                "round": round_number,
                "seller_text": question,
                "buyer_text": turn.buyer.text,
                "buyer_action": turn.buyer.action.value,
                "analysis": analysis.to_dict(),
                "state": _state_dict(state),
            }
        )

        if turn.is_ended:
            break

    records = read_jsonl(transcript_path)
    events = events_from_log_records(records)
    final_analysis = analyzer.analyze(events)
    final_state = build_buyer_state(records, final_analysis)

    profile = {
        "persona_id": persona_id,
        "match_id": start.match_id,
        "scenario_name": start.scenario.name,
        "scenario_brief": start.scenario.brief,
        "transcript_log": str(transcript_path),
        "discovery_turns": len(turn_snapshots),
        "turn_snapshots": turn_snapshots,
        "final_analysis": final_analysis.to_dict(),
        "final_state": _state_dict(final_state),
    }

    profile_path = profile_path_for(persona_id, profiles_dir)
    profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return profile


def discover_remaining_personas(
    *,
    client: DealRoomClient,
    analyzer: ConversationAnalyzer,
    profiles_dir: str | Path = "logs/persona_profiles",
    summary_path: str | Path = "logs/persona_summary.json",
    num_turns: int = 4,
) -> dict[str, Any]:
    """Discover all target personas and write summary JSON."""
    profiles_dir = Path(profiles_dir)
    profiles_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {}
    for persona_id in TARGET_PERSONAS:
        profile = run_discovery_session(
            persona_id,
            client=client,
            analyzer=analyzer,
            profiles_dir=profiles_dir,
            num_turns=num_turns,
        )
        summary[persona_id] = profile_to_summary(profile)

    summary_path = Path(summary_path)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary
