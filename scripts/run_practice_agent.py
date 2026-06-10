#!/usr/bin/env python3
"""Phase 8A: multi-persona practice runner scaffold.

PRACTICE MODE ONLY. Never calls POST /match {}.
Routes known personas to implemented paths; others run discovery-only.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dealbreakers.api import DealRoomClient
from dealbreakers.config import load_settings
from dealbreakers.constants import PRACTICE_PERSONAS
from dealbreakers.logging import TranscriptRecorder
from dealbreakers.mcp import TourRadarClient, TravelSupermarketClient
from dealbreakers.models.match import MatchStartResponse
from dealbreakers.negotiation import NegotiationAction, fallback_reply, generate_reply
from dealbreakers.offers import (
    build_holiday_offer,
    build_tour_offer,
    pick_best_candidate,
    pick_best_tour_candidate,
)
from dealbreakers.state import BuyerState

ALLOWED_PERSONAS = frozenset(PRACTICE_PERSONAS)

BOB_MARKUP_PCT = 30.0
TONI_MARKUP_PCT = 12.0

BOB_DISCOVERY = (
    "I can absolutely find you that happy week in the sun. To pick the best fit: "
    "would you prefer Spain, Greece, or Portugal — and is a pool a must-have for you?"
)
TONI_DISCOVERY = (
    "A guided Spain tour sounds ideal. Would you prefer a relaxed cultural itinerary "
    "around 7-10 days, and are you more focused on comfort or keeping the price lean?"
)
GENERIC_DISCOVERY = (
    "To find the perfect trip for you: are you after a beach holiday, a guided tour, "
    "or a city break — and which destinations appeal most?"
)


def assert_practice_match(start: MatchStartResponse) -> None:
    if "PRACTICE" not in start.scenario.brief.upper():
        raise RuntimeError(
            "Safety stop: practice runner must never run an official match. "
            f"Scenario brief was: {start.scenario.brief!r}"
        )


def log_path_for(persona_id: str) -> str:
    return f"logs/practice_agent_{persona_id}.jsonl"


def run_holiday_path(client: DealRoomClient, recorder: TranscriptRecorder, match_id: str, buyer_text: str) -> int:
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
        recorder.record_error(match_id, RuntimeError("No offerable holiday candidates"))
        print("No offerable holiday candidates found.")
        return 1

    offer = build_holiday_offer(best, markup_pct=BOB_MARKUP_PCT)
    buyer_state = BuyerState(trip_type="holiday", destinations=["Spain"], must_haves=["pool"])
    text = generate_reply(
        NegotiationAction.OFFER,
        buyer_state,
        offer.to_api_dict(),
        buyer_text,
    ) or fallback_reply(NegotiationAction.OFFER, offer.to_api_dict())

    print(f"\nSeller: {text}")
    turn2 = client.send_turn(match_id, text, offer=offer)
    recorder.record_seller_message(match_id, text, offer=offer.to_api_dict(), round_number=2)
    recorder.record_turn_response(match_id, turn2)
    print(f"\nBuyer: {turn2.buyer.text}")
    print(f"Buyer action: {turn2.buyer.action.value}")
    if turn2.result:
        print(f"Closed: {turn2.result.closed}, rounds: {turn2.result.rounds}")
    return 0


def run_tour_path(client: DealRoomClient, recorder: TranscriptRecorder, match_id: str, buyer_text: str) -> int:
    candidates = TourRadarClient().search_tours(
        query="guided tour of Spain relaxed cultural",
        country="Spain",
        min_days=5,
        max_days=12,
        limit=10,
    )
    best = pick_best_tour_candidate(candidates, country="Spain", min_days=5, max_days=12)
    if best is None:
        recorder.record_error(match_id, RuntimeError("No offerable tour candidates"))
        print("No offerable tour candidates found.")
        return 1

    offer = build_tour_offer(best, markup_pct=TONI_MARKUP_PCT)
    buyer_state = BuyerState(trip_type="tour", destinations=["Spain"], must_haves=["guided tour"])
    text = generate_reply(
        NegotiationAction.OFFER,
        buyer_state,
        offer.to_api_dict(),
        buyer_text,
    ) or fallback_reply(NegotiationAction.OFFER, offer.to_api_dict())

    print(f"\nSeller: {text}")
    turn2 = client.send_turn(match_id, text, offer=offer)
    recorder.record_seller_message(match_id, text, offer=offer.to_api_dict(), round_number=2)
    recorder.record_turn_response(match_id, turn2)
    print(f"\nBuyer: {turn2.buyer.text}")
    print(f"Buyer action: {turn2.buyer.action.value}")
    if turn2.result:
        print(f"Closed: {turn2.result.closed}, rounds: {turn2.result.rounds}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Practice-only multi-persona runner scaffold.")
    parser.add_argument("--persona", required=True, choices=sorted(ALLOWED_PERSONAS))
    args = parser.parse_args()

    if args.persona not in ALLOWED_PERSONAS:
        print(f"Unknown persona: {args.persona}")
        return 1

    print("PRACTICE MODE ONLY — PRACTICE AGENT")
    print(f"Persona: {args.persona}\n")

    settings = load_settings()
    client = DealRoomClient(settings)
    recorder = TranscriptRecorder(path=log_path_for(args.persona))

    start = client.start_match(practice=True, persona_id=args.persona)
    if not isinstance(start, MatchStartResponse):
        print("Unexpected: match did not start.")
        return 1
    assert_practice_match(start)

    print(f"Match ID: {start.match_id}")
    print(f"Scenario: {start.scenario.name} — {start.scenario.brief}")
    print(f"\nBuyer: {start.buyer.text}")

    recorder.record_match_started(start, practice=True, persona_id=args.persona)
    recorder.record_buyer_message(
        start.match_id,
        start.buyer,
        scenario_name=start.scenario.name,
        persona_id=args.persona,
    )

    if args.persona == "practice-bob":
        discovery = BOB_DISCOVERY
    elif args.persona == "practice-toni":
        discovery = TONI_DISCOVERY
    else:
        discovery = GENERIC_DISCOVERY

    print(f"\nSeller: {discovery}")
    turn1 = client.send_turn(start.match_id, discovery)
    recorder.record_seller_message(start.match_id, discovery, round_number=1)
    recorder.record_turn_response(start.match_id, turn1)
    print(f"\nBuyer: {turn1.buyer.text}")

    if turn1.is_ended:
        print("Match ended after discovery.")
        print(f"\nTranscript saved to {log_path_for(args.persona)}")
        return 0

    if args.persona == "practice-bob":
        result = run_holiday_path(client, recorder, start.match_id, turn1.buyer.text)
    elif args.persona == "practice-toni":
        result = run_tour_path(client, recorder, start.match_id, turn1.buyer.text)
    else:
        print("\nDiscovery-only path for this persona (offer path not implemented yet).")
        result = 0

    print(f"\nTranscript saved to {log_path_for(args.persona)}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
