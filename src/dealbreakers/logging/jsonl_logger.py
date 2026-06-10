"""Append-only JSONL logger for match interactions."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

DEFAULT_LOG_PATH = Path("logs/runs.jsonl")


def serialize_for_log(value: Any) -> Any:
    """Recursively convert dataclasses, enums, and paths into JSON-safe values."""
    if is_dataclass(value) and not isinstance(value, type):
        return {key: serialize_for_log(val) for key, val in asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: serialize_for_log(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize_for_log(item) for item in value]
    return value


def append_run_log(record: dict[str, Any], path: str | Path = DEFAULT_LOG_PATH) -> None:
    """Append one JSON line to the log. Never raises — logging must not kill the agent."""
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        entry = serialize_for_log(record)
        if "timestamp" not in entry:
            entry = {"timestamp": datetime.now(timezone.utc).isoformat(), **entry}

        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"Warning: logging failed: {exc}", file=sys.stderr)


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Read all records from a JSONL file. Returns [] if the file does not exist."""
    path = Path(path)
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def clear_log(path: str | Path) -> None:
    """Delete the log file if it exists. Never raises."""
    try:
        Path(path).unlink(missing_ok=True)
    except Exception as exc:
        print(f"Warning: clearing log failed: {exc}", file=sys.stderr)
