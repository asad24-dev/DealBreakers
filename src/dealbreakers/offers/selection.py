"""Candidate scoring and offer assembly (Phase 6A — simple heuristics)."""

from __future__ import annotations

from dealbreakers.mcp.car_normalizers import CarCandidate, is_premium_looking
from dealbreakers.mcp.normalizers import HolidayCandidate, normalize_amenity
from dealbreakers.mcp.tour_normalizers import TourCandidate
from dealbreakers.models.offer import Offer, Source
from dealbreakers.state.buyer_state import BuyerState

_CENTRAL_KEYWORDS = (
    "central",
    "city centre",
    "city center",
    "downtown",
    "mitte",
    "inner city",
    "city break",
)


def _location_text(candidate: HolidayCandidate) -> str:
    parts = [candidate.location, candidate.region, candidate.hotel_name]
    return " ".join(part for part in parts if part).lower()


def _central_location_bonus(candidate: HolidayCandidate) -> float:
    text = _location_text(candidate)
    return 8.0 if any(keyword in text for keyword in _CENTRAL_KEYWORDS) else 0.0


def _luxury_board_bonus(candidate: HolidayCandidate) -> float:
    if candidate.board_basis in ("AI", "HB"):
        return 5.0
    return 0.0


def score_candidate(
    candidate: HolidayCandidate,
    *,
    wanted_amenities: tuple[str, ...] = ("pool", "close_to_beach"),
) -> float:
    """Higher is better. Balances price, review score, amenity fit, and stars."""
    if not candidate.is_offerable:
        return float("-inf")

    score = 0.0

    # Cheaper is better: ~1 point per £100 below a £4000 reference.
    score += (4000 - candidate.price_total) / 100

    if candidate.review_score is not None:
        score += candidate.review_score * 2

    for amenity in wanted_amenities:
        if amenity in candidate.amenities:
            score += 5

    if candidate.star_rating is not None and candidate.star_rating >= 4:
        score += 3

    return score


def pick_best_candidate(
    candidates: list[HolidayCandidate],
    *,
    wanted_amenities: tuple[str, ...] = ("pool", "close_to_beach"),
) -> HolidayCandidate | None:
    offerable = [candidate for candidate in candidates if candidate.is_offerable]
    if not offerable:
        return None
    return max(
        offerable,
        key=lambda candidate: score_candidate(candidate, wanted_amenities=wanted_amenities),
    )


def build_holiday_offer(candidate: HolidayCandidate, *, markup_pct: float = 8.0) -> Offer:
    """Assemble a sendable Offer from an offerable candidate."""
    return Offer(
        holiday=candidate.to_holiday(),
        markup_pct=markup_pct,
        sources=[
            Source(
                mcp="travelsupermarket",
                url=candidate.url or "",
                price=candidate.price_total or 0.0,
            )
        ],
    )


def score_tour_candidate(
    candidate: TourCandidate,
    *,
    country: str | None = "Spain",
    min_days: int | None = None,
    max_days: int | None = None,
) -> float:
    if not candidate.is_offerable:
        return float("-inf")

    score = 0.0
    if candidate.price_total is not None:
        score += (5000 - candidate.price_total) / 100
    if country and candidate.country and candidate.country.lower() == country.lower():
        score += 10
    if candidate.duration_days is not None:
        if min_days is not None and candidate.duration_days >= min_days:
            score += 3
        if max_days is not None and candidate.duration_days <= max_days:
            score += 3
        if min_days is not None and max_days is not None:
            if min_days <= candidate.duration_days <= max_days:
                score += 5
    if candidate.operator:
        score += 2
    return score


def pick_best_tour_candidate(
    candidates: list[TourCandidate],
    *,
    country: str | None = "Spain",
    min_days: int | None = None,
    max_days: int | None = None,
) -> TourCandidate | None:
    offerable = [candidate for candidate in candidates if candidate.is_offerable]
    if not offerable:
        return None
    return max(
        offerable,
        key=lambda candidate: score_tour_candidate(
            candidate,
            country=country,
            min_days=min_days,
            max_days=max_days,
        ),
    )


def build_tour_offer(candidate: TourCandidate, *, markup_pct: float = 12.0) -> Offer:
    """Assemble a sendable Offer from an offerable tour candidate."""
    return Offer(
        tour=candidate.to_tour(),
        markup_pct=markup_pct,
        sources=[
            Source(
                mcp="tourradar",
                url=candidate.url or "",
                price=candidate.price_total or 0.0,
            )
        ],
    )


def score_elon_candidate(
    candidate: HolidayCandidate,
    *,
    selected_city: str | None = None,
) -> float:
    """City-break scoring per Phase 8F weights."""
    if not candidate.is_offerable:
        return float("-inf")

    score = 0.0
    if selected_city:
        location_text = _location_text(candidate)
        if selected_city.lower() in location_text:
            score += 25
    if candidate.star_rating is not None and candidate.star_rating >= 4:
        score += 20
    if "wifi" in candidate.amenities:
        score += 20
    if "gym" in candidate.amenities:
        score += 20
    score += _central_location_bonus(candidate)
    if _central_location_bonus(candidate) > 0:
        score += 15
    if candidate.review_score is not None and candidate.review_score >= 8.5:
        score += 10
    if candidate.price_total is not None:
        score += (3000 - candidate.price_total) / 100
    return score


def pick_best_elon_candidate(candidates: list[HolidayCandidate]) -> HolidayCandidate | None:
    offerable = [candidate for candidate in candidates if candidate.is_offerable]
    if not offerable:
        return None
    return max(offerable, key=score_elon_candidate)


def score_gordon_candidate(candidate: HolidayCandidate) -> float:
    """Luxury beach/spa: 5-star, reviews, spa/beach/pool over lowest price."""
    if not candidate.is_offerable:
        return float("-inf")

    score = 0.0
    if candidate.review_score is not None:
        score += candidate.review_score * 5
    if candidate.star_rating is not None:
        if candidate.star_rating >= 5:
            score += 25
        elif candidate.star_rating >= 4:
            score += 5
    for amenity in ("spa", "close_to_beach", "pool"):
        if amenity in candidate.amenities:
            score += 10
    score += _luxury_board_bonus(candidate)
    if candidate.price_total is not None:
        # Quality-first: modest premium acceptable, not cheapest-first.
        score += min(candidate.price_total / 500, 8.0)
    return score


def pick_best_gordon_candidate(candidates: list[HolidayCandidate]) -> HolidayCandidate | None:
    offerable = [candidate for candidate in candidates if candidate.is_offerable]
    if not offerable:
        return None
    return max(offerable, key=score_gordon_candidate)


def score_cris_candidate(candidate: HolidayCandidate) -> float:
    """Luxury impatient buyer: spa, gym, beach, sun terrace, 5-star, reviews."""
    if not candidate.is_offerable:
        return float("-inf")

    score = 0.0
    if candidate.review_score is not None:
        score += candidate.review_score * 5
    if candidate.star_rating is not None:
        if candidate.star_rating >= 5:
            score += 25
        elif candidate.star_rating >= 4:
            score += 5
    amenity_weights = {
        "spa": 12,
        "gym": 10,
        "close_to_beach": 12,
        "sun_terrace": 8,
    }
    for amenity, weight in amenity_weights.items():
        if amenity in candidate.amenities:
            score += weight
    score += _luxury_board_bonus(candidate)
    if candidate.price_total is not None:
        score += min(candidate.price_total / 500, 8.0)
    return score


def pick_best_cris_candidate(candidates: list[HolidayCandidate]) -> HolidayCandidate | None:
    offerable = [candidate for candidate in candidates if candidate.is_offerable]
    if not offerable:
        return None
    return max(offerable, key=score_cris_candidate)


def amenities_from_must_haves(must_haves: list[str]) -> list[str]:
    """Map free-text must-haves to canonical amenity vocabulary."""
    found: list[str] = []
    for phrase in must_haves:
        lowered = phrase.lower()
        for token in lowered.replace("-", " ").split():
            canonical = normalize_amenity(token)
            if canonical and canonical not in found:
                found.append(canonical)
        for keyword, canonical in (
            ("wifi", "wifi"),
            ("wi-fi", "wifi"),
            ("gym", "gym"),
            ("fitness", "gym"),
            ("spa", "spa"),
            ("beach", "close_to_beach"),
            ("beachfront", "close_to_beach"),
            ("pool", "pool"),
            ("terrace", "sun_terrace"),
            ("sun terrace", "sun_terrace"),
        ):
            if keyword in lowered and canonical not in found:
                found.append(canonical)
    return found


def is_city_break_state(state: BuyerState) -> bool:
    text = " ".join(
        [state.trip_type or "", *state.destinations, *state.must_haves]
    ).lower()
    return any(
        phrase in text
        for phrase in ("city break", "city-break", "city centre", "central", "wifi", "berlin", "stockholm", "amsterdam")
    )


def infer_star_rating(state: BuyerState) -> int | None:
    text = " ".join(state.must_haves).lower()
    if state.luxury_preference >= 0.7 or "five-star" in text or "five star" in text or "5-star" in text:
        return 5
    if "four-star" in text or "4-star" in text or "4 star" in text:
        return 4
    if state.luxury_preference >= 0.5:
        return 4
    return None


def score_holiday_for_state(candidate: HolidayCandidate, state: BuyerState) -> float:
    """State-driven holiday scoring — no persona hardcoding."""
    if not candidate.is_offerable:
        return float("-inf")

    wanted = tuple(amenities_from_must_haves(state.must_haves))
    score = 0.0

    if state.luxury_preference >= 0.7:
        if candidate.review_score is not None:
            score += candidate.review_score * 5
        if candidate.star_rating is not None:
            if candidate.star_rating >= 5:
                score += 25
            elif candidate.star_rating >= 4:
                score += 5
        if candidate.price_total is not None:
            score += min(candidate.price_total / 500, 8.0)
        score += _luxury_board_bonus(candidate)
    else:
        if candidate.price_total is not None:
            score += (4000 - candidate.price_total) / 100
        if candidate.review_score is not None:
            score += candidate.review_score * 2
        if candidate.star_rating is not None and candidate.star_rating >= 4:
            score += 3

    weight = 10 if state.luxury_preference >= 0.7 else 5
    for amenity in wanted:
        if amenity in candidate.amenities:
            score += weight

    if is_city_break_state(state):
        selected_city = state.destinations[0] if state.destinations else None
        score = score_elon_candidate(candidate, selected_city=selected_city)

    if state.desired_nights is not None:
        if candidate.nights == state.desired_nights:
            score += 30
        elif candidate.nights is not None:
            score -= 15

    return score


def score_tour_for_state(candidate: TourCandidate, state: BuyerState) -> float:
    if not candidate.is_offerable:
        return float("-inf")

    country = state.destinations[0] if state.destinations else None
    return score_tour_candidate(
        candidate,
        country=country,
        min_days=5,
        max_days=14,
    )


def pick_best_holiday_for_state(
    candidates: list[HolidayCandidate], state: BuyerState
) -> HolidayCandidate | None:
    return pick_best_holiday_for_duration(candidates, state)


def pick_best_holiday_for_duration(
    candidates: list[HolidayCandidate],
    state: BuyerState,
    *,
    shorter_stay_accepted: bool | None = None,
) -> HolidayCandidate | None:
    offerable = [candidate for candidate in candidates if candidate.is_offerable]
    if not offerable:
        return None

    if state.desired_nights is not None:
        exact = [
            candidate
            for candidate in offerable
            if candidate.nights == state.desired_nights
        ]
        if exact:
            return max(exact, key=lambda c: score_holiday_for_state(c, state))
        if shorter_stay_accepted is not True:
            return None

    return max(offerable, key=lambda candidate: score_holiday_for_state(candidate, state))


def find_cheaper_equivalent_holiday(
    candidates: list[HolidayCandidate],
    current: HolidayCandidate,
    state: BuyerState,
) -> HolidayCandidate | None:
    """Gordon pivot: same quality tier, spa/beach/pool, review>=8.5, 20% cheaper."""
    if current.price_total is None:
        return None
    target_cost = current.price_total * 0.8
    min_stars = current.star_rating or 4.0
    viable = [
        candidate
        for candidate in candidates
        if candidate.is_offerable
        and candidate.url != current.url
        and candidate.price_total is not None
        and candidate.price_total <= target_cost
        and (candidate.review_score is None or candidate.review_score >= 8.5)
        and (candidate.star_rating is None or candidate.star_rating >= min_stars - 0.5)
        and any(
            amenity in candidate.amenities
            for amenity in ("spa", "close_to_beach", "pool")
        )
    ]
    if not viable:
        return None
    return max(viable, key=lambda candidate: score_holiday_for_state(candidate, state))


def build_city_break_offer(
    candidate: HolidayCandidate,
    *,
    markup_pct: float = 12.0,
) -> Offer:
    """Build offer from city-break hotel (optionally with flight in sources)."""
    sources: list[Source] = []
    raw = candidate.raw if isinstance(candidate.raw, dict) else {}
    hotel_raw = raw.get("hotel") if isinstance(raw.get("hotel"), dict) else {}
    hotel_url = candidate.url or hotel_raw.get("accommodation_url") or ""
    sources.append(
        Source(mcp="trivago", url=hotel_url, price=candidate.price_total or 0.0)
    )
    flight_raw = raw.get("flight")
    if isinstance(flight_raw, dict):
        flight_url = flight_raw.get("deepLink") or flight_raw.get("url")
        flight_price = flight_raw.get("price")
        if isinstance(flight_url, str) and flight_url.startswith("http") and flight_price:
            try:
                sources.append(
                    Source(mcp="kiwi", url=flight_url, price=float(flight_price))
                )
            except (TypeError, ValueError):
                pass
    return Offer(
        holiday=candidate.to_holiday(),
        markup_pct=markup_pct,
        sources=sources,
    )


def pick_best_tour_for_state(
    candidates: list[TourCandidate], state: BuyerState
) -> TourCandidate | None:
    offerable = [candidate for candidate in candidates if candidate.is_offerable]
    if not offerable:
        return None
    return max(offerable, key=lambda candidate: score_tour_for_state(candidate, state))


_PREMIUM_CAR_TIERS = (
    frozenset({"premium", "luxury", "executive"}),
    frozenset({"fullsize", "suv"}),
)


def _car_category_text(candidate: CarCandidate) -> str:
    return " ".join(
        part for part in (candidate.vehicle_name, candidate.category) if part
    ).lower()


def _premium_tier_candidates(candidates: list[CarCandidate]) -> list[CarCandidate]:
    for tier in _PREMIUM_CAR_TIERS:
        tier_cars = [
            candidate
            for candidate in candidates
            if any(word in _car_category_text(candidate) for word in tier)
        ]
        if tier_cars:
            return tier_cars
    return candidates


def score_car_candidate(candidate: CarCandidate, *, premium: bool) -> float:
    if not candidate.is_offerable:
        return float("-inf")

    score = 0.0
    text = _car_category_text(candidate)

    if premium:
        if any(word in text for word in ("premium", "luxury", "executive")):
            score += 25
        if "suv" in text:
            score += 20
        if any(brand in text for brand in (
            "mercedes", "bmw", "audi", "range rover", "tesla", "jaguar", "lexus", "volvo"
        )):
            score += 20
        if candidate.transmission == "Automatic":
            score += 10
        if candidate.seats is not None and candidate.seats >= 4:
            score += 5
        if candidate.price_total is not None:
            score -= candidate.price_total / 1000
    else:
        if candidate.price_total is not None:
            score += (2000 - candidate.price_total) / 50
        if candidate.transmission == "Automatic":
            score += 5
        if candidate.seats is not None and candidate.seats >= 4:
            score += 3

    return score


def pick_best_car_candidate(
    candidates: list[CarCandidate], *, premium: bool
) -> CarCandidate | None:
    offerable = [candidate for candidate in candidates if candidate.is_offerable]
    if not offerable:
        return None
    pool = _premium_tier_candidates(offerable) if premium else offerable
    return max(pool, key=lambda candidate: score_car_candidate(candidate, premium=premium))


def build_holiday_with_car_offer(
    holiday_candidate: HolidayCandidate,
    car_candidate: CarCandidate | None,
    *,
    markup_pct: float,
) -> Offer:
    sources = [
        Source(
            mcp="travelsupermarket",
            url=holiday_candidate.url or "",
            price=holiday_candidate.price_total or 0.0,
        )
    ]
    car = None
    if car_candidate is not None and car_candidate.is_offerable:
        car = car_candidate.to_car()
        sources.append(
            Source(
                mcp=car_candidate.source_mcp or "economybookings",
                url=car_candidate.url or "",
                price=car_candidate.price_total or 0.0,
            )
        )
    return Offer(
        holiday=holiday_candidate.to_holiday(),
        car=car,
        markup_pct=markup_pct,
        sources=sources,
    )
