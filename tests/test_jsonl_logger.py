import builtins
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from dealbreakers.logging import append_run_log, clear_log, read_jsonl


class Colour(Enum):
    RED = "red"


@dataclass
class Inner:
    score: float


@dataclass
class Outer:
    name: str
    inner: Inner
    tags: list[str] = field(default_factory=list)


def test_append_creates_parent_dirs(tmp_path: Path) -> None:
    log = tmp_path / "nested" / "deeper" / "log.jsonl"
    append_run_log({"event": "test"}, log)
    assert log.exists()


def test_one_json_object_per_line(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    append_run_log({"n": 1}, log)
    append_run_log({"n": 2}, log)

    lines = log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["n"] for line in lines] == [1, 2]


def test_dataclass_serialization(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    append_run_log({"payload": Outer(name="x", inner=Inner(score=9.5), tags=["a"])}, log)

    record = read_jsonl(log)[0]
    assert record["payload"] == {"name": "x", "inner": {"score": 9.5}, "tags": ["a"]}


def test_enum_serialization(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    append_run_log({"colour": Colour.RED}, log)
    assert read_jsonl(log)[0]["colour"] == "red"


def test_path_serialization(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    append_run_log({"where": Path("logs/runs.jsonl")}, log)
    assert read_jsonl(log)[0]["where"] == str(Path("logs/runs.jsonl"))


def test_timestamp_added_when_missing(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    append_run_log({"event": "x"}, log)
    assert "timestamp" in read_jsonl(log)[0]


def test_existing_timestamp_preserved(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    append_run_log({"timestamp": "2026-01-01T00:00:00+00:00", "event": "x"}, log)
    assert read_jsonl(log)[0]["timestamp"] == "2026-01-01T00:00:00+00:00"


def test_logging_failure_is_non_fatal(tmp_path: Path, monkeypatch, capsys) -> None:
    def broken_open(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "open", broken_open)
    append_run_log({"event": "x"}, tmp_path / "log.jsonl")

    captured = capsys.readouterr()
    assert "Warning: logging failed" in captured.err


def test_read_jsonl_roundtrip(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    append_run_log({"a": 1}, log)
    append_run_log({"b": 2}, log)

    records = read_jsonl(log)
    assert len(records) == 2
    assert records[0]["a"] == 1
    assert records[1]["b"] == 2


def test_read_jsonl_missing_file(tmp_path: Path) -> None:
    assert read_jsonl(tmp_path / "missing.jsonl") == []


def test_read_jsonl_skips_blank_lines(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    log.write_text('{"a": 1}\n\n{"b": 2}\n', encoding="utf-8")
    assert len(read_jsonl(log)) == 2


def test_clear_log_removes_file(tmp_path: Path) -> None:
    log = tmp_path / "log.jsonl"
    append_run_log({"a": 1}, log)
    assert log.exists()

    clear_log(log)
    assert not log.exists()

    clear_log(log)  # second clear is a safe no-op
    assert not log.exists()
