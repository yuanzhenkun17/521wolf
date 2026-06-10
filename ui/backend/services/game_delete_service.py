"""Delete coordinator for UI backend game records."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class GameDeleteCoordinator:
    """Coordinates UI-level game delete policy around the storage delete call."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def delete_game(self, game_id: str, *, force: bool = False) -> dict[str, Any]:
        store = self._store
        store.check_live_game_watchdog()
        live = store.live_sessions.get(game_id)
        game = live.snapshot() if live is not None else store.games.get(game_id)
        if game is None:
            game = store._load_game_from_pg(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")

        log_source = store._snapshot_log_source(game)
        if log_source != "normal" and not force:
            raise HTTPException(
                status_code=409,
                detail=f"{log_source} game requires force delete",
            )

        if live is not None:
            self._cancel_live_game(game_id, live)

        store._delete_game_from_pg(game_id)
        store._mark_game_deleted(game_id)
        store.games.pop(game_id, None)
        store.invalidate_game_history_index()
        return {
            "game_id": game_id,
            "deleted": True,
            "log_source": log_source,
            "force": bool(force),
        }

    def _cancel_live_game(self, game_id: str, live: Any) -> None:
        store = self._store
        store._mark_game_deleted(game_id)
        live.cancel()
        store.live_sessions.pop(game_id, None)
        persistence = getattr(live, "persistence", None)
        close = getattr(persistence, "close", None)
        if callable(close):
            close()


__all__ = ["GameDeleteCoordinator"]
