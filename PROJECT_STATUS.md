# DealBreakers — AI Travel Seller Agent

Hackathon project for the **Antler Deploy Hack "Deal Room" challenge** (Listo x Antler x Google, June 2026).

We build an AI **seller** agent that negotiates with the organiser's AI **buyers** (hidden budgets, preferences, and constraints), searches real travel inventory via public MCP servers, and closes deals through a structured offer API.

---

## The Challenge

- The organiser runs AI buyers with hidden briefs (persona, budget, must-haves).
- Our agent must discover what the buyer wants through conversation, find real travel deals on live MCPs, and close the best package.
- **Scoring:** Close = 50 pts, Margin = 30 pts, Buyer satisfaction = 20 pts. Closing is the top priority.
- 5 unlimited **practice buyers** (`practice-bob`, `practice-toni`, `practice-elon`, `practice-gordon`, `practice-cris`); 5 **official buyers**, one attempt each, no retries.
- Max 15 rounds per match. Buyer actions: `continue` / `accept` / `walk`.
- Deals only close via a structured `offer` JSON object with a numeric `priceTotal` — words alone do nothing.
- Markup: buyer pays `cost × (1 + markupPct/100)`. Never below cost. Misrepresentation = disqualification.

### Deal Room API (confirmed working)

- **Base URL:** `https://project-parley-production.up.railway.app`
- **Auth:** `x-team-key` header on every request (team: `dealbreakers`, key in local `.env`, gitignored)
- **`POST /match`** — start a match. Body: `{}` (official), `{"practice": true}`, or `{"practice": true, "personaId": "practice-bob"}`. Returns `matchId`, `scenario`, buyer's opening message. Returns `{"done": true}` when all 5 official matches are played.
- **`POST /match/{matchId}/turn`** — body `{"text": "...", "offer": {...}}` (offer optional). Returns buyer reply, `status`, `quote` (on offer turns), `result` (when match ends).
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
    "sources": [{ "mcp": "travelsupermarket", "url": "...", "price": 2440 }]
  }
}
```

Amenities use a canonical vocabulary (25 words: `pool`, `close_to_beach`, `kids_club`, `spa`, `family_friendly`, etc. — full list in `src/dealbreakers/constants.py`).

### Travel MCP servers (live, public, Streamable HTTP, no keys)

| Provider | Products | URL |
|---|---|---|
| TravelSupermarket | UK package holidays (flight+hotel) + car hire — main catalogue | `https://travel-supermarket-integration-dev-test.up.railway.app/mcp` |
| trivago | Standalone hotels | `https://mcp.trivago.com/mcp` |
| Kiwi.com | Flights | `https://mcp.kiwi.com/mcp` |
| EconomyBookings | Car hire | `https://economybookings-integration-dev.up.railway.app/mcp` |
| TourRadar | Multi-day guided tours | `https://ai.tourradar.com/mcp/main` |

---

## What's Built So Far

**Phases 1, 2, 3, 4, 5A, 5B, 5C, 5D-A, 6A, 6B, 7A, 7B, 7C, 7D, 7E, 8A, 8B, 8C — complete and verified**

**Headline:** Branch consolidation complete. Cherry-picked deterministic ideas from `origin/feature/deal-room-agent` (total-based counters, duration search, pivot, strategist). Bob/Toni/Cris close autonomously. Gordon duration mismatch now disclosed; Elon city-break interfaces stubbed.

### Persona status (all live data)

| Persona | Difficulty | Product | Closed? | Autonomous | Key insight |
|---|---|---|---|---|---|
| **practice-bob** | Easy | Holiday | **Yes** | **Yes** (4 rounds) | Autonomous loop; ceiling **35%** via scripted sweep |
| **practice-toni** | Medium | Tour | **Yes** | **Yes** (3 rounds) | Policy routes to TourRadar from `trip_type=tour` |
| **practice-elon** | Medium | City-break* | No | Not tested | TSM: 0 offerable Berlin/Stockholm — needs trivago/Kiwi |
| **practice-gordon** | Hard | Holiday | No | No (walked, 5 rounds) | Luxury ladder 25→18→12; walked on 7n vs 14n duration |
| **practice-cris** | Hard | Holiday + car | **Yes** | **Yes** (5 rounds) | Combined offer with car; luxury counter 35→18; accept |

\*Elon brief says city-break; TSM package holidays don't cover Berlin/Stockholm.

### Project structure

```
DealBreakers/
├── .env.example                      # DEAL_ROOM_BASE_URL, DEAL_ROOM_TEAM_KEY, OPENAI_API_KEY
├── requirements.txt                  # requests, python-dotenv, openai
├── requirements-dev.txt              # pytest, requests-mock
├── pyproject.toml
├── src/dealbreakers/
│   ├── config.py                     # frozen Settings dataclass, fail-fast env loading
│   ├── constants.py                  # personas, board basis, amenity vocab, MCP URLs, enums
│   ├── models/
│   │   ├── offer.py                  # Holiday, Tour, Car, Source, Offer + to_api_dict()
│   │   ├── match.py                  # MatchStartResponse, TurnResponse, Quote, MatchResult
│   │   └── transcript.py             # TranscriptEvent, MatchTranscript (Phase 2)
│   ├── api/
│   │   ├── client.py                 # DealRoomClient (start_match, send_turn)
│   │   └── errors.py                 # typed exceptions per HTTP status
│   ├── logging/
│   │   ├── jsonl_logger.py           # hardened JSONL: append/read/clear, never crashes
│   │   └── transcript_recorder.py    # TranscriptRecorder — structured per-turn events
│   ├── mcp/
│   │   ├── client.py                 # MCPClient — JSON-RPC over Streamable HTTP (5A)
│   │   ├── discovery.py              # discover_all / discover_provider
│   │   ├── normalizers.py            # HolidayCandidate + amenity/board/price (5B)
│   │   ├── travelsupermarket.py      # TravelSupermarketClient.search_holidays (5B)
│   │   ├── tour_normalizers.py       # TourCandidate + merge/price/URL helpers (5C)
│   │   └── tourradar.py              # TourRadarClient.search_tours (5C)
│   ├── analysis/
│   │   ├── models.py                 # ConversationAnalysis (Phase 3)
│   │   ├── prompts.py                # strict-JSON extraction prompt
│   │   └── analyzer.py               # ConversationAnalyzer + events_from_log_records
│   ├── state/
│   │   ├── buyer_state.py            # BuyerState + markup estimators (Phase 4)
│   │   └── updater.py                # build_buyer_state — replay JSONL + analysis
│   ├── offers/
│   │   └── selection.py              # state-based scoring + persona closers (6A/7C/8C)
│   ├── experiments/
│   │   ├── markup_sweep.py           # practice-only markup ladder (6B)
│   │   └── persona_discovery.py      # multi-turn discovery sessions (8B)
│   └── negotiation/
│       ├── actions.py                # NegotiationAction enum (7A)
│       ├── policy.py                 # PolicyDecision, decide_action, walk risk (7A)
│       ├── pricing.py                # estimate_markup, counter ladder (7A)
│       ├── responder.py              # OpenAI reply generator with guardrails (7B)
│       └── live_agent.py             # autonomous policy loop (7C)
├── scripts/
│   ├── smoke_match.py                # live practice smoke test (--persona, --log)
│   ├── run_practice_once.py          # single-persona discovery skeleton
│   ├── run_practice_agent.py         # multi-persona runner scaffold (8A)
│   ├── run_autonomous_practice.py    # policy-driven autonomous agent (7C)
│   ├── discover_remaining_personas.py # elon/gordon/cris discovery (8B)
│   ├── discover_mcp_tools.py         # MCP tool discovery → logs/mcp_tools.json
│   ├── search_holidays.py            # live TSM search CLI
│   ├── search_tours.py               # live TourRadar search CLI (5C)
│   ├── close_bob.py                  # end-to-end close vs practice-bob (PRACTICE ONLY)
│   ├── close_toni.py                 # end-to-end close vs practice-toni (PRACTICE ONLY)
│   ├── close_elon.py                 # city-break close vs practice-elon (8C)
│   ├── close_gordon.py               # luxury 5-star close vs practice-gordon (8C)
│   ├── close_cris.py                 # impatient luxury close vs practice-cris (8C)
│   ├── markup_sweep.py               # markup ladder vs Bob (PRACTICE ONLY)
│   ├── find_markup_ceiling.py        # binary-search ceiling per persona (PRACTICE ONLY)
│   ├── analyze_transcript.py         # run analyzer on any JSONL transcript
│   └── build_state.py                # replay log + analysis into BuyerState
├── logs/
│   ├── mcp_tools.json                # raw tool schemas from all 5 MCP servers
│   ├── holiday_search.json           # last TSM search results
│   ├── tour_search.json              # last TourRadar search results (5C)
│   ├── close_bob.jsonl               # first closed deal transcript
│   ├── close_toni.jsonl              # Toni closed deal transcript (5C)
│   ├── close_elon.jsonl              # Elon close attempt — no TSM inventory (8C)
│   ├── close_gordon.jsonl            # Gordon close attempt — offer rejected at 30% (8C)
│   ├── close_cris.jsonl              # Cris close attempt — holiday ok, car missing (8C)
│   ├── analysis.json                 # analyzer output on Bob transcript
│   ├── buyer_state.json              # BuyerState built from Bob log
│   ├── markup_sweep.jsonl            # per-match markup ladder transcripts
│   ├── markup_sweep_summary.json     # compact markup results table
│   ├── markup_ceiling.jsonl          # binary-search probe transcripts
│   ├── persona_markup_profiles.json  # Bob ceiling: safe/balanced/aggressive/ceiling
│   ├── persona_profiles/             # per-persona discovery JSON + JSONL (8B)
│   │   ├── practice-elon.json / .jsonl
│   │   ├── practice-gordon.json / .jsonl
│   │   └── practice-cris.json / .jsonl
│   ├── persona_summary.json          # compact discovery summary (8B)
│   ├── car_search.json               # live car hire search results (5D-A)
│   └── autonomous/                   # per-persona agent turn logs (7C)
│       ├── practice-bob.jsonl
│       ├── practice-toni.jsonl
│       ├── practice-gordon.jsonl
│       └── practice-cris.jsonl
├── branch_inventory.json             # git branch audit (7E)
├── high_value_branches.json
├── cris_branch_analysis.json
├── branch_diffs/                     # per-prefix diff summaries (7E)
├── post_port_summary.json            # multi-run eval after porting (7E)
└── tests/                            # 209 unit tests, all offline
    ├── test_deal_room_client.py      (8)
    ├── test_jsonl_logger.py          (12)
    ├── test_transcript_recorder.py   (8)
    ├── test_mcp_client.py            (8)
    ├── test_travelsupermarket.py     (15)
    ├── test_tourradar.py             (13)
    ├── test_offer_smoke.py           (4)
    ├── test_analysis_models.py       (10)
    ├── test_buyer_state.py           (15)
    ├── test_markup_sweep.py          (15)
    ├── test_policy.py                (21)
    ├── test_pricing.py               (15)
    ├── test_persona_discovery.py     (5)
    ├── test_remaining_closers.py     (13)
    ├── test_car_search.py            (13)
    ├── test_live_agent.py            (14)
    └── test_live_agent_hard_personas.py (7)
```

---

## Phase 1 — Deal Room API Client

**Module:** `src/dealbreakers/api/client.py`, `models/`, `errors.py`

- `start_match(practice=..., persona_id=...)` → `MatchStartResponse | AllMatchesDone`
- `send_turn(match_id, text, offer=None)` → `TurnResponse`
- Shared `requests.Session` with `x-team-key` header
- Typed exceptions: `OfferValidationError` (400), `AuthenticationError` (401/403), `NotFoundError` (404), `RateLimitError` (429), `ServerError` (5xx)
- One automatic retry with backoff on 429/5xx
- Helper properties: `turn.is_ended`, `turn.buyer_accepted`, `turn.buyer_walked`

**Models:** dataclasses mirror the API contract; `to_api_dict()` emits camelCase, numeric `priceTotal`, omits `None` fields. `from_api()` normalizes camelCase responses.

---

## Phase 2 — Logging + Transcripts

**Module:** `src/dealbreakers/logging/`

- `append_run_log(record, path)` — one JSON object per line, UTF-8; auto-creates parent dirs; adds timestamp if missing; serializes dataclasses/enums/paths; **never raises**
- `read_jsonl(path)` / `clear_log(path)` — for analysis scripts and tests
- **`TranscriptRecorder`** — structured per-event records:

| `record_type` | Contents |
|---|---|
| `match_started` | match id, practice flag, persona, scenario name + brief, buyer opening |
| `buyer_message` | role, text, action, round number |
| `seller_message` | text, offer dict (when sent), round number |
| `turn_response` | status, buyer reply + action, quote, result |
| `error` | error type + message, optional context |

- Round convention: buyer opening = `round_number: null`; first seller turn = round 1
- `TranscriptEvent` / `MatchTranscript` models for future aggregation

**Safety:** practice-only scripts hardcode `practice=True` on `start_match` — they cannot start an official (scored) match.

---

## Phase 3 — Conversation Analyzer

**Module:** `src/dealbreakers/analysis/`

Converts conversation history into actionable signals. Deterministic plumbing, single OpenAI call, fully inspectable. **Never generates seller replies** — extraction only.

**`ConversationAnalysis` dataclass:**
- `trip_type` ("holiday" | "tour" | None), `destinations`, `must_haves`, `nice_to_haves`
- `budget_min` / `budget_max` (None unless buyer gave real clues)
- `price_sensitivity`, `trust_sensitivity`, `luxury_preference`, `confidence` — floats 0.0–1.0
- `objections` — short quotes/paraphrases of buyer pushback
- `from_dict()` clamps scores, rejects unknown trip types, swaps inverted budget bounds

**`ConversationAnalyzer.analyze(transcript)`** — OpenAI `response_format=json_object`, temperature 0, model from `OPENAI_MODEL` (default `gpt-4o-mini`). Injectable client for offline tests.

**Prompt anchors:** "don't rip me off" → `trust_sensitivity >= 0.7`; "too expensive" → `price_sensitivity >= 0.7`; "something special" → `luxury_preference >= 0.7`.

**`events_from_log_records()`** — rebuilds `TranscriptEvent`s from Phase 2 JSONL logs.

**Live Bob analysis:**

```json
{
  "trip_type": "holiday",
  "destinations": ["Spain", "Greece", "Portugal"],
  "must_haves": ["pool"],
  "budget_max": 978.0,
  "price_sensitivity": 0.0, "trust_sensitivity": 0.0, "luxury_preference": 0.0,
  "objections": [], "confidence": 0.8
}
```

Note: `budget_max=978` echoes our quoted cost — Phase 4 state model rejects it.

---

## Phase 4 — Buyer State Model

**Module:** `src/dealbreakers/state/`

Deterministic buyer state updated from analyses, offers, and turn responses. No LLM. Ready to drive Phase 7 policy.

**Three distinct budget concepts:**

| Field | Meaning | Source |
|---|---|---|
| `stated_budget_max` | Explicit buyer ceiling | Only from genuine buyer budget language |
| `known_affordable_total` | Proven floor — buyer accepted this | `action=accept` on quoted total |
| `rejected_total` | Proven ceiling — too expensive | Price objection on `last_offer_total` |

**Update methods:**
- `update_from_analysis()` — merges lists, ratchets sensitivities upward. Rejects analyzer budgets that echo our quoted prices (within 10% of `seen_offer_prices`).
- `update_from_offer()` — records cost/total/markup from Quote, Offer, or API dicts.
- `update_from_turn_response()` — phrase detection for price/trust objections; accept → `known_affordable_total`.

**`build_buyer_state(records, analysis)`** — replays JSONL **first**, then applies analysis (enables echo filter).

**Markup estimators (superseded by Phase 7A for live use):**
- `estimate_safe_markup()` — trust≥0.7→5%, price≥0.7→6%, luxury≥0.7→18%, affordable+no objections→15%, else 10%
- `estimate_aggressive_markup()` — trust≥0.7→8%, price≥0.7→10%, luxury≥0.7→35%, affordable+no objections→25%, else 15%

**Live Bob state:** `known_affordable_total=1056.24`, `stated_budget_max=null`, `accepted=true`. Phase 6B proved ceiling **35%** — far above Phase 4 estimates.

---

## Phase 5A — MCP Discovery

**Module:** `src/dealbreakers/mcp/client.py`, `discovery.py`

**`MCPClient`** — JSON-RPC 2.0 over Streamable HTTP:
- `request(method, params)` / `list_tools()`
- Auto `initialize` → `notifications/initialized` handshake; reuses `Mcp-Session-Id`
- Parses plain JSON and SSE (`text/event-stream`) responses
- Errors: `MCPError`, `MCPHTTPError`, `MCPProtocolError`

**Hardening (found via live runs):**
- Any request auto-initializes (raw `tools/call` previously failed)
- Force UTF-8 on SSE (latin-1 NEL corruption fixed)
- Multi-line `data:` SSE parsing per spec

**MCP discovery results (live, 5/5 reachable, 26 tools total):**

| Provider | Tools | Key tools and gotchas |
|---|---|---|
| TravelSupermarket | 2 | `search-holidays`: destination, departureMonth, duration, boardBasis, starRating, facilities, maxPrice. `search-car-hire`: city or IATA (not "Airport"). |
| trivago | 3 | `trivago-search-suggestions` before `trivago-accommodation-search`; requires dates. |
| Kiwi | 2 | `search-flight`: flyFrom/flyTo/departureDate, passengers, cabinClass. |
| EconomyBookings | 1 | `search-car-hire`: pickupLocation + dates; driverAge affects price. |
| TourRadar | 18 | `vertex-tour-search` → `b2b-tour-details` → `b2b-tour-departures`. Richest server. |

Raw schemas: `logs/mcp_tools.json` (~5,400 lines).

---

## Phase 5B — TravelSupermarket Holiday Search

**Module:** `src/dealbreakers/mcp/travelsupermarket.py`, `normalizers.py`

- `TravelSupermarketClient.search_holidays()` → `list[HolidayCandidate]`
- `HolidayCandidate.is_offerable` — `price_total` numeric + `url` present
- `to_holiday()` → valid `Holiday` offer payload
- Amenity facility IDs 1–24 map 1:1 to canonical vocab; never invent amenities from prose
- **Pricing gotcha:** TSM `maxPrice` is per person; `totalPrice` is party total
- **Live:** `search_holidays.py` → 5/5 offerable (e.g. H10 Conquistador: 4-star, 9.6 review, HB, 7 nights, Tenerife, £3,015 total)

**Offer selection (`offers/selection.py`):**
- `score_candidate()` — cheaper better, review×2, +5 per wanted amenity, +3 for 4-star+
- `pick_best_candidate()` / `build_holiday_offer(candidate, markup_pct)`

---

## Phase 5C — TourRadar Tour Search

**Module:** `src/dealbreakers/mcp/tour_normalizers.py`, `tourradar.py`

**Tool chain:** `vertex-tour-search` → `b2b-tour-details` → `b2b-tour-departures`

**`TourCandidate` dataclass:**

| Field | Notes |
|---|---|
| `name`, `url`, `operator`, `region`, `country` | From search + details merge |
| `duration_days`, `price_total`, `departure_date` | Duration from `tour_length_days`; price from best source |
| `raw` | Full search/details/departures payloads + `price_source` |

- `is_offerable` — `price_total` numeric AND `url` exists. Never invent price or URL.
- `to_tour()` → `models.offer.Tour` → `to_api_dict()`

**Price policy (safest first):**
1. `b2b-tour-departures` `prices.price_total` (date-specific, bookable)
2. `b2b-tour-details` `prices.price_total`
3. `vertex-tour-search` `prices.price`
4. `raw["price_source"]`: `"departure"` | `"details"` | `"search_result"`

**URL extraction:** `tour_url`, `url`, `links.book-now`, `links.tour-page`, slug → `tourradar.com/t/{id}`

**`TourRadarClient.search_tours()`** — enriches top N with details + departures; offerable first.

**Tour offer selection:**
- `score_tour_candidate()` / `pick_best_tour_candidate()` / `build_tour_offer()`

**`scripts/search_tours.py`:**

```bash
python scripts/search_tours.py
python scripts/search_tours.py --query "guided tour of Spain" --country Spain --limit 5
python scripts/search_tours.py --min-days 5 --max-days 12 --max-price 3000
```

**Live:** 5/5 offerable; departure-priced book-now URLs. Saves `logs/tour_search.json`.

**`scripts/close_toni.py` (PRACTICE ONLY):**
- Hardcoded `PERSONA_ID = "practice-toni"`; `assert_practice_match()`; prints `PRACTICE MODE ONLY — CLOSE TONI`
- Flow: discovery question → silent TourRadar search → `pick_best_tour_candidate()` → offer at 12% → `generate_reply()` with fallback
- **Live result:** South of Spain with Lisbon (Europamundo, 8 days, £1,241 cost, 12% → £1,389.92) — `closed=True`, accept in 2 rounds, no 400

---

## Phase 5D-A — Car Hire MCP Wrapper

**Modules:** `src/dealbreakers/mcp/car_normalizers.py`, `cars.py`, `offers/selection.py`, `scripts/search_cars.py`

**`CarCandidate` dataclass:**
- Fields: `vehicle_name`, `url`, `price_total`, `category`, `transmission`, `seats`, `supplier`, `source_mcp`, `raw`
- `is_offerable` — numeric `price_total`, `url`, and (`vehicle_name` or `category`)
- `to_car()` → `models.offer.Car` → `to_api_dict()` — never invents data

**Normalization helpers:** `extract_car_price()` (strings like `"£112"`, nested `pricing.total`, EconomyBookings `redirectUrl`), `extract_vehicle_name()`, `extract_car_url()`, `extract_car_category()` (`categoryName`), `extract_transmission()` (Manual/Automatic), `extract_seats()`, `extract_car_listings()`.

**`CarSearchClient.search_cars()`** — provider order:
1. EconomyBookings `search-car-hire`
2. TravelSupermarket `search-car-hire` (fallback)

Fails gracefully per provider; sorts offerable first, premium-looking first when `premium=True`, then price.

**Selection:** `score_car_candidate()`, `pick_best_car_candidate()`, `build_holiday_with_car_offer()` — `sources` includes both holiday and car MCP entries.

**CLI:**

```bash
python scripts/search_cars.py --location Faro --pickup-date 2026-07-10 --dropoff-date 2026-07-17 --premium
```

**Live:** Faro/Tenerife → 10/10 offerable via EconomyBookings (`redirectUrl`). Algarve region name returns 0 (use city/IATA). Saves `logs/car_search.json`.

**Tests:** 13 offline tests in `test_car_search.py`.

---

## Phase 6A — First Close (Bob)

**Module:** `scripts/close_bob.py`, `offers/selection.py`

- One discovery question → silent TSM search → one structured offer
- **Live (2026-06-10):** Be Live Adults Only Tenerife, £978 cost, 8% → £1,056.24, accept in 2 rounds
- Safety: `PERSONA_ID = "practice-bob"` hardcoded; only `start_match(practice=True, persona_id=PERSONA_ID)`

---

## Phase 6B — Markup Sweep

**Module:** `src/dealbreakers/experiments/markup_sweep.py`, `scripts/markup_sweep.py`

Practice-only ladder against Bob. Default: `[5, 8, 12, 15, 18, 20, 25, 30, 35, 40]`.

| Markup | Quote total | Closed | Buyer action |
|---|---|---|---|
| 5% | £1,026.90 | Yes | accept |
| 8% | £1,056.24 | Yes | accept |
| 12% | £1,095.36 | Yes | accept |
| 15% | £1,124.70 | Yes | accept |
| 18% | £1,154.04 | Yes | accept |
| 20% | £1,173.60 | Yes | accept |
| 25% | £1,222.50 | Yes | accept |
| 30% | £1,271.40 | Yes | accept |
| 35% | £1,320.30 | Yes | accept |
| 40% | £1,369.20 | **No** | continue (price objection) |

**Ceiling:** highest accepted = **35%**; first rejected = **40%** (Bob negotiates, never walks).
**Anchor recommendation:** open at **30%**, concede to **35%** via COUNTER ladder.
Outputs: `logs/markup_sweep.jsonl`, `logs/markup_sweep_summary.json`

---

## Phase 7A — Negotiation Policy Engine

**Module:** `src/dealbreakers/negotiation/actions.py`, `policy.py`, `pricing.py`

**`NegotiationAction`:** `DISCOVER` | `REFINE` | `SEARCH` | `OFFER` | `COUNTER` | `CLOSE`

**`decide_action(buyer_state, analysis, latest_message, inventory_ready=)`** — deterministic priority:

1. **CLOSE** — acceptance phrases + offer was sent (`confidence=0.95`)
2. **COUNTER** — price words after offer; `target_markup = generate_counter_markup()` (`confidence=0.85`)
3. **DISCOVER** — trip type or destination unknown
4. **REFINE** — must-haves unclear
5. **SEARCH** — enough info, no inventory yet
6. **OFFER** — enough info + `inventory_ready=True`; `target_markup = estimate_markup(BALANCED)`

**`estimate_walk_risk()`** → 0.0–1.0:
- Base 0.1; +0.15 per objection (cap 3); +0.2 trust complaint; +0.15 repeat price pushback
- −0.1 follow-up question; −0.1 positive sentiment; −0.15 prior acceptance; `walked=True` → 1.0

**`estimate_markup(state, Aggressiveness)` profile table:**

| Profile | SAFE | BALANCED | AGGRESSIVE |
|---|---|---|---|
| trust_sensitivity ≥ 0.7 | 5% | 8% | 10% |
| price_sensitivity ≥ 0.7 | 6% | 8% | 10% |
| luxury_preference ≥ 0.7 | 18% | 25% | 35% |
| known affordable + no objections | 15% | 25% | 35% |
| default | 10% | 12% | 15% |

**`generate_counter_markup()`** — ladder `40→35→30→25→20→15→10→5→0`. Never increases. Price-hypersensitive (≥0.9) concedes two rungs.

---

## Phase 7B — OpenAI Reply Generator + Ceiling Discovery

**Module:** `src/dealbreakers/negotiation/responder.py`, `scripts/find_markup_ceiling.py`

**`generate_reply(action, state, selected_offer, latest_message)`** — OpenAI wording **only**:
- Strict JSON `{"text": "..."}`; facts from `_offer_facts()` only
- `validate_reply()` rejects banned filler ("I'm searching", "Let me look", "Give me a moment", "I'm checking"), >90 words, empty
- Failure → `fallback_reply()` deterministic template

**`find_markup_ceiling.py`** — binary search between accepted/rejected bounds:

```bash
python scripts/find_markup_ceiling.py --lo 35 --hi 40   # Bob: ceiling = 35%
```

**Live:** 37% and 36% rejected → Bob's exact ceiling is **35%**:

```json
{ "practice-bob": { "safe": 25.0, "balanced": 30.0, "aggressive": 35.0, "ceiling": 35.0 } }
```

---

## Phase 7C — Autonomous Negotiation Loop

**Module:** `src/dealbreakers/negotiation/live_agent.py`, `scripts/run_autonomous_practice.py`, `tests/test_live_agent.py`

Single policy-driven seller replaces hardcoded `close_*.py` flows. No persona routing — all decisions from `BuyerState` + `decide_action()`.

### Loop (max 15 rounds)

```
while not ended:
  analyze(transcript)           → ConversationAnalyzer
  update BuyerState
  decide_action()               → DISCOVER|REFINE|SEARCH|OFFER|COUNTER|CLOSE
  apply_policy_overrides()      → car unresolved → honest REFINE; impatience → SEARCH/OFFER
  execute action                → search / build offer / generate reply
  send_turn(text, offer?)
  log agent_turn                → logs/autonomous/<persona>.jsonl
```

### Action execution

| Action | Behaviour |
|---|---|
| **DISCOVER** | One useful question via `generate_reply()`; max 2 questions; banned filler |
| **REFINE** | Clarify one ambiguity (city vs beach, holiday vs tour, luxury vs budget) |
| **SEARCH** | Silent MCP search; `holiday` → TSM, `tour` → TourRadar; state-driven params |
| **OFFER** | Score candidates (`score_holiday_for_state` / `score_tour_for_state`); markup from walk risk |
| **COUNTER** | `generate_counter_markup()` — never increase; never repeat identical markup |
| **CLOSE** | Confirmation text only; no new search |

### Walk-risk markup (before every offer)

| Walk risk | Profile | Example (luxury buyer) |
|---|---|---|
| > 0.7 | SAFE | 18% |
| 0.3–0.7 | BALANCED | 25% |
| < 0.3 | AGGRESSIVE | 35% |

### MCP routing (from BuyerState, not persona)

- `trip_type=holiday` → TravelSupermarket (`destinations`, `must_haves` → stars/amenities)
- `trip_type=tour` → TourRadar
- City-break detected via destinations/must-haves → shorter durations (3/4/7 nights)
- Car requested → EconomyBookings/TSM search; combined offer or `unresolved_requirements: ["car"]`

### OpenAI responsibilities

| Allowed | Forbidden |
|---|---|
| Wording, questions, explanations | Markup, inventory, offer structure, prices |

### Logging (`record_type: agent_turn`)

Each turn records: `analysis`, `buyer_state`, `policy_decision`, `selected_inventory`, `markup`, `walk_risk`, `seller_text`, `buyer_action`.

### Terminal output (`verbose=True`)

Prints per round: action, policy reasoning, walk risk, search note, markup, selected inventory, seller/buyer messages, quote.

### Live autonomous results

| Persona | Closed? | Rounds | End reason | Notes |
|---|---|---|---|---|
| **practice-bob** | **Yes** | 4 | accept | DISCOVER → SEARCH → OFFER → accept |
| **practice-toni** | **Yes** | 3 | accept | Analyzer tags `tour`; TourRadar path |
| **practice-gordon** | No | 5 | walk | 2× COUNTER (25%→18→12); duration mismatch |
| **practice-cris** | **Yes** | 5 | accept | Holiday+car offer; luxury counter closes deal |

```bash
python scripts/run_autonomous_practice.py --persona practice-bob
python scripts/run_autonomous_practice.py --persona practice-toni
python scripts/run_autonomous_practice.py --persona practice-gordon
python scripts/run_autonomous_practice.py --persona practice-cris
```

**Tests:** 13 offline tests in `test_live_agent.py` — loop, routing, counters, walk-risk markup, max rounds, practice guard.

**Legacy:** `close_*.py` scripts remain for comparison; `run_autonomous_practice.py` is the unified path.

---

## Phase 7D — Car Path + Hard-Persona Tuning

**Modules:** `live_agent.py`, `pricing.py`, `policy.py`, `tests/test_live_agent_hard_personas.py`

### Car requirement handling

- Detect car from `BuyerState.must_haves` or buyer message keywords
- Silent car search on SEARCH/OFFER when car required
- `car_pickup_location()` prefers holiday `location` over vague destinations (e.g. "Mediterranean" → "Tenerife")
- Combined `offer.holiday` + `offer.car` via `build_holiday_with_car_offer()`
- No car found → `unresolved_requirements: ["car"]`, honest one-time message, no repeated counter loop

### Impatience fast-path

Phrases like "stop asking", "show me", "concrete package", "right now" → force SEARCH/OFFER (max 1 DISCOVER/REFINE turn).

### Gordon luxury counter tuning

`generate_luxury_counter_markup()` when `luxury_preference >= 0.8` and `last_offer_total > 3000`:

| Current | Next |
|---|---|
| 30 / 25 | 18 |
| 20 / 18 | 12 |
| 12 | 8 |

`MAX_PRICE_COUNTERS_PER_MATCH = 2` — after two price counters, best-and-final at 8% or cheaper equivalent holiday.

### Live autonomous results (post-7D)

| Persona | Closed? | Rounds | End reason | Notes |
|---|---|---|---|---|
| **practice-bob** | **Yes** | 4 | accept | Unchanged |
| **practice-toni** | **Yes** | 3 | accept | Unchanged |
| **practice-gordon** | No | 5 | walk | Luxury ladder 25→18→12; walked on 7n vs 14n duration |
| **practice-cris** | **Yes** | 5 | accept | Holiday+car offer; counter 35→18; no round-cap |

**Tests:** 7 offline tests in `test_live_agent_hard_personas.py` + 1 luxury ladder test in `test_pricing.py`.

---

## Phase 7E — Branch Consolidation + Gordon Duration

**Modules:** `scripts/analyze_branches.py`, `experiments/ported_improvements.py`, `negotiation/strategist.py`, `mcp/city_break.py`, `scripts/evaluate_personas.py`

Audited all git branches; cherry-picked deterministic ideas from `origin/feature/deal-room-agent` (parallel monolith — **no merge**).

### Branch audit outputs

- `logs/branch_inventory.json` — 6 branches, keyword hits, candidate files
- `logs/high_value_branches.json` — `deal-room-agent` ranked HIGH
- `logs/branch_diffs/` — per-prefix diff summaries vs current branch
- `logs/cris_branch_analysis.json` — why ~31% Cris markup: lower opening + total-based concessions

### Ported improvements (traceable in `ported_improvements.py`)

| Feature | Source | Target |
|---|---|---|
| Total-based counter (92%/85% of last total) | `MarkupLadder.clamp` | `pricing.py`, `policy.py` |
| Luxury opening cap (25% max first offer) | `_fallback_markup` | `pricing.py`, `live_agent.py` |
| Cheaper-product pivot (≤80% cost) | `_find_cheaper_alternative` | `live_agent.py` |
| Premium car tier filter | `search.find_car` | `selection.py` |
| `desired_nights` search order 14→10→7 | `profile.nights` | `BuyerState`, `live_agent.py` |
| Duration mismatch disclosure | — | `live_agent._car_aware_reply` |
| Conversation dead-stop | `_conversation_is_dead` | `live_agent.run` |
| Negotiation Strategist (advisory) | `BuyerRead` | `strategist.py`, `responder.py` |
| City-break interfaces (stub) | `_search_trivago` | `mcp/city_break.py` |

**Rejected:** LLM `PricingStrategist` (no LLM-controlled markup).

### Gordon duration fix

- `desired_nights` in `ConversationAnalysis` + `BuyerState` (regex: "two weeks" → 14)
- `holiday_duration_plan()` searches TSM at desired duration first
- `session.duration_mismatch` set when offer nights ≠ desired; disclosed in seller text

### Evaluation

```bash
python scripts/analyze_branches.py
python scripts/evaluate_personas.py --runs 5
```

Output: `logs/post_port_summary.json` (close_rate, walk_rate, average/median markup per persona).

**Tests:** 209 offline tests (`test_strategist.py`, `test_ported_improvements.py`, duration/counter tests).

---

## Phase 8A — Multi-Persona Practice Runner

**Module:** `scripts/run_practice_agent.py`

Practice-only scaffold. Whitelisted personas. `PRACTICE` brief guard. Never `POST /match {}`.

| Persona | Path |
|---|---|
| `practice-bob` | Holiday — TSM search, 30% markup, `generate_reply(OFFER)` |
| `practice-toni` | Tour — TourRadar search, 12% markup, `generate_reply(OFFER)` |
| `practice-elon` | Discovery-only (no offer yet) |
| `practice-gordon` | Discovery-only |
| `practice-cris` | Discovery-only |

```bash
python scripts/run_practice_agent.py --persona practice-bob
python scripts/run_practice_agent.py --persona practice-toni
```

Logs: `logs/practice_agent_<persona>.jsonl`

---

## Phase 8B — Discover Remaining Personas

**Module:** `src/dealbreakers/experiments/persona_discovery.py`, `scripts/discover_remaining_personas.py`

Targets: `practice-elon`, `practice-gordon`, `practice-cris` only (Bob/Toni excluded — already closed).

- 4 discovery turns per persona (configurable 1–5); **no offers sent**
- `ConversationAnalyzer` + `BuyerState` updated after **every turn**
- Per-turn snapshots in profile JSON (analysis + state per round)

**Outputs per persona:**
- `logs/persona_profiles/<persona>.jsonl` — full transcript
- `logs/persona_profiles/<persona>.json` — profile with turn snapshots + final analysis/state

**Summary:** `logs/persona_summary.json`

```bash
python scripts/discover_remaining_personas.py
python scripts/discover_remaining_personas.py --persona practice-gordon --turns 5
```

**Live discovery results:**

```json
{
  "practice-elon": {
    "product": "holiday",
    "luxury": 0.5,
    "price_sensitivity": 0.0,
    "trust_sensitivity": 0.0,
    "destinations": ["Berlin", "Stockholm"],
    "must_haves": ["fast reliable wifi", "proper gym", "modern 4-star minimum", "central location"],
    "estimate_safe_markup": 10.0,
    "estimate_aggressive_markup": 15.0,
    "objections": []
  },
  "practice-gordon": {
    "product": "holiday",
    "luxury": 1.0,
    "price_sensitivity": 0.0,
    "trust_sensitivity": 0.0,
    "destinations": [],
    "must_haves": ["genuinely five-star hotel", "outstanding reviews", "world-class spa", "immediate beach access"],
    "estimate_safe_markup": 18.0,
    "estimate_aggressive_markup": 35.0,
    "objections": []
  },
  "practice-cris": {
    "product": "holiday",
    "luxury": 1.0,
    "price_sensitivity": 0.0,
    "trust_sensitivity": 0.0,
    "destinations": ["Algarve", "Amalfi Coast"],
    "must_haves": ["five stars", "world-class spa", "serious gym", "beachfront", "elegant sun terrace", "luxury car"],
    "estimate_safe_markup": 18.0,
    "estimate_aggressive_markup": 35.0,
    "objections": ["stop asking questions and show me what you've actually got", "give me a concrete package right now"]
  }
}
```

---

## Phase 8C — Close Remaining Personas

**Module:** `scripts/close_elon.py`, `close_gordon.py`, `close_cris.py`, `offers/selection.py`, `tests/test_remaining_closers.py`

Practice-only close scripts for the three remaining personas. One refinement/confirmation turn, silent TSM search, one structured offer. Superseded by 7C autonomous agent for general use; kept for comparison. No fabricated inventory.

**Shared safety (all three):**
- Hardcoded `PERSONA_ID`; only `start_match(practice=True, persona_id=...)`
- `assert_practice_match()` — halts if brief lacks `"PRACTICE"`
- Prints `PRACTICE MODE ONLY — CLOSE <PERSONA>`
- No `--official`, `--practice`, or persona flags
- Aborts without offer when no offerable candidate exists

**Persona-specific scoring (`selection.py`):**
- `score/pick_best_elon_candidate` — WiFi, gym, 4-star+, central location, value
- `score/pick_best_gordon_candidate` — 5-star, spa/beach/pool, reviews over price
- `score/pick_best_cris_candidate` — spa, gym, beach, sun terrace, quality-first

### close_elon.py

- **Strategy:** City-break via TSM — Berlin then Stockholm, durations 3/4/7 nights
- **Turn 1:** refinement question (Berlin vs Stockholm, central 4-star WiFi + gym)
- **Search:** `month=7`, `stars=4`, `facilities=["wifi","gym"]`, `limit=10`
- **Markup:** 15%
- **Live result:** 0 offerable across all destination/duration combos — aborted cleanly, no fabricated offer
- **Blocker:** TSM is UK package holidays; no Berlin/Stockholm inventory — needs **trivago** (hotels) or **Kiwi** (flights)

### close_gordon.py

- **Strategy:** Luxury 5-star beach/spa — Spain, Greece, Portugal fallback
- **Turn 1:** one refinement question (true 5-star spa, best-reviewed over cheapest)
- **Search:** `stars=5`, `facilities=["spa","close_to_beach","pool"]`; 4-star fallback if no 5-star offerable
- **Markup:** 30%
- **Live result:** Hotel Suite Villa Maria, La Caleta, Tenerife — 5★, review 9.7, £4,356 cost → £5,662.80 total. Buyer: price too high (`continue`). **5-star TSM path works**; 7C autonomous agent now COUNTERs but Gordon still walks.

### close_cris.py

- **Strategy:** Impatient luxury — confirmation (not a question), fast offer
- **Turn 1:** "Understood — I'll keep this premium and concrete…" (no multi-question discovery)
- **Search:** Algarve → Amalfi Coast → Portugal → Italy; progressive relaxation (drop `sun_terrace`, then allow 4-star)
- **Markup:** 30%; **holiday-only** — `car_wrapper_available()` returns `False`, logs `"car missing"`
- **Live result:** Tivoli Marina Vilamoura Algarve Resort, Vilamoura — 5★, £3,130 cost → £4,069 total. Buyer: wants premium rental car included (`continue`). **Holiday path works**; car wrapper is the close blocker.

```bash
python scripts/close_elon.py
python scripts/close_gordon.py
python scripts/close_cris.py
```

**Tests:** 13 offline tests in `test_remaining_closers.py` — hardcoded persona, practice guard, persona scoring, no car invented, no offer when unofferable.

---

## How closing works today

Deals close via **structured `offer` JSON** — words alone do nothing.

### Primary path: autonomous agent (`run_autonomous_practice.py`)

Multi-turn policy loop (up to 15 rounds):

1. **Analyze** conversation → extract trip type, destinations, must-haves, sensitivities
2. **Decide** next action deterministically (`decide_action()`)
3. **Execute** — question, silent search, offer, or counter-offer
4. **Send** turn to Deal Room; buyer LLM responds
5. **Repeat** until accept, walk, or round-cap

### Legacy path: scripted closers (`close_*.py`)

Two-turn hardcoded flow — one question, one offer. Still works for Bob/Toni; superseded by 7C for general use.

| Component | Uses LLM? | Role |
|---|---|---|
| `LiveNegotiationAgent` | Mixed | Policy loop orchestrator |
| `decide_action()` | **No** | Business decisions — action + markup target |
| `ConversationAnalyzer` | **Yes** (our OpenAI) | Per-turn extraction into BuyerState |
| `generate_reply()` | **Yes** (our OpenAI) | Wording only — never markup/inventory |
| Deal Room buyer | **Yes** (their server) | Buyer replies; main turn latency |
| TSM / TourRadar MCP | No | Inventory search (routed by `trip_type`) |
| `close_*.py` scripts | Template/OpenAI text | Legacy 2-turn closers |

---

## Verification status

**174/174 unit tests pass**, all offline.

**Live runs verified:**

| Script | Result |
|---|---|
| `smoke_match.py --persona practice-bob` | All 4 event types in JSONL |
| `run_practice_once.py --persona practice-toni` | Tour-path persona confirmed |
| `discover_mcp_tools.py` | 5/5 MCP servers, 26 tools |
| `search_holidays.py` | 5/5 offerable TSM candidates |
| `search_tours.py` | 5/5 offerable TourRadar candidates |
| `close_bob.py` | Holiday closed (8%, 2 rounds) |
| `close_toni.py` | Tour closed (12%, 2 rounds, no 400) |
| `markup_sweep.py` | Bob accepts 5–35%, rejects 40% |
| `find_markup_ceiling.py --lo 35 --hi 40` | Bob exact ceiling 35% |
| `analyze_transcript.py` | Bob intelligence extracted correctly |
| `build_state.py` | Bob state: `known_affordable_total=1056.24` |
| `run_practice_agent.py` | Bob + Toni practice-only |
| `discover_remaining_personas.py` | Elon, Gordon, Cris profiles generated |
| `close_elon.py` | No offer — TSM 0 offerable Berlin/Stockholm |
| `close_gordon.py` | Valid 5★ offer sent; rejected at 30% markup |
| `close_cris.py` | Valid 5★ holiday sent; buyer wants car |
| `run_autonomous_practice.py --persona practice-bob` | **Closed** autonomously (4 rounds) |
| `run_autonomous_practice.py --persona practice-toni` | **Closed** autonomously (3 rounds) |
| `run_autonomous_practice.py --persona practice-gordon` | Walked after 2× COUNTER (6 rounds) |
| `run_autonomous_practice.py --persona practice-cris` | Round-cap; multiple COUNTERs (15 rounds) |

### Example log shape

```json
{"timestamp": "...", "record_type": "match_started", "match_id": "34fb...", "practice": true, "persona_id": "practice-bob", "scenario_name": "Bob Ross", "scenario_brief": "...", "status": "awaiting-seller", "buyer_text": "...", "buyer_action": "continue"}
{"timestamp": "...", "record_type": "buyer_message", "match_id": "34fb...", "role": "buyer", "round_number": null, "text": "...", "action": "continue"}
{"timestamp": "...", "record_type": "seller_message", "match_id": "34fb...", "role": "seller", "round_number": 1, "text": "...", "offer": null}
{"timestamp": "...", "record_type": "turn_response", "match_id": "34fb...", "status": "awaiting-seller", "buyer_text": "...", "buyer_action": "continue", "quote": null, "result": null}
```

### Example agent_turn log shape (7C)

```json
{"record_type": "agent_turn", "round_number": 2, "action": "offer", "policy_decision": {"action": "offer", "reasoning": "...", "target_markup": 12.0}, "walk_risk": 0.1, "markup": 12.0, "buyer_state": {"trip_type": "holiday", "destinations": ["Spain"], "must_haves": ["pool"]}, "selected_inventory": {"type": "holiday", "hotel_name": "...", "cost": 978.0}, "seller_text": "...", "offer_sent": true, "buyer_action": "accept"}
```

---

## How to Run

```bash
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env          # DEAL_ROOM_BASE_URL, DEAL_ROOM_TEAM_KEY, OPENAI_API_KEY
pytest tests/ -v

# --- Practice smoke ---
python scripts/smoke_match.py --persona practice-bob
python scripts/smoke_match.py --persona practice-toni --log logs/toni.jsonl
python scripts/run_practice_once.py --persona practice-gordon --log logs/gordon.jsonl

# --- MCP discovery (read-only) ---
python scripts/discover_mcp_tools.py

# --- Inventory search (read-only) ---
python scripts/search_holidays.py --destination Spain --month July --duration 7 --stars 4 --limit 5
python scripts/search_tours.py --query "guided tour of Spain" --country Spain --limit 5

# --- Practice closes (PRACTICE ONLY, hardcoded personas) ---
python scripts/close_bob.py
python scripts/close_toni.py
python scripts/close_elon.py
python scripts/close_gordon.py
python scripts/close_cris.py

# --- Markup experiments (Bob, PRACTICE ONLY) ---
python scripts/markup_sweep.py
python scripts/markup_sweep.py --markups 8,12,15,18,20,25
python scripts/find_markup_ceiling.py --lo 35 --hi 40

# --- Autonomous agent (7C, PRACTICE ONLY) — primary path ---
python scripts/run_autonomous_practice.py --persona practice-bob
python scripts/run_autonomous_practice.py --persona practice-toni
python scripts/run_autonomous_practice.py --persona practice-gordon
python scripts/run_autonomous_practice.py --persona practice-cris

# --- Multi-persona runner (8A, PRACTICE ONLY) ---
python scripts/run_practice_agent.py --persona practice-bob
python scripts/run_practice_agent.py --persona practice-toni

# --- Discover unknown personas (8B, needs OPENAI_API_KEY) ---
python scripts/discover_remaining_personas.py
python scripts/discover_remaining_personas.py --persona practice-cris --turns 4

# --- Graph orchestrator (8E, PRACTICE ONLY) ---
python scripts/run_graph_practice.py --persona practice-bob
python scripts/train_bandit_practice.py --personas practice-bob,practice-toni --runs 5
python scripts/compare_runners.py --runs 3

# --- Post-hoc analysis ---
python scripts/analyze_transcript.py --log logs/close_bob.jsonl --out logs/analysis.json
python scripts/build_state.py --log logs/close_bob.jsonl --analysis logs/analysis.json
```

---

## Roadmap

| Phase | Module | What it does | Status |
|---|---|---|---|
| 1 | `api/` + `models/` | Deal Room API client | **Done** |
| 2 | `logging/` | JSONL + TranscriptRecorder + practice scripts | **Done** |
| 3 | `analysis/` | ConversationAnalyzer — sensitivity scores, must-haves, objections | **Done** |
| 4 | `state/` | BuyerState — budget semantics, markup estimators | **Done** |
| 5A | `mcp/client.py` + `discovery.py` | MCP JSON-RPC + live tool discovery | **Done** |
| 5B | `travelsupermarket.py` + `normalizers.py` | TSM holiday search → `HolidayCandidate` | **Done** |
| 5C | `tourradar.py` + `tour_normalizers.py` | TourRadar search → `TourCandidate`; `close_toni.py` | **Done** |
| 5D-A | `car_normalizers.py` + `cars.py` | Car hire MCP wrapper (EconomyBookings/TSM) | **Done** |
| 5D | `mcp/` | Hotels (trivago), flights (Kiwi) | Stub |
| 6A | `close_bob.py` + `selection.py` | First holiday close vs Bob | **Done** |
| 6B | `markup_sweep.py` | Bob markup ladder; ceiling 35% | **Done** |
| 6C | `offers/` | Full offer generator — close probability scoring | Stub |
| 7A | `negotiation/policy.py` + `pricing.py` | Policy engine + adaptive markup + walk risk | **Done** |
| 7B | `responder.py` + `find_markup_ceiling.py` | Guard-railed reply generator + ceiling search | **Done** |
| 7C | `live_agent.py` + `run_autonomous_practice.py` | Autonomous policy loop; Bob/Toni close live | **Done** |
| 8A | `run_practice_agent.py` | Multi-persona scaffold — Bob/Toni paths | **Done** |
| 8B | `discover_remaining_personas.py` | Elon/Gordon/Cris 4-turn discovery profiles | **Done** |
| 8C | `close_elon/gordon/cris.py` | Close paths for elon/gordon/cris | **Done** — Gordon/Cris offer sent; Elon blocked on TSM |
| 7D | `live_agent.py` tuning | Car path, impatience fast-path, luxury counters | **Done** — Cris closes |
| 7E | `analyze_branches.py` + ports | Branch audit, total-based counters, duration, strategist | **Done** |
| 8E | `graph/` + `learning/bandit.py` | Optional LangGraph orchestrator + practice bandit | **Done** |
| 8F | `trivago.py` + `kiwi.py` + `city_break.py` | Elon city-break path + Gordon duration/pivot | **Done** |
| 9 | — | Official match runner with opt-in guard | Not started |

### Planned negotiation strategy

- **Early (rounds 1–3):** discover — at most 2 questions per turn, no price talk.
- **Mid (rounds 4–8):** narrow requirements, search MCP inventory, present first offer with healthy markup (anchor high).
- **Late (rounds 9–15):** close — concede markup in steps if buyer objects; protect close (50 pts) over margin (30 pts).

---

## Phase 8E — LangGraph Orchestrator + Bandit Learning

**Optional orchestration layer** wrapping existing deterministic modules. `LiveNegotiationAgent` unchanged.

| Module | Purpose |
|---|---|
| `graph/state.py` | Serializable `GraphState` (persona, transcript, policy, offer, logs) |
| `graph/nodes.py` | Thin wrappers: analyze, strategist, decide, search, select, counter, reply, send |
| `graph/runner.py` | LangGraph when installed; deterministic fallback loop otherwise |
| `learning/bandit.py` | Epsilon-greedy strategy arms (markup/search/counter); practice-only |
| `scripts/run_graph_practice.py` | CLI → `logs/graph/<persona>.jsonl` |
| `scripts/train_bandit_practice.py` | Practice training → `logs/bandit_policy.json` |
| `scripts/compare_runners.py` | live_agent vs graph vs graph+bandit → `logs/runner_comparison.json` |

**Safety:** practice whitelist only; `assert_practice_match()`; max 15 rounds; no LLM markup/inventory control; bandit `epsilon=0` on exploit/compare.

**Deps:** `langgraph` + `langchain-core` in `requirements.txt` (optional — import failure uses fallback).

**Tests:** `test_graph_state.py`, `test_graph_nodes.py`, `test_bandit.py`, `test_runner_comparison.py` (+229 total offline).

---

## Phase 8F — Close All Five Personas (Elon + Gordon)

**City-break MCP stack:**
- `hotel_normalizers.py` + `trivago.py` — suggestions → accommodation search
- `flight_normalizers.py` + `kiwi.py` — London → BER/STO flights (price in package cost only)
- `city_break.py` — `CityBreakCandidate`, `CityBreakSearchClient`, `to_holiday()`
- CLIs: `search_hotels.py`, `search_flights.py`

**Elon routing:** `run_inventory_search()` branches to city-break when `city_break` trip type or Berlin/Stockholm detected. Live: **closed in 2 rounds** (INNSiDE Berlin Mitte via Trivago, 12% markup).

**Gordon duration:** accumulates all duration searches (14→10→7), permission REFINE for shorter stay, duration mismatch disclosure, cheaper-equivalent pivot at 0% markup on luxury counters.

**Evaluation:** `compare_runners.py` — all 5 personas, `failure_reason`, `logs/all_persona_comparison.json`. `official_readiness_check.py` — READY/NOT READY gate.

**Tests:** 262 offline passing (`test_trivago`, `test_kiwi`, `test_city_break`, `test_elon_routing`, `test_gordon_duration`, `test_official_readiness`).

---

## Practice learnings

### practice-bob (easy) — 7C closes autonomously
- **Autonomous close in 4 rounds** via DISCOVER → SEARCH → OFFER.
- Scripted ceiling: **35%** (binary search). Autonomous uses walk-risk BALANCED (~12% default profile).
- Bob negotiates rather than walks — COUNTER ladder available if needed.

### practice-toni (medium) — 7C closes autonomously
- **Autonomous close in 3 rounds.** Analyzer extracts `trip_type=tour` → TourRadar search.
- Scripted close was 12% markup; autonomous uses state-driven scoring + walk-risk markup.

### practice-elon (medium) — 8C blocked
- Chose **Stockholm** in live close; wants central 4-star, real WiFi, serious gym.
- **TSM returned 0 offerable** for Berlin/Stockholm at 3/4/7 nights — script aborted without offer.
- **Next:** trivago standalone hotels + Kiwi flights, or different MCP city-break path.

### practice-gordon (hard) — 7D luxury ladder, walked on duration
- Autonomous agent sends **2× COUNTER** (25% → 18% → 12% luxury ladder).
- Buyer walked at round 5 — primary objection was **7 nights vs 14 nights requested**, not small counters.
- Impatience fast-path reduces DISCOVER stalling.

### practice-cris (hard) — 7D closes with holiday+car
- **5 rounds** — OFFER with car (Fiat Panda via EconomyBookings, Tenerife pickup).
- Luxury counter 35% → 18% on price objection → **accept**.
- Car search uses holiday `location` (not vague "Mediterranean").

### General
- **7C/7D autonomous loop** closes Bob, Toni, and Cris without hardcoded persona routing.
- Gordon still blocked on duration inventory (7n packages only); Elon needs trivago/Kiwi.
- Every autonomous turn is explainable from `logs/autonomous/*.jsonl` (`agent_turn` records).
- TourRadar departure price is the safest bookable cost.
- Bob markup sweep: ~3–7 min for 10 sequential matches (no per-markup progress output).
- OpenAI used per turn: analyzer (extraction) + responder (wording). Policy/markup/inventory stay deterministic.

---

## Open design questions

1. ~~How aggressively to anchor markup?~~ **Answered:** Bob ceiling 35%; anchor 30%; COUNTER ladder for recovery.
2. ~~When to switch from discovery to offer?~~ **Answered (7A):** `decide_action()` information-completeness heuristic.
3. ~~Walk risk from objection language?~~ **Partially answered (7A):** `estimate_walk_risk()` deterministic.
4. ~~TourRadar bookable price?~~ **Answered (5C):** `b2b-tour-departures` departure price.
5. ~~MCP amenity mapping?~~ **Answered (5B):** TSM facility IDs 1–24 → canonical vocab.
6. ~~**Elon product type**~~ **Answered (8C):** city-break; TSM has no Berlin/Stockholm — needs trivago/Kiwi.
7. ~~**Cris car path**~~ **Answered (5D-A/7D):** EconomyBookings wrapper + combined `offer.car`; Cris closes live.
8. ~~**Gordon 5-star**~~ **Answered (8C):** TSM 5-star filter works; 30% opening markup too high.
9. ~~**Wire Phase 7C**~~ **Answered:** `LiveNegotiationAgent` closes Bob/Toni; COUNTER works for Gordon/Cris.
10. ~~**Impatient-buyer fast-path**~~ **Answered (7D):** `apply_impatience_override()` forces SEARCH/OFFER.
11. **Official match guard** — explicit opt-in before `start_match({})`.
12. **Buyer budget semantics** — Phase 4 distinguishes stated/affordable/rejected; TSM `maxPrice` per-person vs party total remains.

---

## Tech Stack

- **Python 3.11+** (dataclasses, type hints, no agent framework)
- **`requests`** for HTTP, **`python-dotenv`** for config
- **OpenAI API** (`openai>=1.40`):
  - Phase 3 **analyzer** — extraction, `response_format=json_object`, temperature 0
  - Phase 7B **responder** — wording only, temperature 0.7, banned-phrase validation, deterministic fallback
  - OpenAI **never** controls markup, inventory, or offer structure
- **Deal Room buyer LLM** on every `send_turn` (their server)
- **`pytest`** + **`requests-mock`** for tests (262 offline tests)
- **`langgraph`** + **`langchain-core`** (optional, Phase 8E orchestration)
