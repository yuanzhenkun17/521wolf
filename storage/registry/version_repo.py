"""Repository for PostgreSQL-backed role version registry data."""

from __future__ import annotations

import json
from collections.abc import Callable
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
            self._insert_version_unlocked(
                version_id=version_id,
                role=role,
                parent_id=parent_id,
                source=source,
                run_id=run_id,
                skills=skills,
                notes=notes,
                status=status,
                provenance=provenance,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def update_version_status(self, *, role: str, version_id: str, status: str, provenance: dict[str, Any]) -> None:
        self._update_version_status_unlocked(
            role=role,
            version_id=version_id,
            status=status,
            provenance=provenance,
        )
        self._conn.commit()

    def publish_version(
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
        set_as_baseline: bool = False,
        expected_current: str | None = None,
        _retry_on_insert_conflict: bool = True,
    ) -> bool:
        """Insert or refresh an already-normalized PostgreSQL role version."""
        insert_attempted = False
        begin_write(self._conn)
        try:
            if set_as_baseline:
                rows = execute_for_update(
                    self._conn,
                    "SELECT id, status FROM role_versions WHERE role = ? ORDER BY created_at",
                    (role,),
                ).fetchall()
                if self.current_baseline_unlocked(role, rows) != expected_current:
                    self._conn.rollback()
                    return False

            existing = execute_for_update(
                self._conn,
                "SELECT * FROM role_versions WHERE role = ? AND id = ?",
                (role, version_id),
            ).fetchone()
            if existing is not None:
                self._refresh_existing_version_unlocked(
                    existing,
                    role=role,
                    version_id=version_id,
                    skills=skills,
                    status=status,
                    provenance=provenance,
                    set_as_baseline=set_as_baseline,
                )
            else:
                insert_attempted = True
                self._insert_version_unlocked(
                    version_id=version_id,
                    role=role,
                    parent_id=parent_id,
                    source=source,
                    run_id=run_id,
                    skills=skills,
                    notes=notes,
                    status=status,
                    provenance=provenance,
                )

            if set_as_baseline and not self._set_baseline_unlocked(
                role=role,
                version_id=version_id,
                expected_current=expected_current,
            ):
                self._conn.rollback()
                return False
            self._conn.commit()
            return True
        except Exception:
            self._conn.rollback()
            if insert_attempted and _retry_on_insert_conflict:
                existing = self.load_version_row(role, version_id)
                if existing is not None:
                    existing_skills = _loads_json_object(existing["skills"], default={})
                    if existing_skills != skills:
                        raise ValueError(f"Version {role}/{version_id} already exists with different skill content")
                    return self.publish_version(
                        version_id=version_id,
                        role=role,
                        parent_id=parent_id,
                        source=source,
                        run_id=run_id,
                        skills=skills,
                        notes=notes,
                        status=status,
                        provenance=provenance,
                        set_as_baseline=set_as_baseline,
                        expected_current=expected_current,
                        _retry_on_insert_conflict=False,
                    )
            raise

    def _insert_version_unlocked(
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

    def _update_version_status_unlocked(
        self,
        *,
        role: str,
        version_id: str,
        status: str,
        provenance: dict[str, Any],
    ) -> None:
        self._conn.execute(
            "UPDATE role_versions SET status = ?, provenance_json = ? WHERE role = ? AND id = ?",
            (status, json.dumps(provenance, ensure_ascii=False), role, version_id),
        )

    def _refresh_existing_version_unlocked(
        self,
        existing: StorageRow,
        *,
        role: str,
        version_id: str,
        skills: dict[str, str],
        status: str,
        provenance: dict[str, Any],
        set_as_baseline: bool,
    ) -> None:
        existing_skills = _loads_json_object(existing["skills"], default={})
        if existing_skills != skills:
            raise ValueError(f"Version {role}/{version_id} already exists with different skill content")
        current_status = str(existing["status"] or "draft")
        if set_as_baseline or _should_update_existing_release_status(current_status, status):
            if not set_as_baseline:
                validate_release_stage_transition(current_status, status)
            self._update_version_status_unlocked(
                role=role,
                version_id=version_id,
                status=status,
                provenance=provenance,
            )

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
            if not self._set_baseline_unlocked(
                role=role,
                version_id=version_id,
                expected_current=expected_current,
            ):
                self._conn.rollback()
                return False
            self._conn.commit()
            return True
        except Exception:
            self._conn.rollback()
            raise

    def _set_baseline_unlocked(self, *, role: str, version_id: str, expected_current: str | None) -> bool:
        rows = execute_for_update(
            self._conn,
            "SELECT id, status FROM role_versions WHERE role = ? ORDER BY created_at",
            (role,),
        ).fetchall()
        if not any(str(row["id"]) == version_id for row in rows):
            return False
        current = self.current_baseline_unlocked(role, rows)
        if current != expected_current:
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
        return True

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

    def save_rejected_payload(self, *, role: str, build_payload: Callable[[Any | None], str]) -> None:
        begin_write(self._conn)
        try:
            self._conn.execute(
                "INSERT INTO rejected_proposals (role, proposals_json) VALUES (?, ?) "
                "ON CONFLICT(role) DO NOTHING",
                (role, "[]"),
            )
            row = execute_for_update(
                self._conn,
                "SELECT proposals_json FROM rejected_proposals WHERE role = ?",
                (role,),
            ).fetchone()
            proposals_json = build_payload(row["proposals_json"] if row is not None else None)
            self._conn.execute(
                "UPDATE rejected_proposals SET proposals_json = ? WHERE role = ?",
                (proposals_json, role),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def load_rejected_payload(self, role: str) -> Any | None:
        row = self._conn.execute(
            "SELECT proposals_json FROM rejected_proposals WHERE role = ?",
            (role,),
        ).fetchone()
        self._conn.commit()
        return row["proposals_json"] if row is not None else None

    def current_baseline_unlocked(self, role: str, rows: list[Any]) -> str | None:
        row = self._conn.execute(
            "SELECT version_id FROM role_current_baseline WHERE role = ?",
            (role,),
        ).fetchone()
        if row is not None:
            return str(row["version_id"])
        baseline_row = next((item for item in rows if item["status"] == "baseline"), None)
        return str(baseline_row["id"]) if baseline_row is not None else None


def _loads_json(value: Any, *, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _loads_json_object(value: Any, *, default: dict[str, Any]) -> dict[str, Any]:
    data = _loads_json(value, default=default)
    if not isinstance(data, dict):
        return dict(default)
    return {str(key): item for key, item in data.items()}


_RELEASE_STAGE_ORDER = {"active": 0, "shadow": 1, "canary": 2, "baseline": 3, "promoted": 3}

_RELEASE_STAGE_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"active", "shadow", "canary", "baseline"},
    "active": {"shadow", "canary", "baseline", "rejected"},
    "shadow": {"canary", "baseline", "rejected", "active"},
    "canary": {"baseline", "rejected", "active", "shadow"},
    "baseline": set(),  # terminal — only manual rollback can leave
    "promoted": set(),
    "rejected": {"active", "draft"},
}


def validate_release_stage_transition(current: str, target: str) -> None:
    """Raise ValueError if the transition is not allowed."""
    current_norm = str(current or "draft").strip().lower()
    target_norm = str(target or "active").strip().lower()
    allowed = _RELEASE_STAGE_TRANSITIONS.get(current_norm, {"active"})
    if target_norm not in allowed:
        raise ValueError(
            f"invalid release stage transition: {current_norm} → {target_norm} "
            f"(allowed: {', '.join(sorted(allowed)) or 'none'})"
        )


def _should_update_existing_release_status(current_status: str, next_status: str) -> bool:
    current = str(current_status or "active").strip().lower()
    target = str(next_status or "active").strip().lower()
    if current in {"baseline", "promoted", "rejected"}:
        return False
    return _RELEASE_STAGE_ORDER.get(target, 0) > _RELEASE_STAGE_ORDER.get(current, 0)


__all__ = ["RegistryVersionRepository"]
