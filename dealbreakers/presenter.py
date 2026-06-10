"""Sales Presenter: rewrites draft turns into persuasive, buyer-facing pitches."""
from __future__ import annotations

import json
from typing import Any

from openai import OpenAI, RateLimitError

from .negotiation import NegotiationTracker, offer_total, product_highlights, product_label
from .orchestrator import BuyerNeeds


PRESENTER_SYSTEM = """You are a world-class luxury travel closer. You receive a draft message, structured offer
facts, and negotiation context. Write the FINAL message the buyer reads.

RULES:
- NEVER mention cost, markup, margin, agency fee, wholesale, or "what we pay". The buyer only hears
  THE TOTAL PRICE you quote (already computed for you). Never break down pre-markup numbers.
- OPEN with value: 2-3 concrete wins (review score + count, stars, board, location, amenities that
  match what they asked for, flights/transfers included when true).
- If there is a reduction vs last quote or vs opening quote, state it in pounds with confidence:
  "I've brought this down by £1,200 from where we started" or "That's £800 less than my last figure."
  Only use reduction amounts provided in context - do not invent them.
- If switching to a new property, frame it as finding them a smarter deal that still hits their
  must-haves - do not apologise for the switch.
- If buyer locked onto a specific hotel, lead with THAT name and why it delivers what they asked for.
- Close with momentum: ask for the handshake, "shall we lock this in?", "ready to book today?"
- Tone: warm, confident, concise. Match a demanding buyer with direct respect, not grovelling.
- 3-6 sentences. No bullet lists unless the buyer asked to compare options. No markdown links -
  plain text only. Quote exactly the buyer_total provided.
- Do not invent amenities, stars, or prices not in the offer facts.
- If board is AI, say all-inclusive with flights/transfers when from TravelSupermarket package.
- NEVER pitch room-only as luxury. NEVER mention euros. NEVER claim a huge discount if board was downgraded."""


class SalesPresenter:
    def __init__(self, api_key: str, model: str):
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def present(
        self,
        draft: str,
        offer: dict[str, Any],
        buyer_text: str,
        tracker: NegotiationTracker,
        needs: BuyerNeeds | None = None,
    ) -> str:
        total = offer_total(offer)
        context = {
            "buyer_said": buyer_text[:1200],
            "draft": draft[:1500],
            "product": product_label(offer),
            "highlights": product_highlights(offer),
            "buyer_total_gbp": total,
            "buyer_locked_product": tracker.buyer_locked_product,
            "reduction_vs_last_gbp": round(tracker.last_total - total, 2) if tracker.last_total and total < tracker.last_total - 1 else None,
            "reduction_vs_opening_gbp": round(tracker.opening_total - total, 2) if tracker.opening_total and total < tracker.opening_total - 1 else None,
            "opening_total_gbp": tracker.opening_total,
            "last_total_gbp": tracker.last_total,
            "price_pushbacks": tracker.price_pushbacks,
            "must_be_all_inclusive": needs.board_required == "AI" if needs else False,
            "must_include_flights": needs.wants_flights if needs else True,
        }
        try:
            response = self._chat_with_backoff(context)
            text = (response.choices[0].message.content or "").strip()
            return text or draft
        except Exception as exc:
            print(f"[presenter] fallback to draft: {exc}")
            return draft

    def _chat_with_backoff(self, context: dict[str, Any]):
        delay = 6.0
        for attempt in range(4):
            try:
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": PRESENTER_SYSTEM},
                        {
                            "role": "user",
                            "content": (
                                "Write the final buyer-facing pitch.\n\n"
                                f"CONTEXT:\n{json.dumps(context, ensure_ascii=False, indent=2)}"
                            ),
                        },
                    ],
                    temperature=0.55,
                    max_tokens=450,
                )
            except RateLimitError:
                print(f"[presenter] rate limited, retrying in {delay:.0f}s")
                import time
                time.sleep(delay)
                delay = min(delay * 1.5, 30)
        return self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": PRESENTER_SYSTEM},
                {
                    "role": "user",
                    "content": f"CONTEXT:\n{json.dumps(context, ensure_ascii=False, indent=2)}",
                },
            ],
            temperature=0.55,
            max_tokens=450,
        )
