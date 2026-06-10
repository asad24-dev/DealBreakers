"""Pricing strategy: ceiling inference, amenity-filtered search, margin ladder."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .negotiation import NegotiationTracker, offer_total
from .prompts import AMENITY_VOCAB, TSM_FACILITY_MAP

# Reverse map: canonical amenity -> TSM facility ID(s)
_AMENITY_TO_TSM: dict[str, int] = {v: k for k, v in TSM_FACILITY_MAP.items()}

# Margin ladder phases (generic — works for any buyer)
PHASE_ANCHOR = "ANCHOR"           # cheapest fit + high markup
PHASE_CONCEDE = "CONCEDE_MARKUP"  # same product, lower markup toward ceiling
PHASE_RESOURCE = "RE_SOURCE"      # same constraints, cheaper listing (cost cut)
PHASE_CLOSE = "CLOSE"             # buyer warm — land just under ceiling
PHASE_GAP = "STRUCTURAL_GAP"      # cheapest fit still above ceiling — must relax or pivot


@dataclass
class CeilingModel:
    """Hidden budget inferred from buyer reactions (never say this aloud)."""
    reject_above: float | None = None   # last quote they rejected → ceiling likely below this
    accept_below: float | None = None   # quote they warmed to → ceiling likely above this
    stated_budget: float | None = None  # if they said "£X" explicitly

    @property
    def best_guess(self) -> float | None:
        if self.stated_budget:
            return self.stated_budget
        if self.reject_above and self.accept_below:
            return (self.reject_above + self.accept_below) / 2
        if self.reject_above:
            return self.reject_above * 0.88
        if self.accept_below:
            return self.accept_below * 1.08
        return None


@dataclass
class StrategyState:
    amenities: set[str] = field(default_factory=set)
    min_stars: float | None = None
    board: str | None = None
    luxury: bool = False
    solo: bool = False
    ceiling: CeilingModel = field(default_factory=CeilingModel)
    phase: str = PHASE_ANCHOR
    last_cost: float | None = None
    last_markup: float | None = None
    markup_ladder: list[float] = field(default_factory=lambda: [18.0, 14.0, 10.0, 7.0, 5.0, 3.0])
    ladder_index: int = 0


def infer_amenities(text: str) -> set[str]:
    lower = text.lower().replace("_", " ")
    found: set[str] = set()
    for amenity in AMENITY_VOCAB:
        token = amenity.replace("_", " ")
        if token in lower or amenity in lower:
            found.add(amenity)
    if any(w in lower for w in ("beach", "beachy", "coastal", "seaside")):
        found.add("close_to_beach")
    if any(w in lower for w in ("review", "reviews", "rating")):
        pass  # handled via reviewScore in search, not TSM facility
    return found


def tsm_facility_ids(amenities: set[str]) -> str | None:
    ids = sorted({_AMENITY_TO_TSM[a] for a in amenities if a in _AMENITY_TO_TSM})
    return ",".join(str(i) for i in ids) if ids else None


def infer_stated_budget(text: str) -> float | None:
    money = re.findall(r"(?:£|gbp\s*)\s*(\d{3,6})", text.lower())
    if money:
        return float(money[-1])
    return None


class StrategyEngine:
    """Deterministic negotiation strategy (margin score = (quote-cost)/(ceiling-cost))."""

    def __init__(self) -> None:
        self.state = StrategyState()

    def observe_buyer(self, text: str, tracker: NegotiationTracker) -> None:
        lower = text.lower()
        self.state.amenities |= infer_amenities(text)
        if any(w in lower for w in ("five-star", "5-star", "5 star", "luxury")):
            self.state.luxury = True
            self.state.min_stars = 5.0
        stars = re.search(r"([345])\s*(?:\+|-)?\s*star", lower)
        if stars:
            self.state.min_stars = float(stars.group(1))
        if any(w in lower for w in ("all-inclusive", "all inclusive")):
            self.state.board = "AI"
        if any(w in lower for w in ("solo", "just me", "traveling solo", "on my own")):
            self.state.solo = True
        budget = infer_stated_budget(text)
        if budget:
            self.state.ceiling.stated_budget = budget

        # Ceiling inference from reactions to OUR last quote
        if tracker.last_total:
            hostile = any(
                p in lower
                for p in (
                    "outrageous", "not happening", "far too", "way beyond", "walking",
                    "done here", "not a chance", "absolutely not", "too high", "too steep",
                    "not moved a penny", "sharpen your pencil",
                )
            )
            warm = tracker.buyer_engaged or any(
                p in lower
                for p in ("more like it", "shows you're serious", "hotel sounds", "push it further", "room to work with")
            )
            if hostile:
                self.state.ceiling.reject_above = tracker.last_total
                self.state.ladder_index = min(self.state.ladder_index + 1, len(self.state.markup_ladder) - 1)
            if warm and not hostile:
                self.state.ceiling.accept_below = tracker.last_total
                self.state.phase = PHASE_CLOSE

        self._pick_phase(tracker)

    def observe_offer(self, offer: dict[str, Any] | None, quote: dict[str, Any] | None) -> None:
        if not offer:
            return
        part = offer.get("holiday") or offer.get("tour") or {}
        if part.get("priceTotal"):
            self.state.last_cost = float(part["priceTotal"])
        self.state.last_markup = float(offer.get("markupPct") or 0)

    def _pick_phase(self, tracker: NegotiationTracker) -> None:
        if self.state.phase == PHASE_CLOSE:
            return
        if tracker.price_pushbacks >= 2 and not tracker.buyer_engaged:
            self.state.phase = PHASE_RESOURCE
        elif tracker.price_pushbacks >= 1:
            self.state.phase = PHASE_CONCEDE
        else:
            self.state.phase = PHASE_ANCHOR

    def target_markup(self, cost: float) -> float:
        ceiling = self.state.ceiling.best_guess
        if ceiling and cost > 0:
            # Land at ~94% of inferred ceiling to maximize margin score safely
            target_total = ceiling * 0.94
            if target_total <= cost:
                self.state.phase = PHASE_GAP
                return 3.0
            pct = (target_total / cost - 1) * 100
            return round(max(3.0, min(18.0, pct)), 1)
        if self.state.phase == PHASE_ANCHOR:
            return self.state.markup_ladder[0]
        if self.state.phase in (PHASE_CONCEDE, PHASE_CLOSE):
            idx = min(self.state.ladder_index, len(self.state.markup_ladder) - 1)
            return self.state.markup_ladder[idx]
        return self.state.markup_ladder[min(self.state.ladder_index, len(self.state.markup_ladder) - 1)]

    def search_params(self) -> dict[str, Any]:
        """Build travelsupermarket search-holidays args from inferred must-haves."""
        params: dict[str, Any] = {
            "adults": "1" if self.state.solo else "2",
            "children": "0",
            "limit": 10,
            "departureMonth": "6,7,8",
        }
        if self.state.min_stars:
            params["starRating"] = str(int(self.state.min_stars))
        if self.state.luxury:
            params["theme"] = "luxury"
        if self.state.board:
            params["boardBasis"] = self.state.board
        fac = tsm_facility_ids(self.state.amenities)
        if fac:
            params["facilities"] = fac
        return params

    def brief(self, tracker: NegotiationTracker, round_no: int, last_offer: dict[str, Any] | None) -> str:
        lines = [
            "=== PRICING STRATEGY (internal — never mention ceiling/markup to buyer) ===",
            f"PHASE: {self.state.phase}",
            "MARGIN SCORE = (quote - cost) / (ceiling - cost). Infer ceiling, quote just under it.",
        ]
        if self.state.amenities:
            lines.append(f"MUST-HAVE AMENITIES (filter search + declare in offer): {', '.join(sorted(self.state.amenities))}")
            sp = self.search_params()
            lines.append(f"TSM SEARCH PARAMS: {sp}")
        if self.state.ceiling.best_guess:
            lines.append(f"INFERRED CEILING ~£{self.state.ceiling.best_guess:,.0f} (reject_above={self.state.ceiling.reject_above}, accept_below={self.state.ceiling.accept_below})")
        if self.state.phase == PHASE_ANCHOR:
            lines.append(
                "ANCHOR: search with amenity filters; pick LOWEST totalPrice listing that satisfies "
                f"all constraints; markupPct={self.state.markup_ladder[0]}."
            )
        elif self.state.phase == PHASE_CONCEDE and last_offer:
            cost = self.state.last_cost or (last_offer.get("holiday") or {}).get("priceTotal")
            if cost:
                mk = self.target_markup(float(cost))
                lines.append(
                    f"CONCEDE: keep same listing (priceTotal={cost}); set markupPct={mk} "
                    f"(target total ~£{float(cost) * (1 + mk/100):,.0f}). Do NOT re-search yet."
                )
        elif self.state.phase == PHASE_RESOURCE:
            lines.append(
                "RE-SOURCE: search again with same amenity filters; pick a NEW cheaper listing "
                "(different departure/hotel) at full anchor markup. Cost must drop, not just markup."
            )
        elif self.state.phase == PHASE_CLOSE and last_offer:
            cost = self.state.last_cost
            if cost:
                mk = self.target_markup(float(cost))
                lines.append(f"CLOSE NOW: same product, markupPct={mk}, ask for handshake.")
        elif self.state.phase == PHASE_GAP:
            lines.append(
                "STRUCTURAL GAP: even cheapest amenity-fit may exceed ceiling — re-search with "
                "maxPrice or relax one soft amenity; or hold at 3% markup and close."
            )
        if round_no == 1:
            lines.append("Round 1: one offer only — cheapest qualifying package after filtered search.")
        lines.append("=== END STRATEGY ===")
        return "\n".join(lines)
