#!/usr/bin/env python3
"""Phase 8C: end-to-end close attempt against practice-cris.

PRACTICE MODE ONLY. Hardwired to practice-cris:
- start_match is always called with practice=True and personaId=practice-cris
- no flag to change persona or practice mode
- safety guard halts if the assigned scenario is not marked as practice

Flow: one confirmation (not a question), silent TravelSupermarket search,
one structured holiday offer. Car included only if a real car wrapper exists.
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
from dealbreakers.offers import build_holiday_offer, pick_best_cris_candidate

PERSONA_ID = "practice-cris"  # hardcoded by design — never parameterised
LOG_PATH = "logs/close_cris.jsonl"
MARKUP_PCT = 30.0

CONFIRMATION_MESSAGE = (
    "Understood — I'll keep this premium and concrete: five-star, beachfront, spa, "
    "gym, and a stylish base in either the Algarve or Amalfi Coast."
)

SEARCH_MONTH = "7"
SEARCH_DURATION = 7
SEARCH_LIMIT = 10
DESTINATIONS = ("Algarve", "Amalfi Coast", "Portugal", "Italy")

SEARCH_ATTEMPTS: list[dict] = [
    {"stars": 5, "facilities": ["spa", "gym", "close_to_beach", "sun_terrace"]},
    {"stars": 5, "facilities": ["spa", "gym", "close_to_beach"]},
    {"stars": 4, "facilities": ["spa", "gym", "close_to_beach"]},
]


def assert_practice_match(start: MatchStartResponse) -> None:
    if "PRACTICE" not in start.scenario.brief.upper():
        raise RuntimeError(
            "Safety stop: close_cris.py must never run an official match. "
            f"Scenario brief was: {start.scenario.brief!r}"
        )


def car_wrapper_available() -> bool:
    """No car MCP wrapper is implemented yet — holiday-only for now."""
    return False


def search_cris_candidates(
    client: TravelSupermarketClient,
) -> tuple[list[HolidayCandidate], str]:
    """Progressive relaxation: full luxury filters, then drop sun_terrace, then 4-star."""
    notes: list[str] = []
    all_candidates: list[HolidayCandidate] = []

    for attempt in SEARCH_ATTEMPTS:
        stars = attempt["stars"]
        facilities = attempt["facilities"]
        for destination in DESTINATIONS:
            candidates = client.search_holidays(
                destination=destination,
                month=SEARCH_MONTH,
                duration=SEARCH_DURATION,
                stars=stars,
                facilities=facilities,
                limit=SEARCH_LIMIT,
            )
            offerable = [candidate for candidate in candidates if candidate.is_offerable]
            notes.append(
                f"{destination} {stars}-star {','.join(facilities)}: "
                f"{len(candidates)} results, {len(offerable)} offerable"
            )
            all_candidates.extend(candidates)
            if offerable:
                if stars < 5:
                    notes.append("warning: 4-star fallback used for impatient luxury buyer")
                return all_candidates, "; ".join(notes)

    return all_candidates, "; ".join(notes)


def offer_text(hotel_name: str, location: str | None) -> str:
    where = f" in {location}" if location else ""
    return (
        f"Here is a concrete premium package{where}: {hotel_name} — five-star beachfront "
        "with spa, gym, and sun terrace. Flights included; price below is the full "
        "holiday package. Ready to proceed?"
    )


def main() -> int:
    print("PRACTICE MODE ONLY — CLOSE CRIS")
    print(f"Persona: {PERSONA_ID} (hardcoded)\n")

    if not car_wrapper_available():
        print("Note: car wrapper unavailable — holiday-only offer (car missing).\n")

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

    print(f"\nSeller: {CONFIRMATION_MESSAGE}")
    turn1 = client.send_turn(start.match_id, CONFIRMATION_MESSAGE)
    recorder.record_seller_message(start.match_id, CONFIRMATION_MESSAGE, round_number=1)
    recorder.record_turn_response(start.match_id, turn1)
    print(f"\nBuyer: {turn1.buyer.text}")

    if turn1.is_ended:
        print("Match ended before an offer could be made.")
        return 0

    candidates, search_note = search_cris_candidates(tsm)
    print(f"\nSearch: {search_note}")
    best = pick_best_cris_candidate(candidates)
    if best is None:
        recorder.record_error(
            start.match_id,
            RuntimeError("No offerable candidates from TravelSupermarket"),
            context={"search_note": search_note, "candidates": len(candidates)},
        )
        print("No offerable candidates — aborting without an offer.")
        return 1

    offer = build_holiday_offer(best, markup_pct=MARKUP_PCT)
    if not car_wrapper_available():
        recorder.record_error(
            start.match_id,
            RuntimeError("car missing"),
            context={"note": "No car wrapper — holiday-only offer sent"},
        )

    text = offer_text(best.hotel_name or "a premium beachfront resort", best.location)

    print(f"\nSeller: {text}")
    print(
        f"Offering: {best.hotel_name} at £{best.price_total} cost, {MARKUP_PCT}% markup "
        f"({best.location}, {best.star_rating}-star)"
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
