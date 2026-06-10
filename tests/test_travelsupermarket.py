import json
from unittest.mock import MagicMock

from dealbreakers.mcp.normalizers import (
    HolidayCandidate,
    extract_price,
    normalize_amenities,
    normalize_amenity,
    normalize_board_basis,
)
from dealbreakers.mcp.travelsupermarket import (
    TravelSupermarketClient,
    extract_listings,
    normalize_holiday_listing,
)

RAW_LISTING = {
    "hotelName": "Iberostar Waves Ciudad Blanca",
    "bookingUrl": "https://www.travelsupermarket.com/holiday/123",
    "starRating": 4,
    "reviewScore": 9.4,
    "boardBasis": "All Inclusive",
    "nights": 7,
    "location": "Alcudia, Majorca, Spain",
    "region": "Majorca",
    "country": "Spain",
    "facilities": ["Swimming pool", "Close to beach", "Kids club", "Spa facilities"],
    "totalPrice": "£2,440",
}


def make_client_with_result(result: dict) -> TravelSupermarketClient:
    mcp = MagicMock()
    mcp.request.return_value = result
    return TravelSupermarketClient(client=mcp)


# --- tools/call body shape ---


def test_search_holidays_builds_correct_tools_call() -> None:
    mcp = MagicMock()
    mcp.request.return_value = {"content": []}
    client = TravelSupermarketClient(client=mcp)

    client.search_holidays(
        destination="Spain",
        month="7",
        duration=7,
        board="AI",
        stars=4,
        facilities=["pool", "spa"],
        max_price=800,
        limit=5,
    )

    method, params = mcp.request.call_args.args
    assert method == "tools/call"
    assert params["name"] == "search-holidays"
    arguments = params["arguments"]
    assert arguments["destination"] == "Spain"
    assert arguments["departureMonth"] == "7"
    assert arguments["duration"] == "7"
    assert arguments["boardBasis"] == "AI"
    assert arguments["starRating"] == "4"
    assert arguments["facilities"] == "1,12"  # pool=1, spa=12
    assert arguments["maxPrice"] == 800
    assert arguments["limit"] == 5


def test_search_holidays_omits_unset_filters() -> None:
    mcp = MagicMock()
    mcp.request.return_value = {"content": []}
    TravelSupermarketClient(client=mcp).search_holidays(destination="Spain", duration=None)

    arguments = mcp.request.call_args.args[1]["arguments"]
    assert set(arguments) == {"destination", "limit"}


# --- raw result extraction ---


def test_extract_listings_from_content_text_json() -> None:
    result = {
        "content": [
            {"type": "text", "text": json.dumps({"offers": [RAW_LISTING]})},
        ]
    }
    assert extract_listings(result) == [RAW_LISTING]


def test_extract_listings_from_structured_content() -> None:
    result = {"structuredContent": {"results": [RAW_LISTING]}}
    assert extract_listings(result) == [RAW_LISTING]


def test_extract_listings_from_direct_list() -> None:
    assert extract_listings({"offers": [RAW_LISTING]}) == [RAW_LISTING]


def test_extract_listings_unknown_shape_returns_empty() -> None:
    assert extract_listings({"content": [{"type": "text", "text": "no holidays found"}]}) == []


# --- amenity normalization (conservative) ---


def test_amenity_normalization_clear_matches() -> None:
    assert normalize_amenity("Swimming pool") == "pool"
    assert normalize_amenity("Close to beach") == "close_to_beach"
    assert normalize_amenity("Beachfront") == "close_to_beach"
    assert normalize_amenity("Kids club") == "kids_club"
    assert normalize_amenity("Wellness") == "spa"
    assert normalize_amenity("Wi-Fi") == "wifi"
    assert normalize_amenity("Air conditioning") == "air_conditioning"
    assert normalize_amenity("Fitness") == "gym"
    assert normalize_amenity("Family friendly") == "family_friendly"


def test_amenity_normalization_never_invents() -> None:
    assert normalize_amenity("Lovely sea views") is None
    assert normalize_amenity("Barbecue area") is None  # must not match "bar"
    assert normalize_amenity("") is None


def test_normalize_amenities_handles_facility_ids_and_dedupes() -> None:
    assert normalize_amenities([1, "12", "Swimming pool", "unknown thing"]) == ["pool", "spa"]


# --- board basis normalization ---


def test_board_basis_normalization() -> None:
    assert normalize_board_basis("All Inclusive") == "AI"
    assert normalize_board_basis("ai") == "AI"
    assert normalize_board_basis("Half Board") == "HB"
    assert normalize_board_basis("Bed and Breakfast") == "BB"
    assert normalize_board_basis("Self-Catering") == "SC"
    assert normalize_board_basis("Room Only") == "RO"
    assert normalize_board_basis("Something weird") is None
    assert normalize_board_basis(None) is None


# --- numeric price extraction ---


def test_extract_price_variants() -> None:
    assert extract_price(2440) == 2440.0
    assert extract_price(2440.5) == 2440.5
    assert extract_price("£2,440") == 2440.0
    assert extract_price("2440.50 GBP") == 2440.5
    assert extract_price("free") is None
    assert extract_price(None) is None
    assert extract_price(True) is None


# --- full listing normalization + to_holiday ---


def test_normalize_holiday_listing() -> None:
    candidate = normalize_holiday_listing(RAW_LISTING)

    assert candidate.hotel_name == "Iberostar Waves Ciudad Blanca"
    assert candidate.url == "https://www.travelsupermarket.com/holiday/123"
    assert candidate.star_rating == 4
    assert candidate.review_score == 9.4
    assert candidate.board_basis == "AI"
    assert candidate.nights == 7
    assert candidate.country == "Spain"
    assert candidate.amenities == ["pool", "close_to_beach", "kids_club", "spa"]
    assert candidate.price_total == 2440.0
    assert candidate.raw == RAW_LISTING
    assert candidate.is_offerable


def test_candidate_to_holiday_round_trip() -> None:
    candidate = normalize_holiday_listing(RAW_LISTING)
    holiday = candidate.to_holiday()

    api_dict = holiday.to_api_dict()
    assert api_dict["priceTotal"] == 2440.0
    assert isinstance(api_dict["priceTotal"], float)
    assert api_dict["hotelName"] == "Iberostar Waves Ciudad Blanca"
    assert api_dict["boardBasis"] == "AI"
    assert api_dict["country"] == "Spain"
    assert api_dict["amenities"] == ["pool", "close_to_beach", "kids_club", "spa"]


def test_candidate_without_price_is_not_offerable() -> None:
    candidate = HolidayCandidate(url="https://example.com")
    assert not candidate.is_offerable


def test_search_holidays_end_to_end_with_mocked_result() -> None:
    result = {
        "content": [
            {"type": "text", "text": json.dumps({"offers": [RAW_LISTING]})},
        ]
    }
    client = make_client_with_result(result)

    candidates = client.search_holidays(destination="Spain")

    assert len(candidates) == 1
    assert candidates[0].is_offerable
    assert candidates[0].price_total == 2440.0
