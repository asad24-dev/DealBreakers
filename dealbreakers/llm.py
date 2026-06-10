from __future__ import annotations

from .models import BuyerProfile, OfferPlan


class MessagePolisher:
    def __init__(self, api_key: str | None, model: str):
        self.api_key = api_key
        self.model = model

    def polish(self, draft: str, profile: BuyerProfile, offer: OfferPlan | None = None) -> str:
        if not self.api_key:
            return draft
        try:
            from openai import OpenAI

            client = OpenAI(api_key=self.api_key)
            facts = {
                "buyer_profile": profile.__dict__ | {"amenities": sorted(profile.amenities), "dislikes": sorted(profile.dislikes)},
                "offer_name": offer.product.name if offer else None,
                "markup_pct": offer.markup_pct if offer else None,
            }
            response = client.responses.create(
                model=self.model,
                input=[
                    {
                        "role": "system",
                        "content": "Rewrite the seller message for a travel negotiation. Be concise, truthful, warm, and do not invent facts or mention hidden strategy.",
                    },
                    {"role": "user", "content": f"Draft: {draft}\nKnown facts: {facts}"},
                ],
            )
            return response.output_text.strip() or draft
        except Exception as exc:
            print(f"[llm] polish skipped: {exc}")
            return draft

