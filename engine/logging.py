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
    def __init__(self, stream_path: str | Path | None = None) -> None:
        self.entries: list[GameLogEntry] = []
        self._stream_path: Path | None = Path(stream_path) if stream_path else None
        if self._stream_path:
            self._stream_path.parent.mkdir(parents=True, exist_ok=True)
            self._stream_path.touch()

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
        if self._stream_path:
            line = json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True)
            with self._stream_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
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
    """Generate a timestamp-based game log name: yyyyMMdd_HHmmss_N."""
    from datetime import datetime, timezone, timedelta
    BEIJING = timezone(timedelta(hours=8))
    directory = Path(log_dir)
    ts = datetime.now(BEIJING).strftime("%Y%m%d_%H%M%S")
    # Find the max N for this timestamp
    max_n = 0
    for path in directory.glob(f"{ts}_*"):
        name = path.name if path.is_dir() else path.stem
        parts = name.rsplit("_", 1)
        if len(parts) == 2 and parts[1].isdigit():
            max_n = max(max_n, int(parts[1]))
    return f"{ts}_{max_n + 1}"


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
