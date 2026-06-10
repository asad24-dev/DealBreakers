"""OpenAI reply generator (Phase 7B): wording only, never business decisions.

The LLM writes natural language around facts we hand it. It may NOT invent
amenities, prices, URLs, destinations, or reviews — everything comes from
the selected offer. Invalid output falls back to a deterministic template,
so a bad generation can never waste a turn or corrupt an offer.
"""

from __future__ import annotations

import json
import os
from typing import Any

from dotenv import load_dotenv

from dealbreakers.models.offer import Offer
from dealbreakers.negotiation.actions import NegotiationAction
from dealbreakers.negotiation.strategist import NegotiationBrief
from dealbreakers.state.buyer_state import BuyerState

DEFAULT_MODEL = "gpt-4o-mini"
MAX_WORDS = 90

# Filler phrases that waste a turn — generated text containing any is rejected.
BANNED_PHRASES = (
    "i'm searching",
    "i am searching",
    "let me look",
    "give me a moment",
    "i'm checking",
    "i am checking",
)

_SYSTEM_PROMPT = """You write one short message from a travel seller to a buyer.

HARD RULES:
- Use ONLY the facts provided in the OFFER FACTS block. Never invent amenities, \
prices, URLs, destinations, hotel names, or review scores.
- Maximum 90 words.
- Never say you are searching, looking, or checking — every message must move \
the deal forward NOW.
- Match the requested intent (question, offer pitch, counter, or close).
- Respond with STRICT JSON: {"text": "..."} and nothing else.
"""

_ACTION_INTENT = {
    NegotiationAction.DISCOVER: (
        "Ask at most two crisp discovery questions to pin down trip type, "
        "destination, or must-haves. No price talk."
    ),
    NegotiationAction.REFINE: (
        "Ask one focused question to clarify the buyer's constraints "
        "(must-haves, dates, party size). No price talk."
    ),
    NegotiationAction.SEARCH: (
        "Ask one useful clarifying question while inventory is retrieved. "
        "Never mention searching or looking."
    ),
    NegotiationAction.OFFER: (
        "Pitch the offer warmly and concretely using only the offer facts, "
        "and ask for the booking."
    ),
    NegotiationAction.COUNTER: (
        "Acknowledge the price concern, present the improved price as a "
        "genuine concession, and ask for the booking."
    ),
    NegotiationAction.CLOSE: (
        "Confirm the deal enthusiastically and concisely. Reassure the buyer "
        "they chose well."
    ),
}


def _offer_facts(selected_offer: Offer | dict[str, Any] | None) -> dict[str, Any]:
    """Extract the only facts the model is allowed to mention."""
    if selected_offer is None:
        return {}
    data = selected_offer.to_api_dict() if isinstance(selected_offer, Offer) else dict(selected_offer)

    facts: dict[str, Any] = {}
    holiday = data.get("holiday")
    if isinstance(holiday, dict):
        facts.update({
            key: holiday[key]
            for key in (
                "hotelName", "location", "region", "country", "nights",
                "starRating", "reviewScore", "boardBasis", "amenities",
            )
            if holiday.get(key) is not None
        })
        cost = holiday.get("priceTotal")
        markup = data.get("markupPct")
        if isinstance(cost, (int, float)) and isinstance(markup, (int, float)):
            facts["quotedTotal"] = round(cost * (1 + markup / 100), 2)
    tour = data.get("tour")
    if isinstance(tour, dict):
        facts.update({
            key: tour[key]
            for key in ("name", "operator", "durationDays", "country", "region")
            if tour.get(key) is not None
        })
    return facts


def validate_reply(text: str) -> str | None:
    """Return a rejection reason, or None if the text is acceptable."""
    stripped = text.strip()
    if not stripped:
        return "empty reply"
    lowered = stripped.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lowered:
            return f"contains banned filler phrase: {phrase!r}"
    if len(stripped.split()) > MAX_WORDS:
        return f"exceeds {MAX_WORDS} words"
    return None


def fallback_reply(
    action: NegotiationAction,
    selected_offer: Offer | dict[str, Any] | None = None,
) -> str:
    """Deterministic template used when generation fails validation."""
    facts = _offer_facts(selected_offer)
    hotel = facts.get("hotelName", "a great option")
    location = facts.get("location") or facts.get("region") or facts.get("country")
    where = f" in {location}" if location else ""
    nights = facts.get("nights")
    length = f"{nights}-night" if nights else "week-long"

    if action is NegotiationAction.DISCOVER:
        return (
            "To find your perfect trip: are you after a beach holiday or a guided "
            "tour, and which destinations appeal to you most?"
        )
    if action is NegotiationAction.REFINE:
        return "What matters most for this trip — pool, beach access, board basis, or something else?"
    if action is NegotiationAction.SEARCH:
        return "One more thing to nail the perfect fit: any must-haves I should prioritise?"
    if action is NegotiationAction.COUNTER:
        return (
            f"I hear you on price — I've brought my fee down for you. The {length} stay "
            f"at {hotel}{where} is now the best value I can offer. Shall we book it?"
        )
    if action is NegotiationAction.CLOSE:
        return f"Wonderful choice — the {length} stay at {hotel}{where} is yours. You'll love it."
    # OFFER
    return (
        f"I found you something lovely: a {length} stay at {hotel}{where}. "
        "The price below is the full package. Shall we make it yours?"
    )


def generate_reply(
    action: NegotiationAction,
    buyer_state: BuyerState,
    selected_offer: Offer | dict[str, Any] | None,
    latest_buyer_message: str,
    *,
    strategist_brief: NegotiationBrief | None = None,
    client: Any | None = None,
    model: str | None = None,
    temperature: float = 0.7,
) -> str:
    """Generate buyer-facing wording via OpenAI; deterministic fallback on failure.

    OpenAI controls ONLY phrasing. Markup, inventory, and offer structure are
    decided before this call and passed in as immutable facts.
    """
    load_dotenv()
    model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
    if client is None:
        from openai import OpenAI

        client = OpenAI()

    payload: dict[str, Any] = {
        "intent": _ACTION_INTENT[action],
        "latest_buyer_message": latest_buyer_message,
        "buyer_must_haves": buyer_state.must_haves,
        "buyer_destinations": buyer_state.destinations,
        "offer_facts": _offer_facts(selected_offer),
    }
    if strategist_brief is not None:
        payload["strategist_brief"] = strategist_brief.to_dict()
    user_prompt = json.dumps(payload, ensure_ascii=False)

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        data = json.loads(raw)
        text = str(data.get("text", "")) if isinstance(data, dict) else ""
    except Exception:
        return fallback_reply(action, selected_offer)

    if validate_reply(text) is not None:
        return fallback_reply(action, selected_offer)
    return text
