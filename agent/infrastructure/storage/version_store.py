"""Version store backed by SQLite — mirrors the file-based VersionStore interface."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from agent.common import beijing_now_iso
from agent.learning.evolution.models import RoleHistory, RoleVersion
from agent.learning.evolution.store import compute_hash

from agent.infrastructure.storage.schema import get_connection

_log = logging.getLogger(__name__)


class HashCollisionError(Exception):
    """Raised when two different skill sets produce the same hash."""


class VersionStoreDB:
    """SQLite-backed version store. Drop-in alternative to the file-based VersionStore."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save_version(
        self,
        role: str,
        skills: dict[str, str],
        parent_hash: str | None,
        source: str,
        source_run_id: str | None = None,
        notes: list[str] | None = None,
    ) -> str:
        """Save a new version, returning its hash. Idempotent."""
        from agent.learning.evolution.store import normalize_skill_path, normalize_skill_text

        h = compute_hash(skills)
        now = beijing_now_iso()

        # Check idempotency
        existing = self.load_version(h)
        if existing is not None:
            existing_normalized = {
                normalize_skill_path(k): normalize_skill_text(v)
                for k, v in existing.skills.items()
            }
            new_normalized = {
                normalize_skill_path(k): normalize_skill_text(v)
                for k, v in skills.items()
            }
            if existing_normalized != new_normalized:
                raise HashCollisionError(
                    f"Hash collision for {h} in role {role}: "
                    f"existing content differs from new content"
                )
            _log.debug("save_version: idempotent hit for %s/%s", role, h)
            return h

        self._conn.execute(
            "INSERT INTO role_versions (id, role, parent_id, source, run_id, skills, notes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                h,
                role,
                parent_hash,
                source,
                source_run_id,
                json.dumps(skills, ensure_ascii=False),
                json.dumps(notes or [], ensure_ascii=False),
                now,
            ),
        )

        # Ensure history has this hash
        self._ensure_history_has(role, h)
        self._conn.commit()
        _log.info("save_version: saved %s/%s (source=%s)", role, h, source)
        return h

    def load_version(self, hash: str) -> RoleVersion | None:
        """Load a version by hash. Returns None if not found."""
        row = self._conn.execute(
            "SELECT * FROM role_versions WHERE id = ?", (hash,)
        ).fetchone()
        if row is None:
            return None
        return RoleVersion(
            hash=row["id"],
            role=row["role"],
            skills=json.loads(row["skills"]),
            created_at=row["created_at"],
            source=row["source"],
            parent_hash=row["parent_id"],
            source_run_id=row["run_id"],
            notes=json.loads(row["notes"]) if row["notes"] else [],
        )

    def list_versions(self, role: str) -> list[RoleVersion]:
        """List all versions for a role, in creation order."""
        history = self.get_history(role)
        versions: list[RoleVersion] = []
        for h in history.versions:
            v = self.load_version(h)
            if v is not None:
                versions.append(v)
        return versions

    def get_baseline(self, role: str) -> RoleVersion:
        """Load the baseline version for a role."""
        history = self.get_history(role)
        v = self.load_version(history.baseline)
        if v is None:
            raise FileNotFoundError(
                f"Baseline version {history.baseline} not found for role {role}"
            )
        return v

    def set_baseline(
        self,
        role: str,
        target_hash: str,
        expected_current: str,
    ) -> bool:
        """Set baseline using compare-and-swap."""
        history = self.get_history(role)
        if history.baseline != expected_current:
            _log.warning(
                "set_baseline: CAS mismatch for %s: expected=%s actual=%s",
                role, expected_current, history.baseline,
            )
            return False

        v = self.load_version(target_hash)
        if v is None:
            _log.warning("set_baseline: target hash %s not found for %s", target_hash, role)
            return False

        self._conn.execute(
            "UPDATE role_versions SET status = 'archived' WHERE role = ? AND status = 'baseline'",
            (role,),
        )
        self._conn.execute(
            "UPDATE role_versions SET status = 'baseline' WHERE id = ?",
            (target_hash,),
        )

        # Update history baseline
        self._conn.execute(
            "UPDATE role_versions SET status = 'baseline' WHERE id = ?",
            (target_hash,),
        )
        # Store baseline marker via a simple approach: use the notes field
        # Actually, we need a separate mechanism. Let's use a metadata approach.
        # For now, store baseline in the history table concept.
        # We'll use a simple approach: update the role_versions table.
        self._conn.commit()
        _log.info("set_baseline: %s → %s", role, target_hash)
        return True

    def get_history(self, role: str) -> RoleHistory:
        """Get the version history for a role."""
        rows = self._conn.execute(
            "SELECT id FROM role_versions WHERE role = ? ORDER BY created_at",
            (role,),
        ).fetchall()
        if not rows:
            raise FileNotFoundError(f"No history for role {role}")

        versions = [r["id"] for r in rows]

        # Find baseline: first version or marked
        baseline_row = self._conn.execute(
            "SELECT id FROM role_versions WHERE role = ? AND status = 'baseline' LIMIT 1",
            (role,),
        ).fetchone()
        baseline = baseline_row["id"] if baseline_row else versions[0]

        return RoleHistory(role=role, baseline=baseline, versions=versions)

    def list_roles(self) -> list[str]:
        """List all roles that have stored versions."""
        rows = self._conn.execute(
            "SELECT DISTINCT role FROM role_versions ORDER BY role"
        ).fetchall()
        return [r["role"] for r in rows]

    def list_histories(self) -> list[RoleHistory]:
        """List all role histories."""
        result: list[RoleHistory] = []
        for role in self.list_roles():
            try:
                result.append(self.get_history(role))
            except FileNotFoundError:
                _log.warning("list_histories: missing history for %s", role)
        return result

    def _ensure_history_has(self, role: str, hash: str) -> None:
        """Ensure the hash is recorded for the role. No-op — rows are in the table."""
        # In the DB version, all versions for a role are inherently in history
        pass
