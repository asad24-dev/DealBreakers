"""Environment configuration."""

from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    base_url: str
    team_key: str


def load_settings() -> Settings:
    load_dotenv()

    base_url = os.getenv("DEAL_ROOM_BASE_URL", "").rstrip("/")
    team_key = os.getenv("DEAL_ROOM_TEAM_KEY", "")

    missing = []
    if not base_url:
        missing.append("DEAL_ROOM_BASE_URL")
    if not team_key:
        missing.append("DEAL_ROOM_TEAM_KEY")

    if missing:
        raise ValueError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Copy .env.example to .env and fill in your values."
        )

    return Settings(base_url=base_url, team_key=team_key)
