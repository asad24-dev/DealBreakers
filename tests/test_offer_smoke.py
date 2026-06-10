from dealbreakers.mcp.normalizers import HolidayCandidate
from dealbreakers.offers import build_holiday_offer, pick_best_candidate, score_candidate


def make_candidate(**overrides) -> HolidayCandidate:
    defaults = dict(
        hotel_name="Test Hotel",
        url="https://www.travelsupermarket.com/holiday/x",
        star_rating=4.0,
        review_score=9.0,
        board_basis="HB",
        nights=7,
        location="Costa Adeje",
        region="Tenerife",
        country="Spain",
        amenities=["pool", "close_to_beach"],
        price_total=1500.0,
    )
    defaults.update(overrides)
    return HolidayCandidate(**defaults)


def test_pick_best_prefers_cheaper_when_otherwise_equal() -> None:
    cheap = make_candidate(hotel_name="Cheap", price_total=1500.0)
    pricey = make_candidate(hotel_name="Pricey", price_total=3000.0)

    assert pick_best_candidate([pricey, cheap]).hotel_name == "Cheap"


def test_pick_best_rewards_wanted_amenities_and_reviews() -> None:
    plain = make_candidate(hotel_name="Plain", amenities=[], review_score=7.0)
    fits = make_candidate(hotel_name="Fits", amenities=["pool", "close_to_beach"], review_score=9.5)

    assert pick_best_candidate([plain, fits]).hotel_name == "Fits"


def test_pick_best_skips_unofferable() -> None:
    no_price = make_candidate(hotel_name="NoPrice", price_total=None)
    no_url = make_candidate(hotel_name="NoUrl", url=None)

    assert pick_best_candidate([no_price, no_url]) is None
    assert score_candidate(no_price) == float("-inf")


def test_build_holiday_offer_payload_shape() -> None:
    candidate = make_candidate()
    offer = build_holiday_offer(candidate, markup_pct=8.0)

    payload = offer.to_api_dict()
    assert payload["markupPct"] == 8.0
    assert payload["holiday"]["priceTotal"] == 1500.0
    assert isinstance(payload["holiday"]["priceTotal"], float)
    assert payload["holiday"]["hotelName"] == "Test Hotel"
    assert payload["holiday"]["country"] == "Spain"
    assert payload["sources"] == [
        {
            "mcp": "travelsupermarket",
            "url": "https://www.travelsupermarket.com/holiday/x",
            "price": 1500.0,
        }
    ]
    assert "tour" not in payload
    assert "car" not in payload
