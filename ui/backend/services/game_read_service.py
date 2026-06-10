"""Read gateway for UI backend game history and detail queries."""

from __future__ import annotations

import threading
from typing import Any, Callable

from storage.game_read_model import GameReadRepository


class GameReadGateway:
    """Owns the cached wolf read connection used by UI game read paths."""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._lock = threading.RLock()
        self._conn: Any | None = None

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def close(self) -> None:
        with self._lock:
            conn = self._conn
            if conn is None:
                return
            self._conn = None
            close = getattr(conn, "close", None)
            if callable(close):
                close()

    def open_connection(self) -> Any:
        with self._lock:
            return self._open_connection_unlocked()

    def _open_connection_unlocked(self) -> Any:
        conn = self._conn
        if conn is not None and not getattr(conn, "closed", False):
            return conn
        conn = self._store._open_wolf_connection()
        self._conn = conn
        return conn

    def read_repository(self, read: Callable[[GameReadRepository], Any]) -> Any:
        with self._lock:
            conn = self._open_connection_unlocked()
            try:
                result = read(GameReadRepository(conn))
                commit = getattr(conn, "commit", None)
                if callable(commit):
                    commit()
                return result
            except Exception:
                rollback = getattr(conn, "rollback", None)
                try:
                    if callable(rollback):
                        rollback()
                except Exception:  # noqa: BLE001 - preserve the original read failure
                    pass
                finally:
                    self.close()
                raise

    def history_fingerprint(self) -> dict[str, Any]:
        return self.read_repository(lambda repo: repo.history_fingerprint())

    def load_game_detail(self, game_id: str) -> dict[str, Any] | None:
        return self.read_repository(lambda repo: repo.load_game_detail(game_id))

    def load_game_history_shell(self, game_id: str) -> dict[str, Any] | None:
        return self.read_repository(lambda repo: repo.load_game_history_shell(game_id))

    def load_game_phase_detail(
        self,
        game_id: str,
        *,
        day: int,
        phase: str,
        log_offset: int = 0,
        log_limit: int | None = None,
        decision_offset: int = 0,
        decision_limit: int | None = None,
    ) -> dict[str, Any] | None:
        return self.read_repository(lambda repo: repo.load_game_phase_detail(
            game_id,
            day=day,
            phase=phase,
            log_offset=log_offset,
            log_limit=log_limit,
            decision_offset=decision_offset,
            decision_limit=decision_limit,
        ))

    def load_game_flow_data(self, game_id: str) -> dict[str, Any] | None:
        return self.read_repository(lambda repo: repo.load_game_flow_data(game_id))

    def load_game_replay(
        self,
        game_id: str,
        *,
        cursor: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any] | None:
        return self.read_repository(lambda repo: repo.load_game_replay(game_id, cursor=cursor, limit=limit))

    def load_game_review(self, game_id: str) -> dict[str, Any] | None:
        return self.read_repository(lambda repo: repo.load_game_review(game_id))

    def list_history_rows(self) -> list[dict[str, Any]]:
        return self.read_repository(lambda repo: repo.list_history_rows())


__all__ = ["GameReadGateway"]
