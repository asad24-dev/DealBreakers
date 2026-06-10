"""Persona-specific markup profiles for practice evaluation (Phase 8G)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PROFILES_PATH = Path("logs/persona_markup_profiles.json")


@dataclass
class PersonaMarkupProfile:
    persona_id: str
    safe: float
    balanced: float
    aggressive: float
    ceiling: float | None = None
    source: str = "heuristic"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> PersonaMarkupProfile:
        return cls(
            persona_id=str(data["persona_id"]),
            safe=float(data["safe"]),
            balanced=float(data["balanced"]),
            aggressive=float(data["aggressive"]),
            ceiling=float(data["ceiling"]) if data.get("ceiling") is not None else None,
            source=str(data.get("source", "heuristic")),
            notes=list(data.get("notes") or []),
        )


_DEFAULTS: dict[str, PersonaMarkupProfile] = {
    "practice-bob": PersonaMarkupProfile(
        persona_id="practice-bob",
        safe=25.0,
        balanced=30.0,
        aggressive=35.0,
        ceiling=35.0,
        source="measured",
        notes=["Binary search ceiling 35% on practice-bob."],
    ),
    "practice-cris": PersonaMarkupProfile(
        persona_id="practice-cris",
        safe=18.0,
        balanced=25.0,
        aggressive=31.0,
        ceiling=None,
        source="team_observed",
        notes=["Friend/team reached ~31%; use controlled sweep to verify."],
    ),
    "practice-toni": PersonaMarkupProfile(
        persona_id="practice-toni",
        safe=12.0,
        balanced=15.0,
        aggressive=20.0,
        ceiling=None,
        source="heuristic",
    ),
    "practice-elon": PersonaMarkupProfile(
        persona_id="practice-elon",
        safe=10.0,
        balanced=12.0,
        aggressive=18.0,
        ceiling=None,
        source="heuristic",
    ),
    "practice-gordon": PersonaMarkupProfile(
        persona_id="practice-gordon",
        safe=0.0,
        balanced=5.0,
        aggressive=8.0,
        ceiling=None,
        source="inventory_limited",
        notes=["Walked even at 0% on mismatched/expensive inventory."],
    ),
    "unknown": PersonaMarkupProfile(
        persona_id="unknown",
        safe=8.0,
        balanced=12.0,
        aggressive=15.0,
        ceiling=None,
        source="default",
    ),
}


def _parse_profile_entry(key: str, value: dict) -> PersonaMarkupProfile:
    base = _DEFAULTS.get(key)
    if base is not None:
        payload = base.to_dict()
        payload.update(value)
    else:
        payload = dict(value)
    payload.setdefault("persona_id", key)
    payload.setdefault("source", "heuristic")
    payload.setdefault("notes", [])
    return PersonaMarkupProfile.from_dict(payload)


def load_profiles(path: str | Path | None = None) -> dict[str, PersonaMarkupProfile]:
    file_path = Path(path) if path else DEFAULT_PROFILES_PATH
    profiles = dict(_DEFAULTS)
    if file_path.exists():
        data = json.loads(file_path.read_text(encoding="utf-8"))
        raw = data.get("profiles") if isinstance(data.get("profiles"), dict) else data
        if isinstance(raw, dict):
            for key, value in raw.items():
                if isinstance(value, dict) and key != "profiles":
                    profiles[key] = _parse_profile_entry(key, value)
    return profiles


def save_profiles(
    profiles: dict[str, PersonaMarkupProfile],
    path: str | Path | None = None,
) -> None:
    file_path = Path(path) if path else DEFAULT_PROFILES_PATH
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "profiles": {key: profile.to_dict() for key, profile in profiles.items()},
    }
    file_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def get_profile(persona_id: str | None, profiles: dict[str, PersonaMarkupProfile] | None = None) -> PersonaMarkupProfile:
    table = profiles or load_profiles()
    if persona_id and persona_id in table:
        return table[persona_id]
    return table.get("unknown", _DEFAULTS["unknown"])


def aggressiveness_from_walk_risk(walk_risk: float) -> str:
    if walk_risk < 0.3:
        return "aggressive"
    if walk_risk < 0.7:
        return "balanced"
    return "safe"


def select_persona_markup(
    persona_id: str | None,
    walk_risk: float,
    *,
    profiles: dict[str, PersonaMarkupProfile] | None = None,
) -> float:
    """Select markup from persona profile based on walk risk. Never exceeds ceiling."""
    profile = get_profile(persona_id, profiles)
    level = aggressiveness_from_walk_risk(walk_risk)
    if level == "aggressive":
        markup = profile.aggressive
    elif level == "balanced":
        markup = profile.balanced
    else:
        markup = profile.safe
    if profile.ceiling is not None:
        markup = min(markup, profile.ceiling)
    return max(0.0, markup)
