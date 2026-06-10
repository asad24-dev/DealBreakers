"""Graph nodes — thin wrappers around existing deterministic modules (Phase 8E)."""

from __future__ import annotations

from typing import Any

from dealbreakers.constants import MAX_ROUNDS
from dealbreakers.graph.context import GraphContext
from dealbreakers.graph.state import GraphState
from dealbreakers.mcp.normalizers import HolidayCandidate
from dealbreakers.negotiation.actions import NegotiationAction
from dealbreakers.negotiation.live_agent import (
    MAX_PRICE_COUNTERS_PER_MATCH,
    apply_policy_overrides,
    build_offer_from_inventory,
    check_duration_mismatch,
    conversation_is_dead,
    find_cheaper_holiday_alternative,
    markup_profile_from_walk_risk,
    pick_cheapest_holiday,
    run_inventory_search,
    search_cars_for_state,
    wants_car,
)
from dealbreakers.negotiation.policy import decide_action, estimate_walk_risk
from dealbreakers.negotiation.pricing import (
    Aggressiveness,
    cap_luxury_opening_markup,
    estimate_markup,
    estimate_markup_for_persona,
    generate_counter_markup,
    generate_luxury_counter_markup,
    generate_total_based_counter_markup,
    should_use_total_based_counter,
)
from dealbreakers.negotiation.responder import fallback_reply, generate_reply
from dealbreakers.negotiation.strategist import feels_overcharged
from dealbreakers.offers.selection import (
    pick_best_holiday_for_state,
    pick_best_tour_for_state,
    score_holiday_for_state,
)
from dealbreakers.state.buyer_state import detect_price_objection


def _log_node(
    state: GraphState,
    node: str,
    *,
    action: str | None = None,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    entry: dict[str, Any] = {
        "node": node,
        "round": state.round_number,
        "action": action,
        "match_id": state.match_id,
        "persona_id": state.persona_id,
    }
    if error:
        entry["error"] = error
    if state.markup_pct is not None:
        entry["markup"] = state.markup_pct
    if state.selected_inventory:
        entry["selected_inventory"] = state.selected_inventory
    if state.turn_response:
        entry["buyer_action"] = state.turn_response.get("buyer_action")
        entry["quote"] = state.turn_response.get("quote")
    if extra:
        entry.update(extra)
    state.logs.append(entry)


def _sync_buyer_state(state: GraphState, ctx: GraphContext) -> None:
    state.buyer_state = ctx.buyer_state.to_dict() if hasattr(ctx.buyer_state, "to_dict") else {
        "trip_type": ctx.buyer_state.trip_type,
        "destinations": ctx.buyer_state.destinations,
        "must_haves": ctx.buyer_state.must_haves,
        "last_offer_total": ctx.buyer_state.last_offer_total,
        "last_markup_pct": ctx.buyer_state.last_markup_pct,
    }


def _inventory_summary(ctx: GraphContext) -> dict[str, Any]:
    inv = ctx.inventory
    return {
        "holiday_count": len(inv.holiday_candidates),
        "tour_count": len(inv.tour_candidates),
        "car_count": len(inv.car_candidates),
        "search_note": inv.search_note,
        "car_search_note": inv.car_search_note,
    }


def start_match_node(state: GraphState, ctx: GraphContext) -> GraphState:
    """Practice-only match start — records opening buyer message."""
    if ctx.start is None:
        state.error = "No match start response in context"
        _log_node(state, "start_match", error=state.error)
        return state

    state.match_id = ctx.start.match_id
    state.latest_buyer_message = ctx.start.buyer.text
    state.transcript.append(
        {
            "role": "buyer",
            "text": ctx.start.buyer.text,
            "action": ctx.start.buyer.action.value,
            "round": None,
        }
    )
    ctx.buyer_messages = [ctx.start.buyer.text]
    _log_node(state, "start_match", action="started")
    return state


def analyze_node(state: GraphState, ctx: GraphContext) -> GraphState:
    """ConversationAnalyzer — updates analysis."""
    try:
        analysis = ctx.analyzer.analyze(ctx.events)
        state.analysis = analysis.to_dict() if hasattr(analysis, "to_dict") else {
            "trip_type": analysis.trip_type,
            "destinations": analysis.destinations,
            "must_haves": analysis.must_haves,
            "desired_nights": getattr(analysis, "desired_nights", None),
        }
        ctx.buyer_state.update_from_analysis(analysis)
        ctx.buyer_state.update_from_message(state.latest_buyer_message)
        if ctx.turn_response is not None:
            ctx.buyer_state.update_from_turn_response(ctx.turn_response)
        if ctx.inventory.last_offer is not None:
            ctx.buyer_state.update_from_offer(ctx.inventory.last_offer)
        _sync_buyer_state(state, ctx)
        _log_node(state, "analyze")
    except Exception as exc:  # noqa: BLE001
        state.error = str(exc)
        _log_node(state, "analyze", error=state.error)
    return state


def _infer_action_for_strategist(state: GraphState, ctx: GraphContext) -> NegotiationAction:
    if state.policy_decision:
        return NegotiationAction(state.policy_decision["action"])
    if not ctx.buyer_state.trip_type and not ctx.buyer_state.destinations:
        return NegotiationAction.DISCOVER
    if not ctx.inventory.has_offerable:
        return NegotiationAction.SEARCH
    if ctx.buyer_state.last_offer_total is not None:
        return NegotiationAction.COUNTER
    return NegotiationAction.OFFER


def strategist_node(state: GraphState, ctx: GraphContext) -> GraphState:
    """Optional NegotiationStrategist — advisory only."""
    action = _infer_action_for_strategist(state, ctx)
    try:
        brief = ctx.strategist.advise(
            ctx.buyer_state,
            state.latest_buyer_message,
            action,
        )
        ctx.brief = brief
        state.insights = brief.to_dict()
        _log_node(state, "strategist", action=action.value)
    except Exception as exc:  # noqa: BLE001
        ctx.brief = None
        state.insights = {"error": str(exc)}
        _log_node(state, "strategist", error=str(exc))
    return state


def update_state_node(state: GraphState, ctx: GraphContext) -> GraphState:
    """BuyerState sync — already updated in analyze; refresh summary."""
    _sync_buyer_state(state, ctx)
    state.inventory_candidates = _inventory_summary(ctx)
    _log_node(state, "update_state")
    return state


def decide_action_node(state: GraphState, ctx: GraphContext) -> GraphState:
    """Deterministic decide_action() — no LLM decisions."""
    from dealbreakers.analysis.models import ConversationAnalysis

    analysis_data = state.analysis or {}
    analysis = ConversationAnalysis(
        trip_type=analysis_data.get("trip_type"),
        destinations=analysis_data.get("destinations") or [],
        must_haves=analysis_data.get("must_haves") or [],
        desired_nights=analysis_data.get("desired_nights"),
    )
    inventory_ready = ctx.inventory.has_offerable
    decision = decide_action(
        ctx.buyer_state,
        analysis,
        state.latest_buyer_message,
        inventory_ready=inventory_ready,
    )
    decision = apply_policy_overrides(
        decision,
        ctx.buyer_state,
        state.latest_buyer_message,
        session=ctx.session,
        inventory_ready=inventory_ready,
        inventory=ctx.inventory,
    )
    ctx.walk_risk = estimate_walk_risk(ctx.buyer_state, state.latest_buyer_message)
    state.policy_decision = decision.to_dict()
    _log_node(state, "decide_action", action=decision.action.value)
    return state


def _markup_from_bandit(
    ctx: GraphContext,
    walk_risk: float,
    *,
    persona_id: str | None = None,
) -> float:
    if ctx.markup_arm is None:
        return estimate_markup_for_persona(ctx.buyer_state, walk_risk, persona_id)

    profile = get_persona_profile(persona_id)
    name = ctx.markup_arm.name
    if name == "conservative":
        markup = profile.safe
    elif name == "balanced":
        markup = profile.balanced
    elif name == "aggressive":
        markup = profile.aggressive
    elif name == "ceiling_minus_2":
        base = estimate_markup_for_persona(ctx.buyer_state, walk_risk, persona_id)
        markup = base - 2.0
    else:
        markup = estimate_markup_for_persona(ctx.buyer_state, walk_risk, persona_id)
    if profile.ceiling is not None:
        markup = min(markup, profile.ceiling)
    return max(0.0, markup)


def get_persona_profile(persona_id: str | None):
    from dealbreakers.personas.markup_profiles import get_profile

    return get_profile(persona_id)


def _select_holiday(ctx: GraphContext) -> HolidayCandidate | None:
    candidates = ctx.inventory.holiday_candidates
    if not candidates:
        return None

    arm_name = ctx.search_arm.name if ctx.search_arm else "best_luxury_fit"
    offerable = [c for c in candidates if c.is_offerable]
    if not offerable:
        return None

    if arm_name == "cheapest_valid":
        return pick_cheapest_holiday(candidates)
    if arm_name == "best_reviewed":
        return max(
            offerable,
            key=lambda c: c.review_score if c.review_score is not None else 0.0,
        )
    if arm_name == "best_profit_adjusted":
        return max(
            offerable,
            key=lambda c: score_holiday_for_state(c, ctx.buyer_state)
            + (c.price_total or 0) / 500.0,
        )
    return pick_best_holiday_for_state(candidates, ctx.buyer_state)


def search_inventory_node(state: GraphState, ctx: GraphContext) -> GraphState:
    """Holiday → TSM, tour → TourRadar, car → CarSearchClient."""
    try:
        searched = run_inventory_search(
            ctx.buyer_state,
            tsm=ctx.tsm,
            tourradar=ctx.tourradar,
            city_break=ctx.city_break,
        )
        ctx.inventory.holiday_candidates = searched.holiday_candidates
        ctx.inventory.tour_candidates = searched.tour_candidates
        ctx.inventory.search_note = searched.search_note

        if wants_car(ctx.buyer_state, state.latest_buyer_message):
            search_cars_for_state(
                ctx.buyer_state,
                ctx.inventory,
                car_client=ctx.car_search,
                latest_message=state.latest_buyer_message,
            )

        state.inventory_candidates = _inventory_summary(ctx)
        _log_node(state, "search_inventory", action="search")
    except Exception as exc:  # noqa: BLE001
        state.error = str(exc)
        _log_node(state, "search_inventory", error=state.error)
    return state


def select_offer_node(state: GraphState, ctx: GraphContext) -> GraphState:
    """Deterministic scoring + optional bandit markup — builds Offer."""
    try:
        if not ctx.inventory.has_offerable:
            search_inventory_node(state, ctx)
        decision = state.policy_decision or {}
        action_name = decision.get("action", NegotiationAction.OFFER.value)
        action = NegotiationAction(action_name)

        markup = decision.get("target_markup")
        if markup is None:
            markup = _markup_from_bandit(ctx, ctx.walk_risk, persona_id=state.persona_id)
            markup = cap_luxury_opening_markup(float(markup), ctx.buyer_state)

        if action is NegotiationAction.COUNTER and markup is not None:
            markup = float(markup)
        elif action is NegotiationAction.OFFER:
            markup = float(markup)

        prefer_cheaper = ctx.session.price_counter_count >= MAX_PRICE_COUNTERS_PER_MATCH
        if prefer_cheaper and ctx.session.pivot_count < 2:
            cheaper = find_cheaper_holiday_alternative(ctx.inventory, ctx.buyer_state)
            if cheaper is not None:
                ctx.inventory.selected_holiday = cheaper
                ctx.session.pivot_count += 1
                markup = min(float(markup), 8.0)

        trip_type = ctx.buyer_state.trip_type or "holiday"
        if trip_type == "tour":
            best = pick_best_tour_for_state(ctx.inventory.tour_candidates, ctx.buyer_state)
            if best:
                ctx.inventory.selected_tour = best
        else:
            best = _select_holiday(ctx)
            if best:
                ctx.inventory.selected_holiday = best

        offer = build_offer_from_inventory(
            ctx.inventory,
            ctx.buyer_state,
            float(markup),
            latest_message=state.latest_buyer_message,
            car_client=ctx.car_search,
            session=ctx.session,
            prefer_cheaper=prefer_cheaper,
        )
        if offer is None:
            state.error = "No offerable inventory"
            _log_node(state, "select_offer", error=state.error)
            return state

        check_duration_mismatch(ctx.inventory.selected_holiday, ctx.buyer_state, ctx.session)
        ctx.pending_offer = offer
        state.offer = offer.to_api_dict()
        state.markup_pct = float(markup)
        state.selected_inventory = ctx.inventory.selected_summary()
        if ctx.inventory.selected_car:
            state.selected_car = {
                "vehicle_name": ctx.inventory.selected_car.vehicle_name,
                "cost": ctx.inventory.selected_car.price_total,
                "url": ctx.inventory.selected_car.url,
            }
        _log_node(state, "select_offer", action=action_name, extra={"markup": markup})
    except Exception as exc:  # noqa: BLE001
        state.error = str(exc)
        _log_node(state, "select_offer", error=state.error)
    return state


def counter_node(state: GraphState, ctx: GraphContext) -> GraphState:
    """Existing counter ladder — never increases markup."""
    try:
        decision = state.policy_decision or {}
        markup = decision.get("target_markup")
        current = ctx.buyer_state.last_markup_pct or estimate_markup(
            ctx.buyer_state, Aggressiveness.BALANCED
        )

        if markup is None:
            counter_arm = ctx.counter_arm.name if ctx.counter_arm else "slow_ladder"
            if counter_arm == "best_and_final":
                markup = 8.0
            elif counter_arm == "luxury_jump":
                markup = generate_luxury_counter_markup(current, ctx.buyer_state)
            elif counter_arm == "total_based" and should_use_total_based_counter(ctx.buyer_state):
                markup = generate_total_based_counter_markup(
                    current,
                    ctx.buyer_state.last_offer_cost or 0.0,
                    ctx.buyer_state.last_offer_total or 0.0,
                    feels_overcharged=feels_overcharged(state.latest_buyer_message),
                )
            else:
                markup = generate_counter_markup(current, ctx.buyer_state)
        else:
            markup = float(markup)

        if (
            ctx.buyer_state.last_markup_pct is not None
            and markup >= ctx.buyer_state.last_markup_pct
        ):
            markup = generate_counter_markup(ctx.buyer_state.last_markup_pct, ctx.buyer_state)

        state.markup_pct = float(markup)
        state.policy_decision = {
            **decision,
            "target_markup": markup,
            "action": NegotiationAction.COUNTER.value,
        }

        prefer_cheaper = ctx.session.price_counter_count >= MAX_PRICE_COUNTERS_PER_MATCH
        offer = build_offer_from_inventory(
            ctx.inventory,
            ctx.buyer_state,
            float(markup),
            latest_message=state.latest_buyer_message,
            car_client=ctx.car_search,
            session=ctx.session,
            prefer_cheaper=prefer_cheaper,
        )
        if offer is not None:
            check_duration_mismatch(ctx.inventory.selected_holiday, ctx.buyer_state, ctx.session)
            ctx.pending_offer = offer
            state.offer = offer.to_api_dict()
            state.selected_inventory = ctx.inventory.selected_summary()

        _log_node(state, "counter", action="counter", extra={"markup": markup})
    except Exception as exc:  # noqa: BLE001
        state.error = str(exc)
        _log_node(state, "counter", error=state.error)
    return state


def _call_reply_generator(
    ctx: GraphContext,
    action: NegotiationAction,
    offer: Any,
    latest_message: str,
) -> str:
    generator = ctx.reply_generator or generate_reply
    kwargs: dict[str, Any] = {}
    if ctx.brief is not None:
        kwargs["strategist_brief"] = ctx.brief
    try:
        return generator(action, ctx.buyer_state, offer, latest_message, **kwargs)
    except TypeError:
        return generator(action, ctx.buyer_state, offer, latest_message)


def generate_reply_node(state: GraphState, ctx: GraphContext) -> GraphState:
    """OpenAI responder — wording only."""
    try:
        decision = state.policy_decision or {}
        action = NegotiationAction(decision.get("action", NegotiationAction.DISCOVER.value))
        offer_dict = state.offer

        if action in (NegotiationAction.OFFER, NegotiationAction.COUNTER) and offer_dict is None:
            state.seller_text = fallback_reply(NegotiationAction.REFINE, ctx.inventory.last_offer)
            _log_node(state, "generate_reply", action=action.value)
            return state

        if action is NegotiationAction.CLOSE:
            offer_arg = ctx.inventory.last_offer
        elif action in (NegotiationAction.OFFER, NegotiationAction.COUNTER):
            offer_arg = offer_dict
        elif action is NegotiationAction.SEARCH:
            offer_arg = (
                ctx.inventory.last_offer.to_api_dict() if ctx.inventory.last_offer else None
            )
        else:
            offer_arg = None

        if (
            action is NegotiationAction.REFINE
            and "car" in ctx.session.unresolved_requirements
            and wants_car(ctx.buyer_state, state.latest_buyer_message)
        ):
            state.seller_text = (
                "The five-star hotel package is ready. Premium rental car inventory "
                "isn't available for these dates — I can only offer the complete "
                "holiday as shown."
            )
            ctx.session.car_unresolved_notified = True
        else:
            state.seller_text = _call_reply_generator(
                ctx, action, offer_arg, state.latest_buyer_message
            )

        _log_node(state, "generate_reply", action=action.value)
    except Exception as exc:  # noqa: BLE001
        state.seller_text = fallback_reply(NegotiationAction.REFINE, None)
        state.error = str(exc)
        _log_node(state, "generate_reply", error=state.error)
    return state


def send_turn_node(state: GraphState, ctx: GraphContext) -> GraphState:
    """DealRoomClient.send_turn() — logs quote/result."""
    try:
        offer_obj = ctx.pending_offer
        if offer_obj is None and state.policy_decision:
            action = NegotiationAction(state.policy_decision.get("action", ""))
            if action not in (NegotiationAction.OFFER, NegotiationAction.COUNTER):
                offer_obj = None
            else:
                offer_obj = ctx.inventory.last_offer

        turn = ctx.deal_room.send_turn(
            state.match_id,
            state.seller_text,
            offer=offer_obj,
        )
        ctx.turn_response = turn
        ctx.seller_rounds += 1
        state.round_number = ctx.seller_rounds

        quote = None
        if turn.quote is not None:
            quote = {
                "total": turn.quote.total,
                "markup_pct": turn.quote.markup_pct,
            }

        state.turn_response = {
            "buyer_text": turn.buyer.text,
            "buyer_action": turn.buyer.action.value,
            "is_ended": turn.is_ended,
            "quote": quote,
        }
        state.latest_buyer_message = turn.buyer.text
        ctx.buyer_messages.append(turn.buyer.text)
        state.transcript.append(
            {
                "role": "seller",
                "text": state.seller_text,
                "offer": state.offer,
                "round": ctx.seller_rounds,
            }
        )
        state.transcript.append(
            {
                "role": "buyer",
                "text": turn.buyer.text,
                "action": turn.buyer.action.value,
                "round": ctx.seller_rounds,
            }
        )

        if offer_obj is not None:
            ctx.buyer_state.update_from_offer(offer_obj)
            ctx.inventory.last_offer = offer_obj
        ctx.pending_offer = None

        decision = state.policy_decision or {}
        action = NegotiationAction(decision.get("action", ""))
        if action is NegotiationAction.COUNTER:
            ctx.session.price_counter_count += 1
        if action in (NegotiationAction.DISCOVER, NegotiationAction.REFINE):
            ctx.session.discover_refine_count += 1
        if (
            action is NegotiationAction.OFFER
            and decision.get("reasoning", "").startswith("Max price counters")
        ):
            ctx.session.best_and_final_sent = True

        _log_node(state, "send_turn", action=action.value if action else None)
    except Exception as exc:  # noqa: BLE001
        state.error = str(exc)
        state.ended = True
        _log_node(state, "send_turn", error=state.error)
    return state


def check_end_node(state: GraphState, ctx: GraphContext) -> GraphState:
    """Accept / walk / 15 rounds / dead conversation."""
    turn = ctx.turn_response
    if turn is not None and turn.is_ended:
        state.ended = True
        _log_node(state, "check_end", action="ended")
        return state

    if ctx.seller_rounds >= MAX_ROUNDS:
        state.ended = True
        _log_node(state, "check_end", action="max_rounds")
        return state

    if conversation_is_dead(ctx.buyer_messages):
        state.ended = True
        _log_node(state, "check_end", action="dead_conversation")
        return state

    if turn is not None and turn.buyer.action.value in ("accept", "walk"):
        state.ended = True
        _log_node(state, "check_end", action=turn.buyer.action.value)
        return state

    state.ended = False
    state.offer = None
    state.seller_text = ""
    state.turn_response = None
    _log_node(state, "check_end", action="continue")
    return state


def route_after_decide(state: GraphState) -> str:
    """Conditional routing after decide_action_node."""
    decision = state.policy_decision or {}
    action = decision.get("action", NegotiationAction.DISCOVER.value)
    mapping = {
        NegotiationAction.DISCOVER.value: "wording_path",
        NegotiationAction.REFINE.value: "wording_path",
        NegotiationAction.SEARCH.value: "search_path",
        NegotiationAction.OFFER.value: "offer_path",
        NegotiationAction.COUNTER.value: "counter_path",
        NegotiationAction.CLOSE.value: "wording_path",
    }
    return mapping.get(action, "wording_path")


def route_after_check_end(state: GraphState) -> str:
    return "end" if state.ended else "analyze"
