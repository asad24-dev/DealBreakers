"""Persona-specific configuration (Phase 8G)."""

from dealbreakers.personas.markup_profiles import (
    PersonaMarkupProfile,
    get_profile,
    load_profiles,
    save_profiles,
    select_persona_markup,
)

__all__ = [
    "PersonaMarkupProfile",
    "get_profile",
    "load_profiles",
    "save_profiles",
    "select_persona_markup",
]
