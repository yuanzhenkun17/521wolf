"""Repository for persisted benchmark leaderboard snapshots."""

from __future__ import annotations

import json
from typing import Any

from storage.shared.database import StorageConnection, StorageRow


_SNAPSHOT_COLUMNS = (
    "snapshot_id, title, release_notes, scope, benchmark_id, benchmark_version, "
    "evaluation_set_id, seed_set_id, benchmark_config_hash, target_role, "
    "source_filter, view_config, rows_json, summary_json, row_count, content_hash, created_at"
)


class BenchmarkSnapshotRepository:
    """Persist and query frozen benchmark leaderboard snapshots.

    Schema creation is owned by Alembic migrations; this repository only reads
    and writes runtime data.
    """

    def __init__(self, conn: StorageConnection) -> None:
        self._conn = conn

    def save(self, snapshot: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO benchmark_leaderboard_snapshots "
            "(snapshot_id, title, release_notes, scope, benchmark_id, benchmark_version, "
            "evaluation_set_id, seed_set_id, benchmark_config_hash, target_role, "
            "source_filter, view_config, rows_json, summary_json, row_count, content_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                snapshot.get("snapshot_id"),
                snapshot.get("title"),
                snapshot.get("release_notes"),
                snapshot.get("scope"),
                snapshot.get("benchmark_id"),
                snapshot.get("benchmark_version"),
                snapshot.get("evaluation_set_id"),
                snapshot.get("seed_set_id"),
                snapshot.get("benchmark_config_hash"),
                snapshot.get("target_role"),
                json.dumps(snapshot.get("source_filter") or {}, ensure_ascii=False),
                json.dumps(snapshot.get("view_config") or {}, ensure_ascii=False),
                json.dumps(snapshot.get("rows") or [], ensure_ascii=False),
                json.dumps(snapshot.get("summary") or {}, ensure_ascii=False),
                int(snapshot.get("row_count") or 0),
                snapshot.get("content_hash"),
                snapshot.get("created_at"),
            ),
        )
        self._conn.commit()

    def list(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        where = "WHERE 1 = 1 "
        params: list[Any] = []
        if scope:
            where += "AND scope = ? "
            params.append(scope)
        if evaluation_set_id:
            where += "AND evaluation_set_id = ? "
            params.append(evaluation_set_id)
        if benchmark_id:
            where += "AND benchmark_id = ? "
            params.append(benchmark_id)
        if target_role:
            where += "AND target_role = ? "
            params.append(target_role)
        params.append(_bounded_limit(limit))
        rows = self._conn.execute(
            f"SELECT {_SNAPSHOT_COLUMNS} "
            "FROM benchmark_leaderboard_snapshots "
            f"{where}"
            "ORDER BY created_at DESC, snapshot_id DESC LIMIT ?",
            tuple(params),
        ).fetchall()
        return [_snapshot_from_row(row) for row in rows]

    def get(self, snapshot_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            f"SELECT {_SNAPSHOT_COLUMNS} "
            "FROM benchmark_leaderboard_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return _snapshot_from_row(row) if row is not None else None


def _snapshot_from_row(row: StorageRow) -> dict[str, Any]:
    payload = _row_to_dict(row)
    rows = _decode_json_field(payload.get("rows_json"), fallback=[])
    summary = _decode_json_field(payload.get("summary_json"), fallback={})
    source_filter = _decode_json_field(payload.get("source_filter"), fallback={})
    view_config = _decode_json_field(payload.get("view_config"), fallback={})
    frozen_rows = rows if isinstance(rows, list) else []
    summary_payload = summary if isinstance(summary, dict) else {}
    snapshot = {
        "kind": "benchmark_leaderboard_snapshot",
        "schema_version": 1,
        "snapshot_id": str(payload.get("snapshot_id") or ""),
        "title": str(payload.get("title") or ""),
        "release_notes": str(payload.get("release_notes") or ""),
        "scope": payload.get("scope"),
        "benchmark_id": payload.get("benchmark_id"),
        "benchmark_version": payload.get("benchmark_version"),
        "evaluation_set_id": payload.get("evaluation_set_id"),
        "seed_set_id": payload.get("seed_set_id"),
        "benchmark_config_hash": payload.get("benchmark_config_hash"),
        "target_role": payload.get("target_role"),
        "source_filter": source_filter if isinstance(source_filter, dict) else {},
        "view_config": view_config if isinstance(view_config, dict) else {},
        "rows": frozen_rows,
        "summary": summary_payload,
        "row_count": payload.get("row_count"),
        "content_hash": payload.get("content_hash"),
        "created_at": payload.get("created_at"),
    }
    release_gate = summary_payload.get("release_gate")
    if isinstance(release_gate, dict):
        snapshot["release_gate"] = release_gate
    return snapshot


def _row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    keys = getattr(row, "keys", None)
    if callable(keys):
        return {key: row[key] for key in keys()}
    return {}


def _decode_json_field(value: Any, *, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _bounded_limit(limit: int) -> int:
    return max(1, min(int(limit or 50), 500))
