"""Game event logging, persistence, and replay infrastructure.

This module provides the GameLogger that records, streams, and serializes
game events as GameEvent objects (from engine.models).

GameLogger is the single source of truth for all game events. It creates
GameEvent instances, persists them to JSONL files, streams them to an
EventSink (e.g. SQLite), and provides serialization for replay and UI display.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from engine.models import GameEvent, Phase


_NIGHT_PUBLIC_EVENT_TYPES = {
    "night_start",
    "night_end",
    "night_death_reveal",
    "death",
    "hunter_shot",
    "hunter_no_shot",
    "sheriff_badge_transfer",
    "sheriff_badge_destroy",
    "game_end",
}


class EventSink(Protocol):
    def record_event(self, entry: GameEvent) -> None:
        ...


class GameLogger:
    def __init__(
        self,
        stream_path: str | Path | None = None,
        sink: EventSink | None = None,
    ) -> None:
        self.entries: list[GameEvent] = []
        self._stream_path: Path | None = Path(stream_path) if stream_path else None
        self._next_index: int = 1
        if self._stream_path:
            self._stream_path.parent.mkdir(parents=True, exist_ok=True)
            self._stream_path.touch()
        self._sink = sink

    def record(
        self,
        *,
        day: int,
        phase: Any,
        event_type: str,
        message: str,
        actor: int | None = None,
        target: int | None = None,
        payload: dict[str, Any] | None = None,
        public: bool = True,
    ) -> GameEvent:
        if isinstance(phase, Phase):
            phase_enum = phase
        else:
            try:
                phase_enum = Phase(phase)
            except ValueError:
                phase_enum = phase  # type: ignore[assignment]
        entry = GameEvent(
            type=event_type,
            day=day,
            phase=phase_enum,
            actor=actor,
            target=target,
            payload=payload or {},
            public=_resolve_public_visibility(phase_enum, event_type, public),
            message=message,
            index=self._next_index,
        )
        self._next_index += 1
        self.entries.append(entry)
        if self._stream_path:
            line = json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True)
            with self._stream_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        if self._sink is not None:
            self._sink.record_event(entry)
        return entry

    def to_jsonl(self) -> str:
        lines = [json.dumps(entry.to_dict(), ensure_ascii=False, sort_keys=True) for entry in self.entries]
        return "\n".join(lines) + ("\n" if lines else "")

    def to_text(self) -> str:
        lines = []
        for entry in self.entries:
            actor = f" actor={entry.actor}" if entry.actor is not None else ""
            target = f" target={entry.target}" if entry.target is not None else ""
            phase_str = entry.phase.value if hasattr(entry.phase, "value") else str(entry.phase)
            lines.append(
                f"[{entry.index:04d}] 第 {entry.day} 天 {phase_str} "
                f"{entry.type}{actor}{target}: {entry.message}"
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


def next_game_log_name(log_dir: str | Path) -> str:
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


def _resolve_public_visibility(phase: Any, event_type: str, requested_public: bool) -> bool:
    if not requested_public:
        return False
    if _is_night_phase(phase):
        return event_type in _NIGHT_PUBLIC_EVENT_TYPES
    return True


def _is_night_phase(phase: Any) -> bool:
    if phase is Phase.NIGHT:
        return True
    return str(getattr(phase, "value", phase)) == Phase.NIGHT.value
