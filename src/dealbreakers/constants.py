"""Shared constants for the Deal Room agent."""

from enum import StrEnum

MAX_ROUNDS = 15

PRACTICE_PERSONAS: dict[str, str] = {
    "practice-bob": "easy — beach holiday",
    "practice-toni": "medium — guided tour of Spain",
    "practice-elon": "medium — tech city-break in European capital",
    "practice-gordon": "hard — 5-star perfectionist",
    "practice-cris": "hard — smug luxury, wants premium car",
}

BOARD_BASIS = frozenset({"AI", "FB", "HB", "BB", "SC", "RO"})

AMENITY_VOCABULARY = frozenset({
    "pool",
    "close_to_beach",
    "air_conditioning",
    "wifi",
    "balcony",
    "kids_club",
    "restaurant",
    "childrens_pool",
    "wheelchair_access",
    "nightclub",
    "bar",
    "spa",
    "playground",
    "pool_bar",
    "sun_loungers",
    "entertainment",
    "water_sports",
    "sports",
    "gym",
    "jacuzzi",
    "sun_terrace",
    "games_room",
    "golf",
    "shopping",
    "family_friendly",
})

MCP_SOURCES: dict[str, str] = {
    "travelsupermarket": "https://travel-supermarket-integration-dev-test.up.railway.app/mcp",
    "trivago": "https://mcp.trivago.com/mcp",
    "kiwi": "https://mcp.kiwi.com/mcp",
    "economybookings": "https://economybookings-integration-dev.up.railway.app/mcp",
    "tourradar": "https://ai.tourradar.com/mcp/main",
}


class BuyerAction(StrEnum):
    CONTINUE = "continue"
    ACCEPT = "accept"
    WALK = "walk"


class MatchStatus(StrEnum):
    AWAITING_SELLER = "awaiting-seller"
    ENDED = "ended"
