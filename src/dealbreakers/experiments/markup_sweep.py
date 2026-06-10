"""Practice-only markup sweep experiment against practice-bob (Phase 6B)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from dealbreakers.api.client import DealRoomClient
from dealbreakers.logging.jsonl_logger import clear_log
from dealbreakers.logging.transcript_recorder import TranscriptRecorder
from dealbreakers.mcp.travelsupermarket import TravelSupermarketClient
from dealbreakers.models.match import MatchStartResponse
from dealbreakers.offers.selection import build_holiday_offer, pick_best_candidate

PERSONA_ID = "practice-bob"  # hardcoded by design — never parameterised

DEFAULT_MARKUPS: list[float] = [5, 8, 12, 15, 18, 20, 25, 30, 35, 40]

DISCOVERY_QUESTION = (
    "I can absolutely find you that happy week in the sun. To pick the best fit: "
    "would you prefer Spain, Greece, or Portugal — and is a pool a must-have for you?"
)

SEARCH_DESTINATION = "Spain"
SEARCH_MONTH = "7"  # July
SEARCH_DURATION = 7
SEARCH_STARS = 4
SEARCH_FACILITIES = ["pool", "close_to_beach"]
SEARCH_LIMIT = 10


def parse_markup_list(value: str) -> list[float]:
    """Parse a comma-separated markup list, e.g. '5,10,15,20'."""
    parts = [part.strip() for part in value.split(",") if part.strip()]
    if not parts:
        raise ValueError("Empty markup list")
    return [float(part) for part in parts]


def assert_practice_match(start: MatchStartResponse) -> None:
    """Halt immediately if the assigned scenario is not marked as practice."""
    if "PRACTICE" not in start.scenario.brief.upper():
        raise RuntimeError(
            "Safety stop: markup sweep must never run an official match. "
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


@dataclass
class MarkupSweepResult:
    persona_id: str
    markup_pct: float
    match_id: str
    hotel_name: str | None
    cost: float | None
    quote_total: float | None
    buyer_action: str | None
    closed: bool
    walked: bool
    rounds: int | None
    buyer_text: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_summary_rows(results: list[MarkupSweepResult]) -> list[dict[str, Any]]:
    """Build the summary JSON rows written to logs/markup_sweep_summary.json."""
    return [
        {
            "markup_pct": result.markup_pct,
            "closed": result.closed,
            "walked": result.walked,
            "buyer_action": result.buyer_action,
            "cost": result.cost,
            "quote_total": result.quote_total,
            "hotel_name": result.hotel_name,
            "rounds": result.rounds,
            "buyer_text": result.buyer_text,
            "error": result.error,
        }
        for result in results
    ]


def highest_accepted_markup(results: list[MarkupSweepResult]) -> float | None:
    """Return the highest markup percentage where the buyer accepted."""
    accepted = [result.markup_pct for result in results if result.closed and result.error is None]
    return max(accepted) if accepted else None


def first_rejected_or_walked_markup(results: list[MarkupSweepResult]) -> float | None:
    """Return the first markup (in run order) where the offer was not accepted."""
    for result in results:
        if result.error is not None:
            continue
        if result.walked or not result.closed:
            return result.markup_pct
    return None


def format_results_table(results: list[MarkupSweepResult]) -> str:
    """Compact table: markup | closed | walked | quote_total | hotel | buyer_action."""
    header = "markup | closed | walked | quote_total | hotel | buyer_action"
    lines = [header]
    for result in results:
        quote = f"{result.quote_total:.2f}" if result.quote_total is not None else "-"
        hotel = result.hotel_name or "-"
        action = result.buyer_action or ("ERROR" if result.error else "-")
        lines.append(
            f"{result.markup_pct:g} | {result.closed} | {result.walked} | "
            f"{quote} | {hotel} | {action}"
        )
    return "\n".join(lines)


def save_summary(results: list[MarkupSweepResult], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(build_summary_rows(results), handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def run_single_markup(
    markup_pct: float,
    *,
    client: DealRoomClient,
    tsm_client: TravelSupermarketClient,
    recorder: TranscriptRecorder,
    persona_id: str = PERSONA_ID,
) -> MarkupSweepResult:
    """Run one practice-bob match at a single markup percentage."""
    result = MarkupSweepResult(
        persona_id=persona_id,
        markup_pct=markup_pct,
        match_id="",
        hotel_name=None,
        cost=None,
        quote_total=None,
        buyer_action=None,
        closed=False,
        walked=False,
        rounds=None,
        buyer_text="",
    )

    try:
        start = client.start_match(practice=True, persona_id=persona_id)
        if not isinstance(start, MatchStartResponse):
            raise RuntimeError("Unexpected: match did not start")
        assert_practice_match(start)

        result.match_id = start.match_id
        recorder.record_match_started(start, practice=True, persona_id=persona_id)
        recorder.record_buyer_message(
            start.match_id,
            start.buyer,
            scenario_name=start.scenario.name,
            persona_id=persona_id,
        )

        turn1 = client.send_turn(start.match_id, DISCOVERY_QUESTION)
        recorder.record_seller_message(start.match_id, DISCOVERY_QUESTION, round_number=1)
        recorder.record_turn_response(start.match_id, turn1)

        if turn1.is_ended:
            result.buyer_text = turn1.buyer.text
            result.buyer_action = turn1.buyer.action.value
            result.walked = turn1.buyer_walked
            if turn1.result:
                result.closed = turn1.result.closed
                result.rounds = turn1.result.rounds
            return result

        candidates = tsm_client.search_holidays(
            destination=SEARCH_DESTINATION,
            month=SEARCH_MONTH,
            duration=SEARCH_DURATION,
            stars=SEARCH_STARS,
            facilities=SEARCH_FACILITIES,
            limit=SEARCH_LIMIT,
        )
        best = pick_best_candidate(candidates)
        if best is None:
            raise RuntimeError("No offerable candidates from TravelSupermarket")

        result.hotel_name = best.hotel_name
        result.cost = best.price_total

        offer = build_holiday_offer(best, markup_pct=markup_pct)
        text = offer_text(best.hotel_name or "a great hotel", best.location, best.nights)

        turn2 = client.send_turn(start.match_id, text, offer=offer)
        recorder.record_seller_message(
            start.match_id,
            text,
            offer=offer.to_api_dict(),
            round_number=2,
        )
        recorder.record_turn_response(start.match_id, turn2)

        result.buyer_text = turn2.buyer.text
        result.buyer_action = turn2.buyer.action.value
        result.walked = turn2.buyer_walked
        if turn2.quote:
            result.quote_total = turn2.quote.total
        if turn2.result:
            result.closed = turn2.result.closed
            result.rounds = turn2.result.rounds

        return result
    except Exception as exc:
        result.error = str(exc)
        recorder.record_error(
            result.match_id or None,
            exc,
            context={"markup_pct": markup_pct, "persona_id": persona_id},
        )
        return result


def run_markup_sweep(
    markups: list[float],
    *,
    client: DealRoomClient,
    tsm_client: TravelSupermarketClient,
    recorder: TranscriptRecorder,
    persona_id: str = PERSONA_ID,
) -> list[MarkupSweepResult]:
    """Run the full markup ladder. One failure does not stop the sweep."""
    results: list[MarkupSweepResult] = []
    for markup_pct in markups:
        results.append(
            run_single_markup(
                markup_pct,
                client=client,
                tsm_client=tsm_client,
                recorder=recorder,
                persona_id=persona_id,
            )
        )
    return results


def run_and_report(
    markups: list[float],
    *,
    transcript_path: str | Path = "logs/markup_sweep.jsonl",
    summary_path: str | Path = "logs/markup_sweep_summary.json",
    client: DealRoomClient | None = None,
    tsm_client: TravelSupermarketClient | None = None,
) -> list[MarkupSweepResult]:
    """Full sweep with log clearing, summary save, and console report."""
    from dealbreakers.config import load_settings

    clear_log(transcript_path)
    recorder = TranscriptRecorder(path=transcript_path)
    deal_client = client or DealRoomClient(load_settings())
    search_client = tsm_client or TravelSupermarketClient()

    results = run_markup_sweep(
        markups,
        client=deal_client,
        tsm_client=search_client,
        recorder=recorder,
        persona_id=PERSONA_ID,
    )
    save_summary(results, summary_path)
    return results
