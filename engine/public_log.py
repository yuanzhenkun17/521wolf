from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from engine.engine import GameEngine


def append_public_event(
    engine: GameEngine,
    event_type: str,
    *,
    actor: int | None = None,
    target: int | None = None,
    content: str = "",
    payload: dict[str, Any] | None = None,
) -> None:
    entry = {
        "day": engine.state.day,
        "phase": engine.state.phase.value,
        "type": event_type,
        "actor": actor,
        "target": target,
        "content": content,
    }
    if payload:
        entry["payload"] = payload
    engine.state.public_log.append(json.dumps(entry, ensure_ascii=False, sort_keys=True))
