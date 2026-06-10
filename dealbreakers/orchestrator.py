"""Satisfaction orchestrator: reads buyer state and routes the next seller action."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from .messages import is_valid_locked_name
from .negotiation import NegotiationTracker, offer_total


@dataclass
class BuyerNeeds:
    """Inferred must-haves that every offer must satisfy."""
    trip_style: str = "package"  # package | tour | city_hotel
    min_stars: float | None = None
    board_required: str | None = None  # AI, BB, etc.
    wants_flights: bool = True
    luxury: bool = False
    locked_hotel: str | None = None
    rejected_room_only: bool = False
    rejected_hotel_switch: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class ActionPlan:
    action: str  # SEARCH_THEN_OFFER | OFFER | MESSAGE_ONLY
    instructions: str
    needs: BuyerNeeds
    search_hints: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)

    def to_brief(self) -> str:
        lines = [
            "=== SATISFACTION ORCHESTRATOR (follow exactly) ===",
            f"ACTION: {self.action}",
            self.instructions,
        ]
        if self.search_hints:
            lines.append("SEARCH HINTS: " + "; ".join(self.search_hints))
        if self.forbidden:
            lines.append("FORBIDDEN: " + "; ".join(self.forbidden))
        if self.needs.locked_hotel:
            lines.append(f"BUYER LOCKED HOTEL: {self.needs.locked_hotel}")
        if self.needs.board_required:
            lines.append(f"BOARD REQUIRED: {self.needs.board_required} (never downgrade board)")
        if self.needs.luxury:
            lines.append("LUXURY MODE: 5-star full packages only - flights + hotel bundled from TravelSupermarket.")
        lines.append("=== END ORCHESTRATOR ===")
        return "\n".join(lines)


ORCHESTRATOR_SYSTEM = """You are the satisfaction / strategy director for a travel sales team.
Given buyer messages and negotiation history, decide the NEXT seller action.

Actions:
- SEARCH_THEN_OFFER: run MCP inventory searches first, then send_turn with a structured offer.
- OFFER: send_turn with offer immediately (no new search needed).
- MESSAGE_ONLY: send_turn without offer (rare - only early discovery).

Rules you MUST enforce:
1. If buyer wants luxury / 5-star / all-inclusive PACKAGE: NEVER route to trivago hotel-only or
   room-only (RO board). Use travelsupermarket search-holidays only (flights+hotel bundled).
2. If buyer locked onto a specific hotel: re-search THAT hotel on TravelSupermarket with different
   departure months/airports/brands - do NOT switch hotels unless buyer explicitly allows it.
3. If buyer rejected a tiny markup cut (<£500 reduction): action is SEARCH_THEN_OFFER for a
   structurally cheaper FULL PACKAGE (same hotel different departure, or cheaper 5-star AI package).
4. Round 1 luxury buyer: search for CHEAPEST qualifying 5-star all-inclusive PACKAGE first -
   open with the lowest totalPrice that meets stars/reviews, not the most expensive.
5. If buyer asked for all-inclusive back after room-only offer: board_required=AI, forbidden=trivago.
6. Never switch hotels silently when buyer locked onto one - if pivoting, buyer must have given up
   on the locked hotel.

Respond JSON only:
{
  "action": "SEARCH_THEN_OFFER|OFFER|MESSAGE_ONLY",
  "instructions": "2-4 sentences for the inventory agent",
  "search_hints": ["travelsupermarket search-holidays ..."],
  "forbidden": ["trivago", "room-only", "switch hotel"],
  "board_required": "AI|null",
  "luxury": true/false,
  "wants_flights": true/false
}"""


class SatisfactionOrchestrator:
    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.needs = BuyerNeeds()

    def plan(
        self,
        buyer_text: str,
        tracker: NegotiationTracker,
        round_no: int,
        scenario_brief: str,
        last_offer: dict[str, Any] | None = None,
    ) -> ActionPlan:
        self._update_needs(buyer_text, tracker, last_offer)
        if tracker.rejected_hotel_switch:
            self.needs.rejected_hotel_switch = True
        plan = self._llm_plan(buyer_text, tracker, round_no, scenario_brief, last_offer)
        plan = self._apply_hard_rules(plan, tracker, round_no, last_offer)
        plan.needs = self.needs
        print(f"[orchestrator] {plan.action} | {plan.instructions[:120]}")
        if plan.forbidden:
            print(f"[orchestrator] forbidden: {', '.join(plan.forbidden)}")
        return plan

    def _update_needs(
        self, buyer_text: str, tracker: NegotiationTracker, last_offer: dict[str, Any] | None
    ) -> None:
        lower = buyer_text.lower()
        if tracker.buyer_locked_product:
            self.needs.locked_hotel = tracker.buyer_locked_product
        if any(w in lower for w in ("five-star", "5-star", "5 star", "luxury", "no compromises", "top-tier", "perfectionist")):
            self.needs.luxury = True
            self.needs.min_stars = 5.0
        if any(w in lower for w in ("all-inclusive", "all inclusive", "full board", "full experience")):
            self.needs.board_required = "AI"
            self.needs.wants_flights = True
            self.needs.trip_style = "package"
        if any(w in lower for w in ("room-only", "room only", "not the luxury", "nickel-and-dimed", "stripped out")):
            self.needs.rejected_room_only = True
            self.needs.board_required = "AI"
            self.needs.wants_flights = True
        if any(w in lower for w in ("switched propert", "changed what's on the table", "switching hotels", "not downgrade me", "same hotel", "that original")):
            self.needs.rejected_hotel_switch = True
        if any(w in lower for w in ("guided tour", "multi-day tour")):
            self.needs.trip_style = "tour"
            self.needs.wants_flights = False
        if any(w in lower for w in ("city break", "city-break")):
            self.needs.trip_style = "city_hotel"
            self.needs.wants_flights = False

    def _llm_plan(
        self,
        buyer_text: str,
        tracker: NegotiationTracker,
        round_no: int,
        scenario_brief: str,
        last_offer: dict[str, Any] | None,
    ) -> ActionPlan:
        context = {
            "round": round_no,
            "scenario": scenario_brief,
            "buyer_text": buyer_text[:1500],
            "needs_so_far": self.needs.__dict__,
            "price_pushbacks": tracker.price_pushbacks,
            "locked_hotel": tracker.buyer_locked_product,
            "opening_total": tracker.opening_total,
            "last_total": tracker.last_total,
            "last_product": tracker.last_product,
            "history": tracker.history[-4:],
            "last_offer_board": (last_offer or {}).get("holiday", {}).get("boardBasis"),
            "last_offer_source": _offer_source(last_offer),
        }
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": ORCHESTRATOR_SYSTEM},
                    {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
                ],
                temperature=0.2,
                max_tokens=400,
                response_format={"type": "json_object"},
            )
            data = json.loads(response.choices[0].message.content or "{}")
            needs = self.needs
            if data.get("board_required"):
                needs.board_required = str(data["board_required"])
            if data.get("luxury") is True:
                needs.luxury = True
            if data.get("wants_flights") is False:
                needs.wants_flights = False
            return ActionPlan(
                action=str(data.get("action") or "SEARCH_THEN_OFFER"),
                instructions=str(data.get("instructions") or "Search and offer the best fit."),
                search_hints=list(data.get("search_hints") or []),
                forbidden=list(data.get("forbidden") or []),
                needs=needs,
            )
        except Exception as exc:
            print(f"[orchestrator] LLM fallback: {exc}")
            return self._fallback_plan(tracker, round_no)

    def _fallback_plan(self, tracker: NegotiationTracker, round_no: int) -> ActionPlan:
        if round_no == 1 and self.needs.luxury:
            return ActionPlan(
                action="SEARCH_THEN_OFFER",
                instructions=(
                    "Search travelsupermarket for 5-star all-inclusive packages (theme=luxury, boardBasis=AI). "
                    "Pick the CHEAPEST qualifying full package (totalPrice) with strong reviews. Offer ONLY that one."
                ),
                search_hints=[
                    'travelsupermarket: starRating=5, theme=luxury, boardBasis=AI, adults=1, children=0, limit=10',
                ],
                forbidden=["trivago", "room-only", "RO board"],
                needs=self.needs,
            )
        if self.needs.rejected_room_only or self.needs.board_required == "AI":
            hotel = self.needs.locked_hotel or tracker.buyer_locked_product
            if hotel and not is_valid_locked_name(hotel):
                hotel = None
            hint = f"destination={hotel or 'Turkey'}, starRating=5, boardBasis=AI"
            return ActionPlan(
                action="SEARCH_THEN_OFFER",
                instructions=(
                    f"Re-search TravelSupermarket for a full all-inclusive PACKAGE (flights included) "
                    f"{'for ' + hotel if hotel else ''} with different departure months/airports. "
                    "Never use trivago hotel-only."
                ),
                search_hints=[f"travelsupermarket: {hint}"],
                forbidden=["trivago", "room-only", "RO"],
                needs=self.needs,
            )
        if tracker.price_pushbacks >= 2:
            return ActionPlan(
                action="SEARCH_THEN_OFFER",
                instructions="Strong price resistance - search for a structurally cheaper 5-star AI package on TravelSupermarket.",
                search_hints=["travelsupermarket: starRating=5, boardBasis=AI, maxPrice filter"],
                forbidden=["trivago", "markup-only concession"],
                needs=self.needs,
            )
        return ActionPlan(
            action="SEARCH_THEN_OFFER",
            instructions="Search inventory and make a concrete offer.",
            needs=self.needs,
        )

    def _apply_hard_rules(
        self,
        plan: ActionPlan,
        tracker: NegotiationTracker,
        round_no: int,
        last_offer: dict[str, Any] | None,
    ) -> ActionPlan:
        forbidden = set(plan.forbidden)
        hints = list(plan.search_hints)

        if self.needs.trip_style == "package" and self.needs.wants_flights:
            forbidden.update({"trivago", "trivago hotel-only", "room-only", "RO board", "RO"})
        if self.needs.rejected_room_only:
            forbidden.update({"trivago", "room-only", "RO"})
            self.needs.board_required = "AI"
        if self.needs.locked_hotel and self.needs.rejected_hotel_switch:
            forbidden.add("switch hotel")
            plan.instructions += (
                f" Stay on {self.needs.locked_hotel} - re-source via TravelSupermarket only."
            )
        locked = self.needs.locked_hotel or tracker.buyer_locked_product
        if locked and not is_valid_locked_name(locked):
            self.needs.locked_hotel = None
            tracker.buyer_locked_product = None
        if round_no == 1 and self.needs.luxury:
            plan.action = "SEARCH_THEN_OFFER"
            plan.instructions = (
                "Round 1 LUXURY: run travelsupermarket search-holidays with starRating=5, theme=luxury, "
                "boardBasis=AI, adults=1, children=0, limit=10. From results pick the offer with the "
                "LOWEST totalPrice that has reviewScore >= 8.5. Sort every result by totalPrice ascending "
                "and pick the cheapest first — higher review score is NOT a reason to pick a pricier option "
                "on round 1. One hotel in structured offer only."
            )
            hints.append("Sort mentally by totalPrice ascending; pick #1 that qualifies.")
            forbidden.update({"trivago", "multi-hotel menu without single offer"})
        # Buyer warmed up after a big price drop -> close via markup, not another tiny re-search.
        if tracker.buyer_engaged and last_offer and round_no >= 2:
            part = last_offer.get("holiday") or last_offer.get("tour") or {}
            cost = part.get("priceTotal")
            markup = float(last_offer.get("markupPct") or 15)
            target = max(3.0, round(markup - 10, 1))
            plan.action = "SEARCH_THEN_OFFER"
            plan.instructions = (
                f"Buyer is negotiating positively - CLOSE NOW. Keep the same listing (priceTotal={cost}, "
                f"same url). Do NOT re-search or switch hotels. Set markupPct={target} (down from {markup}). "
                "The Persuasion layer will sell the reduction - ask for the handshake."
            )
            forbidden.discard("markup-only concession")
        elif len(tracker.history) >= 2:
            last_drop = tracker.history[-2]["total"] - tracker.history[-1]["total"]
            if 0 < last_drop < 400 and tracker.price_pushbacks >= 2 and not tracker.buyer_engaged:
                plan.action = "SEARCH_THEN_OFFER"
                plan.instructions = (
                    "Last price drop was under £400 and buyer is still hostile. Re-search TravelSupermarket "
                    "for a structurally cheaper full package or same hotel on a different departure."
                )
                forbidden.add("markup-only concession")

        plan.forbidden = sorted(forbidden)
        plan.search_hints = hints
        plan.needs = self.needs
        return plan


def validate_offer_for_needs(offer: dict[str, Any], needs: BuyerNeeds) -> str | None:
    """Return error string if offer violates buyer needs, else None."""
    holiday = offer.get("holiday")
    if not holiday:
        return None
    board = str(holiday.get("boardBasis") or "").upper()
    url = str(holiday.get("url") or "").lower()
    name = str(holiday.get("hotelName") or "")

    if needs.board_required == "AI" and board == "RO":
        return "buyer requires all-inclusive (AI) - room-only (RO) is forbidden"
    if needs.wants_flights and needs.trip_style == "package" and "trivago" in url:
        return "buyer wants a full holiday PACKAGE (flights+hotel) - trivago hotel-only is forbidden"
    if needs.min_stars and holiday.get("starRating"):
        if float(holiday["starRating"]) < needs.min_stars:
            return f"buyer requires {needs.min_stars}-star minimum"
    if needs.locked_hotel and needs.rejected_hotel_switch:
        locked = needs.locked_hotel
        if locked and is_valid_locked_name(locked):
            if locked.lower() not in name.lower() and not _fuzzy_hotel_match(locked, name):
                return f"buyer locked onto '{locked}' - do not switch hotels without permission"
    if needs.rejected_room_only and board == "RO":
        return "buyer already rejected room-only"
    return None


def _fuzzy_hotel_match(locked: str, offered: str) -> bool:
    locked_tokens = set(re.findall(r"[a-z]{4,}", locked.lower()))
    offered_tokens = set(re.findall(r"[a-z]{4,}", offered.lower()))
    return len(locked_tokens & offered_tokens) >= 2


def _offer_source(offer: dict[str, Any] | None) -> str | None:
    if not offer:
        return None
    sources = offer.get("sources") or []
    if sources and isinstance(sources[0], dict):
        return sources[0].get("mcp")
    url = str((offer.get("holiday") or {}).get("url") or "")
    return "trivago" if "trivago" in url else "travelsupermarket"
