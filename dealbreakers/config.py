from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


TRAVEL_MCP_ENDPOINTS = {
    "travelsupermarket": "https://travel-supermarket-integration-dev-test.up.railway.app/mcp",
    "trivago": "https://mcp.trivago.com/mcp",
    "kiwi": "https://mcp.kiwi.com/mcp",
    "economybookings": "https://economybookings-integration-dev.up.railway.app/mcp",
    "tourradar": "https://ai.tourradar.com/mcp/main",
}


@dataclass(frozen=True)
class Settings:
    team_key: str
    dealroom_base_url: str
    openai_api_key: str
    model: str
    aux_model: str
    request_timeout: float
    max_seller_rounds: int


def load_settings() -> Settings:
    load_dotenv()
    team_key = os.getenv("TEAM_KEY", "").strip()
    base_url = os.getenv("DEALROOM_BASE_URL", "").strip().rstrip("/")
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    main_model = os.getenv("MODEL", "gpt-4o")
    if not team_key:
        raise SystemExit("TEAM_KEY is missing. Put it in .env or the environment.")
    if not base_url or "replace-with" in base_url:
        raise SystemExit("DEALROOM_BASE_URL is missing. Put the Deal Room API host in .env.")
    if not openai_api_key:
        raise SystemExit("OPENAI_API_KEY is missing. The seller agent is LLM-driven and requires it.")
    return Settings(
        team_key=team_key,
        dealroom_base_url=base_url,
        openai_api_key=openai_api_key,
        model=main_model,
        aux_model=os.getenv("AUX_MODEL", "gpt-4o-mini"),
        request_timeout=float(os.getenv("REQUEST_TIMEOUT", "60")),
        max_seller_rounds=int(os.getenv("MAX_SELLER_ROUNDS", "15")),
    )
