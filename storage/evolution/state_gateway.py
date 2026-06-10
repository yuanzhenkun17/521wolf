"""Connection-owning gateway for evolution runtime state."""

from __future__ import annotations

from typing import Any

from storage.interfaces import EvolutionRunData


class EvolutionStateGateway:
    """Open evolution storage connections and delegate run state operations."""

    def __init__(self, *, paths: Any | None = None) -> None:
        self._paths = paths

    def save_run(self, run: EvolutionRunData) -> None:
        conn = self._open_connection()
        try:
            self._store(conn).save_run(run)
        finally:
            conn.close()

    def get_run(self, run_id: str) -> EvolutionRunData | None:
        conn = self._open_connection()
        try:
            return self._store(conn).get_run(run_id)
        finally:
            conn.close()

    def list_runs(
        self,
        *,
        role: str | None = None,
        status: str | None = None,
        limit: int = 200,
    ) -> list[EvolutionRunData]:
        conn = self._open_connection()
        try:
            return self._store(conn).list_runs(role=role, status=status, limit=limit)
        finally:
            conn.close()

    def _open_connection(self) -> Any:
        import storage.provider as provider_mod

        if self._paths is None:
            provider = provider_mod.storage_provider_from_env()
        else:
            provider = provider_mod.storage_provider_from_env(paths=self._paths)
        return provider.open_evolution_connection()

    @staticmethod
    def _store(conn: Any) -> Any:
        import storage.evolution.run_repo as run_repo

        return run_repo.EvolutionStore(conn)


__all__ = ["EvolutionStateGateway"]
