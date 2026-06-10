"""Runtime context for graph nodes — non-serializable negotiation state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from dealbreakers.analysis.analyzer import ConversationAnalyzer
from dealbreakers.api.client import DealRoomClient
from dealbreakers.learning.bandit import BanditPolicy, StrategyArm
from dealbreakers.mcp.cars import CarSearchClient
from dealbreakers.mcp.city_break import CityBreakSearchClient
from dealbreakers.mcp.tourradar import TourRadarClient
from dealbreakers.mcp.travelsupermarket import TravelSupermarketClient
from dealbreakers.models.match import MatchStartResponse, TurnResponse
from dealbreakers.models.offer import Offer
from dealbreakers.models.transcript import TranscriptEvent
from dealbreakers.negotiation.live_agent import AgentSessionState, InventoryState
from dealbreakers.negotiation.strategist import NegotiationBrief, NegotiationStrategist
from dealbreakers.state.buyer_state import BuyerState


@dataclass
class GraphContext:
    deal_room: DealRoomClient
    analyzer: ConversationAnalyzer = field(default_factory=ConversationAnalyzer)
    tsm: TravelSupermarketClient = field(default_factory=TravelSupermarketClient)
    tourradar: TourRadarClient = field(default_factory=TourRadarClient)
    car_search: CarSearchClient = field(default_factory=CarSearchClient)
    city_break: CityBreakSearchClient = field(default_factory=CityBreakSearchClient)
    strategist: NegotiationStrategist = field(default_factory=NegotiationStrategist)
    reply_generator: Callable[..., str] | None = None

    buyer_state: BuyerState = field(default_factory=BuyerState)
    inventory: InventoryState = field(default_factory=InventoryState)
    session: AgentSessionState = field(default_factory=AgentSessionState)
    events: list[TranscriptEvent] = field(default_factory=list)
    buyer_messages: list[str] = field(default_factory=list)
    walk_risk: float = 0.0
    brief: NegotiationBrief | None = None
    start: MatchStartResponse | None = None
    turn_response: TurnResponse | None = None

    bandit_policy: BanditPolicy | None = None
    markup_arm: StrategyArm | None = None
    search_arm: StrategyArm | None = None
    counter_arm: StrategyArm | None = None
    bandit_epsilon: float = 0.0

    seller_rounds: int = 0
    pending_offer: Offer | None = None
