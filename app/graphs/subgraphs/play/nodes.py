"""Play subgraph nodes."""

from __future__ import annotations


async def init_play_run_node(state: dict) -> dict:
    """Initialize a play run: generate game_id, set up run metadata."""
    import uuid
    from app.util.time import beijing_now_iso

    state["run_type"] = "play"
    state.setdefault("game_id", f"play_{uuid.uuid4().hex[:12]}")
    state.setdefault("started_at", beijing_now_iso())
    return state


async def persist_play_node(state: dict) -> dict:
    """Persist play results."""
    state["finished_at"] = __import__("app.util.time").util.time.beijing_now_iso()
    return state
