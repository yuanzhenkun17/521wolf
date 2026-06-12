"""Compatibility facade for benchmark evaluation persistence repositories."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from storage.benchmark.batch_repo import BenchmarkBatchRepository
from storage.benchmark.leaderboard_repo import BenchmarkLeaderboardRepository
from storage.shared.database import StorageConnection

_log = logging.getLogger(__name__)


class PersistenceWarning(str):
    """Backward-compatible warning string carrying structured diagnostics."""

    diagnostic: dict[str, Any]

    def __new__(cls, operation: str, exc: Exception) -> "PersistenceWarning":
        message = f"{operation} failed: {type(exc).__name__}: {exc}"
        value = str.__new__(cls, message)
        value.diagnostic = _persistence_diagnostic(operation, exc, message)
        return value


class BenchmarkEvaluationRepository:
    """Backward-compatible facade for benchmark batch and leaderboard repos."""

    def __init__(self, conn: StorageConnection, *, autocommit: bool = True) -> None:
        self._batch_repo = BenchmarkBatchRepository(conn, autocommit=autocommit)
        self._leaderboard_repo = BenchmarkLeaderboardRepository(conn, autocommit=autocommit)

    def save_batch(self, batch: dict[str, Any]) -> None:
        self._batch_repo.save(batch)

    def save_leaderboard_entry(self, entry: dict[str, Any]) -> None:
        self._leaderboard_repo.save(entry)

    def load_comparison_group(
        self,
        comparison_group_id: str,
        *,
        exclude_batch_id: str = "",
    ) -> list[dict[str, Any]]:
        return self._batch_repo.load_comparison_group(
            comparison_group_id,
            exclude_batch_id=exclude_batch_id,
        )

    def list_leaderboard_rows(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        limit: int = 100,
    ) -> list[Any]:
        return self._leaderboard_repo.list(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role,
            limit=limit,
        )

    def list_role_leaderboard_rows(
        self,
        role: str,
        *,
        evaluation_set_id: str | None = None,
    ) -> list[Any]:
        return self._leaderboard_repo.list_role_rows(
            role,
            evaluation_set_id=evaluation_set_id,
        )

    def list_role_leaderboard_rows_for_roles(
        self,
        roles: list[str],
        *,
        evaluation_set_id: str | None = None,
    ) -> list[Any]:
        return self._leaderboard_repo.list_role_rows_for_roles(
            roles,
            evaluation_set_id=evaluation_set_id,
        )


def open_benchmark_connection(paths: Any = None) -> StorageConnection:
    """Open the wolf-domain storage connection used by benchmark persistence."""
    from storage.provider import open_wolf_connection

    return open_wolf_connection(paths=paths)


def open_eval_connection(paths: Any = None) -> StorageConnection:
    """Open the wolf-domain storage connection used by evaluation persistence."""
    return open_benchmark_connection(paths=paths)


def save_evaluation_batch(conn: Any, batch: dict[str, Any]) -> str | None:
    """Persist an evaluation batch row to evaluation_batches (idempotent by id).

    Returns a warning string when the best-effort write fails.
    """
    try:
        _run_write_transaction(conn, lambda repo: repo.save_batch(batch))
        return None
    except Exception as exc:  # noqa: BLE001 - persistence is best-effort
        _log.warning("save_evaluation_batch failed", exc_info=True)
        return _persistence_warning("save_evaluation_batch", exc)


def persist_leaderboard_entry(conn: Any, entry: dict[str, Any]) -> str | None:
    """Persist a leaderboard entry to the benchmark_leaderboard table.

    Idempotent per (scope, subject_id, comparison_group_id) - re-running a
    batch overwrites its row rather than accumulating duplicates. Returns a
    warning string when the best-effort write fails.
    """
    try:
        _run_write_transaction(conn, lambda repo: repo.save_leaderboard_entry(entry))
        return None
    except Exception as exc:  # noqa: BLE001 - leaderboard write is best-effort
        _log.warning("persist_leaderboard_entry failed", exc_info=True)
        return _persistence_warning("persist_leaderboard_entry", exc)


def load_comparison_group(conn: Any, comparison_group_id: str, *, exclude_batch_id: str = "") -> list[dict[str, Any]]:
    """Load sibling batches in a comparison group, excluding the current batch.

    Read failures are raised so callers can distinguish storage problems from
    a genuinely empty comparison group.
    """
    try:
        return BenchmarkEvaluationRepository(conn).load_comparison_group(
            comparison_group_id,
            exclude_batch_id=exclude_batch_id,
        )
    except Exception:  # noqa: BLE001 - keep the original error for caller diagnostics
        _log.warning("load_comparison_group failed", exc_info=True)
        raise


def _persistence_diagnostic(operation: str, exc: Exception, message: str) -> dict[str, Any]:
    return {
        "kind": "persistence_error",
        "stage": f"persist_batch.{operation}",
        "level": "warning",
        "message": message,
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
        "traceback": _format_traceback(exc),
    }


def _format_traceback(exc: Exception) -> str:
    import traceback
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-2000:]


def _persistence_warning(operation: str, exc: Exception) -> PersistenceWarning:
    return PersistenceWarning(operation, exc)


def _run_write_transaction(
    conn: Any,
    operation: Callable[[BenchmarkEvaluationRepository], None],
) -> None:
    try:
        _begin_write_if_supported(conn)
        operation(BenchmarkEvaluationRepository(conn, autocommit=False))
        conn.commit()
    except Exception:
        _rollback_quietly(conn)
        raise


def _begin_write_if_supported(conn: Any) -> None:
    begin_write = getattr(conn, "begin_write", None)
    if callable(begin_write):
        begin_write()


def _rollback_quietly(conn: Any) -> None:
    rollback = getattr(conn, "rollback", None)
    if not callable(rollback):
        return
    try:
        rollback()
    except Exception:  # noqa: BLE001 - keep original persistence failure
        pass


__all__ = [
    "BenchmarkEvaluationRepository",
    "PersistenceWarning",
    "load_comparison_group",
    "open_benchmark_connection",
    "open_eval_connection",
    "persist_leaderboard_entry",
    "save_evaluation_batch",
]
