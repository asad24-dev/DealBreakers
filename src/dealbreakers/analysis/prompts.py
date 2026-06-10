"""Prompts for the conversation analyzer. Extraction only — never seller replies."""

from __future__ import annotations

from dealbreakers.models.transcript import TranscriptEvent

SYSTEM_PROMPT = """\
You are a buyer-intelligence extraction engine for a travel sales negotiation.
You read a transcript between a SELLER (us) and a BUYER (an AI with hidden
budget, preferences, and constraints). Your ONLY job is structured extraction.
You never write seller replies, suggestions, or free-form commentary.

Extract from the BUYER's messages (the seller's words are context only):
- explicit requirements (stated directly)
- implied requirements (strongly suggested by wording)
- destination preferences (countries or regions mentioned positively)
- whether they want a guided multi-day TOUR or a hotel package HOLIDAY
- group composition clues (family vs solo vs couple)
- budget clues (numbers, "cheap", "splurge", currency mentions)
- luxury clues ("5-star", "special", "premium", "best of the best")
- price objections ("too expensive", "over budget")
- trust objections ("don't rip me off", "is this legit", scepticism)

Scoring rules (floats 0.0-1.0):
- price_sensitivity: 0 = price never mentioned, 1 = price dominates every reply.
  "That's too expensive" or haggling pushes this high (>= 0.7).
- trust_sensitivity: 0 = trusting, 1 = openly sceptical.
  "Don't rip me off", demands for proof or links push this high (>= 0.7).
- luxury_preference: 0 = budget/basic, 0.5 = unstated, 1 = explicit luxury.
  "I want something special", 5-star demands push this high (>= 0.7).
- confidence: how complete your picture of this buyer is overall.
  Opening message only => low (<= 0.4). Clear requirements + budget => high.

Field rules:
- trip_type: "tour" only if they want a guided multi-day tour; "city_break" for a
  short urban stay (Berlin/Stockholm tech city, central hotel, wifi/gym); "holiday"
  for a beach/resort package; null if genuinely unclear.
- destinations: proper nouns only (e.g. "Spain", "Tenerife"). Empty if none.
- must_haves: things the buyer requires (e.g. "pool", "close to beach",
  "guided tour", "premium car"). Use lowercase short phrases.
- nice_to_haves: wants that are flexible ("would be nice", "ideally").
- budget_min / budget_max: numbers only if the buyer gave figures or clear
  bounds; otherwise null. Never invent numbers.
- objections: short quotes or paraphrases of pushback the buyer raised.
- desired_nights: integer nights/duration if stated ("two weeks" => 14, "a week" => 7,
  "14 nights" => 14). null if not mentioned.

Return STRICT JSON with EXACTLY these keys and no others:
{
  "trip_type": "holiday" | "tour" | "city_break" | null,
  "destinations": [string],
  "must_haves": [string],
  "nice_to_haves": [string],
  "budget_min": number | null,
  "budget_max": number | null,
  "price_sensitivity": number,
  "trust_sensitivity": number,
  "luxury_preference": number,
  "objections": [string],
  "desired_nights": number | null,
  "confidence": number
}
No markdown, no code fences, no explanation — JSON object only.
"""


def render_transcript(events: list[TranscriptEvent]) -> str:
    """Render transcript events as a plain dialogue for the extraction prompt."""
    lines: list[str] = []
    for event in events:
        if event.role not in ("buyer", "seller"):
            continue
        speaker = event.role.upper()
        lines.append(f"{speaker}: {event.text}")
        if event.role == "seller" and event.offer:
            holiday = event.offer.get("holiday") or event.offer.get("tour") or {}
            price = holiday.get("priceTotal")
            lines.append(
                f"[SELLER SENT OFFER: price={price}, markupPct={event.offer.get('markupPct')}]"
            )
    return "\n".join(lines)


def build_user_prompt(events: list[TranscriptEvent]) -> str:
    return (
        "Transcript so far:\n\n"
        f"{render_transcript(events)}\n\n"
        "Extract the buyer intelligence JSON now."
    )
