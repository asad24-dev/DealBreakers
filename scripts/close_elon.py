#!/usr/bin/env python3
"""Phase 8C: end-to-end close attempt against practice-elon.

PRACTICE MODE ONLY. Hardwired to practice-elon:
- start_match is always called with practice=True and personaId=practice-elon
- no flag to change persona or practice mode
- safety guard halts if the assigned scenario is not marked as practice

Flow: one city-break refinement question, silent TravelSupermarket search,
one structured holiday offer. No fabricated inventory.
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
from dealbreakers.mcp.normalizers import HolidayCandidate
from dealbreakers.models.match import MatchStartResponse
from dealbreakers.offers import build_holiday_offer, pick_best_elon_candidate

PERSONA_ID = "practice-elon"  # hardcoded by design — never parameterised
LOG_PATH = "logs/close_elon.jsonl"
MARKUP_PCT = 15.0

REFINEMENT_QUESTION = (
    "Got it — for a sharp tech-friendly city break, would you rather do Berlin or "
    "Stockholm, and is a central 4-star hotel with strong WiFi and a proper gym "
    "the priority?"
)

SEARCH_MONTH = "7"
SEARCH_STARS = 4
SEARCH_FACILITIES = ["wifi", "gym"]
SEARCH_LIMIT = 10
DESTINATIONS = ("Berlin", "Stockholm")
DURATIONS = (3, 4, 7)


def assert_practice_match(start: MatchStartResponse) -> None:
    if "PRACTICE" not in start.scenario.brief.upper():
        raise RuntimeError(
            "Safety stop: close_elon.py must never run an official match. "
            f"Scenario brief was: {start.scenario.brief!r}"
        )


def search_elon_candidates(
    client: TravelSupermarketClient,
) -> tuple[list[HolidayCandidate], str]:
    """Try Berlin then Stockholm; shorter city-break durations first."""
    notes: list[str] = []
    all_candidates: list[HolidayCandidate] = []

    for destination in DESTINATIONS:
        for duration in DURATIONS:
            candidates = client.search_holidays(
                destination=destination,
                month=SEARCH_MONTH,
                duration=duration,
                stars=SEARCH_STARS,
                facilities=SEARCH_FACILITIES,
                limit=SEARCH_LIMIT,
            )
            offerable = [candidate for candidate in candidates if candidate.is_offerable]
            notes.append(
                f"{destination} {duration}n: {len(candidates)} results, "
                f"{len(offerable)} offerable"
            )
            all_candidates.extend(candidates)
            if offerable:
                return all_candidates, "; ".join(notes)

    if any("7n" in note for note in notes):
        notes.append("city-break durations unavailable — fell back to 7 nights")
    return all_candidates, "; ".join(notes)


def offer_text(hotel_name: str, location: str | None, nights: int | None) -> str:
    where = f" in {location}" if location else ""
    length = f"{nights}-night" if nights else "short"
    return (
        f"I've lined up a {length} city break at {hotel_name}{where} — central, "
        "4-star, with strong WiFi and a proper gym for your routine. "
        "Flights included; the price below is the full package. "
        "Does this work for you?"
    )


def main() -> int:
    print("PRACTICE MODE ONLY — CLOSE ELON")
    print(f"Persona: {PERSONA_ID} (hardcoded)\n")

    settings = load_settings()
    client = DealRoomClient(settings)
    recorder = TranscriptRecorder(path=LOG_PATH)
    tsm = TravelSupermarketClient()

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
        start.match_id,
        start.buyer,
        scenario_name=start.scenario.name,
        persona_id=PERSONA_ID,
    )

    print(f"\nSeller: {REFINEMENT_QUESTION}")
    turn1 = client.send_turn(start.match_id, REFINEMENT_QUESTION)
    recorder.record_seller_message(start.match_id, REFINEMENT_QUESTION, round_number=1)
    recorder.record_turn_response(start.match_id, turn1)
    print(f"\nBuyer: {turn1.buyer.text}")

    if turn1.is_ended:
        print("Match ended before an offer could be made.")
        return 0

    candidates, search_note = search_elon_candidates(tsm)
    print(f"\nSearch: {search_note}")
    best = pick_best_elon_candidate(candidates)
    if best is None:
        recorder.record_error(
            start.match_id,
            RuntimeError("No offerable candidates from TravelSupermarket"),
            context={"search_note": search_note, "candidates": len(candidates)},
        )
        print("No offerable candidates — aborting without an offer.")
        return 1

    offer = build_holiday_offer(best, markup_pct=MARKUP_PCT)
    text = offer_text(best.hotel_name or "a central 4-star hotel", best.location, best.nights)

    print(f"\nSeller: {text}")
    print(
        f"Offering: {best.hotel_name} at £{best.price_total} cost, {MARKUP_PCT}% markup "
        f"({best.location}, {best.nights} nights)"
    )
    turn2 = client.send_turn(start.match_id, text, offer=offer)
    recorder.record_seller_message(
        start.match_id,
        text,
        offer=offer.to_api_dict(),
        round_number=2,
    )
    recorder.record_turn_response(start.match_id, turn2)

    print(f"\nBuyer: {turn2.buyer.text}")
    print("\n--- Result ---")
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
