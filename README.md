# DealBreakers Seller Agent

Seller agent for Listo's Deal Room challenge. It connects to the public travel MCPs, talks to the Deal Room buyer API, builds structured offers from real listings, and manages markup concessions over a turn-limited negotiation.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` with:

- `TEAM_KEY`: your `x-team-key`
- `DEALROOM_BASE_URL`: the Deal Room API host, for example `https://...`
- `OPENAI_API_KEY`: optional, used only for polishing seller messages

Before running a negotiation, inspect the live MCP schemas:

```powershell
python -m dealbreakers discover-tools
```

## Practice

```powershell
python -m dealbreakers run --practice --persona practice-bob
python -m dealbreakers run --practice --persona practice-toni
python -m dealbreakers run --practice --persona practice-elon
python -m dealbreakers run --practice --persona practice-gordon
python -m dealbreakers run --practice --persona practice-cris
```

## Official

Only run this when ready; each official buyer is one attempt.

```powershell
python -m dealbreakers run --official
```

## Strategy

The agent:

1. Builds a live buyer profile from the scenario and transcript: trip style, destination, party size, nights, budget, car need, must-have amenities, luxury signals, and price sensitivity.
2. Reads the buyer's latest message for mood, impatience, price resistance, overcharge suspicion, close signal, and whether the objection is about price, fit, or trust.
3. Asks concise qualifying questions only while they are useful. Impatient buyers or sufficiently specified trips get concrete offers quickly.
4. Searches TravelSupermarket, trivago, TourRadar, EconomyBookings, and other travel MCPs through typed tool calls, then normalizes all results into one candidate model.
5. Scores candidates by product type, destination fit, budget headroom, amenities, reviews, quality level, and live cost.
6. Sends only structured offers backed by MCP source URLs and prices. The verified cost stays separate from the seller markup.
7. Opens with meaningful markup, concedes visibly on total price when the buyer pushes back, and avoids going below cost.
8. Holds the price when the buyer sounds close to accepting, because unnecessary concessions donate margin.
9. Pivots to a cheaper base product only after sustained price pressure or exhausted markup room, and only when the new option is a real improvement rather than a confusing sideways swap.
10. Prefers closing once the buyer indicates fit and price is plausible, because close rate dominates the score.

## Architecture

The seller is deliberately a deterministic controller with internal evaluator agents, not a single unconstrained chatbot. `SellerAgent` owns the match state and decides when each specialist runs. The LLMs are used for bounded judgement calls; live facts, prices, source URLs, payload validation, and negotiation guard rails remain in code.

- `dealbreakers.agent` orchestrates the full observe/reason/act loop, maintains quote history, tracks objections, manages sticky candidates and pivots, adds car hire when requested, writes logs, and stops when the buyer accepts, walks, or the round limit is reached.
- `dealbreakers.profile` provides the deterministic baseline extractor for buyer intent, budget pressure, luxury signals, trip type, destination, party size, nights, car preference, and must-haves.
- `dealbreakers.evaluators.ProfileEvaluator` layers structured LLM extraction and a psychological buyer read on top of the baseline. An echo guard rejects "budgets" that merely mirror our previous quote or discount.
- `dealbreakers.search` acts as the tool-using inventory agent: it ranks MCP servers and tools, fills arguments only from known buyer facts, broadens failed searches, and handles the two-step trivago flow plus car hire lookup.
- `dealbreakers.mcp` talks directly to Streamable HTTP MCP servers, performs the initialize/session flow, lists tools, calls tools, and decodes JSON-RPC or event-stream responses.
- `dealbreakers.catalog` normalizes heterogeneous MCP responses into canonical `ListingCandidate` objects, extracts amenities, scores fit, and builds source-backed structured offers.
- `dealbreakers.evaluators.ShortlistEvaluator` chooses the most sellable candidate from the scored shortlist while avoiding an expensive base that leaves no room to negotiate.
- `dealbreakers.evaluators.PricingStrategist` estimates the buyer ceiling from quote/reaction history, sets markup, enforces a concession ladder, prevents accidental price increases, caps endgame markup, and resets anchors after product-class rescues.
- `dealbreakers.evaluators.MessageComposerLLM` drafts short seller messages from a precise turn intent and verified candidate summary.
- `dealbreakers.evaluators.MessageCritic` reviews every draft before send, checking tone, factual grounding, concession framing, and amenity wording.
- `dealbreakers.models` validates every structured offer before it reaches the Deal Room API.

The result is an agentic negotiation controller: it observes the buyer, reasons through specialised agents, uses MCP tools to gather live inventory, acts through a structured Deal Room turn, receives feedback, and updates its state. It is also intentionally grounded. Real listings, verified prices, source receipts, and API payloads stay outside the free-form LLM path.

For full architecture and negotiation flow detail, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/NEGOTIATION-FLOW.md](docs/NEGOTIATION-FLOW.md). For a fuller write-up of the agentic approach, including the TikZ architecture diagram, see `docs/DealBreakers-One-Pager.tex`.

