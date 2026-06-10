from __future__ import annotations

from typing import Any

from .config import Settings
from .dealroom import DealRoomClient
from .inventory import InventoryBroker
from .llm import MessagePolisher
from .negotiator import Negotiator


class MatchRunner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.dealroom = DealRoomClient(settings.dealroom_base_url, settings.team_key, settings.request_timeout)
        self.inventory = InventoryBroker(settings.request_timeout)
        self.polisher = MessagePolisher(settings.openai_api_key, settings.model)

    def run(self, practice: bool, persona_id: str | None = None) -> None:
        self.inventory.connect()
        while True:
            match = self.dealroom.start_match(practice=practice, persona_id=persona_id)
            if match.get("done"):
                print("[dealroom] all official matches complete")
                return
            self._run_match(match)
            if practice or persona_id:
                return

    def _run_match(self, match: dict[str, Any]) -> None:
        match_id = match["matchId"]
        negotiator = Negotiator()
        negotiator.observe_opening(match)
        print(f"[dealroom] match {match_id}: {(match.get('scenario') or {}).get('name')}")
        print(f"[buyer] {(match.get('buyer') or {}).get('text', '')}")
        status = match.get("status")
        response = match
        while status == "awaiting-seller":
            negotiator.round_no += 1
            listings = self.inventory.search(negotiator.profile)
            plan = negotiator.choose_offer(listings)
            should_offer = plan is not None and (negotiator.round_no >= 2 or negotiator.profile.budget_hint)
            draft = negotiator.next_message(can_offer=bool(should_offer))
            offer = negotiator.offer_to_payload(plan) if should_offer and plan else None
            text = self.polisher.polish(draft, negotiator.profile, plan if offer else None)
            print(f"[seller] round {negotiator.round_no}: {text}")
            if offer:
                print(f"[offer] {offer}")
            response = self.dealroom.take_turn(match_id, text=text, offer=offer)
            buyer = response.get("buyer") or {}
            print(f"[buyer] {buyer.get('text', '')}")
            if response.get("quote"):
                print(f"[quote] {response['quote']}")
            negotiator.update_profile(buyer.get("text", ""))
            status = response.get("status")
            if status == "ended":
                print(f"[result] {response.get('result')}")
                return
            if negotiator.round_no >= max(1, self.settings.max_seller_rounds - 1):
                final_text = "I can meet you at the sharpest price I can justify on the live listing. If this works, I would accept now rather than risk losing availability."
                final_offer = negotiator.offer_to_payload(plan) if plan else None
                response = self.dealroom.take_turn(match_id, text=final_text, offer=final_offer)
                print(f"[result] {response.get('result')}")
                return
