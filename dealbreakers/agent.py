from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace
from pathlib import Path

from rich.console import Console

from dealbreakers.catalog import ListingCandidate, ScoredCandidate, build_offer_from_candidate
from dealbreakers.composer import MessageComposer
from dealbreakers.config import get_settings
from dealbreakers.dealroom import DealRoomClient
from dealbreakers.evaluators import (
    BuyerRead,
    MessageComposerLLM,
    PricingStrategist,
    ProfileEvaluator,
    ShortlistEvaluator,
    merge_extraction,
)
from dealbreakers.models import BuyerAction, MatchStart, Quote, SellerTurn
from dealbreakers.profile import BuyerProfile, infer_profile
from dealbreakers.search import McpSearchEngine
from dealbreakers.strategy import NegotiationPolicy


@dataclass
class NegotiationState:
    profile: BuyerProfile
    read: BuyerRead | None = None
    shortlist: list[ScoredCandidate] = field(default_factory=list)
    candidate: ScoredCandidate | None = None
    search_key: tuple | None = None
    quotes: list[Quote] = field(default_factory=list)
    turns: list[dict] = field(default_factory=list)
    price_objections: int = 0  # consecutive
    pivots: int = 0
    pivoted_this_turn: bool = False
    car: ListingCandidate | None = None
    car_searched: bool = False


class SellerAgent:
    def __init__(
        self,
        dealroom: DealRoomClient,
        *,
        search: McpSearchEngine | None = None,
        console: Console | None = None,
        log_dir: str = "logs",
    ) -> None:
        self._dealroom = dealroom
        self._search = search or McpSearchEngine()
        self._policy = NegotiationPolicy()
        self._fallback_composer = MessageComposer()
        self._profile_agent = ProfileEvaluator()
        self._shortlist_agent = ShortlistEvaluator()
        self._pricing_agent = PricingStrategist()
        self._composer = MessageComposerLLM()
        self._console = console or Console()
        self._log_dir = Path(log_dir)
        self._log_path = self._log_dir / "match.json"
        self._max_rounds = get_settings().max_rounds

    def run_match(self, match: MatchStart) -> None:
        state = NegotiationState(
            profile=infer_profile(match.scenario.name, match.scenario.brief, [match.buyer.text])
        )
        buyer_messages = [match.buyer.text]
        seller_messages: list[str] = []
        self._log_path = self._log_dir / (
            f"{time.strftime('%Y%m%d-%H%M%S')}-{match.scenario.name.replace(' ', '_')}.json"
        )

        self._console.rule(f"{match.scenario.name}")
        self._console.print(f"[bold cyan]Buyer:[/bold cyan] {match.buyer.text}")

        for round_number in range(1, self._max_rounds + 1):
            self._evaluate(match, state, buyer_messages, seller_messages, round_number)
            turn = self._build_turn(state, buyer_messages, round_number)

            self._console.print(f"[bold green]Seller:[/bold green] {turn.text}")
            if turn.offer:
                primary = turn.offer.holiday or turn.offer.tour
                self._console.print(
                    f"[dim]offer: cost={turn.offer.cost:.0f} markup={turn.offer.markup_pct:.1f}% "
                    f"-> total~{turn.offer.cost * (1 + turn.offer.markup_pct / 100):.0f} "
                    f"({getattr(primary, 'hotel_name', None) or getattr(primary, 'name', '?')})[/dim]"
                )

            response = self._dealroom.take_turn(match.match_id, turn)
            self._console.print(f"[bold cyan]Buyer:[/bold cyan] {response.buyer.text}")
            if response.quote:
                state.quotes.append(response.quote)
                self._console.print(
                    f"[magenta]Quote:[/magenta] cost={response.quote.cost:.2f} "
                    f"markup={response.quote.markup_pct:.1f}% total={response.quote.total:.2f}"
                )

            seller_messages.append(turn.text)
            buyer_messages.append(response.buyer.text)
            state.turns.append(
                {
                    "round": round_number,
                    "seller": turn.text,
                    "offer": turn.offer.api_payload() if turn.offer else None,
                    "buyer": response.buyer.text,
                    "buyer_action": response.buyer.action.value,
                    "quote": response.quote.model_dump() if response.quote else None,
                }
            )
            self._write_log(match, state, {"closed": None, "endReason": "in-progress"})

            if response.buyer.action in {BuyerAction.ACCEPT, BuyerAction.WALK} or response.result:
                result = response.result.model_dump() if response.result else {"action": response.buyer.action.value}
                self._console.print(f"[bold]Ended:[/bold] {result}")
                self._write_log(match, state, result)
                return

            # The buyer has clearly left even if the server still says 'continue';
            # stop burning rounds, LLM calls, and rate limit on a dead conversation.
            if _conversation_is_dead(buyer_messages):
                self._console.print("[yellow]Buyer has left the conversation; stopping.[/yellow]")
                self._write_log(match, state, {"closed": False, "endReason": "buyer-left"})
                return

        self._console.print("[yellow]Round limit reached.[/yellow]")
        self._write_log(match, state, {"closed": False, "endReason": "round-limit"})

    # ------------------------------------------------------------ internal eval

    def _evaluate(
        self,
        match: MatchStart,
        state: NegotiationState,
        buyer_messages: list[str],
        seller_messages: list[str],
        round_number: int,
    ) -> None:
        transcript = _render_transcript(buyer_messages, seller_messages)

        # 1. Regex baseline, then LLM extraction layered on top.
        state.profile = infer_profile(match.scenario.name, match.scenario.brief, list(buyer_messages))
        extraction = self._profile_agent.extract(match.scenario.brief, transcript)
        state.profile = merge_extraction(state.profile, extraction)

        # 2. Psychological read of the latest buyer message.
        quote_context = (
            f"Our last quoted total was GBP {state.quotes[-1].total:.0f}" if state.quotes else "No quote sent yet"
        )
        state.read = self._profile_agent.read_buyer(buyer_messages[-1], quote_context)
        if state.read is not None and (state.read.main_objection == "price" or state.read.feels_overcharged):
            state.price_objections += 1
        else:
            state.price_objections = 0

        # After round 1, an unstated destination is treated as flexible: we would rather
        # show a strong concrete option than interrogate the buyer (they walk if we stall).
        if round_number >= 2 and not state.profile.destination:
            state.profile.destination_flexible = True

        # 3. Re-search when the picture materially changes.
        key = (
            state.profile.product_preference,
            state.profile.destination,
            state.profile.nights,
            state.profile.party_size,
            round(state.profile.budget or 0),
        )
        needs_search = key != state.search_key and state.profile.ready_to_search()
        fit_objection = state.read is not None and state.read.main_objection == "fit"
        if needs_search or (fit_objection and round_number >= 2):
            shortlist = self._search.find_shortlist(state.profile, limit=5)
            if shortlist:
                state.shortlist = shortlist
                state.search_key = key
                # Sticky candidate: once we have quoted a package, never swap it from a
                # background re-search. Buyers read unexplained hotel switches as chaos;
                # only the deliberate pivot path may change the base product.
                if not state.quotes or fit_objection:
                    pick = self._shortlist_agent.pick(state.profile, shortlist)
                    state.candidate = shortlist[pick] if pick is not None else shortlist[0]

        self._console.print(
            f"[dim]round={round_number} profile: dest={state.profile.destination or '?'} "
            f"type={state.profile.product_preference} budget={state.profile.budget} "
            f"missing={state.profile.missing_critical_fields()} "
            f"read={f'{state.read.mood}/res={state.read.resistance:.1f}' if state.read else 'n/a'} "
            f"candidate={state.candidate.candidate.name if state.candidate else 'none'}[/dim]"
        )

    def _build_turn(
        self,
        state: NegotiationState,
        buyer_messages: list[str],
        round_number: int,
    ) -> SellerTurn:
        profile = state.profile
        missing = profile.missing_critical_fields()

        # Pacing: patient buyers can absorb a probing round or two (better ceiling info);
        # impatient ones get an offer immediately. Once we CAN search, never stall again.
        buyer_impatient = state.read is not None and state.read.impatience >= 0.55
        may_ask = round_number <= (1 if buyer_impatient else 2) and not (
            buyer_impatient and profile.ready_to_search()
        )
        if missing and state.candidate is None and may_ask:
            question = self._policy.qualifying_question(profile, missing)
            text = self._composer.compose(
                intent=f"Ask the buyer (in one friendly message) about: {', '.join(missing[:3])}",
                profile=profile,
                read=state.read,
                candidate_summary="",
                fallback=question,
                last_buyer_message=buyer_messages[-1],
            )
            return SellerTurn(text=text)

        if state.candidate is None:
            if not profile.ready_to_search():
                # Assume the most common product and search broad rather than stall.
                profile.product_preference = "holiday"
            shortlist = self._search.find_shortlist(profile, limit=5)
            if shortlist:
                state.shortlist = shortlist
                pick = self._shortlist_agent.pick(profile, shortlist)
                state.candidate = shortlist[pick] if pick is not None else shortlist[0]

        if state.candidate is None:
            fallback = self._fallback_composer.no_listing_found(profile)
            text = self._composer.compose(
                intent="We could not find a live listing yet; ask for one piece of flexibility (dates or nearby destination)",
                profile=profile,
                read=state.read,
                candidate_summary="",
                fallback=fallback,
                last_buyer_message=buyer_messages[-1],
            )
            return SellerTurn(text=text)

        # The markup lever is nearly exhausted but the buyer still objects on price:
        # pivot to a cheaper base product instead of shaving pennies (buyers read
        # repeated tiny concessions as not being serious).
        state.pivoted_this_turn = False
        if (
            state.quotes
            and state.price_objections >= 1
            and state.quotes[-1].markup_pct <= 10
            and state.pivots < 2
        ):
            cheaper = self._find_cheaper_alternative(state)
            if cheaper is not None:
                state.candidate = cheaper
                state.pivots += 1
                state.pivoted_this_turn = True
                self._console.print(
                    f"[dim]pivot: switching base to {cheaper.candidate.name} "
                    f"(cost {cheaper.candidate.price_total:.0f})[/dim]"
                )

        candidate = state.candidate.candidate

        if (
            profile.wants_car
            and state.car is None
            and not state.car_searched
            and (profile.place or profile.destination or candidate.location)
        ):
            state.car_searched = True
            car_profile = profile if (profile.place or profile.destination) else replace(
                profile, place=candidate.location.split(",")[0]
            )
            state.car = self._search.find_car(car_profile)
            if state.car:
                self._console.print(
                    f"[dim]car: {state.car.name} ({state.car.raw.get('categoryName', '?')}) "
                    f"at {state.car.price_total:.0f}[/dim]"
                )
        if profile.wants_car is False:
            state.car = None

        cost = candidate.price_total + (state.car.price_total if state.car else 0)
        quote_history = "; ".join(
            f"r{i + 1}: total {q.total:.0f} at {q.markup_pct:.0f}%" for i, q in enumerate(state.quotes)
        )
        pricing = self._pricing_agent.decide(
            profile,
            state.read,
            cost=cost,
            round_number=round_number,
            max_rounds=self._max_rounds,
            quote_history=quote_history,
            pivots_available=state.pivots < 2 and len(state.shortlist) > 1,
        )
        self._console.print(
            f"[dim]pricing: markup={pricing.markup_pct:.1f}% ceiling~{pricing.ceiling_estimate} "
            f"({pricing.rationale[:90]})[/dim]"
        )

        offer = build_offer_from_candidate(candidate, pricing.markup_pct, car=state.car)
        conceding = bool(state.quotes) and pricing.markup_pct < state.quotes[-1].markup_pct - 0.5
        if state.pivoted_this_turn:
            intent = (
                "You heard their price feedback and are pivoting to a DIFFERENT property at a much "
                "better total. Acknowledge their pushback, present this alternative as an equally "
                "strong fit, state it is a significantly better number, and invite them to accept."
            )
        elif conceding:
            intent = "Concede on price gracefully and nudge them to accept; emphasise the value they keep"
        elif (
            state.quotes
            and pricing.markup_pct <= 3.1
            and state.quotes[-1].markup_pct <= 3.1
        ):
            intent = (
                "You are at your genuine floor and cannot move the price again. Hold firm with "
                "respect: say plainly this is your final and best number, the package is priced "
                "at essentially cost, and invite them to accept it as it stands."
            )
        else:
            intent = "Present this package persuasively and invite them to accept"
        if state.car:
            intent += (
                ". A car IS included: state its exact model, category and supplier from the package "
                "details. Never promise any other make or model."
            )
        summary = (
            f"{candidate.name}, {candidate.location or candidate.region}, {candidate.nights or '?'} nights, "
            f"stars={candidate.star_rating or '?'}, review={candidate.rating or '?'}, "
            f"board={candidate.board_basis or '?'}, amenities: {', '.join(candidate.amenities[:10])}"
        )
        if state.car:
            summary += (
                f"; includes car hire: {state.car.name} ({state.car.raw.get('categoryName', '')}, "
                f"{state.car.raw.get('transmission', '')}) from {state.car.operator}"
            )
        fallback = (
            self._fallback_composer.concede(state.candidate, pricing.markup_pct)
            if conceding
            else self._fallback_composer.present_offer(profile, state.candidate, pricing.markup_pct)
        )
        text = self._composer.compose(
            intent=intent,
            profile=profile,
            read=state.read,
            candidate_summary=summary,
            fallback=fallback,
            last_buyer_message=buyer_messages[-1],
        )
        return SellerTurn(text=text, offer=offer)

    def _find_cheaper_alternative(self, state: NegotiationState) -> ScoredCandidate | None:
        assert state.candidate is not None
        current = state.candidate.candidate
        target_cost = current.price_total * 0.8

        def viable(scored: ScoredCandidate) -> bool:
            c = scored.candidate
            return c.url != current.url and c.price_total <= target_cost and scored.score >= 0

        in_shortlist = [s for s in state.shortlist if viable(s)]
        if in_shortlist:
            return max(in_shortlist, key=lambda s: s.score)

        # Nothing cheap enough on hand: re-search with the implied ceiling as budget.
        implied = replace(state.profile, budget=target_cost)
        shortlist = self._search.find_shortlist(implied, limit=5)
        viable_new = [s for s in shortlist if viable(s)]
        if viable_new:
            state.shortlist = shortlist
            pick = self._shortlist_agent.pick(implied, viable_new)
            return viable_new[pick] if pick is not None and pick < len(viable_new) else viable_new[0]
        return None

    def _write_log(self, match: MatchStart, state: NegotiationState, result: dict) -> None:
        self._log_dir.mkdir(exist_ok=True)
        path = self._log_path
        path.write_text(
            json.dumps(
                {
                    "matchId": match.match_id,
                    "scenario": match.scenario.model_dump(),
                    "result": result,
                    "turns": state.turns,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self._console.print(f"[dim]log: {path}[/dim]")


_DEPARTURE_PHRASES = (
    "already gone",
    "walks toward the door",
    "out the door",
    "we are done",
    "we're done",
    "we're finished",
    "nothing more to discuss",
    "goodbye",
    "adios",
    "adiós",
    "walking away",
    "i'm walking away",
)


def _conversation_is_dead(buyer_messages: list[str]) -> bool:
    if len(buyer_messages) < 2:
        return False
    recent = [message.lower() for message in buyer_messages[-2:]]
    return all(any(phrase in message for phrase in _DEPARTURE_PHRASES) for message in recent)


def _render_transcript(buyer_messages: list[str], seller_messages: list[str]) -> str:
    lines: list[str] = []
    for i, buyer in enumerate(buyer_messages):
        lines.append(f"Buyer: {buyer}")
        if i < len(seller_messages):
            lines.append(f"Seller: {seller_messages[i]}")
    return "\n".join(lines[-20:])
