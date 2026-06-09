"""Repository for PostgreSQL-backed role version registry data."""

from __future__ import annotations

import json
from typing import Any

from app.util.time import beijing_now_iso
from storage.shared.database import StorageConnection, StorageRow, begin_write, execute_for_update


class RegistryVersionRepository:
    """Read and write registry schema rows for role versions.

    Schema creation is owned by Alembic migrations; this repository only owns
    runtime SQL and transaction boundaries.
    """

    def __init__(self, conn: StorageConnection) -> None:
        self._conn = conn

    def close(self) -> None:
        self._conn.close()

    def load_version_row(self, role: str, version_id: str) -> StorageRow | None:
        row = self._conn.execute(
            "SELECT * FROM role_versions WHERE role = ? AND id = ?",
            (role, version_id),
        ).fetchone()
        self._conn.commit()
        return row

    def load_version_row_uncommitted(self, role: str, version_id: str) -> StorageRow | None:
        return self._conn.execute(
            "SELECT * FROM role_versions WHERE role = ? AND id = ?",
            (role, version_id),
        ).fetchone()

    def insert_version(
        self,
        *,
        version_id: str,
        role: str,
        parent_id: str | None,
        source: str,
        run_id: str | None,
        skills: dict[str, str],
        notes: list[str],
        status: str,
        provenance: dict[str, Any],
    ) -> None:
        try:
            self._conn.execute(
                "INSERT INTO role_versions "
                "(id, role, parent_id, source, run_id, skills, notes, status, created_at, provenance_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    version_id,
                    role,
                    parent_id,
                    source,
                    run_id,
                    json.dumps(skills, ensure_ascii=False),
                    json.dumps(notes, ensure_ascii=False),
                    status,
                    beijing_now_iso(),
                    json.dumps(provenance, ensure_ascii=False),
                ),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def update_version_status(self, *, role: str, version_id: str, status: str, provenance: dict[str, Any]) -> None:
        self._conn.execute(
            "UPDATE role_versions SET status = ?, provenance_json = ? WHERE role = ? AND id = ?",
            (status, json.dumps(provenance, ensure_ascii=False), role, version_id),
        )
        self._conn.commit()

    def get_baseline(self, role: str) -> str | None:
        row = self._conn.execute(
            "SELECT version_id FROM role_current_baseline WHERE role = ?",
            (role,),
        ).fetchone()
        if row is not None:
            result = str(row["version_id"])
        else:
            row = self._conn.execute(
                "SELECT id FROM role_versions WHERE role = ? AND status = 'baseline' "
                "ORDER BY created_at LIMIT 1",
                (role,),
            ).fetchone()
            result = str(row["id"]) if row is not None else None
        self._conn.commit()
        return result

    def set_baseline(self, *, role: str, version_id: str, expected_current: str | None) -> bool:
        begin_write(self._conn)
        try:
            rows = execute_for_update(
                self._conn,
                "SELECT id, status FROM role_versions WHERE role = ? ORDER BY created_at",
                (role,),
            ).fetchall()
            if not any(str(row["id"]) == version_id for row in rows):
                self._conn.rollback()
                return False
            current = self.current_baseline_unlocked(role, rows)
            if current != expected_current:
                self._conn.rollback()
                return False
            now = beijing_now_iso()
            self._conn.execute(
                "UPDATE role_versions SET status = 'archived' "
                "WHERE role = ? AND status = 'baseline' AND id <> ?",
                (role, version_id),
            )
            self._conn.execute(
                "UPDATE role_versions SET status = 'baseline' WHERE role = ? AND id = ?",
                (role, version_id),
            )
            self._conn.execute(
                "INSERT INTO role_current_baseline (role, version_id, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(role) DO UPDATE SET "
                "version_id = excluded.version_id, updated_at = excluded.updated_at",
                (role, version_id, now),
            )
            self._conn.execute(
                "INSERT INTO role_baseline_history "
                "(role, version_id, previous_version_id, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (role, version_id, current, "baseline_set", now),
            )
            self._conn.commit()
            return True
        except Exception:
            self._conn.rollback()
            raise

    def reject_version(self, *, role: str, version_id: str, reason: str = "") -> bool:
        if self.load_version_row_uncommitted(role, version_id) is None:
            self._conn.commit()
            return False
        now = beijing_now_iso()
        try:
            self._conn.execute(
                "UPDATE role_versions SET status = 'rejected' WHERE role = ? AND id = ?",
                (role, version_id),
            )
            self._conn.execute(
                "INSERT INTO role_baseline_history "
                "(role, version_id, previous_version_id, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (role, version_id, None, f"rejected: {reason}" if reason else "rejected", now),
            )
            self._conn.commit()
            return True
        except Exception:
            self._conn.rollback()
            raise

    def list_version_rows(self, role: str) -> list[StorageRow]:
        rows = self._conn.execute(
            "SELECT id, role, source, created_at, status, provenance_json "
            "FROM role_versions WHERE role = ? ORDER BY created_at",
            (role,),
        ).fetchall()
        self._conn.commit()
        return rows

    def list_roles(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT role FROM role_versions ORDER BY role"
        ).fetchall()
        result = [str(row["role"]) for row in rows]
        self._conn.commit()
        return result

    def begin_rejected_update(self, role: str) -> StorageRow | None:
        begin_write(self._conn)
        self._conn.execute(
            "INSERT INTO rejected_proposals (role, proposals_json) VALUES (?, ?) "
            "ON CONFLICT(role) DO NOTHING",
            (role, "[]"),
        )
        return execute_for_update(
            self._conn,
            "SELECT proposals_json FROM rejected_proposals WHERE role = ?",
            (role,),
        ).fetchone()

    def update_rejected(self, *, role: str, proposals_json: str) -> None:
        self._conn.execute(
            "UPDATE rejected_proposals SET proposals_json = ? WHERE role = ?",
            (proposals_json, role),
        )
        self._conn.commit()

    def load_rejected_payload(self, role: str) -> Any | None:
        row = self._conn.execute(
            "SELECT proposals_json FROM rejected_proposals WHERE role = ?",
            (role,),
        ).fetchone()
        self._conn.commit()
        return row["proposals_json"] if row is not None else None

    def rollback(self) -> None:
        self._conn.rollback()

    def current_baseline_unlocked(self, role: str, rows: list[Any]) -> str | None:
        row = self._conn.execute(
            "SELECT version_id FROM role_current_baseline WHERE role = ?",
            (role,),
        ).fetchone()
        if row is not None:
            return str(row["version_id"])
        baseline_row = next((item for item in rows if item["status"] == "baseline"), None)
        return str(baseline_row["id"]) if baseline_row is not None else None


__all__ = ["RegistryVersionRepository"]
