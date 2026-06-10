"""Autonomous policy-driven negotiation loop (Phase 7C).

Single seller agent: analyze → update state → decide → execute → send turn.
No hardcoded persona routing — all decisions flow from BuyerState + policy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from dealbreakers.analysis.analyzer import ConversationAnalyzer
from dealbreakers.analysis.models import ConversationAnalysis
from dealbreakers.api.client import DealRoomClient
from dealbreakers.constants import MAX_ROUNDS
from dealbreakers.logging.jsonl_logger import append_run_log
from dealbreakers.logging.transcript_recorder import TranscriptRecorder
from dealbreakers.mcp.car_normalizers import CarCandidate
from dealbreakers.mcp.cars import CarSearchClient
from dealbreakers.mcp.client import MCPError
from dealbreakers.mcp.city_break import (
    CityBreakCandidate,
    CityBreakSearchClient,
    needs_city_break_path,
    normalize_trip_type,
    pick_city_break_city,
    search_city_breaks_for_state,
)
from dealbreakers.mcp.normalizers import HolidayCandidate
from dealbreakers.mcp.tour_normalizers import TourCandidate
from dealbreakers.mcp.tourradar import TourRadarClient
from dealbreakers.mcp.travelsupermarket import TravelSupermarketClient
from dealbreakers.models.match import MatchStartResponse, TurnResponse
from dealbreakers.models.offer import Offer
from dealbreakers.models.transcript import TranscriptEvent
from dealbreakers.negotiation.actions import NegotiationAction
from dealbreakers.negotiation.policy import PolicyDecision, decide_action, estimate_walk_risk
from dealbreakers.negotiation.pricing import (
    Aggressiveness,
    cap_city_break_opening_markup,
    cap_luxury_opening_markup,
    estimate_markup,
    estimate_markup_for_persona,
    generate_total_based_counter_markup,
    should_use_total_based_counter,
)
from dealbreakers.negotiation.responder import fallback_reply, generate_reply
from dealbreakers.negotiation.strategist import NegotiationBrief, NegotiationStrategist, feels_overcharged
from dealbreakers.offers.selection import (
    amenities_from_must_haves,
    build_city_break_offer,
    build_holiday_offer,
    build_holiday_with_car_offer,
    build_tour_offer,
    find_cheaper_equivalent_holiday,
    infer_star_rating,
    is_city_break_state,
    pick_best_car_candidate,
    pick_best_holiday_for_duration,
    pick_best_holiday_for_state,
    pick_best_tour_for_state,
    score_holiday_for_state,
)
from dealbreakers.state.buyer_state import (
    BuyerState,
    detect_price_objection,
    detect_shorter_stay_acceptance,
    detect_shorter_stay_rejection,
)

CAR_PHRASES = (
    "rental car",
    "premium car",
    "luxury car",
    "hire car",
    "hire a car",
    "rent a car",
    "car hire",
    "car included",
    "premium rental",
    "premium rental car",
    "chauffeur",
    " suv",
    "vehicle",
    "driver",
)

IMPATIENCE_PHRASES = (
    "stop asking",
    "show me",
    "concrete package",
    "right now",
    "enough questions",
    "what you've actually got",
    "stop stalling",
    "stop gathering",
)

BANNED_QUESTION_PHRASES = (
    "anything else",
    "what do you think",
)

MAX_PRICE_COUNTERS_PER_MATCH = 2
MAX_PIVOTS_PER_MATCH = 2
DEFAULT_CAR_PICKUP = "2026-07-10"
DEFAULT_CAR_DROPOFF = "2026-07-17"

_DEPARTURE_PHRASES = (
    "already gone",
    "walks toward the door",
    "out the door",
    "we are done",
    "we're done",
    "we're finished",
    "nothing more to discuss",
    "goodbye",
    "walking away",
    "i'm walking away",
    "i'm done here",
)

_VAGUE_CAR_LOCATIONS = frozenset({
    "mediterranean",
    "maldives",
    "middle east",
    "europe",
    "asia",
    "caribbean",
    "worldwide",
    "anywhere",
})


@dataclass
class InventoryState:
    holiday_candidates: list[HolidayCandidate] = field(default_factory=list)
    tour_candidates: list[TourCandidate] = field(default_factory=list)
    car_candidates: list[CarCandidate] = field(default_factory=list)
    selected_holiday: HolidayCandidate | None = None
    selected_tour: TourCandidate | None = None
    selected_car: CarCandidate | None = None
    last_offer: Offer | None = None
    search_note: str = ""
    car_search_note: str = ""
    car_search_location: str = ""

    @property
    def has_offerable(self) -> bool:
        return bool(self.holiday_candidates or self.tour_candidates)

    def selected_summary(self) -> dict[str, Any] | None:
        if self.selected_holiday is not None:
            summary: dict[str, Any] = {
                "type": "holiday",
                "hotel_name": self.selected_holiday.hotel_name,
                "location": self.selected_holiday.location,
                "cost": self.selected_holiday.price_total,
                "url": self.selected_holiday.url,
            }
            if self.selected_car is not None:
                summary["car"] = {
                    "vehicle_name": self.selected_car.vehicle_name,
                    "cost": self.selected_car.price_total,
                    "url": self.selected_car.url,
                }
            return summary
        if self.selected_tour is not None:
            return {
                "type": "tour",
                "name": self.selected_tour.name,
                "country": self.selected_tour.country,
                "cost": self.selected_tour.price_total,
                "url": self.selected_tour.url,
            }
        return None


@dataclass
class AgentSessionState:
    price_counter_count: int = 0
    discover_refine_count: int = 0
    car_unresolved_notified: bool = False
    unresolved_requirements: list[str] = field(default_factory=list)
    best_and_final_sent: bool = False
    duration_mismatch: bool = False
    shorter_stay_permission_asked: bool = False
    shorter_stay_accepted: bool | None = None
    city_fallback_offered: bool = False
    pivot_count: int = 0
    pivoted_this_turn: bool = False


@dataclass
class MatchOutcome:
    match_id: str
    persona_id: str
    closed: bool
    walked: bool
    rounds: int | None
    end_reason: str | None
    seller_rounds: int


@dataclass
class ExecuteResult:
    text: str
    offer: Offer | None = None
    markup: float | None = None
    walk_risk: float | None = None


def car_wrapper_available() -> bool:
    return True


def wants_car(state: BuyerState, message: str) -> bool:
    text = " ".join([*state.must_haves, *state.objections, message]).lower()
    return any(phrase in text for phrase in CAR_PHRASES) or (
        " car" in f" {text}" and "scar" not in text
    )


def wants_premium_car(state: BuyerState, message: str) -> bool:
    text = " ".join([*state.must_haves, message]).lower()
    return any(word in text for word in ("premium", "luxury", "suv", "chauffeur", "executive"))


def is_impatient(message: str, state: BuyerState) -> bool:
    text = " ".join([message, *state.objections]).lower()
    return any(phrase in text for phrase in IMPATIENCE_PHRASES)


def _is_specific_car_location(location: str) -> bool:
    cleaned = location.strip()
    if not cleaned:
        return False
    lowered = cleaned.lower()
    if lowered in _VAGUE_CAR_LOCATIONS:
        return False
    return not any(vague in lowered for vague in _VAGUE_CAR_LOCATIONS)


def conversation_is_dead(buyer_messages: list[str]) -> bool:
    if len(buyer_messages) < 2:
        return False
    recent = [message.lower() for message in buyer_messages[-2:]]
    return all(any(phrase in message for phrase in _DEPARTURE_PHRASES) for message in recent)


def holiday_duration_plan(state: BuyerState) -> tuple[int, ...]:
    city_break = is_city_break_state(state)
    desired = state.desired_nights
    if desired:
        order: list[int] = []
        for duration in (desired, 10, 7):
            if 1 <= duration <= 21 and duration not in order:
                order.append(duration)
        return tuple(order)
    return (3, 4, 7) if city_break else (7,)


def car_pickup_location(state: BuyerState, holiday: HolidayCandidate | None) -> str:
    if holiday:
        for field in (holiday.location, holiday.region):
            if field and _is_specific_car_location(field):
                return field.strip()
    for destination in state.destinations:
        if destination and _is_specific_car_location(destination):
            return destination.strip()
    if holiday and holiday.location:
        return holiday.location.strip()
    if holiday and holiday.region:
        return holiday.region.strip()
    if state.destinations:
        return state.destinations[0].strip()
    return "Faro"


def assert_practice_match(start: MatchStartResponse) -> None:
    if "PRACTICE" not in start.scenario.brief.upper():
        raise RuntimeError(
            "Safety stop: autonomous agent must never run an official match. "
            f"Scenario brief was: {start.scenario.brief!r}"
        )


def markup_profile_from_walk_risk(walk_risk: float) -> Aggressiveness:
    if walk_risk > 0.7:
        return Aggressiveness.SAFE
    if walk_risk < 0.3:
        return Aggressiveness.AGGRESSIVE
    return Aggressiveness.BALANCED


def _sanitize_reply(text: str, action: NegotiationAction, offer: Offer | None) -> str:
    lowered = text.lower()
    if any(phrase in lowered for phrase in BANNED_QUESTION_PHRASES):
        return fallback_reply(action, offer)
    return text


def apply_impatience_override(
    decision: PolicyDecision,
    *,
    latest_message: str,
    state: BuyerState,
    inventory_ready: bool,
    session: AgentSessionState,
) -> PolicyDecision:
    if not is_impatient(latest_message, state):
        return decision
    if decision.action not in (NegotiationAction.DISCOVER, NegotiationAction.REFINE):
        return decision
    if inventory_ready:
        return PolicyDecision(
            action=NegotiationAction.OFFER,
            confidence=0.85,
            reasoning="Buyer is impatient; skip further discovery and present the package.",
            target_markup=None,
        )
    return PolicyDecision(
        action=NegotiationAction.SEARCH,
        confidence=0.85,
        reasoning="Buyer is impatient; search inventory now instead of more questions.",
        target_markup=None,
    )


def _has_exact_duration_inventory(
    inventory: InventoryState,
    desired_nights: int | None,
) -> bool:
    if desired_nights is None:
        return True
    return any(
        candidate.is_offerable and candidate.nights == desired_nights
        for candidate in inventory.holiday_candidates
    )


def _has_shorter_duration_inventory(
    inventory: InventoryState,
    desired_nights: int | None,
) -> bool:
    if desired_nights is None:
        return False
    return any(
        candidate.is_offerable
        and candidate.nights is not None
        and candidate.nights < desired_nights
        for candidate in inventory.holiday_candidates
    )


def apply_policy_overrides(
    decision: PolicyDecision,
    state: BuyerState,
    latest_message: str,
    *,
    session: AgentSessionState,
    inventory_ready: bool,
    inventory: InventoryState | None = None,
) -> PolicyDecision:
    decision = apply_impatience_override(
        decision,
        latest_message=latest_message,
        state=state,
        inventory_ready=inventory_ready,
        session=session,
    )

    if detect_shorter_stay_acceptance(latest_message):
        session.shorter_stay_accepted = True
    if detect_shorter_stay_rejection(latest_message):
        session.shorter_stay_accepted = False

    if inventory is not None and state.desired_nights is not None and inventory_ready:
        exact = _has_exact_duration_inventory(inventory, state.desired_nights)
        shorter = _has_shorter_duration_inventory(inventory, state.desired_nights)
        if not exact and shorter:
            if session.shorter_stay_accepted is False:
                if decision.action is NegotiationAction.OFFER:
                    return PolicyDecision(
                        action=NegotiationAction.REFINE,
                        confidence=0.8,
                        reasoning="Buyer rejected shorter stay; do not offer mismatched duration.",
                    )
            elif session.shorter_stay_accepted is not True:
                if not session.shorter_stay_permission_asked:
                    session.shorter_stay_permission_asked = True
                    return PolicyDecision(
                        action=NegotiationAction.REFINE,
                        confidence=0.85,
                        reasoning=(
                            "Desired duration unavailable; ask permission for shorter luxury stay."
                        ),
                    )
                if decision.action is NegotiationAction.OFFER:
                    return PolicyDecision(
                        action=NegotiationAction.REFINE,
                        confidence=0.8,
                        reasoning="Await buyer permission before offering shorter package.",
                    )

    if (
        is_city_break_state(state)
        and inventory is not None
        and inventory_ready
        and not inventory.holiday_candidates
        and not session.city_fallback_offered
        and pick_city_break_city(state) is not None
    ):
        session.city_fallback_offered = True
        return PolicyDecision(
            action=NegotiationAction.REFINE,
            confidence=0.75,
            reasoning="No city-break inventory; ask once about alternate tech-friendly city.",
        )

    if (
        session.discover_refine_count >= 1
        and is_impatient(latest_message, state)
        and decision.action in (NegotiationAction.DISCOVER, NegotiationAction.REFINE)
    ):
        if inventory_ready:
            return PolicyDecision(
                action=NegotiationAction.OFFER,
                confidence=0.9,
                reasoning="Max discovery/refine for impatient buyer; offer now.",
            )
        return PolicyDecision(
            action=NegotiationAction.SEARCH,
            confidence=0.9,
            reasoning="Max discovery/refine for impatient buyer; search now.",
        )

    if "car" in session.unresolved_requirements and wants_car(state, latest_message):
        if not detect_price_objection(latest_message):
            if session.car_unresolved_notified:
                return PolicyDecision(
                    action=NegotiationAction.REFINE,
                    confidence=0.8,
                    reasoning="Car still unavailable; explain once without re-offering.",
                )
            if is_impatient(latest_message, state) and inventory_ready:
                return PolicyDecision(
                    action=NegotiationAction.OFFER,
                    confidence=0.85,
                    reasoning="Impatient buyer needs a concrete package now.",
                )
            return PolicyDecision(
                action=NegotiationAction.REFINE,
                confidence=0.7,
                reasoning="Car requirement unresolved; explain holiday package availability.",
            )

    if state.last_offer_total is None:
        return decision

    if session.price_counter_count >= MAX_PRICE_COUNTERS_PER_MATCH and detect_price_objection(
        latest_message
    ):
        return PolicyDecision(
            action=NegotiationAction.OFFER,
            confidence=0.9,
            reasoning="Max price counters reached; best-and-final offer with low markup.",
            target_markup=8.0,
        )

    if decision.action in (NegotiationAction.COUNTER, NegotiationAction.CLOSE):
        return decision

    if detect_price_objection(latest_message) and decision.action not in (
        NegotiationAction.COUNTER,
        NegotiationAction.CLOSE,
    ):
        from dealbreakers.negotiation.pricing import (
            generate_counter_markup,
            generate_luxury_counter_markup,
            should_use_luxury_counter,
        )

        current = state.last_markup_pct or estimate_markup(state, Aggressiveness.BALANCED)
        if should_use_total_based_counter(state):
            target = generate_total_based_counter_markup(
                current,
                state.last_offer_cost or 0.0,
                state.last_offer_total or 0.0,
                feels_overcharged=feels_overcharged(latest_message),
            )
            reasoning = "Luxury buyer price objection; total-based concession."
        elif should_use_luxury_counter(state):
            target = generate_luxury_counter_markup(current, state)
            reasoning = "Luxury buyer price objection; aggressive concession."
        else:
            target = generate_counter_markup(current, state)
            reasoning = "Buyer raised a price concern after our offer; concede one rung."
        return PolicyDecision(
            action=NegotiationAction.COUNTER,
            confidence=0.85,
            reasoning=reasoning,
            target_markup=target,
        )
    return decision


def search_holidays(state: BuyerState, client: TravelSupermarketClient) -> InventoryState:
    inventory = InventoryState()
    destinations = list(state.destinations) or ["Spain", "Greece", "Portugal"]
    amenities = amenities_from_must_haves(state.must_haves)
    stars = infer_star_rating(state)
    city_break = is_city_break_state(state)
    durations = holiday_duration_plan(state)
    notes: list[str] = []

    for destination in destinations[:4]:
        for duration in durations:
            try:
                candidates = client.search_holidays(
                    destination=destination,
                    month="7",
                    duration=duration,
                    stars=stars,
                    facilities=amenities or None,
                    limit=10,
                )
            except MCPError as exc:
                notes.append(f"{destination} {duration}n: error — {exc}")
                continue
            offerable = [candidate for candidate in candidates if candidate.is_offerable]
            notes.append(
                f"{destination} {duration}n: {len(candidates)} results, {len(offerable)} offerable"
            )
            inventory.holiday_candidates.extend(candidates)

    if inventory.holiday_candidates:
        inventory.search_note = "; ".join(notes)
        return inventory

    if city_break and durations != (7,):
        notes.append("city-break durations unavailable — tried 3/4/7 nights")
    inventory.search_note = "; ".join(notes) if notes else "no holiday search results"
    return inventory


def search_tours(state: BuyerState, client: TourRadarClient) -> InventoryState:
    inventory = InventoryState()
    country = state.destinations[0] if state.destinations else "Spain"
    query_parts = ["guided tour", country, *state.must_haves[:2]]
    query = " ".join(part for part in query_parts if part)

    candidates = client.search_tours(
        query=query,
        country=country,
        min_days=5,
        max_days=14,
        limit=10,
    )
    offerable = [candidate for candidate in candidates if candidate.is_offerable]
    inventory.tour_candidates = candidates
    inventory.search_note = (
        f"tour search {country!r}: {len(candidates)} results, {len(offerable)} offerable"
    )
    return inventory


def city_break_to_holiday_candidate(candidate: CityBreakCandidate) -> HolidayCandidate:
    holiday = candidate.to_holiday()
    return HolidayCandidate(
        hotel_name=holiday.hotel_name,
        url=holiday.url,
        star_rating=holiday.star_rating,
        review_score=holiday.review_score,
        board_basis=holiday.board_basis,
        nights=holiday.nights,
        location=holiday.location,
        region=holiday.region,
        country=holiday.country,
        amenities=list(holiday.amenities),
        price_total=holiday.price_total,
        raw=candidate.raw,
    )


def search_city_breaks(
    state: BuyerState,
    client: CityBreakSearchClient,
) -> InventoryState:
    inventory = InventoryState()
    candidates, note = search_city_breaks_for_state(state, client)
    inventory.holiday_candidates = [
        city_break_to_holiday_candidate(candidate) for candidate in candidates
    ]
    inventory.search_note = note
    if client.last_errors:
        inventory.search_note += "; errors: " + "; ".join(client.last_errors)
    return inventory


def run_inventory_search(
    state: BuyerState,
    *,
    tsm: TravelSupermarketClient,
    tourradar: TourRadarClient,
    city_break: CityBreakSearchClient | None = None,
) -> InventoryState:
    trip_type = normalize_trip_type(state.trip_type) or state.trip_type or "holiday"
    if trip_type == "tour":
        return search_tours(state, tourradar)
    if needs_city_break_path(state.destinations, trip_type) or is_city_break_state(state):
        return search_city_breaks(state, city_break or CityBreakSearchClient())
    return search_holidays(state, tsm)


def pick_cheapest_holiday(candidates: list[HolidayCandidate]) -> HolidayCandidate | None:
    offerable = [candidate for candidate in candidates if candidate.is_offerable]
    if not offerable:
        return None
    return min(offerable, key=lambda candidate: candidate.price_total or float("inf"))


def find_cheaper_holiday_alternative(
    inventory: InventoryState,
    state: BuyerState,
) -> HolidayCandidate | None:
    current = inventory.selected_holiday
    if current is None or current.price_total is None:
        return None
    if state.luxury_preference >= 0.7:
        equivalent = find_cheaper_equivalent_holiday(
            inventory.holiday_candidates, current, state
        )
        if equivalent is not None:
            return equivalent
    target_cost = current.price_total * 0.8
    viable = [
        candidate
        for candidate in inventory.holiday_candidates
        if candidate.is_offerable
        and candidate.url != current.url
        and candidate.price_total is not None
        and candidate.price_total <= target_cost
        and score_holiday_for_state(candidate, state) > float("-inf")
    ]
    if not viable:
        return None
    return max(viable, key=lambda candidate: score_holiday_for_state(candidate, state))


def check_duration_mismatch(
    holiday: HolidayCandidate | None,
    state: BuyerState,
    session: AgentSessionState,
) -> None:
    if holiday is None or state.desired_nights is None or holiday.nights is None:
        return
    session.duration_mismatch = holiday.nights != state.desired_nights


def search_cars_for_state(
    state: BuyerState,
    inventory: InventoryState,
    *,
    car_client: CarSearchClient,
    latest_message: str,
) -> None:
    holiday = inventory.selected_holiday or pick_best_holiday_for_state(
        inventory.holiday_candidates, state
    )
    location = car_pickup_location(state, holiday)
    premium = wants_premium_car(state, latest_message)
    offerable_count = sum(1 for candidate in inventory.car_candidates if candidate.is_offerable)
    should_search = (
        location != inventory.car_search_location
        or not inventory.car_candidates
        or offerable_count == 0
    )
    if not should_search:
        return
    candidates = car_client.search_cars(
        location,
        DEFAULT_CAR_PICKUP,
        DEFAULT_CAR_DROPOFF,
        premium=premium,
        limit=10,
    )
    inventory.car_candidates = candidates
    inventory.car_search_location = location
    offerable = sum(1 for candidate in candidates if candidate.is_offerable)
    errors = "; ".join(car_client.last_errors) if car_client.last_errors else ""
    inventory.car_search_note = (
        f"car search {location!r}: {len(candidates)} results, {offerable} offerable"
        + (f"; errors: {errors}" if errors else "")
    )


def build_offer_from_inventory(
    inventory: InventoryState,
    state: BuyerState,
    markup_pct: float,
    *,
    latest_message: str = "",
    car_client: CarSearchClient | None = None,
    session: AgentSessionState | None = None,
    prefer_cheaper: bool = False,
) -> Offer | None:
    trip_type = state.trip_type or "holiday"
    if trip_type == "tour":
        best = pick_best_tour_for_state(inventory.tour_candidates, state)
        if best is None:
            return None
        inventory.selected_tour = best
        inventory.selected_holiday = None
        return build_tour_offer(best, markup_pct=markup_pct)

    shorter_accepted = session.shorter_stay_accepted if session is not None else None
    if prefer_cheaper:
        best = pick_cheapest_holiday(inventory.holiday_candidates)
    else:
        best = pick_best_holiday_for_duration(
            inventory.holiday_candidates,
            state,
            shorter_stay_accepted=shorter_accepted,
        )
    if best is None:
        return None
    inventory.selected_holiday = best
    inventory.selected_tour = None

    car_needed = wants_car(state, latest_message)
    selected_car: CarCandidate | None = None
    if car_needed and car_client is not None:
        search_cars_for_state(
            state, inventory, car_client=car_client, latest_message=latest_message
        )
        premium = wants_premium_car(state, latest_message)
        selected_car = pick_best_car_candidate(inventory.car_candidates, premium=premium)
        inventory.selected_car = selected_car
        if selected_car is not None:
            if session is not None and "car" in session.unresolved_requirements:
                session.unresolved_requirements.remove("car")
                session.car_unresolved_notified = False
            return build_holiday_with_car_offer(best, selected_car, markup_pct=markup_pct)
        if session is not None and "car" not in session.unresolved_requirements:
            session.unresolved_requirements.append("car")

    if is_city_break_state(state) or (
        isinstance(best.raw, dict) and best.raw.get("flight") is not None
    ):
        return build_city_break_offer(best, markup_pct=markup_pct)
    return build_holiday_offer(best, markup_pct=markup_pct)


class LiveNegotiationAgent:
    """Policy-driven autonomous seller for practice matches."""

    def __init__(
        self,
        *,
        deal_room: DealRoomClient,
        analyzer: ConversationAnalyzer | None = None,
        tsm: TravelSupermarketClient | None = None,
        tourradar: TourRadarClient | None = None,
        car_search: CarSearchClient | None = None,
        city_break: CityBreakSearchClient | None = None,
        recorder: TranscriptRecorder | None = None,
        log_path: str | Path | None = None,
        reply_generator: Callable[..., str] | None = None,
        verbose: bool = False,
    ) -> None:
        self._client = deal_room
        self._analyzer = analyzer or ConversationAnalyzer()
        self._tsm = tsm or TravelSupermarketClient()
        self._tourradar = tourradar or TourRadarClient()
        self._car_search = car_search or CarSearchClient()
        self._city_break = city_break or CityBreakSearchClient()
        self._recorder = recorder
        self._log_path = Path(log_path) if log_path else None
        self._reply_generator = reply_generator or generate_reply
        self._strategist = NegotiationStrategist()
        self._verbose = verbose
        self.last_run_context: dict[str, Any] = {}
        self._forced_opening_markup: float | None = None

    def run(
        self,
        start: MatchStartResponse,
        *,
        persona_id: str,
        forced_opening_markup: float | None = None,
    ) -> MatchOutcome:
        assert_practice_match(start)
        self._forced_opening_markup = forced_opening_markup
        if self._recorder:
            self._recorder.record_match_started(start, practice=True, persona_id=persona_id)
            self._recorder.record_buyer_message(
                start.match_id,
                start.buyer,
                scenario_name=start.scenario.name,
                persona_id=persona_id,
            )

        state = BuyerState()
        inventory = InventoryState()
        session = AgentSessionState()
        events: list[TranscriptEvent] = [
            TranscriptEvent(
                match_id=start.match_id,
                persona_id=persona_id,
                scenario_name=start.scenario.name,
                round_number=None,
                role="buyer",
                text=start.buyer.text,
                action=start.buyer.action.value,
            )
        ]
        latest_message = start.buyer.text
        buyer_messages = [start.buyer.text]
        seller_rounds = 0
        turn_response: TurnResponse | None = None

        while seller_rounds < MAX_ROUNDS:
            if turn_response is not None and turn_response.is_ended:
                break
            if conversation_is_dead(buyer_messages):
                break

            analysis = self._analyzer.analyze(events)
            state.update_from_analysis(analysis)
            state.update_from_message(latest_message)
            if turn_response is not None:
                state.update_from_turn_response(turn_response)
            # Quote markup can differ from what we sent — keep our offer authoritative for counters.
            if inventory.last_offer is not None:
                state.update_from_offer(inventory.last_offer)

            inventory_ready = inventory.has_offerable
            decision = decide_action(
                state,
                analysis,
                latest_message,
                inventory_ready=inventory_ready,
            )
            decision = apply_policy_overrides(
                decision,
                state,
                latest_message,
                session=session,
                inventory_ready=inventory_ready,
                inventory=inventory,
            )

            walk_risk = estimate_walk_risk(state, latest_message)
            brief = self._strategist.advise(state, latest_message, decision.action)
            executed = self._execute(
                decision,
                state,
                inventory,
                session,
                latest_message,
                walk_risk=walk_risk,
                brief=brief,
                persona_id=persona_id,
            )

            seller_rounds += 1
            offer_dict = executed.offer.to_api_dict() if executed.offer else None
            turn_response = self._client.send_turn(
                start.match_id,
                executed.text,
                offer=executed.offer,
            )

            if self._recorder:
                self._recorder.record_seller_message(
                    start.match_id,
                    executed.text,
                    offer=offer_dict,
                    round_number=seller_rounds,
                )
                self._recorder.record_turn_response(start.match_id, turn_response)

            events.append(
                TranscriptEvent(
                    match_id=start.match_id,
                    persona_id=persona_id,
                    scenario_name=start.scenario.name,
                    round_number=seller_rounds,
                    role="seller",
                    text=executed.text,
                    offer=offer_dict,
                )
            )
            events.append(
                TranscriptEvent(
                    match_id=start.match_id,
                    persona_id=persona_id,
                    scenario_name=start.scenario.name,
                    round_number=seller_rounds,
                    role="buyer",
                    text=turn_response.buyer.text,
                    action=turn_response.buyer.action.value,
                )
            )

            self._log_turn(
                match_id=start.match_id,
                persona_id=persona_id,
                round_number=seller_rounds,
                analysis=analysis,
                state=state,
                decision=decision,
                inventory=inventory,
                session=session,
                markup=executed.markup,
                walk_risk=executed.walk_risk,
                seller_text=executed.text,
                offer_sent=executed.offer is not None,
                buyer_text=turn_response.buyer.text,
                buyer_action=turn_response.buyer.action.value,
                strategist_brief=brief,
            )
            if self._verbose:
                self._print_turn(
                    round_number=seller_rounds,
                    decision=decision,
                    walk_risk=walk_risk,
                    executed=executed,
                    inventory=inventory,
                    turn_response=turn_response,
                )

            if executed.offer is not None:
                state.update_from_offer(executed.offer)
                inventory.last_offer = executed.offer

            if decision.action is NegotiationAction.COUNTER:
                session.price_counter_count += 1
            if decision.action in (NegotiationAction.DISCOVER, NegotiationAction.REFINE):
                session.discover_refine_count += 1
            if (
                decision.action is NegotiationAction.OFFER
                and decision.reasoning.startswith("Max price counters")
            ):
                session.best_and_final_sent = True

            latest_message = turn_response.buyer.text
            buyer_messages.append(latest_message)

            if turn_response.is_ended:
                break

        result = turn_response.result if turn_response else None
        self.last_run_context = {
            "duration_mismatch": session.duration_mismatch,
            "final_markup_pct": state.last_markup_pct,
            "quote_total": (
                turn_response.quote.total
                if turn_response and turn_response.quote
                else state.last_offer_total
            ),
            "cost": state.last_offer_cost,
            "offer_sent": inventory.last_offer is not None,
            "unresolved_car": "car" in session.unresolved_requirements
            and wants_car(state, latest_message),
            "unresolved_requirement": bool(session.unresolved_requirements),
        }
        return MatchOutcome(
            match_id=start.match_id,
            persona_id=persona_id,
            closed=bool(result and result.closed),
            walked=bool(result and result.end_reason == "walked"),
            rounds=result.rounds if result else seller_rounds,
            end_reason=result.end_reason if result else None,
            seller_rounds=seller_rounds,
        )

    def _execute(
        self,
        decision: PolicyDecision,
        state: BuyerState,
        inventory: InventoryState,
        session: AgentSessionState,
        latest_message: str,
        *,
        walk_risk: float,
        brief: NegotiationBrief | None = None,
        persona_id: str | None = None,
    ) -> ExecuteResult:
        action = decision.action
        session.pivoted_this_turn = False

        if action is NegotiationAction.SEARCH:
            self._refresh_inventory(state, inventory)
            if wants_car(state, latest_message):
                search_cars_for_state(
                    state,
                    inventory,
                    car_client=self._car_search,
                    latest_message=latest_message,
                )
            text = self._call_reply_generator(
                NegotiationAction.SEARCH,
                state,
                inventory.last_offer.to_api_dict() if inventory.last_offer else None,
                latest_message,
                brief=brief,
            )
            text = _sanitize_reply(text, NegotiationAction.SEARCH, inventory.last_offer)
            return ExecuteResult(text=text, walk_risk=walk_risk)

        if action is NegotiationAction.OFFER:
            if not inventory.has_offerable:
                self._refresh_inventory(state, inventory)
            if self._forced_opening_markup is not None and state.last_markup_pct is None:
                markup = self._forced_opening_markup
            else:
                markup = estimate_markup_for_persona(state, walk_risk, persona_id)
            markup = cap_luxury_opening_markup(markup, state)
            markup = cap_city_break_opening_markup(markup, state)
            if decision.target_markup is not None:
                markup = decision.target_markup
            if session.shorter_stay_accepted:
                markup = min(markup, 12.0)
            prefer_cheaper = session.price_counter_count >= MAX_PRICE_COUNTERS_PER_MATCH
            if (
                prefer_cheaper
                and session.pivot_count < MAX_PIVOTS_PER_MATCH
            ):
                cheaper = find_cheaper_holiday_alternative(inventory, state)
                if cheaper is not None:
                    inventory.selected_holiday = cheaper
                    session.pivot_count += 1
                    session.pivoted_this_turn = True
                    markup = min(markup, 8.0)
            offer = build_offer_from_inventory(
                inventory,
                state,
                markup,
                latest_message=latest_message,
                car_client=self._car_search,
                session=session,
                prefer_cheaper=prefer_cheaper,
            )
            if offer is None:
                text = fallback_reply(NegotiationAction.REFINE, None)
                return ExecuteResult(text=text, walk_risk=walk_risk)
            check_duration_mismatch(inventory.selected_holiday, state, session)
            text = self._car_aware_reply(
                action, state, offer, latest_message, session=session, brief=brief
            )
            text = _sanitize_reply(text, action, offer)
            return ExecuteResult(text=text, offer=offer, markup=markup, walk_risk=walk_risk)

        if action is NegotiationAction.COUNTER:
            if inventory.last_offer is None and not inventory.has_offerable:
                self._refresh_inventory(state, inventory)
            markup = decision.target_markup
            if markup is None:
                markup = estimate_markup(state, Aggressiveness.BALANCED)
            if (
                inventory.last_offer is not None
                and state.last_markup_pct is not None
                and markup >= state.last_markup_pct
            ):
                from dealbreakers.negotiation.pricing import generate_counter_markup

                markup = generate_counter_markup(state.last_markup_pct, state)
            luxury_pivot = (
                state.luxury_preference >= 0.7
                and session.price_counter_count >= 1
            )
            prefer_cheaper = (
                session.price_counter_count >= MAX_PRICE_COUNTERS_PER_MATCH
                or luxury_pivot
            )
            if (
                (prefer_cheaper or (markup is not None and markup <= 10))
                and session.pivot_count < MAX_PIVOTS_PER_MATCH
            ):
                cheaper = find_cheaper_holiday_alternative(inventory, state)
                if cheaper is not None:
                    inventory.selected_holiday = cheaper
                    session.pivot_count += 1
                    session.pivoted_this_turn = True
                    markup = min(markup or 8.0, 8.0)
            elif prefer_cheaper:
                cheaper = pick_cheapest_holiday(inventory.holiday_candidates)
                if cheaper is not None:
                    inventory.selected_holiday = cheaper
                markup = min(markup or 8.0, 8.0)
            if session.pivot_count > 0:
                markup = min(markup or 0.0, 0.0)
            offer = self._rebuild_offer(
                inventory,
                state,
                markup,
                latest_message=latest_message,
                session=session,
                prefer_cheaper=prefer_cheaper,
            )
            if offer is None:
                text = fallback_reply(NegotiationAction.REFINE, inventory.last_offer)
                return ExecuteResult(text=text, walk_risk=walk_risk)
            check_duration_mismatch(inventory.selected_holiday, state, session)
            text = self._car_aware_reply(
                action, state, offer, latest_message, session=session, brief=brief
            )
            text = _sanitize_reply(text, action, offer)
            return ExecuteResult(text=text, offer=offer, markup=markup, walk_risk=walk_risk)

        if action is NegotiationAction.CLOSE:
            text = self._call_reply_generator(
                action,
                state,
                inventory.last_offer,
                latest_message,
                brief=brief,
            )
            text = _sanitize_reply(text, action, inventory.last_offer)
            return ExecuteResult(text=text, walk_risk=walk_risk)

        # DISCOVER / REFINE — wording only
        if (
            action is NegotiationAction.REFINE
            and decision.reasoning.startswith("Desired duration unavailable")
        ):
            text = (
                "Would you consider a shorter 7-night luxury stay if the property "
                "quality is genuinely stronger? I want to be upfront that it would "
                "not be your full two-week request."
            )
        elif (
            action is NegotiationAction.REFINE
            and decision.reasoning.startswith("No city-break inventory")
        ):
            text = (
                "I couldn't find a strong central 4-star option with fast WiFi and a "
                "proper gym in that city right now. Would you be open to another "
                "tech-friendly city like Amsterdam or Paris?"
            )
        elif (
            action is NegotiationAction.REFINE
            and "car" in session.unresolved_requirements
            and wants_car(state, latest_message)
        ):
            text = (
                "The five-star hotel package is ready. Premium rental car inventory "
                "isn't available for these dates — I can only offer the complete "
                "holiday as shown."
            )
            session.car_unresolved_notified = True
        else:
            text = self._call_reply_generator(
                action, state, None, latest_message, brief=brief
            )
        text = _sanitize_reply(text, action, None)
        return ExecuteResult(text=text, walk_risk=walk_risk)

    def _call_reply_generator(
        self,
        action: NegotiationAction,
        state: BuyerState,
        offer: Offer | dict[str, Any] | None,
        latest_message: str,
        *,
        brief: NegotiationBrief | None = None,
    ) -> str:
        kwargs: dict[str, Any] = {}
        if brief is not None:
            kwargs["strategist_brief"] = brief
        try:
            return self._reply_generator(
                action, state, offer, latest_message, **kwargs
            )
        except TypeError:
            return self._reply_generator(action, state, offer, latest_message)

    def _refresh_inventory(self, state: BuyerState, inventory: InventoryState) -> None:
        searched = run_inventory_search(
            state,
            tsm=self._tsm,
            tourradar=self._tourradar,
            city_break=self._city_break,
        )
        inventory.holiday_candidates = searched.holiday_candidates
        inventory.tour_candidates = searched.tour_candidates
        inventory.search_note = searched.search_note

    def _car_aware_reply(
        self,
        action: NegotiationAction,
        state: BuyerState,
        offer: Offer,
        latest_message: str,
        *,
        session: AgentSessionState,
        brief: NegotiationBrief | None = None,
    ) -> str:
        if session.pivoted_this_turn:
            return self._call_reply_generator(
                action, state, offer, latest_message, brief=brief
            )
        if session.duration_mismatch and state.desired_nights:
            nights = offer.holiday.nights if offer.holiday else None
            prefix = (
                f"I found a strong {nights}-night option, but it is shorter than your "
                f"{state.desired_nights}-night target — {state.desired_nights}-night "
                f"inventory isn't available at this destination right now. "
            )
            body = self._call_reply_generator(
                action, state, offer, latest_message, brief=brief
            )
            return prefix + body
        if (
            wants_car(state, latest_message)
            and offer.car is None
            and "car" in session.unresolved_requirements
            and session.car_unresolved_notified
        ):
            return (
                "The premium hotel package is ready below. I wasn't able to source a "
                "matching premium rental car for these dates — the holiday is complete "
                "and bookable as shown."
            )
        if (
            wants_car(state, latest_message)
            and offer.car is None
            and "car" in session.unresolved_requirements
        ):
            session.car_unresolved_notified = True
            return (
                "I've secured the premium hotel package for you. Premium car inventory "
                "isn't available for these dates right now, so the offer below is the "
                "complete holiday package — no car included."
            )
        return self._call_reply_generator(
            action, state, offer, latest_message, brief=brief
        )

    def _rebuild_offer(
        self,
        inventory: InventoryState,
        state: BuyerState,
        markup_pct: float,
        *,
        latest_message: str = "",
        session: AgentSessionState | None = None,
        prefer_cheaper: bool = False,
    ) -> Offer | None:
        if inventory.selected_holiday is not None or inventory.selected_tour is not None:
            if inventory.selected_holiday is not None:
                car = inventory.selected_car
                if wants_car(state, latest_message) and car is not None and car.is_offerable:
                    return build_holiday_with_car_offer(
                        inventory.selected_holiday, car, markup_pct=markup_pct
                    )
                return build_holiday_offer(
                    inventory.selected_holiday, markup_pct=markup_pct
                )
            if inventory.selected_tour is not None:
                return build_tour_offer(inventory.selected_tour, markup_pct=markup_pct)
        return build_offer_from_inventory(
            inventory,
            state,
            markup_pct,
            latest_message=latest_message,
            car_client=self._car_search,
            session=session,
            prefer_cheaper=prefer_cheaper,
        )

    def _print_turn(
        self,
        *,
        round_number: int,
        decision: PolicyDecision,
        walk_risk: float,
        executed: ExecuteResult,
        inventory: InventoryState,
        turn_response: TurnResponse,
    ) -> None:
        print(f"\n--- Round {round_number} — {decision.action.value.upper()} ---")
        print(f"Policy: {decision.reasoning}")
        print(f"Walk risk: {walk_risk:.2f}")
        if inventory.search_note:
            print(f"Search: {inventory.search_note}")
        if inventory.car_search_note:
            print(f"Car search: {inventory.car_search_note}")
        if executed.markup is not None:
            print(f"Markup: {executed.markup}%")
        selected = inventory.selected_summary()
        if selected:
            label = selected.get("hotel_name") or selected.get("name") or "candidate"
            cost = selected.get("cost")
            print(f"Selected: {label}" + (f" (cost £{cost})" if cost else ""))
        print(f"\nSeller: {executed.text}")
        if executed.offer is not None:
            offer = executed.offer
            if offer.holiday:
                print(
                    f"Offer: {offer.holiday.hotel_name} — "
                    f"£{offer.holiday.price_total} cost, {offer.markup_pct}% markup"
                )
            elif offer.tour:
                print(
                    f"Offer: {offer.tour.name} — "
                    f"£{offer.tour.price_total} cost, {offer.markup_pct}% markup"
                )
            if offer.car:
                print(
                    f"Car: {offer.car.vehicle_name} — £{offer.car.price_total} cost"
                )
        if turn_response.quote:
            print(
                f"Quote: cost={turn_response.quote.cost}, "
                f"markup={turn_response.quote.markup_pct}%, "
                f"total={turn_response.quote.total}"
            )
        print(f"\nBuyer ({turn_response.buyer.action.value}): {turn_response.buyer.text}")

    def _log_turn(self, **fields: Any) -> None:
        if self._log_path is None:
            return
        record = {
            "record_type": "agent_turn",
            "analysis": fields["analysis"].to_dict(),
            "buyer_state": fields["state"].to_dict(),
            "policy_decision": fields["decision"].to_dict(),
            "selected_inventory": fields["inventory"].selected_summary(),
            "inventory_search_note": fields["inventory"].search_note,
            "car_search_note": fields["inventory"].car_search_note,
            "unresolved_requirements": list(fields["session"].unresolved_requirements),
            "price_counter_count": fields["session"].price_counter_count,
            "duration_mismatch": fields["session"].duration_mismatch,
            "pivot_count": fields["session"].pivot_count,
            "strategist_brief": (
                fields["strategist_brief"].to_dict()
                if fields.get("strategist_brief") is not None
                else None
            ),
            "markup": fields.get("markup"),
            "walk_risk": fields.get("walk_risk"),
            "action": fields["decision"].action.value,
            "seller_text": fields["seller_text"],
            "offer_sent": fields["offer_sent"],
            "buyer_text": fields.get("buyer_text"),
            "buyer_action": fields.get("buyer_action"),
            "match_id": fields["match_id"],
            "persona_id": fields["persona_id"],
            "round_number": fields["round_number"],
        }
        append_run_log(record, self._log_path)
