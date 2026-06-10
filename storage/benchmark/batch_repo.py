"""Repository for benchmark evaluation batch rows."""

from __future__ import annotations

import json
from typing import Any

from app.util.time import beijing_now_iso
from storage.shared.database import StorageConnection


class BenchmarkBatchRepository:
    """Persist and query benchmark evaluation batch runtime data."""

    def __init__(self, conn: StorageConnection, *, autocommit: bool = False) -> None:
        self._conn = conn
        self._autocommit = autocommit

    def save(self, batch: dict[str, Any]) -> None:
        """Persist an evaluation batch row to evaluation_batches."""
        summary = batch.get("score_summary")
        created_at = str(batch.get("created_at") or beijing_now_iso())
        started_at = _nullable_timestamp(batch.get("started_at"))
        finished_at = _nullable_timestamp(batch.get("finished_at"))
        self._conn.execute(
            """INSERT INTO evaluation_batches
            (id, comparison_group_id, comparison_type, mode, model_id, model_config_hash,
             target_role, target_version_id, role_version_config, game_count,
             evaluation_set_id, seed_set_id, max_days, rankable, rankable_reason,
             summary, started_at, finished_at, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                comparison_group_id = excluded.comparison_group_id,
                comparison_type = excluded.comparison_type,
                mode = excluded.mode,
                model_id = excluded.model_id,
                model_config_hash = excluded.model_config_hash,
                target_role = excluded.target_role,
                target_version_id = excluded.target_version_id,
                role_version_config = excluded.role_version_config,
                game_count = excluded.game_count,
                evaluation_set_id = excluded.evaluation_set_id,
                seed_set_id = excluded.seed_set_id,
                max_days = excluded.max_days,
                rankable = excluded.rankable,
                rankable_reason = excluded.rankable_reason,
                summary = excluded.summary,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                created_at = excluded.created_at""",
            (
                str(batch.get("batch_id", "")),
                batch.get("comparison_group_id"),
                batch.get("comparison_type"),
                str(batch.get("mode", "dev")),
                batch.get("model_id"),
                batch.get("model_config_hash"),
                batch.get("target_role"),
                batch.get("target_version_id"),
                json.dumps(batch.get("role_version_config"), ensure_ascii=False)
                if batch.get("role_version_config") is not None
                else None,
                int(batch.get("game_count", 0) or 0),
                batch.get("evaluation_set_id"),
                batch.get("seed_set_id"),
                int(batch.get("max_days", 20) or 20),
                1 if batch.get("rankable") else 0,
                batch.get("rankable_reason", ""),
                json.dumps(summary, ensure_ascii=False) if summary is not None else None,
                started_at,
                finished_at,
                created_at,
            ),
        )
        if self._autocommit:
            self._conn.commit()

    def load_comparison_group(
        self,
        comparison_group_id: str,
        *,
        exclude_batch_id: str = "",
    ) -> list[dict[str, Any]]:
        """Load sibling batches in a comparison group, excluding the current batch."""
        if not comparison_group_id:
            return []
        rows = self._conn.execute(
            "SELECT id, comparison_group_id, comparison_type, mode, model_id, "
            "model_config_hash, target_role, target_version_id, seed_set_id, game_count "
            "FROM evaluation_batches WHERE comparison_group_id = ? AND id != ?",
            (comparison_group_id, exclude_batch_id),
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["batch_id"] = item.get("id")
            result.append(item)
        return result


def _nullable_timestamp(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


__all__ = ["BenchmarkBatchRepository"]
