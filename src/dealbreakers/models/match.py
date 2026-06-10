"""Match and turn response models."""

from dataclasses import dataclass
from typing import Any

from dealbreakers.constants import BuyerAction, MatchStatus


@dataclass
class BuyerMessage:
    text: str
    action: BuyerAction

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "BuyerMessage":
        return cls(text=data["text"], action=BuyerAction(data["action"]))


@dataclass
class Scenario:
    name: str
    brief: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Scenario":
        return cls(name=data["name"], brief=data["brief"])


@dataclass
class Quote:
    cost: float
    markup_pct: float
    total: float

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "Quote":
        return cls(
            cost=data["cost"],
            markup_pct=data["markupPct"],
            total=data["total"],
        )


@dataclass
class MatchResult:
    closed: bool
    end_reason: str
    rounds: int

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "MatchResult":
        return cls(
            closed=data["closed"],
            end_reason=data["endReason"],
            rounds=data["rounds"],
        )


@dataclass
class MatchStartResponse:
    match_id: str
    scenario: Scenario
    buyer: BuyerMessage
    status: MatchStatus

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "MatchStartResponse":
        return cls(
            match_id=data["matchId"],
            scenario=Scenario.from_api(data["scenario"]),
            buyer=BuyerMessage.from_api(data["buyer"]),
            status=MatchStatus(data["status"]),
        )


@dataclass
class AllMatchesDone:
    done: bool = True

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "AllMatchesDone":
        return cls(done=data.get("done", True))


@dataclass
class TurnResponse:
    buyer: BuyerMessage
    status: MatchStatus
    quote: Quote | None = None
    result: MatchResult | None = None

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> "TurnResponse":
        quote = Quote.from_api(data["quote"]) if data.get("quote") else None
        result = MatchResult.from_api(data["result"]) if data.get("result") else None
        return cls(
            buyer=BuyerMessage.from_api(data["buyer"]),
            status=MatchStatus(data["status"]),
            quote=quote,
            result=result,
        )

    @property
    def is_ended(self) -> bool:
        return self.status == MatchStatus.ENDED

    @property
    def buyer_accepted(self) -> bool:
        return self.buyer.action == BuyerAction.ACCEPT

    @property
    def buyer_walked(self) -> bool:
        return self.buyer.action == BuyerAction.WALK
