from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .agent import SellerAgent
from .config import TRAVEL_MCP_ENDPOINTS, Settings
from .dealroom import DealRoomClient, DealRoomRejection
from .mcp_client import StreamableMCPClient
from .messages import is_stall_message
from .negotiation import NegotiationTracker, offer_total
from .orchestrator import SatisfactionOrchestrator, validate_offer_for_needs
from .presenter import SalesPresenter
from .prompts import ROUND_NOTE_ENDGAME, ROUND_NOTE_MUST_OFFER, ROUND_NOTE_NORMAL
from .strategy import StrategyEngine


MUST_OFFER_NOTE = (
    "CRITICAL: send_turn MUST include a structured offer this round. "
    "Forbidden phrases: technical issue, bear with me, shortly, checking, working on it. "
    "Run inventory tools if needed, then call send_turn with offer + brief factual text."
)


class MatchRunner:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.dealroom = DealRoomClient(settings.dealroom_base_url, settings.team_key, settings.request_timeout)
        self.clients = {
            name: StreamableMCPClient(name, url, timeout=settings.request_timeout)
            for name, url in TRAVEL_MCP_ENDPOINTS.items()
        }
        self.tools_by_server: dict[str, list[dict[str, Any]]] = {}

    def connect(self) -> None:
        for name, client in self.clients.items():
            for attempt in range(3):
                try:
                    client.initialize()
                    self.tools_by_server[name] = client.list_tools()
                    print(f"[mcp] {name}: {len(self.tools_by_server[name])} tools")
                    break
                except Exception as exc:
                    if attempt == 2:
                        self.tools_by_server[name] = []
                        print(f"[mcp] {name}: unavailable after 3 attempts ({exc})")
                    else:
                        time.sleep(3 * (attempt + 1))

    def _reconnect_missing(self) -> None:
        """Before each match, retry any MCP server that was down earlier."""
        for name, tools in list(self.tools_by_server.items()):
            if tools:
                continue
            try:
                client = self.clients[name]
                client.initialize()
                self.tools_by_server[name] = client.list_tools()
                print(f"[mcp] {name}: reconnected ({len(self.tools_by_server[name])} tools)")
            except Exception as exc:
                print(f"[mcp] {name}: still unavailable ({exc})")

    def run(self, practice: bool, persona_id: str | None = None) -> None:
        self.connect()
        while True:
            self._reconnect_missing()
            match = self.dealroom.start_match(practice=practice, persona_id=persona_id)
            if match.get("done"):
                print("[dealroom] all official matches complete")
                return
            self._run_match(match)
            if practice or persona_id:
                return

    def _run_match(self, match: dict[str, Any]) -> None:
        match_id = match["matchId"]
        scenario = match.get("scenario") or {}
        log = MatchLog(match_id)
        log.write("match-start", match)
        print(f"[dealroom] match {match_id}: {scenario.get('name')}")

        agent = SellerAgent(
            openai_api_key=self.settings.openai_api_key,
            model=self.settings.model,
            clients=self.clients,
            tools_by_server=self.tools_by_server,
            scenario_name=scenario.get("name", "Unknown buyer"),
            scenario_brief=scenario.get("brief", ""),
            max_rounds=self.settings.max_seller_rounds,
        )
        presenter = SalesPresenter(self.settings.openai_api_key, self.settings.aux_model)
        orchestrator = SatisfactionOrchestrator(self.settings.openai_api_key, self.settings.aux_model)
        strategy_engine = StrategyEngine()
        tracker = NegotiationTracker()
        scenario_brief = scenario.get("brief", "")
        last_offer: dict[str, Any] | None = None

        buyer_text = (match.get("buyer") or {}).get("text", "")
        print(f"[buyer] {buyer_text}")
        tracker.observe_buyer(buyer_text)
        strategy_engine.observe_buyer(buyer_text, tracker)
        offered_yet = False
        round_no = 0

        while True:
            round_no += 1
            note = self._round_note(round_no, offered_yet)
            plan = orchestrator.plan(buyer_text, tracker, round_no, scenario_brief, last_offer)
            strategy = tracker.strategy_brief(None, round_no, self.settings.max_seller_rounds)
            pricing = strategy_engine.brief(tracker, round_no, last_offer)
            print(f"[strategy] phase={strategy_engine.state.phase} ceiling~{strategy_engine.state.ceiling.best_guess}")
            combined_note = f"{pricing}\n\n{plan.to_brief()}\n\n{strategy}\n\n{note}"
            needs_offer = plan.action == "SEARCH_THEN_OFFER" or offered_yet or round_no >= 2
            text, offer = self._respond_with_offer(agent, buyer_text, combined_note, needs_offer)
            if offer:
                violation = validate_offer_for_needs(offer, plan.needs)
                if violation:
                    print(f"[guardrail] offer rejected: {violation}")
                    text, offer = self._respond_safely(
                        agent,
                        None,
                        f"OFFER REJECTED (satisfaction guardrail): {violation}. "
                        "Follow the orchestrator instructions and call send_turn again with a compliant offer.",
                    )
                if offer and tracker.last_total and abs(offer_total(offer) - tracker.last_total) < 1:
                    print("[guardrail] duplicate price - forcing markup concession")
                    part = (offer.get("holiday") or offer.get("tour") or {})
                    cost = part.get("priceTotal")
                    markup = float(offer.get("markupPct") or 15)
                    target = max(3.0, round(markup - 8, 1))
                    text, offer = self._respond_safely(
                        agent,
                        None,
                        f"FORBIDDEN: same total as last round (£{tracker.last_total:.0f}). "
                        f"Keep priceTotal={cost}, set markupPct={target} (was {markup}), resend offer.",
                    )
                if is_stall_message(text) and offer:
                    print("[guardrail] stripping stall phrasing - presenter will rewrite")
                computed = offer_total(offer)
                pitch = presenter.present(text, offer, buyer_text, tracker, plan.needs)
                print(f"[seller] round {round_no} (draft): {text[:200]}{'...' if len(text) > 200 else ''}")
                print(f"[seller] round {round_no} (pitch): {pitch}")
                text = pitch
            elif needs_offer and (not offer or is_stall_message(text)):
                print("[runner] blocking empty/stall turn - recovery attempt")
                text, offer = self._respond_safely(agent, buyer_text, MUST_OFFER_NOTE)
                if offer:
                    computed = offer_total(offer)
                    text = presenter.present(text, offer, buyer_text, tracker, plan.needs)
                    print(f"[seller] round {round_no} (recovery pitch): {text}")
                else:
                    print(f"[seller] round {round_no}: {text}")
            else:
                print(f"[seller] round {round_no}: {text}")
            if offer:
                print(f"[offer] total £{computed:,.2f} | {json.dumps(offer, ensure_ascii=False)}")

            response = self._take_turn(agent, match_id, text, offer, log)
            if response is None:
                # Unrecoverable rejection: retry the round with no buyer message.
                buyer_text = None
                round_no -= 1
                continue

            offered_yet = offered_yet or offer is not None
            buyer = response.get("buyer") or {}
            buyer_text = buyer.get("text", "")
            print(f"[buyer] {buyer_text}")
            tracker.observe_buyer(buyer_text)
            strategy_engine.observe_buyer(buyer_text, tracker)
            quote = response.get("quote")
            if quote:
                print(f"[quote] {quote}  (internal - buyer only sees your message text)")
                tracker.observe_turn(offer, quote)
                strategy_engine.observe_offer(offer, quote)
                agent.add_note(
                    f"INTERNAL ONLY - buyer does NOT see this breakdown. They pay £{quote.get('total')}. "
                    f"Your pitch must quote exactly £{quote.get('total')} and never mention cost £{quote.get('cost')} "
                    f"or markup {quote.get('markupPct')}%."
                )
            elif offer:
                tracker.observe_turn(offer, None)
            last_offer = offer
            log.write("turn", {"round": round_no, "seller": text, "offer": offer, "plan": plan.to_brief(), "response": response})

            if response.get("status") == "ended":
                print(f"[result] {response.get('result')}")
                log.write("match-end", response.get("result") or {})
                return
            if round_no >= self.settings.max_seller_rounds:
                print("[dealroom] round budget exhausted")
                log.write("match-end", {"endReason": "round-budget-exhausted"})
                return

    def _respond_with_offer(
        self,
        agent: SellerAgent,
        buyer_text: str | None,
        note: str,
        needs_offer: bool,
    ) -> tuple[str, dict[str, Any] | None]:
        """Ensure we never send empty/stall turns when an offer is required."""
        text, offer = self._respond_safely(agent, buyer_text, note)
        for attempt in range(3):
            if not needs_offer or (offer and not is_stall_message(text)):
                return text, offer
            reason = "no structured offer" if not offer else "stall message"
            print(f"[runner] retry ({reason}, attempt {attempt + 1})")
            text, offer = self._respond_safely(
                agent,
                None,
                MUST_OFFER_NOTE + " Use your most recent successful search results if live search fails.",
            )
        return text, offer

    def _respond_safely(self, agent: SellerAgent, buyer_text: str | None, note: str) -> tuple[str, dict[str, Any] | None]:
        """A crash must never abandon a live match - retry, then send a holding message."""
        for attempt in range(2):
            try:
                return agent.respond(buyer_text=buyer_text, note=note)
            except Exception as exc:
                print(f"[agent] respond failed (attempt {attempt + 1}): {exc}")
                buyer_text = None
                time.sleep(10)
        return (
            "To make sure I put exactly the right package in front of you: what matters most - "
            "price, quality, or location? And roughly what budget would feel comfortable?",
            None,
        )

    def _take_turn(
        self, agent: SellerAgent, match_id: str, text: str, offer: dict[str, Any] | None, log: "MatchLog"
    ) -> dict[str, Any] | None:
        """Send the turn; on a 400 (offer rejected, no round consumed) let the agent repair it."""
        for attempt in range(3):
            try:
                return self.dealroom.take_turn(match_id, text=text, offer=offer)
            except DealRoomRejection as exc:
                print(f"[dealroom] turn rejected (attempt {attempt + 1}): {exc.body}")
                log.write("rejected", {"error": exc.body, "offer": offer})
                text, offer = agent.respond(
                    buyer_text=None,
                    note=(
                        "The Deal Room API rejected your last turn with this error (no round was used): "
                        f"{exc.body}. Fix exactly what it names and call send_turn again."
                    ),
                )
                print(f"[seller] repaired turn: {text}")
        print("[dealroom] giving up on this turn after repeated rejections; sending message only")
        try:
            return self.dealroom.take_turn(match_id, text=text, offer=None)
        except DealRoomRejection:
            return None

    def _round_note(self, round_no: int, offered_yet: bool) -> str:
        max_rounds = self.settings.max_seller_rounds
        if round_no >= max_rounds - 3:
            template = ROUND_NOTE_ENDGAME
        elif round_no >= 3 and not offered_yet:
            template = ROUND_NOTE_MUST_OFFER
        else:
            template = ROUND_NOTE_NORMAL
        return template.format(round_no=round_no, max_rounds=max_rounds)


class MatchLog:
    def __init__(self, match_id: str):
        directory = Path("logs")
        directory.mkdir(exist_ok=True)
        self.path = directory / f"{match_id}.jsonl"

    def write(self, event: str, payload: Any) -> None:
        record = {"ts": time.time(), "event": event, "data": payload}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
