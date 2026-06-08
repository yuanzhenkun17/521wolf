"""Version store backed by the registry storage database."""

from __future__ import annotations

import json
import logging

from storage.shared.database import StorageConnection, begin_write, execute_for_update
from storage.interfaces import (
    RoleHistoryData,
    RoleVersionData,
    storage_timestamp,
    compute_hash,
    normalize_skill_path,
    normalize_skill_text,
    TimestampProvider,
)

_log = logging.getLogger(__name__)


class HashCollisionError(Exception):
    """Raised when two different skill sets produce the same hash."""


class VersionStoreDB:
    def __init__(
        self,
        conn: StorageConnection,
        timestamp_provider: TimestampProvider | None = None,
    ) -> None:
        self._conn = conn
        self._timestamp = timestamp_provider or storage_timestamp

    def save_version(
        self,
        role: str,
        skills: dict[str, str],
        parent_hash: str | None,
        source: str,
        source_run_id: str | None = None,
        notes: list[str] | None = None,
    ) -> str:
        version_hash = compute_hash(skills)
        now = self._timestamp()

        existing = self.load_version(version_hash)
        if existing is not None:
            existing_normalized = {
                normalize_skill_path(path): normalize_skill_text(text)
                for path, text in existing.skills.items()
            }
            new_normalized = {
                normalize_skill_path(path): normalize_skill_text(text)
                for path, text in skills.items()
            }
            if existing_normalized != new_normalized:
                raise HashCollisionError(
                    f"Hash collision for {version_hash} in role {role}: "
                    "existing content differs from new content"
                )
            _log.debug("save_version: idempotent hit for %s/%s", role, version_hash)
            return version_hash

        self._conn.execute(
            "INSERT INTO role_versions (id, role, parent_id, source, run_id, skills, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                version_hash,
                role,
                parent_hash,
                source,
                source_run_id,
                json.dumps(skills, ensure_ascii=False),
                json.dumps(notes or [], ensure_ascii=False),
                now,
            ),
        )

        self._conn.commit()
        _log.info("save_version: saved %s/%s (source=%s)", role, version_hash, source)
        return version_hash

    def load_version(self, hash: str) -> RoleVersionData | None:
        row = self._conn.execute(
            "SELECT * FROM role_versions WHERE id = ?", (hash,)
        ).fetchone()
        if row is None:
            return None
        return RoleVersionData(
            hash=row["id"],
            role=row["role"],
            skills=json.loads(row["skills"]),
            created_at=row["created_at"],
            source=row["source"],
            parent_hash=row["parent_id"],
            source_run_id=row["run_id"],
            notes=json.loads(row["notes"]) if row["notes"] else [],
        )

    def list_versions(self, role: str) -> list[RoleVersionData]:
        history = self.get_history(role)
        versions: list[RoleVersionData] = []
        for version_hash in history.versions:
            version = self.load_version(version_hash)
            if version is not None:
                versions.append(version)
        return versions

    def get_baseline(self, role: str) -> RoleVersionData:
        history = self.get_history(role)
        version = self.load_version(history.baseline)
        if version is None:
            raise FileNotFoundError(
                f"Baseline version {history.baseline} not found for role {role}"
            )
        return version

    def set_baseline(self, role: str, target_hash: str, expected_current: str) -> bool:
        begin_write(self._conn)
        try:
            rows = execute_for_update(
                self._conn,
                "SELECT id, status FROM role_versions WHERE role = ? ORDER BY created_at",
                (role,),
            ).fetchall()
            if not rows:
                raise FileNotFoundError(f"No history for role {role}")

            baseline_row = next((row for row in rows if row["status"] == "baseline"), None)
            current = baseline_row["id"] if baseline_row else rows[0]["id"]
            if current != expected_current:
                _log.warning(
                    "set_baseline: CAS mismatch for %s: expected=%s actual=%s",
                    role,
                    expected_current,
                    current,
                )
                self._conn.rollback()
                return False

            if not any(row["id"] == target_hash for row in rows):
                _log.warning("set_baseline: target hash %s not found for %s", target_hash, role)
                self._conn.rollback()
                return False

            self._conn.execute(
                "UPDATE role_versions SET status = 'archived' "
                "WHERE role = ? AND status = 'baseline' AND id <> ?",
                (role, target_hash),
            )
            self._conn.execute(
                "UPDATE role_versions SET status = 'baseline' WHERE role = ? AND id = ?",
                (role, target_hash),
            )
            self._conn.commit()
            _log.info("set_baseline: %s -> %s", role, target_hash)
            return True
        except Exception:
            self._conn.rollback()
            raise

    def get_history(self, role: str) -> RoleHistoryData:
        rows = self._conn.execute(
            "SELECT id FROM role_versions WHERE role = ? ORDER BY created_at",
            (role,),
        ).fetchall()
        if not rows:
            raise FileNotFoundError(f"No history for role {role}")

        versions = [row["id"] for row in rows]
        baseline_row = self._conn.execute(
            "SELECT id FROM role_versions WHERE role = ? AND status = 'baseline' LIMIT 1",
            (role,),
        ).fetchone()
        baseline = baseline_row["id"] if baseline_row else versions[0]

        return RoleHistoryData(role=role, baseline=baseline, versions=versions)

    def list_roles(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT DISTINCT role FROM role_versions ORDER BY role"
        ).fetchall()
        return [row["role"] for row in rows]

    def list_histories(self) -> list[RoleHistoryData]:
        result: list[RoleHistoryData] = []
        for role in self.list_roles():
            try:
                result.append(self.get_history(role))
            except FileNotFoundError:
                _log.warning("list_histories: missing history for %s", role)
        return result
