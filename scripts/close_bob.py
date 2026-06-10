#!/usr/bin/env python3
"""Phase 6A: first end-to-end close attempt against practice-bob.

PRACTICE MODE ONLY. This script is hardwired to practice-bob:
- start_match is always called with practice=True and personaId=practice-bob
- there is no flag to change persona or practice mode
- a safety guard halts if the assigned scenario is not marked as practice

Flow: one real discovery question, one silent TravelSupermarket search,
one structured offer. No "searching..." filler messages.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dealbreakers.api import DealRoomClient
from dealbreakers.config import load_settings
from dealbreakers.logging import TranscriptRecorder
from dealbreakers.mcp import TravelSupermarketClient
from dealbreakers.models.match import MatchStartResponse
from dealbreakers.offers import build_holiday_offer, pick_best_candidate

PERSONA_ID = "practice-bob"  # hardcoded by design — never parameterised
LOG_PATH = "logs/close_bob.jsonl"
MARKUP_PCT = 8.0

DISCOVERY_QUESTION = (
    "I can absolutely find you that happy week in the sun. To pick the best fit: "
    "would you prefer Spain, Greece, or Portugal — and is a pool a must-have for you?"
)


def assert_practice_match(start: MatchStartResponse) -> None:
    """Halt immediately if the assigned scenario is not marked as practice."""
    if "PRACTICE" not in start.scenario.brief.upper():
        raise RuntimeError(
            "Safety stop: close_bob.py must never run an official match. "
            f"Scenario brief was: {start.scenario.brief!r}"
        )


def offer_text(hotel_name: str, location: str | None, nights: int | None) -> str:
    where = f" in {location}" if location else ""
    length = f"{nights}-night" if nights else "week-long"
    return (
        f"I found you something lovely: a {length} stay at {hotel_name}{where} — "
        "sunny, right by the beach, with a great pool to float in. "
        "Flights included, and the price below is the full package. "
        "Shall we make it yours?"
    )


def main() -> int:
    print("PRACTICE MODE ONLY")
    print(f"Persona: {PERSONA_ID} (hardcoded)\n")

    settings = load_settings()
    client = DealRoomClient(settings)
    recorder = TranscriptRecorder(path=LOG_PATH)

    # --- Start practice match (the ONLY start_match call in this script) ---
    start = client.start_match(practice=True, persona_id=PERSONA_ID)
    if not isinstance(start, MatchStartResponse):
        print("Unexpected: match did not start.")
        return 1
    assert_practice_match(start)

    print(f"Match ID: {start.match_id}")
    print(f"Scenario: {start.scenario.name} — {start.scenario.brief}")
    print(f"\nBuyer: {start.buyer.text}")

    recorder.record_match_started(start, practice=True, persona_id=PERSONA_ID)
    recorder.record_buyer_message(
        start.match_id, start.buyer,
        scenario_name=start.scenario.name, persona_id=PERSONA_ID,
    )

    # --- Turn 1: discovery question ---
    print(f"\nSeller: {DISCOVERY_QUESTION}")
    turn1 = client.send_turn(start.match_id, DISCOVERY_QUESTION)
    recorder.record_seller_message(start.match_id, DISCOVERY_QUESTION, round_number=1)
    recorder.record_turn_response(start.match_id, turn1)
    print(f"\nBuyer: {turn1.buyer.text}")

    if turn1.is_ended:
        print("Match ended before an offer could be made.")
        return 0

    # --- Silent backend search (never narrated to the buyer) ---
    candidates = TravelSupermarketClient().search_holidays(
        destination="Spain",
        month="7",
        duration=7,
        stars=4,
        facilities=["pool", "close_to_beach"],
        limit=10,
    )
    best = pick_best_candidate(candidates)
    if best is None:
        recorder.record_error(
            start.match_id,
            RuntimeError("No offerable candidates from TravelSupermarket"),
            context={"candidates": len(candidates)},
        )
        print("No offerable candidates found — aborting without an offer.")
        return 1

    offer = build_holiday_offer(best, markup_pct=MARKUP_PCT)
    text = offer_text(best.hotel_name or "a great hotel", best.location, best.nights)

    # --- Turn 2: the structured offer ---
    print(f"\nSeller: {text}")
    print(f"Offering: {best.hotel_name} at £{best.price_total} cost, {MARKUP_PCT}% markup")
    turn2 = client.send_turn(start.match_id, text, offer=offer)
    recorder.record_seller_message(
        start.match_id, text, offer=offer.to_api_dict(), round_number=2
    )
    recorder.record_turn_response(start.match_id, turn2)

    # --- Outcome ---
    print(f"\nBuyer: {turn2.buyer.text}")
    print(f"\n--- Result ---")
    print(f"Selected hotel: {best.hotel_name} ({best.location}, {best.region})")
    print(f"Cost: £{best.price_total}")
    print(f"Markup: {MARKUP_PCT}%")
    if turn2.quote:
        print(
            f"Quote: cost={turn2.quote.cost}, markup={turn2.quote.markup_pct}%, "
            f"total={turn2.quote.total}"
        )
    print(f"Buyer action: {turn2.buyer.action.value}")
    if turn2.result:
        print(
            f"Match ended: closed={turn2.result.closed}, "
            f"reason={turn2.result.end_reason}, rounds={turn2.result.rounds}"
        )
    print(f"\nTranscript saved to {LOG_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
