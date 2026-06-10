"""Detect stall phrases and validate buyer-facing messages."""
from __future__ import annotations

STALL_PHRASES = (
    "technical issue",
    "bear with me",
    "bear with us",
    "one moment",
    "shortly",
    "checking availability",
    "looking into",
    "working on it",
    "please wait",
    "resolve this",
    "get back to you",
)

GENERIC_PRODUCT_NAMES = frozenset({
    "hotel", "the hotel", "resort", "the resort", "property", "the property",
    "package", "the package", "option", "the option", "holiday", "the holiday",
    "this hotel", "that hotel", "something", "that", "this",
})


def is_stall_message(text: str) -> bool:
    lower = text.lower()
    return any(phrase in lower for phrase in STALL_PHRASES)


def is_valid_locked_name(name: str) -> bool:
    cleaned = " ".join(name.split()).strip()
    if len(cleaned) < 6:
        return False
    if cleaned.lower() in GENERIC_PRODUCT_NAMES:
        return False
    words = cleaned.lower().split()
    if len(words) == 1 and words[0] in {"hotel", "resort", "property", "package"}:
        return False
    if len(words) == 2 and words[1] in {"hotel", "resort", "property"} and words[0] in {"the", "a", "this", "that"}:
        return False
    return True
