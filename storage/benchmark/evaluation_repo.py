"""Compatibility facade for benchmark evaluation persistence repositories."""

from __future__ import annotations

from typing import Any

from storage.benchmark.batch_repo import BenchmarkBatchRepository
from storage.benchmark.leaderboard_repo import BenchmarkLeaderboardRepository
from storage.shared.database import StorageConnection


class BenchmarkEvaluationRepository:
    """Backward-compatible facade for benchmark batch and leaderboard repos."""

    def __init__(self, conn: StorageConnection) -> None:
        self._batch_repo = BenchmarkBatchRepository(conn)
        self._leaderboard_repo = BenchmarkLeaderboardRepository(conn)

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


__all__ = ["BenchmarkEvaluationRepository", "open_benchmark_connection"]
