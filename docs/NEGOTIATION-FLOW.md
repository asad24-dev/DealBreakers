# DealBreakers — Negotiation Flow

Step-by-step flow diagrams for `SellerAgent.run_match()` on the `main` branch. Source of truth: [`dealbreakers/agent.py`](../dealbreakers/agent.py).

**Related:** [System architecture](./ARCHITECTURE.md) · [README](../README.md)

---

## 1. Match lifecycle overview

```mermaid
stateDiagram-v2
    [*] --> Init: start_match returns MatchStart
    Init --> RoundLoop: infer_profile from opening message

    RoundLoop --> Evaluate: for round 1 to MAX_ROUNDS
    Evaluate --> BuildTurn: _evaluate complete
    BuildTurn --> SendTurn: SellerTurn ready
    SendTurn --> LogProgress: take_turn plus append state.turns

    LogProgress --> Accept: buyer action accept
    LogProgress --> Walk: buyer action walk
    LogProgress --> Result: response.result set
    LogProgress --> Dead: two departure phrases
    LogProgress --> NextRound: continue

    NextRound --> RoundLoop: round plus 1
    RoundLoop --> RoundLimit: MAX_ROUNDS exhausted

    Accept --> [*]
    Walk --> [*]
    Result --> [*]
    Dead --> [*]
    RoundLimit --> [*]
```

---

## 2. Full round sequence

```mermaid
sequenceDiagram
    participant R as Round N
    participant E as _evaluate
    participant B as _build_turn
    participant DR as DealRoomClient
    participant LLM as Evaluators plus LLM
    participant MCP as McpSearchEngine

    R->>E: buyer_messages seller_messages
    E->>E: infer_profile plus ProfileEvaluator.extract
    E->>E: echo guard on budget
    E->>LLM: read_buyer last message
    E->>MCP: find_shortlist if profile changed or fit objection
    E->>LLM: ShortlistEvaluator.pick if candidate swap allowed

    R->>B: state buyer_messages round_number
    alt missing fields and no candidate and may_ask
        B->>B: NegotiationPolicy.qualifying_question
        B->>LLM: compose plus critic
        B-->>R: SellerTurn text only
    else no candidate yet
        B->>MCP: find_shortlist
        B->>LLM: ShortlistEvaluator.pick
    end

    alt tour buyer with hotel candidate
        B->>MCP: tour rescue search
        B->>B: reset_ladder
    end

    alt pivot_needed and pivots less than 2
        B->>B: _find_cheaper_alternative
    end

    alt wants_car and not searched
        B->>MCP: find_car
    end

    B->>LLM: PricingStrategist.decide
    B->>B: build_offer_from_candidate
    B->>LLM: compose plus critic with intent
    B-->>R: SellerTurn text plus offer

    R->>DR: take_turn match_id turn
    DR-->>R: TurnResponse buyer quote result
    R->>R: append quotes turns write log

    alt accept walk or result
        R-->>R: return
    else departure phrases x2
        R-->>R: return buyer-left
    end
```

---

## 3. `_evaluate` detail

Runs **before** every `_build_turn`. Updates `NegotiationState` in place.

```mermaid
flowchart TD
    START["_evaluate called"]

    START --> T1["Build transcript from last 20 lines"]
    T1 --> T2["infer_profile scenario plus messages"]
    T2 --> T3["ProfileEvaluator.extract via LLM"]
    T3 --> T4["merge_extraction into BuyerProfile"]

    T4 --> EG{"budget matches our quoted totals?"}
    EG -->|yes| EG2["set budget to None echo guard"]
    EG -->|no| T5
    EG2 --> T5

    T5["ProfileEvaluator.read_buyer"]
    T5 --> PO{"price objection or feels_overcharged?"}
    PO -->|yes| PO2["price_objections plus 1"]
    PO -->|no| PO3["price_objections reset to 0"]
    PO2 --> T6
    PO3 --> T6

    T6{"round at least 2 and no destination?"}
    T6 -->|yes| T6b["destination_flexible equals true"]
    T6 -->|no| T7
    T6b --> T7

    T7["Compute search_key tuple"]
    T7 --> NS{"profile changed and ready_to_search OR fit objection?"}
    NS -->|no| END["return"]
    NS -->|yes| SEARCH["McpSearchEngine.find_shortlist limit 5"]

    SEARCH --> HAS{"shortlist non-empty?"}
    HAS -->|no| END
    HAS -->|yes| STICKY{"already quoted and not fit objection?"}
    STICKY -->|yes| END
    STICKY -->|no| PICK["ShortlistEvaluator.pick"]
    PICK --> SET["state.candidate equals pick"]
    SET --> END
```

### Sticky candidate rule

Once `state.quotes` is non-empty, background re-search **does not** change `state.candidate` unless `main_objection == fit`. Deliberate product changes happen only in `_build_turn` via tour rescue or price pivot.

---

## 4. `_build_turn` decision tree

```mermaid
flowchart TD
    BT["_build_turn called"]

    BT --> Q1{"missing fields AND no candidate AND may_ask?"}
    Q1 -->|yes| ASK["qualifying_question plus compose plus critic"]
    ASK --> RET1["return text-only SellerTurn"]

    Q1 -->|no| Q2{"candidate is None?"}
    Q2 -->|yes| SRCH["find_shortlist plus pick"]
    SRCH --> Q2b{"still None and not ready?"}
    Q2b -->|yes| HOL["assume holiday preference"]
    HOL --> SRCH2["find_shortlist again"]
    SRCH2 --> TR
    Q2b -->|no| TR

    Q2 -->|no| TR

    TR{"tour preference but hotel candidate?"}
    TR -->|yes| RESCUE["re-search tours reset_ladder rescued true"]
    TR -->|no| NC

    RESCUE --> NC
    NC{"candidate still None?"}
    NC -->|yes| NFL["no_listing_found message"]
    NFL --> RET2["return text-only SellerTurn"]

    NC -->|no| PV

    PV{"pivot_needed?"}
    PV -->|yes| PIV["_find_cheaper_alternative max 2 pivots"]
    PV -->|no| CAR
    PIV --> CAR

    CAR{"wants_car and not car_searched?"}
    CAR -->|yes| FCAR["find_car once"]
    CAR -->|no| PRICE
    FCAR --> PRICE

    PRICE["PricingStrategist.decide plus build_offer"]
    PRICE --> INTENT["Select compose intent rescued pivot concede hold floor present"]
    INTENT --> MSG["compose plus critic"]
    MSG --> RET3["return SellerTurn text plus offer"]
```

### `may_ask` pacing logic

| Condition | Max qualifying rounds |
|-----------|---------------------|
| `impatience >= 0.55` | 1 |
| Patient buyer | 2 |
| Impatient **and** `ready_to_search()` | 0 — search immediately |

---

## 5. Price pivot logic

```mermaid
flowchart TD
    PN["pivot_needed"]

    PN --> C1{"prior quotes exist?"}
    C1 -->|no| NO["no pivot"]
    C1 -->|yes| C2{"markup at most 10 pct AND price_objections at least 1?"}
    C2 -->|yes| YES
    C2 -->|no| C3{"price_objections at least 2?"}
    C3 -->|yes| YES
    C3 -->|no| NO

    YES["pivot eligible"] --> G1{"rescued this turn?"}
    G1 -->|yes| NO
    G1 -->|no| G2{"pivots less than 2?"}
    G2 -->|no| NO
    G2 -->|yes| G3{"round at most MAX_ROUNDS minus 4?"}
    G3 -->|no| NO
    G3 -->|yes| FIND["_find_cheaper_alternative"]

    FIND --> V1["target cost equals current times 0.8"]
    V1 --> V2["check shortlist first"]
    V2 --> V3{"viable cheaper found?"}
    V3 -->|yes| SWAP["state.candidate equals cheaper pivots plus 1"]
    V3 -->|no| RE["re-search with budget equals target_cost"]
    RE --> V3
```

### Pivot viability checks

- Different URL from current listing
- `price_total <= current * 0.8`
- `score >= 0`
- Luxury buyers (`luxury_weight >= 0.5`): no star-rating downgrade

---

## 6. Pricing decision flow

```mermaid
flowchart TD
    PD["PricingStrategist.decide"]

    PD --> PIVT{"pivoted_this_turn?"}
    PIVT -->|yes| PIVM["markup from 80 pct of last total floor 4 pct"]
    PIVM --> OUT["PricingDecision"]

    PIVT -->|no| FIRST{"ladder.last_total is None?"}
    FIRST -->|yes| ANCH["anchor_for deterministic 28 pct base"]
    ANCH --> CLAMP1["MarkupLadder.clamp"]
    CLAMP1 --> OUT

    FIRST -->|no| LLM["LLM PricingAdvice or _fallback_markup"]
    LLM --> CLAMP2["MarkupLadder.clamp"]
    CLAMP2 --> OUT
```

### `MarkupLadder.clamp` guardrails

```mermaid
flowchart TD
    CL["clamp advised markup"]

    CL --> NH{"last_total exists?"}
    NH -->|yes| CAP["never quote higher than last total"]
    CAP --> PB{"price pushback?"}
    PB -->|feels_overcharged| CAP85["cap at 85 pct of last"]
    PB -->|resistance at least 0.6| CAP92["cap at 92 pct of last"]
    PB -->|mild| STEP10["min 10 pct step down"]
    PB -->|hard| STEP15["min 15 pct step down"]

    CAP85 --> WARM
    CAP92 --> WARM
    STEP10 --> WARM
    STEP15 --> WARM

    NH -->|no| WARM

    WARM{"close_signal at least 0.6 and no price pushback?"}
    WARM -->|yes| HOLD["hold last total salami-stop"]
    WARM -->|no| SAL{"concessions at least 3 and rounds remain?"}
    SAL -->|yes| HOLD
    SAL -->|no| BUD["clamp to stated budget if price objection"]

    HOLD --> ENDG
    BUD --> ENDG

    ENDG{"rounds remaining?"}
    ENDG -->|at most 3| CAP6["markup at most 6 pct"]
    ENDG -->|at most 1| CAP3["markup at most 3 pct"]
    CAP6 --> FLOOR["floor 2 pct ceiling 35 pct"]
    CAP3 --> FLOOR
    ENDG -->|else| FLOOR
    FLOOR --> DONE["return markup update last_total"]
```

### Opening anchor formula (`anchor_for`)

| Signal | Adjustment |
|--------|------------|
| Base | 28% |
| `luxury_weight >= 0.5` | +6% |
| `resistance <= 0.2` and not overcharged | +3% |
| `impatience >= 0.55` | −4% |
| `price_sensitivity >= 0.5` | −8% |
| Stated budget above cost | cap anchor just under budget |
| Final clamp | 12% – 35% |

---

## 7. Message intent selection

After pricing, `_build_turn` picks a compose `intent` string passed to `MessageComposerLLM`:

```mermaid
flowchart TD
    MI["intent selection"]

    MI --> R{"rescued tour this turn?"}
    R -->|yes| I1["wrong type apology present correct tour"]
    R -->|no| P{"pivoted_this_turn?"}
    P -->|yes| I2["new property dramatic saving in pounds"]
    P -->|no| C{"markup dropped vs last quote?"}
    C -->|yes| I3["concede buyer won negotiation"]
    C -->|no| F{"markup at floor 3 pct twice?"}
    F -->|yes| I4["final best number hold firm"]
    F -->|no| H{"total unchanged vs last quote?"}
    H -->|yes| I5["hold price answer questions no false concession"]
    H -->|no| I6["present package persuasively"]

    I1 --> CAR2{"car included?"}
    I2 --> CAR2
    I3 --> CAR2
    I4 --> CAR2
    I5 --> CAR2
    I6 --> CAR2

    CAR2 -->|yes| APPEND["append exact car model from package details"]
    CAR2 -->|no| COMPOSE
    APPEND --> COMPOSE["MessageComposerLLM.compose"]
    COMPOSE --> CRIT["MessageCritic.review"]
    CRIT --> DONE2["SellerTurn"]
```

---

## 8. `NegotiationState` field evolution

```mermaid
flowchart LR
    subgraph per_round [Updated each _evaluate]
        prof["profile"]
        read["read"]
        shortlist["shortlist"]
        candidate["candidate"]
        search_key["search_key"]
        price_obj["price_objections"]
    end

    subgraph per_turn [Updated each _build_turn]
        pivots["pivots"]
        pivoted["pivoted_this_turn"]
        car["car"]
        car_s["car_searched"]
    end

    subgraph per_response [Updated after take_turn]
        quotes["quotes"]
        turns["turns"]
    end
```

| Field | When set | When cleared / reset |
|-------|----------|----------------------|
| `profile` | Every `_evaluate` | Never — accumulates |
| `read` | Every `_evaluate` | Overwritten each round |
| `candidate` | Search, pick, pivot, rescue | Changed only via sticky rules or pivot |
| `quotes` | After each offer response | Append-only |
| `price_objections` | Consecutive price objections | Reset on non-price read |
| `pivots` | Successful pivot | Max 2 per match |
| `car` | `find_car` success | Cleared if `wants_car == False` |
| `car_searched` | First car attempt | Stays true after attempt |

---

## 9. Qualifying question routing

`NegotiationPolicy.qualifying_question()` in `strategy.py`:

```mermaid
flowchart TD
    QQ["missing_critical_fields"]

    QQ --> M1{"trip style missing?"}
    M1 -->|yes| Q1["hotel holiday city break or tour?"]
    M1 -->|no| M2{"budget and destination missing?"}
    M2 -->|yes| Q2["destination and budget?"]
    M2 -->|no| M3{"budget missing?"}
    M3 -->|yes| Q3["total budget?"]
    M3 -->|no| M4{"party size missing?"}
    M4 -->|yes| Q4["how many people?"]
    M4 -->|no| M5{"children ages missing?"}
    M5 -->|yes| Q5["under 2 or 2-17?"]
    M5 -->|no| M6{"duration missing?"}
    M6 -->|yes| Q6["how many nights?"]
    M6 -->|no| Q7["one must-have for easy yes?"]
```

---

## 10. End-condition detection

### Server-driven

- `response.buyer.action == accept`
- `response.buyer.action == walk`
- `response.result` is non-null

### Client-driven (`agent.py`)

**Departure detection** — last two buyer messages each contain a phrase from `_DEPARTURE_PHRASES`:

- `already gone`, `walks toward the door`, `out the door`
- `we are done`, `we're done`, `we're finished`
- `nothing more to discuss`, `goodbye`, `adios`, `adiós`
- `walking away`, `i'm walking away`

**Round limit** — loop completes `MAX_ROUNDS` without early return.
