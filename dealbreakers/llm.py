from __future__ import annotations

from functools import lru_cache
from typing import TypeVar

from pydantic import BaseModel

from dealbreakers.config import get_settings

ModelT = TypeVar("ModelT", bound=BaseModel)


@lru_cache(maxsize=2)
def _chat(temperature: float):
    settings = get_settings()
    if not settings.openai_api_key:
        return None
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        return None
    return ChatOpenAI(
        api_key=settings.openai_api_key,
        model=settings.model_name,
        temperature=temperature,
        timeout=settings.request_timeout_seconds,
        max_retries=1,
    )


def structured(prompt: str, schema: type[ModelT], *, temperature: float = 0.2) -> ModelT | None:
    """Run one structured-output LLM call. Returns None if the LLM is unavailable or fails,
    so every caller must have a deterministic fallback."""
    chat = _chat(temperature)
    if chat is None:
        return None
    try:
        return chat.with_structured_output(schema).invoke(prompt)
    except Exception:
        return None


def freeform(prompt: str, *, temperature: float = 0.6) -> str | None:
    chat = _chat(temperature)
    if chat is None:
        return None
    try:
        result = chat.invoke(prompt)
        text = result.content if isinstance(result.content, str) else str(result.content)
        return text.strip() or None
    except Exception:
        return None
