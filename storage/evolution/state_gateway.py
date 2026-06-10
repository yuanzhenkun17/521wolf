"""Connection-owning gateway for evolution runtime state."""

from __future__ import annotations

import logging
from typing import Any

from storage.interfaces import EvolutionRunData

_log = logging.getLogger(__name__)


class EvolutionStateGateway:
    """Open evolution storage connections and delegate run state operations."""

    def __init__(self, *, provider: Any | None = None, paths: Any | None = None) -> None:
        self._provider = provider
        self._paths = paths

    def save_run(self, run: EvolutionRunData) -> None:
        conn = self._open_connection()
        try:
            self._store(conn).save_run(run)
        finally:
            conn.close()

    def save_runtime_state(
        self,
        run: EvolutionRunData,
        *,
        trust_bundle: dict[str, Any] | None = None,
    ) -> None:
        conn = self._open_connection()
        try:
            store = self._store(conn)
            store.save_run(run)
            if (
                isinstance(trust_bundle, dict)
                and trust_bundle.get("schema_version") == "trust_bundle_v1"
            ):
                store.save_trust_bundle(trust_bundle)
        finally:
            self._close_best_effort(conn)

    def get_run(self, run_id: str) -> EvolutionRunData | None:
        conn = self._open_connection()
        try:
            return self._store(conn).get_run(run_id)
        finally:
            conn.close()

    def get_trust_bundle(self, run_id_or_bundle_id: str) -> dict[str, Any] | None:
        conn = self._open_connection()
        try:
            return self._store(conn).get_trust_bundle(run_id_or_bundle_id)
        finally:
            self._close_best_effort(conn)

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

        return provider_mod.open_evolution_connection(self._provider, paths=self._paths)

    @staticmethod
    def _store(conn: Any) -> Any:
        import storage.evolution.run_repo as run_repo

        return run_repo.EvolutionStore(conn)

    @staticmethod
    def _close_best_effort(conn: Any) -> None:
        try:
            conn.close()
        except Exception as exc:  # noqa: BLE001 - cleanup is best-effort
            _log.warning("failed to close evolution storage connection: %s", exc)


__all__ = ["EvolutionStateGateway"]
