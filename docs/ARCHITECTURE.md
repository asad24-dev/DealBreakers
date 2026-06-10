# DealBreakers — System Architecture

Deep-dive architecture reference for the `main` branch implementation. All diagrams reflect code in `dealbreakers/` as of this repository state.

**Related:** [Negotiation flow detail](./NEGOTIATION-FLOW.md) · [README](../README.md)

---

## 1. System context

DealBreakers sits between three external systems: the Listo Deal Room API (buyer negotiation), five travel MCP servers (inventory), and OpenAI (optional judgment calls).

```mermaid
flowchart TB
    subgraph operator [Operator]
        CLI["python -m dealbreakers"]
    end

    subgraph dealbreakers [DealBreakers package]
        SA["SellerAgent"]
        DR["DealRoomClient"]
        SE["McpSearchEngine"]
        EV["Evaluators"]
        LLM["llm.py"]
    end

    subgraph listo [Listo Deal Room API]
        MATCH["POST /match"]
        TURN["POST /match/id/turn"]
        BUYER["AI Buyer Agent"]
    end

    subgraph mcps [Travel MCP servers]
        TSM["TravelSupermarket"]
        TRI["trivago"]
        TRD["TourRadar"]
        ECO["EconomyBookings"]
        KIW["Kiwi"]
    end

    subgraph openai [OpenAI]
        GPT["gpt-4o-mini via LangChain"]
    end

    CLI --> SA
    SA --> DR
    DR --> MATCH
    DR --> TURN
    TURN --> BUYER
    BUYER --> TURN

    SA --> SE
    SE --> TSM
    SE --> TRI
    SE --> TRD
    SE --> ECO

    SA --> EV
    EV --> LLM
    LLM --> GPT

    CLI -.-> KIW
```

**Legend:** Solid lines are runtime negotiation and search paths. The dotted line to Kiwi is tool discovery only (`discover-tools`); `McpSearchEngine` does not query Kiwi during inventory search.

---

## 2. Package layering

```mermaid
flowchart TB
    subgraph presentation [Presentation]
        CLI2["cli.py"]
        MAIN["__main__.py"]
    end

    subgraph orchestration [Orchestration]
        AGENT["agent.py — SellerAgent"]
        STATE["NegotiationState"]
    end

    subgraph domain [Domain logic]
        PROF["profile.py — BuyerProfile"]
        STRAT["strategy.py — NegotiationPolicy"]
        CAT["catalog.py — candidates and offers"]
        COMP["composer.py — template messages"]
    end

    subgraph intelligence [Intelligence layer]
        EVAL["evaluators.py"]
        LLM2["llm.py"]
    end

    subgraph integration [Integration layer]
        DR2["dealroom.py"]
        MCP2["mcp.py"]
        SEARCH2["search.py"]
    end

    subgraph foundation [Foundation]
        MODELS["models.py"]
        CONFIG["config.py"]
    end

    MAIN --> CLI2
    CLI2 --> AGENT
    AGENT --> STATE
    AGENT --> PROF
    AGENT --> STRAT
    AGENT --> CAT
    AGENT --> COMP
    AGENT --> EVAL
    AGENT --> SEARCH2
    AGENT --> DR2
    EVAL --> LLM2
    SEARCH2 --> MCP2
    SEARCH2 --> CAT
    CAT --> MODELS
    DR2 --> MODELS
    AGENT --> CONFIG
    DR2 --> CONFIG
    MCP2 --> CONFIG
```

---

## 3. SellerAgent internal wiring

`SellerAgent.__init__` constructs one instance of each collaborator. Nothing is recreated per round except transient LLM calls.

```mermaid
flowchart LR
    SA2["SellerAgent"]

    SA2 --> DR3["DealRoomClient"]
    SA2 --> MS["McpSearchEngine"]
    SA2 --> NP["NegotiationPolicy"]
    SA2 --> MC["MessageComposer templates"]
    SA2 --> PE["ProfileEvaluator"]
    SA2 --> SL["ShortlistEvaluator"]
    SA2 --> PS["PricingStrategist"]
    SA2 --> MCL["MessageComposerLLM"]
    SA2 --> MCR["MessageCritic"]
    SA2 --> NS["NegotiationState"]
    SA2 --> LOG["logs/ JSON writer"]
```

| Collaborator | File | Responsibility |
|--------------|------|----------------|
| `DealRoomClient` | `dealroom.py` | `start_match`, `take_turn`, official lock |
| `McpSearchEngine` | `search.py` | Inventory and car search |
| `NegotiationPolicy` | `strategy.py` | Qualifying question templates |
| `ProfileEvaluator` | `evaluators.py` | Profile extraction and buyer read |
| `ShortlistEvaluator` | `evaluators.py` | Pick best listing from shortlist |
| `PricingStrategist` | `evaluators.py` | Markup decision with `MarkupLadder` |
| `MessageComposerLLM` | `evaluators.py` | Draft seller text |
| `MessageCritic` | `evaluators.py` | Revise draft before send |
| `MessageComposer` | `composer.py` | Template fallbacks |

---

## 4. Data model relationships

```mermaid
erDiagram
    MatchStart ||--|| Scenario : contains
    MatchStart ||--|| BuyerMessage : opening
    SellerTurn ||--o| StructuredOffer : optional
    StructuredOffer ||--o| HolidayOffer : one_of
    StructuredOffer ||--o| TourOffer : one_of
    StructuredOffer ||--o| CarOffer : optional
    StructuredOffer ||--|{ SourceReceipt : requires
    TurnResponse ||--|| BuyerMessage : reply
    TurnResponse ||--o| Quote : when_offered
    TurnResponse ||--o| MatchResult : when_ended

    NegotiationState ||--|| BuyerProfile : profile
    NegotiationState ||--o| BuyerRead : read
    NegotiationState ||--o| ScoredCandidate : candidate
    ScoredCandidate ||--|| ListingCandidate : candidate
```

### Key types

| Type | Module | Role |
|------|--------|------|
| `BuyerProfile` | `profile.py` | Accumulated buyer requirements |
| `BuyerRead` | `evaluators.py` | Latest-message psychology |
| `ListingCandidate` | `catalog.py` | Normalised MCP listing |
| `ScoredCandidate` | `catalog.py` | Listing plus fit score |
| `StructuredOffer` | `models.py` | API offer payload |
| `SellerTurn` | `models.py` | `{ text, offer? }` sent each turn |
| `Quote` | `models.py` | Server-returned cost, markup, total |

---

## 5. MCP integration architecture

```mermaid
flowchart TB
    subgraph engine [McpSearchEngine]
        COL["_collect"]
        RANK["_rank_servers"]
        TOOLS["_rank_tools"]
        ARGS["_arguments_for"]
        EXT["extract_candidates"]
        SCORE["CandidateScorer"]
    end

    subgraph transport [McpClient per server]
        INIT["initialize handshake"]
        LIST["tools/list"]
        CALL["tools/call"]
        DECODE["_decode_mcp_response"]
    end

    subgraph registry [TravelMcpRegistry]
        DISC["discover_all"]
    end

    COL --> RANK
    COL --> TOOLS
    TOOLS --> ARGS
    ARGS --> CALL
    CALL --> EXT
    EXT --> SCORE

    INIT --> LIST
    LIST --> CALL
    CALL --> DECODE

    DISC --> LIST
```

### Server routing by product preference

```mermaid
flowchart LR
    P["BuyerProfile.product_preference"]

    P -->|holiday| H["travelsupermarket then trivago then tourradar"]
    P -->|city_break| C["trivago then travelsupermarket"]
    P -->|tour| T["tourradar exhausted first then fallbacks"]

    H --> STOP["stop at first server with results"]
    C --> STOP
    T --> STOP
```

### Car hire path

```mermaid
flowchart LR
    WC["profile.wants_car"]
    WC --> FC["find_car"]
    FC --> E1["economybookings search-car-hire"]
    E1 -->|empty| E2["travelsupermarket search-car-hire"]
    E2 --> CAR["ListingCandidate car"]
    CAR --> OFFER["CarOffer in StructuredOffer"]
```

---

## 6. LLM integration pattern

Every evaluator follows the same contract: try structured LLM output, fall back to deterministic logic on `None`.

```mermaid
flowchart TB
    CALLER["SellerAgent or Evaluator"]

    CALLER --> CHECK{"OPENAI_API_KEY set?"}
    CHECK -->|no| FB["Deterministic fallback"]
    CHECK -->|yes| LC["LangChain ChatOpenAI"]
    LC --> STRUCT{"structured output?"}
    STRUCT -->|success| OUT["Use LLM result"]
    STRUCT -->|exception| FB

    FB --> CONT["Match continues"]
    OUT --> CONT
```

| Evaluator | LLM call | Fallback |
|-----------|----------|----------|
| `ProfileEvaluator.extract` | `ProfileExtraction` schema | `infer_profile()` regex only |
| `ProfileEvaluator.read_buyer` | `BuyerRead` schema | Default read values inside evaluator |
| `ShortlistEvaluator.pick` | `ShortlistVerdict` schema | Highest `CandidateScorer` score |
| `PricingStrategist.decide` | `PricingAdvice` after first quote | `_fallback_markup()` |
| `MessageComposerLLM.compose` | Freeform text | `MessageComposer` template |
| `MessageCritic.review` | `DraftReview` schema | Return draft unchanged |

First quote markup always uses deterministic `anchor_for()` — never LLM.

---

## 7. Offer construction pipeline

```mermaid
flowchart LR
    MCPR["MCP tool result raw JSON"]
    MCPR --> EC["extract_candidates"]
    EC --> LC2["ListingCandidate"]
    LC2 --> CS["CandidateScorer.score"]
    CS --> SC["ScoredCandidate"]
    SC --> PICK["ShortlistEvaluator.pick"]
    PICK --> PS2["PricingStrategist.decide"]
    PS2 --> BUILD["build_offer_from_candidate"]
    BUILD --> SO["StructuredOffer"]
    SO --> VAL["Pydantic validators"]
    VAL --> API["SellerTurn.api_payload"]
    API --> DR4["DealRoomClient.take_turn"]
```

`build_offer_from_candidate()` sets:

- primary product fields (`holiday` or `tour`)
- optional `car` from `find_car()`
- `markupPct` from pricing decision
- `sources[]` with MCP name, URL, and component price

---

## 8. Configuration and safety

```mermaid
flowchart TB
    ENV[".env file"]
    ENV --> SET["Settings config.py"]

    SET --> TK["TEAM_KEY"]
    SET --> URL["DEALROOM_BASE_URL"]
    SET --> KEY["OPENAI_API_KEY"]
    SET --> MOD["MODEL_NAME"]
    SET --> RND["MAX_ROUNDS"]
    SET --> TMO["REQUEST_TIMEOUT_SECONDS"]
    SET --> OFF["ALLOW_OFFICIAL_MATCHES"]

    CLI3["cli.py run --official"]
    CLI3 --> CONF{"--confirm-official?"}
    CONF -->|no| ERR["parser.error"]
    CONF -->|yes| LOCK{"ALLOW_OFFICIAL_MATCHES true?"}
    LOCK -->|no| OME["OfficialMatchLockedError"]
    LOCK -->|yes| MATCH2["POST /match official"]
```

---

## 9. Observability architecture

```mermaid
flowchart LR
    MATCH3["run_match loop"]

    MATCH3 --> CON["Rich Console live output"]
    MATCH3 --> DIM["dim debug lines per round"]
    MATCH3 --> LOG2["JSON log per turn in-progress"]
    MATCH3 --> LOGF["JSON log final result"]

    LOG2 --> FILE["logs/YYYYMMDD-HHMMSS-matchId-scenario.json"]
    LOGF --> FILE

    BATCH["batch_gordon.py"]
    BATCH --> FILE
    BATCH --> SUM["close rate summary table"]
```

### Log schema (per file)

```json
{
  "matchId": "string",
  "scenario": { "name": "string", "brief": "string" },
  "result": { "closed": true, "endReason": "accept", "rounds": 4 },
  "turns": [
    {
      "round": 1,
      "seller": "text",
      "offer": { "holiday": {}, "markupPct": 12, "sources": [] },
      "buyer": "text",
      "buyer_action": "continue",
      "quote": { "cost": 2552, "markupPct": 12, "total": 2858 }
    }
  ]
}
```

---

## 10. Module file map

| File | Lines of responsibility |
|------|-------------------------|
| `agent.py` | Turn loop, `_evaluate`, `_build_turn`, pivot, logging |
| `evaluators.py` | All LLM evaluators, `MarkupLadder`, `PricingStrategist` |
| `search.py` | MCP search orchestration, car hire |
| `catalog.py` | Candidate extraction, scoring, offer building |
| `mcp.py` | JSON-RPC transport, `TRAVEL_MCPS`, discovery |
| `dealroom.py` | Deal Room HTTP client, official lock |
| `profile.py` | `BuyerProfile`, regex `infer_profile()` |
| `strategy.py` | `NegotiationPolicy`, qualifying questions |
| `composer.py` | Template message fallbacks |
| `models.py` | Pydantic API and offer models |
| `llm.py` | LangChain wrapper with graceful failure |
| `config.py` | `Settings` from environment |
| `cli.py` | `run`, `discover-tools` commands |
