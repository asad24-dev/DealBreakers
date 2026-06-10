"""Negotiation actions the policy engine can choose each turn (Phase 7A)."""

from __future__ import annotations

from enum import Enum


class NegotiationAction(Enum):
    """Explicit, inspectable per-turn action.

    DISCOVER — missing critical info (trip type / destination unknown)
    REFINE   — clarify constraints (e.g. must-haves still unclear)
    SEARCH   — inventory retrieval required before an offer can be made
    OFFER    — present the first offer
    COUNTER  — buyer pushed back on price; concede markup
    CLOSE    — acceptance likely; seal the deal
    """

    DISCOVER = "discover"
    REFINE = "refine"
    SEARCH = "search"
    OFFER = "offer"
    COUNTER = "counter"
    CLOSE = "close"
