"""Advisory negotiation strategist (Phase 7E) — wording hints only.

Does NOT choose markup, inventory, offers, or policy actions.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from dotenv import load_dotenv

from dealbreakers.negotiation.actions import NegotiationAction
from dealbreakers.state.buyer_state import BuyerState, detect_price_objection

DEFAULT_MODEL = "gpt-4o-mini"

_IMPATIENCE_PHRASES = (
    "stop asking",
    "show me",
    "concrete package",
    "right now",
    "enough questions",
    "stop stalling",
)

_OVERCHARGE_PHRASES = (
    "outrageous",
    "insult",
    "robbery",
    "rip me off",
    "absolutely obscene",
)


@dataclass
class NegotiationBrief:
    archetype: str = "general"
    persuasion_angles: list[str] = field(default_factory=list)
    likely_objections: list[str] = field(default_factory=list)
    tone_hint: str = "confident"
    impatience: float = 0.0
    close_signal: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "archetype": self.archetype,
            "persuasion_angles": list(self.persuasion_angles),
            "likely_objections": list(self.likely_objections),
            "tone_hint": self.tone_hint,
            "impatience": self.impatience,
            "close_signal": self.close_signal,
        }


def _fallback_brief(state: BuyerState, latest_message: str, action: NegotiationAction) -> NegotiationBrief:
    text = latest_message.lower()
    impatience = 0.8 if any(p in text for p in _IMPATIENCE_PHRASES) else 0.2
    angles: list[str] = []
    objections: list[str] = []
    archetype = "general"

    if state.luxury_preference >= 0.8:
        archetype = "luxury_impatient" if impatience >= 0.5 else "luxury"
        angles.extend(["exclusivity", "five-star quality", "world-class amenities"])
    elif state.price_sensitivity >= 0.7:
        archetype = "value_sensitive"
        angles.append("transparent value")
    elif state.trust_sensitivity >= 0.7:
        archetype = "trust_cautious"
        angles.append("honest sourcing")

    if detect_price_objection(latest_message):
        objections.append("price")
    if any(p in text for p in _OVERCHARGE_PHRASES):
        objections.append("feels_overcharged")
    if "car" in text or any("car" in mh for mh in state.must_haves):
        objections.append("car_requirement")
    if state.desired_nights and state.desired_nights >= 10:
        objections.append("duration")

    tone = "direct" if impatience >= 0.5 else "warm"
    close_signal = 0.6 if action is NegotiationAction.CLOSE else 0.1

    return NegotiationBrief(
        archetype=archetype,
        persuasion_angles=angles,
        likely_objections=objections,
        tone_hint=tone,
        impatience=impatience,
        close_signal=close_signal,
    )


class NegotiationStrategist:
    """Optional LLM advisory layer; deterministic fallback always available."""

    def __init__(self, client: Any | None = None, model: str | None = None) -> None:
        load_dotenv()
        self._model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        if client is None:
            from openai import OpenAI

            client = OpenAI()
        self._client = client

    def advise(
        self,
        state: BuyerState,
        latest_message: str,
        action: NegotiationAction,
    ) -> NegotiationBrief:
        fallback = _fallback_brief(state, latest_message, action)
        prompt = (
            "You advise a travel seller on persuasion ONLY. Return JSON with keys: "
            "archetype, persuasion_angles (list), likely_objections (list), "
            "tone_hint, impatience (0-1), close_signal (0-1). "
            "Do NOT recommend prices, markup, or inventory.\n"
            f"Buyer state: luxury={state.luxury_preference}, price_sens={state.price_sensitivity}, "
            f"must_haves={state.must_haves}, desired_nights={state.desired_nights}\n"
            f"Latest buyer message: {latest_message}\n"
            f"Planned seller action: {action.value}"
        )
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                temperature=0.0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": "Advisory strategist only. JSON output."},
                    {"role": "user", "content": prompt},
                ],
            )
            raw = response.choices[0].message.content or "{}"
            data = json.loads(raw)
            if not isinstance(data, dict):
                return fallback
            return NegotiationBrief(
                archetype=str(data.get("archetype") or fallback.archetype),
                persuasion_angles=_str_list(data.get("persuasion_angles")) or fallback.persuasion_angles,
                likely_objections=_str_list(data.get("likely_objections")) or fallback.likely_objections,
                tone_hint=str(data.get("tone_hint") or fallback.tone_hint),
                impatience=_clamp01(data.get("impatience"), fallback.impatience),
                close_signal=_clamp01(data.get("close_signal"), fallback.close_signal),
            )
        except Exception:
            return fallback


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _clamp01(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def feels_overcharged(message: str) -> bool:
    lowered = message.lower()
    return any(phrase in lowered for phrase in _OVERCHARGE_PHRASES)
