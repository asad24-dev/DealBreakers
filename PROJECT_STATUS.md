# DealBreakers — AI Travel Seller Agent

Hackathon project for the **Antler Deploy Hack "Deal Room" challenge** (Listo x Antler x Google, June 2026).

We build an AI **seller** agent that negotiates with the organiser's AI **buyers** (hidden budgets, preferences, and constraints), searches real travel inventory via public MCP servers, and closes deals through a structured offer API.

## The Challenge

- The organiser runs AI buyers with hidden briefs (persona, budget, must-haves).
- Our agent must discover what the buyer wants through conversation, find real travel deals on live MCPs, and close the best package.
- **Scoring:** Close = 50 pts, Margin = 30 pts, Buyer satisfaction = 20 pts. Closing is the top priority.
- 5 unlimited **practice buyers** (`practice-bob`, `practice-toni`, `practice-elon`, `practice-gordon`, `practice-cris`); 5 **official buyers**, one attempt each, no retries.
- Max 15 rounds per match. Buyer actions: `continue` / `accept` / `walk`.
- Deals only close via a structured `offer` JSON object with a numeric `priceTotal` — words alone do nothing.
- Markup: buyer pays `cost x (1 + markupPct/100)`. Never below cost. Misrepresentation = disqualification.

### Deal Room API (confirmed working)

- Base URL: `https://project-parley-production.up.railway.app`
- Auth: `x-team-key` header on every request (team: `dealbreakers`, key in local `.env`, gitignored)
- `POST /match` — start a match. Body: `{}` (official), `{"practice": true}`, or `{"practice": true, "personaId": "practice-bob"}`. Returns `matchId`, `scenario`, buyer's opening message. Returns `{"done": true}` when all 5 official matches are played.
- `POST /match/{matchId}/turn` — body `{"text": "...", "offer": {...}}` (offer optional). Returns buyer reply, `status`, `quote` (on offer turns), `result` (when match ends).
- Bad offer → HTTP 400 with explanation, **no round consumed** — safe to fix and resend.

### Offer schema (what closes deals)

One primary product — `holiday` (hotel package) **or** `tour` (guided multi-day) — plus optional `car`, `markupPct`, and `sources[]` receipts:

```json
{
  "text": "Here's a sunny week that fits.",
  "offer": {
    "holiday": {
      "hotelName": "...", "url": "real listing URL", "starRating": 4,
      "reviewScore": 9.4, "boardBasis": "AI", "nights": 7,
      "location": "...", "region": "Majorca", "country": "Spain",
      "amenities": ["pool", "close_to_beach"], "priceTotal": 2440
    },
    "car": { "vehicleName": "Fiat 500", "url": "...", "priceTotal": 112 },
    "markupPct": 12,
    "sources": [ { "mcp": "travelsupermarket", "url": "...", "price": 2440 } ]
  }
}
```

Amenities use a canonical vocabulary (25 words: `pool`, `close_to_beach`, `kids_club`, `spa`, `family_friendly`, etc. — full list in `src/dealbreakers/constants.py`).

### Travel MCP servers (live, public, Streamable HTTP, no keys)

| Provider | Products | URL |
|---|---|---|
| TravelSupermarket | UK package holidays (flight+hotel) + car hire — main catalogue | `https://travel-supermarket-integration-dev-test.up.railway.app/mcp` |
| trivago | standalone hotels | `https://mcp.trivago.com/mcp` |
| Kiwi.com | flights | `https://mcp.kiwi.com/mcp` |
| EconomyBookings | car hire | `https://economybookings-integration-dev.up.railway.app/mcp` |
| TourRadar | multi-day guided tours | `https://ai.tourradar.com/mcp/main` |

## What's Built So Far (Phases 1, 2, 5A, 5B — complete and verified)

### Project structure

```
DealBreakers/
├── .env.example                      # DEAL_ROOM_BASE_URL, DEAL_ROOM_TEAM_KEY, OPENAI_API_KEY
├── requirements.txt                  # requests, python-dotenv
├── requirements-dev.txt              # pytest, requests-mock
├── pyproject.toml
├── src/dealbreakers/
│   ├── config.py                     # frozen Settings dataclass, fail-fast env loading
│   ├── constants.py                  # personas, board basis, amenity vocab, MCP URLs, enums
│   ├── models/
│   │   ├── offer.py                  # Holiday, Tour, Car, Source, Offer + to_api_dict()
│   │   ├── match.py                  # MatchStartResponse, TurnResponse, Quote, MatchResult, AllMatchesDone
│   │   └── transcript.py             # TranscriptEvent, MatchTranscript (Phase 2)
│   ├── api/
│   │   ├── client.py                 # DealRoomClient (start_match, send_turn)
│   │   └── errors.py                 # typed exceptions per HTTP status
│   ├── logging/
│   │   ├── jsonl_logger.py           # hardened JSONL: append/read/clear, never crashes the agent
│   │   └── transcript_recorder.py    # TranscriptRecorder — structured per-turn event records
│   ├── mcp/
│   │   ├── client.py                 # MCPClient — JSON-RPC over Streamable HTTP (Phase 5A)
│   │   ├── discovery.py              # discover_all / discover_provider — tools/list per server
│   │   ├── normalizers.py            # HolidayCandidate + amenity/board/price normalization (5B)
│   │   └── travelsupermarket.py      # TravelSupermarketClient.search_holidays wrapper (5B)
│   ├── analysis/                     # Phase 3 stub — conversation analyzer (OpenAI)
│   ├── state/                        # Phase 4 stub — buyer state model
│   ├── offers/                       # Phase 6 stub — offer generator
│   └── negotiation/                  # Phase 7 stub — policy engine
├── scripts/
│   ├── smoke_match.py                # live practice smoke test (--persona, --log)
│   ├── run_practice_once.py          # single-persona discovery run with error recording
│   ├── discover_mcp_tools.py         # prints all MCP tools, saves logs/mcp_tools.json
│   └── search_holidays.py            # live TSM holiday search CLI, saves logs/holiday_search.json
├── logs/
│   ├── mcp_tools.json                # raw tool schemas from all 5 live MCP servers
│   └── holiday_search.json           # raw + normalized results of last holiday search
└── tests/                            # 51 unit tests, all offline
    ├── test_deal_room_client.py
    ├── test_jsonl_logger.py
    ├── test_transcript_recorder.py
    ├── test_mcp_client.py
    └── test_travelsupermarket.py
```

### Deal Room API client (`src/dealbreakers/api/client.py`)

- `start_match(practice=..., persona_id=...)` → `MatchStartResponse | AllMatchesDone`
- `send_turn(match_id, text, offer=None)` → `TurnResponse`
- Shared `requests.Session` with `x-team-key` header
- Typed exceptions: `OfferValidationError` (400, keeps raw server body), `AuthenticationError` (401/403), `NotFoundError` (404), `RateLimitError` (429), `ServerError` (5xx)
- One automatic retry with backoff on 429/5xx
- Helper properties: `turn.is_ended`, `turn.buyer_accepted`, `turn.buyer_walked`

### Models (`src/dealbreakers/models/`)

- Dataclasses mirror the API contract exactly; `to_api_dict()` emits camelCase, numeric `priceTotal`, and omits `None` fields (the API treats wrong-typed fields as absent).
- `from_api()` factories normalize camelCase responses to snake_case Python.

### Logging (`src/dealbreakers/logging/`) — Phase 2

- `append_run_log(record, path)` — one JSON object per line, UTF-8; auto-creates parent dirs; adds timestamp if missing; serializes dataclasses, enums, and paths; **never raises** — on failure prints a warning and continues (logging can't kill the agent).
- `read_jsonl(path)` / `clear_log(path)` — for analysis scripts and tests.
- `TranscriptRecorder` — structured per-event records, each tagged with a `record_type`:
  - `match_started` — match id, practice flag, persona, scenario name + brief, buyer opening
  - `buyer_message` — role, text, action, round number
  - `seller_message` — text, offer dict (when sent), round number
  - `turn_response` — status, buyer reply + action, quote, result
  - `error` — error type + message (no traceback), optional context
- Round convention: buyer opening = `round_number: null`; first seller turn = round 1.
- These logs are the raw material for reverse-engineering buyer budgets, objection patterns, and acceptance thresholds.

### Transcript models (`src/dealbreakers/models/transcript.py`)

- `TranscriptEvent` and `MatchTranscript` dataclasses with `to_dict()` — typing + future aggregation (full transcript assembly comes with the automated runner).

### Safety: practice-only scripts

- Both scripts hardcode `practice=True` on `start_match` — they can never start an official (scored) match. Official matches will require an explicit, deliberate call path.

### MCP layer (`src/dealbreakers/mcp/`) — Phase 5A

- `MCPClient(base_url, timeout=30)` — JSON-RPC 2.0 over Streamable HTTP:
  - `request(method, params)` → returns JSON-RPC `result`; `list_tools()` → tool descriptors.
  - Performs the required `initialize` → `notifications/initialized` handshake lazily and reuses the `Mcp-Session-Id` header.
  - Parses both plain JSON and SSE (`text/event-stream`) responses — live servers use both.
  - Typed errors: `MCPError` (timeouts/connection), `MCPHTTPError` (non-2xx), `MCPProtocolError` (JSON-RPC error / malformed JSON).
- `discover_all()` — runs `tools/list` against every provider; captures per-provider errors instead of raising.
- `scripts/discover_mcp_tools.py` — prints every tool with description + input schema, saves raw output to `logs/mcp_tools.json`.

### MCP discovery results (live, 5/5 reachable)

| Provider | Tools | Key tools and gotchas |
|---|---|---|
| TravelSupermarket | 2 | `search-holidays`: one-call package store — destination free text (auto-resolved), departureMonth, duration, boardBasis, starRating, facilities, maxPrice; GBP prices + booking URLs. `search-car-hire`: city or IATA code (do NOT append "Airport"). **Fastest path to a valid offer.** |
| trivago | 3 | `trivago-search-suggestions` (resolve query → `id`/`ns`) must be called before `trivago-accommodation-search`; also a radius search. Requires arrival/departure dates. |
| Kiwi | 2 | `search-flight`: flyFrom/flyTo/departureDate, optional flexible ranges, cabinClass, passengers object. |
| EconomyBookings | 1 | `search-car-hire`: pickupLocation + pickup/dropoff dates required; **driverAge materially affects price and eligibility**. |
| TourRadar | 18 | Richest server. Main chain: `vertex-tour-search` (natural-language + filters: countries, duration, price, departures) → `b2b-tour-details` → `b2b-tour-departures` (date-specific pricing). Helper lookups for city/country/operator IDs. Booking/brochure tools exist but we never book (read-only rule). |

Raw schemas: `logs/mcp_tools.json` (~5,400 lines, all parameters and descriptions).

### TravelSupermarket holiday search (`src/dealbreakers/mcp/travelsupermarket.py`) — Phase 5B

This is our primary inventory path: real package holidays (flight+hotel) with prices and booking URLs, one call away from a valid offer.

- `TravelSupermarketClient.search_holidays(destination, month, duration, board, stars, facilities, max_price, limit)` → `list[HolidayCandidate]`
  - Calls MCP `tools/call` with tool `search-holidays`; months as numbers ("7" or "6,7,8"), star/duration as comma-strings per the schema.
  - `facilities` takes canonical amenity words and translates them to TSM facility IDs for server-side filtering.
- **Robust result extraction** (`extract_listings`): tries `structuredContent` → `content[].text` JSON → direct dict/list; unknown shapes return `[]` instead of crashing.
- **`HolidayCandidate`** (in `normalizers.py`): hotel_name, url, star_rating, review_score, board_basis, nights, location, region, country, amenities, price_total, raw. `candidate.to_holiday()` produces our offer-ready `Holiday`; `is_offerable` = has numeric price + URL.
- **Conservative normalization (anti-disqualification):**
  - TSM facility IDs 1-24 map **1:1 onto the canonical amenity vocabulary** (1=pool, 2=close_to_beach, ..., 24=shopping) — amenities come from the server's structured `facilities` list, never guessed from prose.
  - Free-text matching uses word boundaries — "Barbecue area" does NOT become `bar`; unknown text maps to nothing.
  - Board basis mapped from `boardBasisCode`/free text to AI/FB/HB/BB/SC/RO, else `None`.
  - Prices extracted from numbers or strings like "£2,440"; booleans/garbage → `None`.
- **Raw payload field map** (from live responses): booking URL = `deepLinkUrl`, board code = `boardBasisCode`, party total = `totalPrice`, per-person = `pricePerPerson`, plus departureDate/Airport, reviewCount, images, uuid — all preserved in `candidate.raw`.
- **Pricing gotcha:** TSM `maxPrice` filter is **per person** (default 2 adults), but `totalPrice` is for the whole party. When a buyer gives a total budget, halve it for the filter or post-filter on totals.

### MCPClient hardening (found via live 5B runs)

- Any request now auto-performs the `initialize` handshake (previously only `tools/list` did — raw `tools/call` failed).
- Servers omit charset on `text/event-stream`; requests fell back to latin-1, injecting NEL bytes that `str.splitlines()` treated as line breaks, shredding the SSE JSON mid-payload. Fixed: force UTF-8 + split only on CR/LF.
- SSE parser now concatenates multi-line `data:` events per the SSE spec.
- Added `call_tool(name, arguments)` convenience method.

### Verification status

- **51/51 unit tests pass** (8 Deal Room client + 12 logger + 8 recorder + 8 MCP client + 15 TravelSupermarket), all offline.
- **Live runs verified** against the real API:
  - `smoke_match.py --persona practice-bob` — all four event types written to JSONL.
  - `run_practice_once.py --persona practice-toni` — tour-path persona confirmed (scenario "Antonio Banderas": wants a guided multi-day tour of Spain, solo, flexible dates).
  - `discover_mcp_tools.py` — all 5 MCP servers reachable, 26 tools discovered in total.
  - `search_holidays.py --destination Spain --month July --duration 7 --stars 4 --limit 5` — **5/5 offerable candidates** (e.g. H10 Conquistador: 4-star, 9.6 review, HB, 7 nights, Tenerife, £3,015 total, 22 canonical amenities, booking URL). Candidate → `to_holiday().to_api_dict()` yields a valid offer payload with numeric `priceTotal` and real URL.

### Example log shape (real output)

```json
{"timestamp": "...", "record_type": "match_started", "match_id": "34fb...", "practice": true, "persona_id": "practice-bob", "scenario_name": "Bob Ross", "scenario_brief": "...", "status": "awaiting-seller", "buyer_text": "...", "buyer_action": "continue"}
{"timestamp": "...", "record_type": "buyer_message", "match_id": "34fb...", "role": "buyer", "round_number": null, "text": "...", "action": "continue"}
{"timestamp": "...", "record_type": "seller_message", "match_id": "34fb...", "role": "seller", "round_number": 1, "text": "...", "offer": null}
{"timestamp": "...", "record_type": "turn_response", "match_id": "34fb...", "status": "awaiting-seller", "buyer_text": "...", "buyer_action": "continue", "quote": null, "result": null}
```

## How to Run

```bash
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env          # fill in DEAL_ROOM_BASE_URL and DEAL_ROOM_TEAM_KEY
pytest tests/ -v              # offline unit tests

# live practice runs (always practice=True, never scored)
python scripts/smoke_match.py --persona practice-bob
python scripts/smoke_match.py --persona practice-toni --log logs/toni.jsonl
python scripts/run_practice_once.py --persona practice-gordon --log logs/gordon.jsonl

# MCP tool discovery (read-only, saves logs/mcp_tools.json)
python scripts/discover_mcp_tools.py

# live holiday search (read-only, saves logs/holiday_search.json)
python scripts/search_holidays.py --destination Spain --month July --duration 7 --stars 4 --limit 5
```

## Roadmap (Phases 1-8)

| Phase | Module | What it does | Status |
|---|---|---|---|
| 1 | `api/` + `models/` | Deal Room API client | **Done** |
| 2 | `logging/` | Robust per-turn logging + transcript recorder + practice scripts | **Done** |
| 3 | `analysis/` | OpenAI conversation analyzer — extract explicit/implicit preferences, budget clues, objections from each buyer message | Stub |
| 4 | `state/` | Buyer state model — inferred beliefs (budget range, trip type, luxury/family/price-sensitivity scores, must-haves) updated every turn | Stub |
| 5A | `mcp/client.py` + `discovery.py` | MCP JSON-RPC client + live tool discovery across all 5 servers | **Done** |
| 5B | `mcp/travelsupermarket.py` + `normalizers.py` | TravelSupermarket holiday search → offer-ready `HolidayCandidate` | **Done** |
| 5C | `mcp/` | Remaining wrappers — tours (TourRadar), cars (EconomyBookings/TSM), hotels (trivago), flights (Kiwi) | Next (TourRadar first — practice-toni needs it) |
| 6 | `offers/` | Offer generator — conservative/balanced/aggressive candidates scored by close probability, satisfaction, margin | Stub |
| 7 | `negotiation/` | Deterministic policy engine — explicit action choice per turn: DISCOVER / REFINE / SEARCH / OFFER / COUNTER / CLOSE | Stub |
| 8 | `scripts/run_practice.py` | Automated runner across all 5 practice personas with transcripts + stats | Skeleton (`run_practice_once.py`) |

### Planned negotiation strategy

- **Early (rounds 1-3):** discover — at most 2 questions per turn, no price talk.
- **Mid (rounds 4-8):** narrow requirements, search MCP inventory, present a first offer with healthy markup (anchor high).
- **Late (rounds 9-15):** close — concede markup in steps if the buyer objects to price; protect the close (50 pts) over margin (30 pts).

### What we've learned from practice transcripts so far

- `practice-bob` (easy): solo traveller, flexible dates ("next few weeks"), wants sunny beach + pool. Asks the seller to propose destinations — low information friction.
- `practice-toni` (medium): solo, flexible dates, explicitly wants a **guided multi-day tour of Spain** with an expert guide at a relaxed pace — confirms the tour (not holiday) offer path.

### Open design questions (to discuss)

1. How aggressively to anchor markup on the first offer (e.g. start at 15-18%, floor at 3-5%)?
2. When to switch from discovery to first offer — fixed round number vs. information-completeness heuristic?
3. How to estimate close probability and buyer budget from objection language?
4. Single LLM call per turn that does analysis + reply, vs. separate analyzer and responder calls (latency/cost vs. quality)?
5. ~~How to map messy MCP amenity data into the canonical vocabulary?~~ **Solved in 5B**: TSM facility IDs 1-24 map 1:1 onto the canonical amenity words; amenities come from structured server data, never prose.
6. Should `DealRoomClient.start_match` require an explicit opt-in (env var or `official=True`) before sending an official match request, as extra protection against burning one of the 5 attempts?
7. For tours: `vertex-tour-search` results vs. `b2b-tour-departures` pricing — which price is the real bookable cost we must quote? (Resolve in 5C.)
8. Buyer budget semantics: TSM `maxPrice` is per person, `totalPrice` is per party (2 adults default). When the buyer states a budget, is it total or per person? Discovery questions should pin this down.

## Tech Stack

- Python 3.11+ (dataclasses, type hints, no agent framework)
- `requests` for HTTP, `python-dotenv` for config
- OpenAI API planned for Phases 3+ (analysis + reply generation)
- `pytest` + `requests-mock` for tests
