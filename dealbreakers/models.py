from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError, model_validator


Amenity = Literal[
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
]

BoardBasis = Literal["AI", "FB", "HB", "BB", "SC", "RO"]
Transmission = Literal["Manual", "Automatic"]


class BuyerAction(str, Enum):
    CONTINUE = "continue"
    ACCEPT = "accept"
    WALK = "walk"


class Scenario(BaseModel):
    name: str = ""
    brief: str = ""


class BuyerMessage(BaseModel):
    text: str
    action: BuyerAction = BuyerAction.CONTINUE


class MatchStart(BaseModel):
    match_id: str = Field(alias="matchId")
    scenario: Scenario
    buyer: BuyerMessage
    status: str

    model_config = ConfigDict(populate_by_name=True)


class Quote(BaseModel):
    cost: float
    markup_pct: float = Field(alias="markupPct")
    total: float

    model_config = ConfigDict(populate_by_name=True)


class MatchResult(BaseModel):
    closed: bool
    end_reason: str | None = Field(default=None, alias="endReason")
    rounds: int | None = None

    model_config = ConfigDict(populate_by_name=True)


class TurnResponse(BaseModel):
    buyer: BuyerMessage
    status: str
    quote: Quote | None = None
    result: MatchResult | None = None


class SourceReceipt(BaseModel):
    mcp: str
    url: HttpUrl | str
    price: float = Field(ge=0)


class HolidayOffer(BaseModel):
    price_total: float = Field(alias="priceTotal", gt=0)
    hotel_name: str = Field(default="", alias="hotelName")
    url: HttpUrl | str
    star_rating: float | None = Field(default=None, alias="starRating")
    review_score: float | None = Field(default=None, alias="reviewScore")
    board_basis: BoardBasis | None = Field(default=None, alias="boardBasis")
    nights: int | None = Field(default=None, gt=0)
    location: str = ""
    country: str = ""
    region: str = ""
    amenities: list[Amenity] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)


class TourOffer(BaseModel):
    price_total: float = Field(alias="priceTotal", gt=0)
    name: str
    url: HttpUrl | str
    country: str = ""
    region: str = ""
    operator: str = ""
    duration_days: int | None = Field(default=None, alias="durationDays", gt=0)
    location: str = ""
    supplier: str = ""

    model_config = ConfigDict(populate_by_name=True)


class CarOffer(BaseModel):
    price_total: float = Field(alias="priceTotal", gt=0)
    vehicle_name: str = Field(default="", alias="vehicleName")
    url: HttpUrl | str
    category: str = ""
    transmission: Transmission | None = None
    seats: int | None = Field(default=None, gt=0)
    supplier: str = ""

    model_config = ConfigDict(populate_by_name=True)


class StructuredOffer(BaseModel):
    holiday: HolidayOffer | None = None
    tour: TourOffer | None = None
    car: CarOffer | None = None
    markup_pct: float = Field(alias="markupPct", ge=0)
    sources: list[SourceReceipt] = Field(default_factory=list)

    model_config = ConfigDict(populate_by_name=True)

    @model_validator(mode="after")
    def exactly_one_primary_product(self) -> StructuredOffer:
        primary_count = int(self.holiday is not None) + int(self.tour is not None)
        if primary_count != 1:
            raise ValueError("Offer must include exactly one of holiday or tour.")
        if not self.sources:
            raise ValueError("Offer must include at least one source receipt.")
        return self

    @property
    def cost(self) -> float:
        primary = self.holiday or self.tour
        assert primary is not None
        car_cost = self.car.price_total if self.car else 0
        return primary.price_total + car_cost

    def api_payload(self) -> dict:
        return self.model_dump(by_alias=True, exclude_none=True, mode="json")


class SellerTurn(BaseModel):
    text: str
    offer: StructuredOffer | None = None

    def api_payload(self) -> dict:
        payload: dict[str, object] = {"text": self.text}
        if self.offer is not None:
            payload["offer"] = self.offer.api_payload()
        return payload


def validate_offer_payload(payload: dict) -> StructuredOffer:
    try:
        return StructuredOffer.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Invalid offer payload: {exc}") from exc
