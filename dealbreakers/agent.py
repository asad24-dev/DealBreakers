"""LLM-driven seller agent: a plain tool-calling loop over the live travel MCPs."""
from __future__ import annotations

import json
import re
import time
from typing import Any

from openai import APIStatusError, OpenAI, RateLimitError

from .mcp_client import StreamableMCPClient
from .offers import sanitize_offer
from .prompts import system_prompt

# Tools we must never call (competition rules: read-only, no bookings) or that waste rounds.
TOOL_BLACKLIST = {
    "web-tour-booking",
    "web-tour-send-brochure",
    "feedback-to-devs",
}

# TourRadar exposes 18 tools; only these are useful for selling. The rest (currency lists,
# FAQs, maps, operator search...) just bloat every LLM request and burn the TPM budget.
TOURRADAR_ALLOWLIST = {
    "vertex-tour-search",
    "vertex-tour-title-search",
    "b2b-tour-details",
    "b2b-tour-departures",
    "b2b-cities-search",
}

MAX_TOOL_ITERATIONS = 10
TOOL_RESULT_MAX_CHARS = 9000

SEND_TURN_TOOL = {
    "type": "function",
    "function": {
        "name": "send_turn",
        "description": (
            "Send your negotiation turn to the buyer. Call this exactly once per round, after any "
            "inventory searches. Include `offer` whenever you have a real product to propose - the "
            "buyer can only accept structured offers, never words."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Your message to the buyer (2-5 sentences, warm, concrete, truthful).",
                },
                "offer": {
                    "type": "object",
                    "description": "Structured offer. Omit only when purely asking questions.",
                    "properties": {
                        "holiday": {
                            "type": "object",
                            "description": "Hotel package (send this OR tour, never both).",
                            "properties": {
                                "hotelName": {"type": "string"},
                                "url": {"type": "string", "description": "Real listing URL from a tool result."},
                                "starRating": {"type": "number"},
                                "reviewScore": {"type": "number"},
                                "boardBasis": {"type": "string", "enum": ["AI", "FB", "HB", "BB", "SC", "RO"]},
                                "nights": {"type": "number"},
                                "location": {"type": "string"},
                                "region": {"type": "string"},
                                "country": {"type": "string", "description": "Destination country, e.g. 'Spain'. Always set."},
                                "amenities": {"type": "array", "items": {"type": "string"}},
                                "priceTotal": {"type": "number", "description": "True total cost from the listing (number)."},
                            },
                            "required": ["priceTotal", "hotelName", "url", "country"],
                        },
                        "tour": {
                            "type": "object",
                            "description": "Guided multi-day tour (send this OR holiday, never both).",
                            "properties": {
                                "name": {"type": "string"},
                                "url": {"type": "string"},
                                "operator": {"type": "string"},
                                "region": {"type": "string"},
                                "country": {"type": "string"},
                                "durationDays": {"type": "number"},
                                "priceTotal": {"type": "number"},
                            },
                            "required": ["priceTotal", "name", "url", "country"],
                        },
                        "car": {
                            "type": "object",
                            "description": "Optional car hire add-on.",
                            "properties": {
                                "vehicleName": {"type": "string"},
                                "url": {"type": "string"},
                                "priceTotal": {"type": "number"},
                                "transmission": {"type": "string", "enum": ["Manual", "Automatic"]},
                                "seats": {"type": "number"},
                            },
                            "required": ["priceTotal"],
                        },
                        "markupPct": {
                            "type": "number",
                            "description": "Your fee as a percent on top of cost (buyer pays cost*(1+markupPct/100)).",
                        },
                        "sources": {
                            "type": "array",
                            "description": "Receipts for every component.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "mcp": {"type": "string"},
                                    "url": {"type": "string"},
                                    "price": {"type": "number"},
                                },
                            },
                        },
                    },
                },
            },
            "required": ["text"],
        },
    },
}


class SellerAgent:
    def __init__(
        self,
        openai_api_key: str,
        model: str,
        clients: dict[str, StreamableMCPClient],
        tools_by_server: dict[str, list[dict[str, Any]]],
        scenario_name: str,
        scenario_brief: str,
        max_rounds: int,
    ):
        self.llm = OpenAI(api_key=openai_api_key)
        self.model = model
        self.clients = clients
        self.registry: dict[str, tuple[str, str]] = {}
        self.tool_defs: list[dict[str, Any]] = [SEND_TURN_TOOL]
        for server, tools in tools_by_server.items():
            for tool in tools:
                name = tool.get("name", "")
                if name in TOOL_BLACKLIST:
                    continue
                if server == "tourradar" and name not in TOURRADAR_ALLOWLIST:
                    continue
                fq_name = f"{server}__{name}"[:64]
                self.registry[fq_name] = (server, name)
                self.tool_defs.append(
                    {
                        "type": "function",
                        "function": {
                            "name": fq_name,
                            "description": str(tool.get("description", ""))[:1024],
                            "parameters": _clean_schema(tool.get("inputSchema") or {"type": "object", "properties": {}}),
                        },
                    }
                )
        self.messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt(scenario_name, scenario_brief, max_rounds)}
        ]
        # url -> priceTotal of the first offer made for that listing. A listing's cost is a fact;
        # it must never change between rounds (discounts happen via markupPct only).
        self.offered_prices: dict[str, float] = {}

    def respond(self, buyer_text: str | None, note: str | None = None) -> tuple[str, dict[str, Any] | None]:
        """Produce the next turn: (message text, sanitized offer or None)."""
        if buyer_text:
            self.messages.append({"role": "user", "content": f"BUYER SAYS: {buyer_text}"})
        if note:
            self.messages.append({"role": "system", "content": note})
        self._prune()

        nudged = False
        for iteration in range(MAX_TOOL_ITERATIONS):
            force_send = iteration == MAX_TOOL_ITERATIONS - 1
            message = self._chat(force_send=force_send)
            if not message.tool_calls:
                if message.content and nudged:
                    return message.content.strip(), None
                nudged = True
                self.messages.append(
                    {"role": "system", "content": "You must call send_turn to take your turn (and inventory tools first if needed)."}
                )
                continue
            turn = self._handle_tool_calls(message)
            if turn is not None:
                return turn
        return (
            "So I can pin down the perfect option: what matters most to you - price, quality, or location? "
            "And is there a budget you'd like me to stay within?",
            None,
        )

    def add_note(self, note: str) -> None:
        self.messages.append({"role": "system", "content": note})

    def _chat(self, force_send: bool):
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": self.messages,
            "tools": self.tool_defs,
            "tool_choice": {"type": "function", "function": {"name": "send_turn"}} if force_send else "auto",
            "temperature": 0.4,
        }
        response = self._chat_with_backoff(kwargs)
        message = response.choices[0].message
        entry: dict[str, Any] = {"role": "assistant", "content": message.content or ""}
        if message.tool_calls:
            entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in message.tool_calls
            ]
        self.messages.append(entry)
        return message

    def _chat_with_backoff(self, kwargs: dict[str, Any]):
        """Never let a transient 429/5xx kill a live match - wait and retry."""
        delay = 8.0
        for attempt in range(6):
            try:
                return self.llm.chat.completions.create(**kwargs)
            except RateLimitError as exc:
                wait = _suggested_wait(str(exc)) or delay
                print(f"[llm] rate limited, retrying in {wait:.0f}s (attempt {attempt + 1})")
                time.sleep(wait)
                delay = min(delay * 2, 60)
            except APIStatusError as exc:
                if exc.status_code < 500:
                    raise
                print(f"[llm] server error {exc.status_code}, retrying in {delay:.0f}s (attempt {attempt + 1})")
                time.sleep(delay)
                delay = min(delay * 2, 60)
        return self.llm.chat.completions.create(**kwargs)

    def _handle_tool_calls(self, message) -> tuple[str, dict[str, Any] | None] | None:
        """Execute every tool call. Returns the finished turn if send_turn succeeded."""
        turn: tuple[str, dict[str, Any] | None] | None = None
        for tc in message.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError as exc:
                self._tool_result(tc.id, f"ERROR: arguments were not valid JSON ({exc}). Fix and retry.")
                continue

            if name == "send_turn":
                text = str(args.get("text") or "").strip()
                raw_offer = args.get("offer")
                if raw_offer:
                    offer, error = sanitize_offer(raw_offer)
                    if error is None:
                        error = self._check_price_consistency(offer)
                    if error:
                        self._tool_result(tc.id, f"OFFER REJECTED before sending: {error}. Fix the offer and call send_turn again.")
                        continue
                    self._record_prices(offer)
                    self._tool_result(tc.id, "Turn sent to buyer (with offer).")
                    turn = (text or "Here is my offer.", offer)
                else:
                    self._tool_result(tc.id, "Turn sent to buyer (message only).")
                    turn = (text or "Could you tell me a little more about what you're after?", None)
            elif name in self.registry:
                server, tool_name = self.registry[name]
                print(f"[tool] {name} {json.dumps(args, ensure_ascii=False)[:200]}")
                try:
                    result = self.clients[server].call_tool(tool_name, args)
                    self._tool_result(tc.id, _render_result(result))
                except Exception as exc:
                    self._tool_result(tc.id, f"ERROR calling {tool_name}: {str(exc)[:1500]}. Adjust arguments per the error and retry once.")
            else:
                self._tool_result(tc.id, f"ERROR: unknown tool {name}.")
        return turn

    def _check_price_consistency(self, offer: dict[str, Any]) -> str | None:
        """A listing's priceTotal is a fact about the real listing: once offered, it cannot change."""
        for part in (offer.get("holiday"), offer.get("tour"), offer.get("car")):
            if not part or not part.get("url"):
                continue
            url = str(part["url"])
            known = self.offered_prices.get(url)
            if known is not None and abs(known - float(part["priceTotal"])) > 0.01:
                return (
                    f"you changed priceTotal for {url} from {known} to {part['priceTotal']}. The cost of a real "
                    f"listing NEVER changes - discounts happen ONLY via markupPct. Keep priceTotal={known} and set "
                    f"markupPct = (yourTargetTotal / {known} - 1) * 100, then quote that exact total to the buyer"
                )
        return None

    def _record_prices(self, offer: dict[str, Any]) -> None:
        for part in (offer.get("holiday"), offer.get("tour"), offer.get("car")):
            if part and part.get("url"):
                self.offered_prices.setdefault(str(part["url"]), float(part["priceTotal"]))

    def _tool_result(self, call_id: str, content: str) -> None:
        self.messages.append({"role": "tool", "tool_call_id": call_id, "content": content})

    def _prune(self) -> None:
        if len(self.messages) <= 90:
            return
        for entry in self.messages[1:-40]:
            if entry.get("role") == "tool" and len(str(entry.get("content", ""))) > 400:
                entry["content"] = "[older tool output trimmed]"


# Noise keys (image galleries, logos, UI hints) that bloat tool results and can push the
# booking URL past the truncation limit.
_NOISE_KEYS = {"images", "imagesHiRes", "imageUrl", "brandLogoUrl", "_meta", "followupInstructions", "logo", "thumbnail"}


def _strip_noise(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip_noise(v) for k, v in value.items() if k not in _NOISE_KEYS}
    if isinstance(value, list):
        return [_strip_noise(item) for item in value]
    return value


def _render_result(result: Any) -> str:
    """Flatten an MCP tools/call result into compact text for the model."""
    if isinstance(result, dict):
        structured = result.get("structuredContent")
        if structured:
            return json.dumps(_strip_noise(structured), ensure_ascii=False, separators=(",", ":"))[:TOOL_RESULT_MAX_CHARS]
        content = result.get("content")
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
            if parts:
                return "\n".join(parts)[:TOOL_RESULT_MAX_CHARS]
    return json.dumps(_strip_noise(result), ensure_ascii=False, separators=(",", ":"), default=str)[:TOOL_RESULT_MAX_CHARS]


def _suggested_wait(error_text: str) -> float | None:
    match = re.search(r"try again in ([\d.]+)s", error_text)
    return float(match.group(1)) + 1.0 if match else None


def _clean_schema(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {k: _clean_schema(v) for k, v in schema.items() if k not in ("$schema", "_meta")}
    if isinstance(schema, list):
        return [_clean_schema(item) for item in schema]
    return schema
