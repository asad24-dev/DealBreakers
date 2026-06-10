from pathlib import Path

from dealbreakers.constants import BuyerAction, MatchStatus
from dealbreakers.logging import TranscriptRecorder, read_jsonl
from dealbreakers.models.match import (
    BuyerMessage,
    MatchResult,
    MatchStartResponse,
    Quote,
    Scenario,
    TurnResponse,
)


def make_start() -> MatchStartResponse:
    return MatchStartResponse(
        match_id="m1",
        scenario=Scenario(name="Bob Ross", brief="Easy beach week"),
        buyer=BuyerMessage(text="Hi there!", action=BuyerAction.CONTINUE),
        status=MatchStatus.AWAITING_SELLER,
    )


def make_turn(*, quote: Quote | None = None, result: MatchResult | None = None) -> TurnResponse:
    return TurnResponse(
        buyer=BuyerMessage(text="Sounds good", action=BuyerAction.CONTINUE),
        status=MatchStatus.AWAITING_SELLER,
        quote=quote,
        result=result,
    )


def test_record_match_started(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    recorder = TranscriptRecorder(path=log)

    recorder.record_match_started(make_start(), practice=True, persona_id="practice-bob")

    record = read_jsonl(log)[0]
    assert record["record_type"] == "match_started"
    assert record["match_id"] == "m1"
    assert record["practice"] is True
    assert record["persona_id"] == "practice-bob"
    assert record["scenario_name"] == "Bob Ross"
    assert record["scenario_brief"] == "Easy beach week"
    assert record["status"] == "awaiting-seller"
    assert record["buyer_text"] == "Hi there!"
    assert record["buyer_action"] == "continue"


def test_record_buyer_message(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    recorder = TranscriptRecorder(path=log)

    recorder.record_buyer_message(
        "m1",
        BuyerMessage(text="Hello", action=BuyerAction.CONTINUE),
        scenario_name="Bob Ross",
        persona_id="practice-bob",
    )

    record = read_jsonl(log)[0]
    assert record["record_type"] == "buyer_message"
    assert record["role"] == "buyer"
    assert record["text"] == "Hello"
    assert record["action"] == "continue"
    assert record["round_number"] is None


def test_record_seller_message_with_offer(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    recorder = TranscriptRecorder(path=log)

    offer = {"holiday": {"priceTotal": 2440}, "markupPct": 12}
    recorder.record_seller_message("m1", "Here's a deal", offer=offer, round_number=3)

    record = read_jsonl(log)[0]
    assert record["record_type"] == "seller_message"
    assert record["role"] == "seller"
    assert record["round_number"] == 3
    assert record["offer"] == offer


def test_record_turn_response_with_quote_and_result(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    recorder = TranscriptRecorder(path=log)

    turn = make_turn(
        quote=Quote(cost=2440, markup_pct=12, total=2732.8),
        result=MatchResult(closed=True, end_reason="accept", rounds=4),
    )
    recorder.record_turn_response("m1", turn)

    record = read_jsonl(log)[0]
    assert record["record_type"] == "turn_response"
    assert record["quote"] == {"cost": 2440, "markup_pct": 12, "total": 2732.8}
    assert record["result"] == {"closed": True, "end_reason": "accept", "rounds": 4}


def test_record_turn_response_without_quote(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    recorder = TranscriptRecorder(path=log)

    recorder.record_turn_response("m1", make_turn())

    record = read_jsonl(log)[0]
    assert record["quote"] is None
    assert record["result"] is None


def test_record_error(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    recorder = TranscriptRecorder(path=log)

    recorder.record_error("m1", ValueError("bad offer"), context={"round": 2})

    record = read_jsonl(log)[0]
    assert record["record_type"] == "error"
    assert record["error_type"] == "ValueError"
    assert record["error_message"] == "bad offer"
    assert record["context"] == {"round": 2}
    assert "Traceback" not in str(record)


def test_record_error_without_match_id(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    recorder = TranscriptRecorder(path=log)

    recorder.record_error(None, RuntimeError("boom"))

    record = read_jsonl(log)[0]
    assert record["match_id"] is None


def test_recorder_survives_write_failure(tmp_path: Path, monkeypatch, capsys) -> None:
    def broken_open(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "open", broken_open)
    recorder = TranscriptRecorder(path=tmp_path / "log.jsonl")

    recorder.record_error("m1", RuntimeError("boom"))  # must not raise

    captured = capsys.readouterr()
    assert "Warning: logging failed" in captured.err
