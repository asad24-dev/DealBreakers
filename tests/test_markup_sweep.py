"""Offline tests for the markup sweep experiment runner."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dealbreakers.constants import BuyerAction, MatchStatus
from dealbreakers.experiments.markup_sweep import (
    MarkupSweepResult,
    assert_practice_match,
    build_summary_rows,
    first_rejected_or_walked_markup,
    highest_accepted_markup,
    parse_markup_list,
    run_markup_sweep,
    save_summary,
)
from dealbreakers.models.match import (
    BuyerMessage,
    MatchResult,
    MatchStartResponse,
    Quote,
    Scenario,
    TurnResponse,
)
from dealbreakers.mcp.normalizers import HolidayCandidate


def make_start(*, brief: str = "PRACTICE buyer — Bob Ross") -> MatchStartResponse:
    return MatchStartResponse(
        match_id="match-abc",
        scenario=Scenario(name="Bob Ross", brief=brief),
        buyer=BuyerMessage(text="Hi, I want a sunny beach holiday.", action=BuyerAction.CONTINUE),
        status=MatchStatus.AWAITING_SELLER,
    )


def make_candidate() -> HolidayCandidate:
    return HolidayCandidate(
        hotel_name="Be Live Tenerife",
        url="https://www.travelsupermarket.com/holiday/x",
        star_rating=4.0,
        review_score=9.0,
        board_basis="HB",
        nights=7,
        location="Puerto De La Cruz",
        region="Tenerife",
        country="Spain",
        amenities=["pool", "close_to_beach"],
        price_total=978.0,
    )


def make_result(
    markup_pct: float,
    *,
    closed: bool = False,
    walked: bool = False,
    buyer_action: str = "continue",
    error: str | None = None,
) -> MarkupSweepResult:
    return MarkupSweepResult(
        persona_id="practice-bob",
        markup_pct=markup_pct,
        match_id="match-abc",
        hotel_name="Be Live Tenerife",
        cost=978.0,
        quote_total=978.0 * (1 + markup_pct / 100),
        buyer_action=buyer_action,
        closed=closed,
        walked=walked,
        rounds=2 if closed else None,
        buyer_text="I'll take it!" if closed else "Too expensive",
        error=error,
    )


# --- parse_markup_list ---


def test_parse_markup_list_splits_and_parses() -> None:
    assert parse_markup_list("5,10,15,20") == [5.0, 10.0, 15.0, 20.0]


def test_parse_markup_list_strips_whitespace() -> None:
    assert parse_markup_list(" 5 , 10 , 15 ") == [5.0, 10.0, 15.0]


def test_parse_markup_list_rejects_empty() -> None:
    with pytest.raises(ValueError, match="Empty markup list"):
        parse_markup_list("  ,  ")


# --- MarkupSweepResult.to_dict ---


def test_result_to_dict_round_trips() -> None:
    result = make_result(15.0, closed=True, buyer_action="accept")
    data = result.to_dict()

    assert data["markup_pct"] == 15.0
    assert data["closed"] is True
    assert data["persona_id"] == "practice-bob"
    assert data["error"] is None


# --- highest_accepted_markup ---


def test_highest_accepted_markup_picks_max_closed() -> None:
    results = [
        make_result(8.0, closed=True, buyer_action="accept"),
        make_result(15.0, closed=True, buyer_action="accept"),
        make_result(20.0, closed=False, buyer_action="continue"),
    ]
    assert highest_accepted_markup(results) == 15.0


def test_highest_accepted_markup_none_when_all_fail() -> None:
    results = [make_result(8.0, closed=False), make_result(15.0, error="boom")]
    assert highest_accepted_markup(results) is None


# --- first_rejected_or_walked_markup ---


def test_first_rejected_or_walked_markup_in_run_order() -> None:
    results = [
        make_result(8.0, closed=True, buyer_action="accept"),
        make_result(15.0, closed=True, buyer_action="accept"),
        make_result(20.0, closed=False, buyer_action="continue"),
        make_result(25.0, walked=True, buyer_action="walk"),
    ]
    assert first_rejected_or_walked_markup(results) == 20.0


def test_first_rejected_skips_error_runs() -> None:
    results = [
        make_result(8.0, error="network"),
        make_result(15.0, closed=False, buyer_action="continue"),
    ]
    assert first_rejected_or_walked_markup(results) == 15.0


def test_first_rejected_none_when_all_accepted() -> None:
    results = [
        make_result(8.0, closed=True, buyer_action="accept"),
        make_result(15.0, closed=True, buyer_action="accept"),
    ]
    assert first_rejected_or_walked_markup(results) is None


# --- practice safety guard ---


def test_assert_practice_match_accepts_practice_brief() -> None:
    assert_practice_match(make_start(brief="PRACTICE buyer — easy beach holiday"))


def test_assert_practice_match_rejects_official_brief() -> None:
    with pytest.raises(RuntimeError, match="must never run an official match"):
        assert_practice_match(make_start(brief="Official buyer — hidden budget"))


# --- failed run does not stop sweep ---


def test_run_markup_sweep_continues_after_failure(monkeypatch) -> None:
    call_count = 0

    def fake_single(markup_pct, **kwargs):
        nonlocal call_count
        call_count += 1
        if markup_pct == 10.0:
            return make_result(10.0, error="search failed")
        return make_result(markup_pct, closed=True, buyer_action="accept")

    monkeypatch.setattr(
        "dealbreakers.experiments.markup_sweep.run_single_markup",
        fake_single,
    )

    results = run_markup_sweep(
        [5.0, 10.0, 15.0],
        client=MagicMock(),
        tsm_client=MagicMock(),
        recorder=MagicMock(),
    )

    assert call_count == 3
    assert len(results) == 3
    assert results[1].error == "search failed"
    assert results[0].closed is True
    assert results[2].closed is True


def test_run_markup_sweep_rejects_non_practice_at_runtime(monkeypatch) -> None:
    client = MagicMock()
    client.start_match.return_value = make_start(brief="Official scenario — do not use")

    monkeypatch.setattr(
        "dealbreakers.experiments.markup_sweep.TravelSupermarketClient",
        lambda *args, **kwargs: MagicMock(),
    )

    results = run_markup_sweep(
        [8.0],
        client=client,
        tsm_client=MagicMock(),
        recorder=MagicMock(),
    )

    assert len(results) == 1
    assert results[0].error is not None
    assert "official match" in results[0].error.lower()


# --- summary JSON shape ---


def test_build_summary_rows_shape() -> None:
    rows = build_summary_rows([
        make_result(12.0, closed=True, buyer_action="accept"),
        make_result(20.0, walked=True, buyer_action="walk"),
    ])

    assert len(rows) == 2
    row = rows[0]
    assert set(row.keys()) == {
        "markup_pct",
        "closed",
        "walked",
        "buyer_action",
        "cost",
        "quote_total",
        "hotel_name",
        "rounds",
        "buyer_text",
        "error",
    }
    assert row["markup_pct"] == 12.0
    assert row["closed"] is True
    assert row["hotel_name"] == "Be Live Tenerife"


def test_save_summary_writes_json(tmp_path: Path) -> None:
    path = tmp_path / "markup_sweep_summary.json"
    results = [make_result(8.0, closed=True, buyer_action="accept")]

    save_summary(results, path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, list)
    assert data[0]["markup_pct"] == 8.0
    assert data[0]["closed"] is True
