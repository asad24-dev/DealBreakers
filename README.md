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

1. Asks concise qualifying questions for must-haves, trip type, dates, party size, car need, and budget.
2. Searches TravelSupermarket first, then fills gaps with trivago, Kiwi, EconomyBookings, and TourRadar.
3. Sends only structured offers backed by MCP source URLs and prices.
4. Starts with meaningful markup and concedes based on buyer resistance, while never going below cost.
5. Prefers closing once the buyer indicates fit and price is plausible, because close rate dominates the score.

## Architecture

The seller is deliberately a deterministic controller with internal evaluators, not a swarm of chatty agents:

- `dealbreakers.profile` extracts buyer intent, budget pressure, luxury signals, trip type, and must-haves.
- `dealbreakers.strategy` decides whether to ask, search, offer, or concede.
- `dealbreakers.mcp` talks directly to Streamable HTTP MCP servers and discovers tools.
- `dealbreakers.search` ranks MCPs/tools and only fills tool arguments from known buyer facts.
- `dealbreakers.catalog` normalizes raw MCP results and scores candidate fit.
- `dealbreakers.models` validates every structured offer before it reaches the Deal Room API.

LangChain is available for later typed extraction and message polish, but real listings, pricing, and structured offers stay outside the LLM path.

