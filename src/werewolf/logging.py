from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum, StrEnum
from pathlib import Path
from typing import Any


class LogLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"


class LogVisibility(StrEnum):
    GOD = "god"
    PUBLIC = "public"
    PRIVATE = "private"


@dataclass(slots=True)
class GameLogEntry:
    index: int
    day: int
    phase: str
    event_type: str
    message: str
    level: LogLevel = LogLevel.INFO
    visibility: LogVisibility = LogVisibility.GOD
    actor: int | None = None
    target: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "day": self.day,
            "phase": self.phase,
            "event_type": self.event_type,
            "message": self.message,
            "level": self.level.value,
            "visibility": self.visibility.value,
            "actor": self.actor,
            "target": self.target,
            "payload": _jsonable(self.payload),
        }


class GameLogger:
    def __init__(self) -> None:
        self.entries: list[GameLogEntry] = []

    def record(
        self,
        *,
        day: int,
        phase: Any,
        event_type: str,
        message: str,
        level: LogLevel = LogLevel.INFO,
        visibility: LogVisibility = LogVisibility.GOD,
        actor: int | None = None,
        target: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> GameLogEntry:
        entry = GameLogEntry(
            index=len(self.entries) + 1,
            day=day,
            phase=_value(phase),
            event_type=event_type,
            message=message,
            level=level,
            visibility=visibility,
            actor=actor,
            target=target,
            payload=payload or {},
        )
        self.entries.append(entry)
        return entry

    def to_jsonl(self) -> str:
        lines = [json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True) for entry in self.entries]
        return "\n".join(lines) + ("\n" if lines else "")

    def to_text(self) -> str:
        lines = []
        for entry in self.entries:
            actor = f" actor={entry.actor}" if entry.actor is not None else ""
            target = f" target={entry.target}" if entry.target is not None else ""
            lines.append(
                f"[{entry.index:04d}] 第 {entry.day} 天 {entry.phase} "
                f"{entry.event_type}{actor}{target}: {entry.message}"
            )
        return "\n".join(lines) + ("\n" if lines else "")

    def write_jsonl(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(self.to_jsonl(), encoding="utf-8")
        return output

    def write_text(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(self.to_text(), encoding="utf-8")
        return output


def next_game_log_name(log_dir: str | Path, prefix: str = "game") -> str:
    directory = Path(log_dir)
    max_index = 0
    for path in directory.glob(f"{prefix}*.*"):
        stem = path.stem
        if not stem.startswith(prefix):
            continue
        suffix = stem[len(prefix) :]
        if suffix.isdigit():
            max_index = max(max_index, int(suffix))
    return f"{prefix}{max_index + 1}"


def _value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(_value(key)): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return value
