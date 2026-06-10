from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    team_key: str = Field(default="", alias="TEAM_KEY")
    dealroom_base_url: str = Field(default="", alias="DEALROOM_BASE_URL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    model_name: str = Field(default="gpt-4o-mini", alias="MODEL_NAME")
    request_timeout_seconds: float = Field(default=45, alias="REQUEST_TIMEOUT_SECONDS")
    max_rounds: int = Field(default=15, alias="MAX_ROUNDS")
    # SAFETY: official (scored) matches are locked out. Each official buyer is a
    # one-shot attempt, so this must stay False until the team deliberately flips
    # it in .env at submission time (ALLOW_OFFICIAL_MATCHES=true).
    allow_official_matches: bool = Field(default=False, alias="ALLOW_OFFICIAL_MATCHES")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    def require_dealroom(self) -> None:
        missing = []
        if not self.team_key:
            missing.append("TEAM_KEY")
        if not self.dealroom_base_url:
            missing.append("DEALROOM_BASE_URL")
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(f"Missing required Deal Room settings: {joined}")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
