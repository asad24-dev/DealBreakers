"""Negotiation state + deterministic strategy briefs for the sales pipeline."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .messages import is_valid_locked_name


def offer_total(offer: dict[str, Any]) -> float:
    cost = 0.0
    for key in ("holiday", "tour", "car"):
        part = offer.get(key)
        if isinstance(part, dict):
            cost += float(part.get("priceTotal") or 0)
    markup = float(offer.get("markupPct") or 0)
    return round(cost * (1 + markup / 100), 2)


def product_label(offer: dict[str, Any]) -> str:
    if offer.get("holiday"):
        return str(offer["holiday"].get("hotelName") or "Holiday")
    if offer.get("tour"):
        return str(offer["tour"].get("name") or "Tour")
    return "Package"


def product_highlights(offer: dict[str, Any]) -> dict[str, Any]:
    part = offer.get("holiday") or offer.get("tour") or {}
    if not isinstance(part, dict):
        return {}
    keys = (
        "hotelName", "name", "starRating", "reviewScore", "boardBasis", "nights",
        "durationDays", "location", "region", "country", "amenities", "operator",
    )
    return {k: part[k] for k in keys if part.get(k) not in (None, "", [])}


@dataclass
class NegotiationTracker:
    opening_total: float | None = None
    last_total: float | None = None
    last_product: str | None = None
    price_pushbacks: int = 0
    buyer_locked_product: str | None = None
    rejected_hotel_switch: bool = False
    buyer_engaged: bool = False
    rounds_with_offer: int = 0
    history: list[dict[str, Any]] = field(default_factory=list)

    def observe_buyer(self, text: str) -> None:
        locked = _extract_locked_product(text)
        if locked:
            self.buyer_locked_product = locked
        lower = text.lower()
        if any(
            phrase in lower
            for phrase in (
                "too expensive", "too steep", "too much", "come down", "reduce",
                "lower", "not acceptable", "nowhere near", "far too", "price",
                "budget", "walking", "walking away", "barely moved", "significantly lower",
                "rounding error", "not a serious reduction", "shaving",
            )
        ):
            self.price_pushbacks += 1
        if any(
            phrase in lower
            for phrase in (
                "switched propert", "switching hotels", "changed what's on the table",
                "not downgrade me", "downgrade me to a different",
            )
        ):
            self.rejected_hotel_switch = True
        if any(
            phrase in lower
            for phrase in (
                "more like it", "shows you're serious", "might have something",
                "worth talking about", "push it further", "room to work with",
                "sounds promising", "hotel sounds the part", "hotel sounds impressive",
                "that's the standard", "that's exactly the standard", "almost there",
            )
        ):
            self.buyer_engaged = True
            if self.last_product and not self.buyer_locked_product:
                self.buyer_locked_product = self.last_product

    def observe_turn(self, offer: dict[str, Any] | None, quote: dict[str, Any] | None) -> None:
        if not offer:
            return
        total = float((quote or {}).get("total") or offer_total(offer))
        product = product_label(offer)
        if self.opening_total is None:
            self.opening_total = total
        self.last_total = total
        self.last_product = product
        self.rounds_with_offer += 1
        self.history.append({"product": product, "total": total, "markupPct": offer.get("markupPct")})

    def strategy_brief(self, offer: dict[str, Any] | None, round_no: int, max_rounds: int) -> str:
        lines = [f"STRATEGY BRIEF (round {round_no}/{max_rounds}, internal only):"]
        if self.buyer_locked_product:
            lines.append(
                f"- Buyer locked onto: {self.buyer_locked_product}. Your structured offer MUST be that "
                "property on a full TravelSupermarket package, not a different hotel."
            )
        if self.rejected_hotel_switch:
            lines.append("- Buyer rejected hotel switches. Stay on the locked hotel or ask permission first.")
        if self.price_pushbacks >= 2:
            lines.append(
                "- STRONG price resistance: do NOT nibble markup. Re-search TravelSupermarket for a "
                "structurally cheaper FULL PACKAGE (same hotel, different departure month/airport, "
                "or cheapest 5-star AI package). NEVER use trivago hotel-only for package buyers."
            )
        elif self.price_pushbacks == 1:
            lines.append(
                "- First price pushback: one markup step OR pivot to your pre-scouted cheaper backup "
                "at full markup if the gap is large."
            )
        if offer:
            total = offer_total(offer)
            lines.append(f"- This offer quotes the buyer £{total:,.0f} (ONLY number they may hear).")
            if self.last_total and total < self.last_total - 50:
                lines.append(f"- Reduction vs last quote: £{self.last_total - total:,.0f}. SELL this hard.")
            if self.opening_total and total < self.opening_total - 50:
                lines.append(f"- Reduction vs opening quote: £{self.opening_total - total:,.0f}. SELL this hard.")
        if round_no >= max_rounds - 3:
            lines.append("- ENDGAME: close now. Markup 3-5% on best fit. Ask for the handshake.")
        lines.append(
            "- NEVER mention cost, markup, margin, or 'our fee' in send_turn text. "
            "The Persuasion layer will rewrite your message anyway - keep offer facts accurate."
        )
        return "\n".join(lines)


def _extract_locked_product(text: str) -> str | None:
    """Best-effort: hotel/tour name the buyer explicitly picked."""
    for match in re.finditer(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,4})\b", text):
        name = match.group(1).strip()
        if is_valid_locked_name(name):
            return name

    patterns = [
        r"(?:the\s+)?([A-Z][a-z]+(?:\s+[A-Z][\w&'-]+){1,4})\s+(?:catches my eye|catches my attention|is the one|works for me|that one)",
        r"([A-Z][a-z]+(?:\s+[A-Z][\w&'-]+){1,4})\s+(?:on the beach|with that score).{0,40}(?:catches|is the one)",
        r"(?:love|like|want)\s+(?:the\s+)?([A-Z][a-z]+(?:\s+[A-Z][\w&'-]+){1,4})",
        r"sharp(?:en)?\s+(?:the\s+)?deal\s+on\s+(?:the\s+)?([A-Z][a-z]+(?:\s+[A-Z][\w&'-]+){1,4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            name = match.group(1).strip()
            if is_valid_locked_name(name):
                return name
    return None
