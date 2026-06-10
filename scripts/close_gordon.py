#!/usr/bin/env python3
"""Phase 8C: end-to-end close attempt against practice-gordon.

PRACTICE MODE ONLY. Hardwired to practice-gordon:
- start_match is always called with practice=True and personaId=practice-gordon
- no flag to change persona or practice mode
- safety guard halts if the assigned scenario is not marked as practice

Flow: one luxury refinement question, silent TravelSupermarket search,
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
from dealbreakers.offers import build_holiday_offer, pick_best_gordon_candidate

PERSONA_ID = "practice-gordon"  # hardcoded by design — never parameterised
LOG_PATH = "logs/close_gordon.jsonl"
MARKUP_PCT = 30.0

REFINEMENT_QUESTION = (
    "I can focus this properly: are you looking for a true five-star beach resort "
    "with a serious spa, and should I prioritise the best-reviewed option over "
    "the lowest price?"
)

SEARCH_MONTH = "7"
SEARCH_DURATION = 7
SEARCH_LIMIT = 10
DESTINATIONS = ("Spain", "Greece", "Portugal")
LUXURY_FACILITIES = ["spa", "close_to_beach", "pool"]


def assert_practice_match(start: MatchStartResponse) -> None:
    if "PRACTICE" not in start.scenario.brief.upper():
        raise RuntimeError(
            "Safety stop: close_gordon.py must never run an official match. "
            f"Scenario brief was: {start.scenario.brief!r}"
        )


def search_gordon_candidates(
    client: TravelSupermarketClient,
) -> tuple[list[HolidayCandidate], str]:
    """Try 5-star luxury beach/spa across Mediterranean destinations."""
    notes: list[str] = []
    all_candidates: list[HolidayCandidate] = []

    for destination in DESTINATIONS:
        candidates = client.search_holidays(
            destination=destination,
            month=SEARCH_MONTH,
            duration=SEARCH_DURATION,
            stars=5,
            facilities=LUXURY_FACILITIES,
            limit=SEARCH_LIMIT,
        )
        offerable = [candidate for candidate in candidates if candidate.is_offerable]
        notes.append(
            f"{destination} 5-star: {len(candidates)} results, {len(offerable)} offerable"
        )
        all_candidates.extend(candidates)
        if offerable:
            return all_candidates, "; ".join(notes)

    notes.append("no 5-star offerable — trying 4-star with strong reviews/amenities")
    for destination in DESTINATIONS:
        candidates = client.search_holidays(
            destination=destination,
            month=SEARCH_MONTH,
            duration=SEARCH_DURATION,
            stars=4,
            facilities=LUXURY_FACILITIES,
            limit=SEARCH_LIMIT,
        )
        strong = [
            candidate
            for candidate in candidates
            if candidate.is_offerable
            and (
                (candidate.review_score or 0) >= 9.0
                or len(set(candidate.amenities) & set(LUXURY_FACILITIES)) >= 2
            )
        ]
        notes.append(
            f"{destination} 4-star fallback: {len(candidates)} results, "
            f"{len(strong)} strong offerable"
        )
        all_candidates.extend(candidates)
        if strong:
            notes.append("warning: 4-star fallback may hurt Gordon satisfaction")
            return all_candidates, "; ".join(notes)

    return all_candidates, "; ".join(notes)


def offer_text(hotel_name: str, location: str | None, star_rating: float | None) -> str:
    stars = f"{int(star_rating)}-star " if star_rating else ""
    where = f" in {location}" if location else ""
    return (
        f"I've selected a {stars}beach resort{where} — {hotel_name} — with a serious "
        "spa, pool, and immediate beach access. Best-reviewed fit over cheapest price. "
        "Flights included; the figure below is your full package. "
        "Shall we lock this in?"
    )


def main() -> int:
    print("PRACTICE MODE ONLY — CLOSE GORDON")
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

    candidates, search_note = search_gordon_candidates(tsm)
    print(f"\nSearch: {search_note}")
    best = pick_best_gordon_candidate(candidates)
    if best is None:
        recorder.record_error(
            start.match_id,
            RuntimeError("No offerable candidates from TravelSupermarket"),
            context={"search_note": search_note, "candidates": len(candidates)},
        )
        print("No offerable candidates — aborting without an offer.")
        return 1

    offer = build_holiday_offer(best, markup_pct=MARKUP_PCT)
    text = offer_text(best.hotel_name or "a luxury beach resort", best.location, best.star_rating)

    print(f"\nSeller: {text}")
    print(
        f"Offering: {best.hotel_name} at £{best.price_total} cost, {MARKUP_PCT}% markup "
        f"({best.star_rating}-star, review {best.review_score})"
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
