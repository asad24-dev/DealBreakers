#!/usr/bin/env python3
"""Phase 5C: first end-to-end close attempt against practice-toni.

PRACTICE MODE ONLY. This script is hardwired to practice-toni:
- start_match is always called with practice=True and personaId=practice-toni
- there is no flag to change persona or practice mode
- a safety guard halts if the assigned scenario is not marked as practice

Flow: one discovery/refinement question, one silent TourRadar search,
one structured tour offer. No "searching..." filler messages.
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
from dealbreakers.mcp import TourRadarClient
from dealbreakers.models.match import MatchStartResponse
from dealbreakers.negotiation import NegotiationAction, fallback_reply, generate_reply
from dealbreakers.offers import build_tour_offer, pick_best_tour_candidate
from dealbreakers.state import BuyerState

PERSONA_ID = "practice-toni"  # hardcoded by design — never parameterised
LOG_PATH = "logs/close_toni.jsonl"
MARKUP_PCT = 12.0

DISCOVERY_QUESTION = (
    "A guided Spain tour sounds ideal. Would you prefer a relaxed cultural itinerary "
    "around 7-10 days, and are you more focused on comfort or keeping the price lean?"
)

SEARCH_QUERY = "guided tour of Spain relaxed cultural"
SEARCH_COUNTRY = "Spain"
SEARCH_MIN_DAYS = 5
SEARCH_MAX_DAYS = 12
SEARCH_LIMIT = 10


def assert_practice_match(start: MatchStartResponse) -> None:
    if "PRACTICE" not in start.scenario.brief.upper():
        raise RuntimeError(
            "Safety stop: close_toni.py must never run an official match. "
            f"Scenario brief was: {start.scenario.brief!r}"
        )


def main() -> int:
    print("PRACTICE MODE ONLY — CLOSE TONI")
    print(f"Persona: {PERSONA_ID} (hardcoded)\n")

    settings = load_settings()
    client = DealRoomClient(settings)
    recorder = TranscriptRecorder(path=LOG_PATH)

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

    print(f"\nSeller: {DISCOVERY_QUESTION}")
    turn1 = client.send_turn(start.match_id, DISCOVERY_QUESTION)
    recorder.record_seller_message(start.match_id, DISCOVERY_QUESTION, round_number=1)
    recorder.record_turn_response(start.match_id, turn1)
    print(f"\nBuyer: {turn1.buyer.text}")

    if turn1.is_ended:
        print("Match ended before an offer could be made.")
        return 0

    candidates = TourRadarClient().search_tours(
        query=SEARCH_QUERY,
        country=SEARCH_COUNTRY,
        min_days=SEARCH_MIN_DAYS,
        max_days=SEARCH_MAX_DAYS,
        limit=SEARCH_LIMIT,
    )
    best = pick_best_tour_candidate(
        candidates,
        country=SEARCH_COUNTRY,
        min_days=SEARCH_MIN_DAYS,
        max_days=SEARCH_MAX_DAYS,
    )
    if best is None:
        recorder.record_error(
            start.match_id,
            RuntimeError("No offerable tour candidates from TourRadar"),
            context={"candidates": len(candidates)},
        )
        print("No offerable tour candidates found — aborting without an offer.")
        return 1

    offer = build_tour_offer(best, markup_pct=MARKUP_PCT)
    buyer_state = BuyerState(trip_type="tour", destinations=[SEARCH_COUNTRY], must_haves=["guided tour"])
    text = generate_reply(
        NegotiationAction.OFFER,
        buyer_state,
        offer.to_api_dict(),
        turn1.buyer.text,
    )
    if not text:
        text = fallback_reply(NegotiationAction.OFFER, offer.to_api_dict())

    print(f"\nSeller: {text}")
    print(
        f"Offering: {best.name} at £{best.price_total} cost, {MARKUP_PCT}% markup "
        f"({best.duration_days} days, {best.operator})"
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
    print(f"Selected tour: {best.name} ({best.region}, {best.country})")
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
