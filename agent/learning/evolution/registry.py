"""SQLite-backed version registry.

Evolution system writes (publish, set_baseline, reject).
Battle system reads (get_baseline, get_package, list_versions).
The registry is the only bridge between the two systems.

Backward-compatible: ``VersionRegistry(registry_root)`` stores data in
``<registry_root>/registry.db``.  Also accepts a ``sqlite3.Connection``
directly for tests (including ``":memory:"``).
"""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import logging
import shutil
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from agent.common import beijing_now_iso
from agent.learning.evolution.models import (
    KnowledgePackage, KnowledgeDiff, VersionSummary,
    SkillFileRef, ProvenanceRecord, BattleMetrics,
)
from storage.interfaces import normalize_skill_text, normalize_skill_path

_log = logging.getLogger(__name__)


class VersionRegistry:
    """
    SQLite-backed registry for role skill versions.

    Stores all version data (packages, skill files, baselines, history)
    in a single ``registry.db`` database.  For backward compatibility the
    constructor accepts either a filesystem *directory* path (a ``registry.db``
    file is created inside it) or an already-open ``sqlite3.Connection``.
    """

    def __init__(
        self,
        registry_root: Path | str | sqlite3.Connection,
    ) -> None:
        if isinstance(registry_root, sqlite3.Connection):
            self._conn = registry_root
        else:
            root = Path(registry_root)
            if str(root) == ":memory:":
                from storage.registry.connection import get_registry_connection
                self._conn = get_registry_connection(root)
            else:
                db_path = root / "registry.db"
                from storage.registry.connection import get_registry_connection
                self._conn = get_registry_connection(db_path)
        self._locks: dict[str, asyncio.Lock] = {}
        self._owns_connection = not isinstance(registry_root, sqlite3.Connection)

    def close(self) -> None:
        """Close the underlying database connection (if owned by this instance)."""
        if self._owns_connection:
            try:
                self._conn.commit()
                self._conn.close()
            except Exception:
                pass

    def __enter__(self) -> VersionRegistry:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    #  Name validation                                                    #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate_name(name: str, label: str) -> None:
        """Reject path traversal in role/version_id names."""
        if not name or not name.strip():
            raise ValueError(f"Empty {label}")
        if "/" in name or "\\" in name or ".." in name or "\0" in name:
            raise ValueError(f"Unsafe {label}: {name}")
        if ":" in name:
            raise ValueError(f"Unsafe {label}: {name}")

    # ------------------------------------------------------------------ #
    #  Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _next_version_id(self, role: str) -> str:
        """Generate sequential version ID like werewolf_v1, seer_v2."""
        versions = self.list_versions(role)
        max_n = 0
        for v in versions:
            parts = v.version_id.rsplit("_v", 1)
            if len(parts) == 2 and parts[1].isdigit():
                max_n = max(max_n, int(parts[1]))
        return f"{role}_v{max_n + 1}"

    def _lock_for(self, role: str) -> asyncio.Lock:
        if role not in self._locks:
            self._locks[role] = asyncio.Lock()
        return self._locks[role]

    def _read_baseline(self, role: str) -> str | None:
        """Read current baseline version_id for a role, or None."""
        row = self._conn.execute(
            "SELECT version_id FROM role_current_baseline WHERE role = ?",
            (role,),
        ).fetchone()
        return row["version_id"] if row else None

    def _version_exists(self, version_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM role_versions WHERE id = ?", (version_id,),
        ).fetchone()
        return row is not None

    def _compute_skill_content_hash(self, content: str) -> str:
        """SHA-256 of normalized skill content, first 12 hex chars."""
        normalized = normalize_skill_text(content)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _extract_battle_delta(battle_result: dict, role: str) -> dict[str, float | int]:
        """Extract role-specific battle deltas for rejected-proposal learning."""
        base = battle_result.get("baseline_metrics", {})
        cand = battle_result.get("candidate_metrics", {})
        role_base = base.get(role, {})
        role_cand = cand.get(role, {})
        return {
            "role_score_delta": round(
                (role_cand.get("role_weighted_score", 0) or 0)
                - (role_base.get("role_weighted_score", 0) or 0),
                3,
            ),
            "win_rate_delta": round(
                (role_cand.get("win_rate", 0) or 0)
                - (role_base.get("win_rate", 0) or 0),
                3,
            ),
            "games": battle_result.get("games_played", 0),
        }

    # ------------------------------------------------------------------ #
    #  Write operations (evolution system)                                #
    # ------------------------------------------------------------------ #

    async def publish(
        self,
        package: KnowledgePackage,
        skill_contents: dict[str, str],
        *,
        version_id: str | None = None,
    ) -> str:
        """
        Publish a new version.

        1. Normalize and hash skill contents
        2. Check for existing version (idempotency)
        3. Insert version row and skill file rows
        4. Append 'created' event to history
        Returns version_id.
        """
        role = package.role
        self._validate_name(role, "role")
        version_id = version_id or self._next_version_id(role)
        self._validate_name(version_id, "version_id")

        async with self._lock_for(role):
            # Normalize skills
            normalized_skills: dict[str, str] = {}
            for rel_path, content in skill_contents.items():
                np = normalize_skill_path(rel_path)
                if np in normalized_skills:
                    raise ValueError(f"Duplicate normalized skill path: {np}")
                normalized_skills[np] = normalize_skill_text(content)

            actual_refs = [
                SkillFileRef(
                    path=rel_path,
                    content_hash=self._compute_skill_content_hash(content),
                )
                for rel_path, content in sorted(normalized_skills.items())
            ]
            package = KnowledgePackage(
                version_id=version_id,
                role=package.role,
                parent_id=package.parent_id,
                skills=actual_refs,
                patterns=package.patterns,
                provenance=package.provenance,
                metrics=package.metrics,
                created_at=package.created_at,
            )

            # Idempotency check
            row = self._conn.execute(
                "SELECT * FROM role_versions WHERE id = ? AND role = ?",
                (version_id, role),
            ).fetchone()
            if row is not None:
                existing_pkg = KnowledgePackage.from_dict({
                    "version_id": row["id"],
                    "role": row["role"],
                    "parent_id": row["parent_id"],
                    "skills": json.loads(row["skills"]),
                    "patterns": json.loads(row["patterns_json"]) if row["patterns_json"] else [],
                    "provenance": json.loads(row["provenance_json"]) if row["provenance_json"] else {},
                    "metrics": json.loads(row["metrics_json"]) if row["metrics_json"] else None,
                    "created_at": row["created_at"],
                })
                if existing_pkg.to_dict() != package.to_dict():
                    raise ValueError(
                        f"Version {role}/{version_id} already exists with different metadata"
                    )
                existing_file_rows = self._conn.execute(
                    "SELECT file_path, content FROM skill_files WHERE version_id = ?",
                    (version_id,),
                ).fetchall()
                existing_map = {r["file_path"]: r["content"] for r in existing_file_rows}
                for rel_path, normalized_content in normalized_skills.items():
                    if rel_path not in existing_map:
                        raise ValueError(
                            f"Version {role}/{version_id} is missing skill file {rel_path}"
                        )
                    if normalize_skill_text(existing_map[rel_path]) != normalized_content:
                        raise ValueError(
                            f"Version {role}/{version_id} already exists with different skill content"
                        )
                return version_id

            # Insert new version
            now = beijing_now_iso()
            self._conn.execute(
                """INSERT INTO role_versions
                   (id, role, parent_id, source, run_id, skills, notes, status,
                    created_at, patterns_json, metrics_json, provenance_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
                (
                    version_id,
                    role,
                    package.parent_id,
                    package.provenance.source,
                    package.provenance.run_id,
                    json.dumps([s.to_dict() for s in package.skills], ensure_ascii=False),
                    json.dumps([], ensure_ascii=False),
                    now,
                    json.dumps(package.patterns, ensure_ascii=False),
                    json.dumps(package.metrics.to_dict(), ensure_ascii=False) if package.metrics else None,
                    json.dumps(package.provenance.to_dict(), ensure_ascii=False),
                ),
            )

            # Insert skill files
            for rel_path, normalized_content in normalized_skills.items():
                self._conn.execute(
                    """INSERT INTO skill_files
                       (version_id, file_path, content_hash, content, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        version_id,
                        rel_path,
                        self._compute_skill_content_hash(normalized_content),
                        normalized_content,
                        now,
                    ),
                )

            # History event
            self._conn.execute(
                """INSERT INTO role_baseline_history
                   (role, version_id, reason, created_at)
                   VALUES (?, ?, ?, ?)""",
                (role, version_id, "created", now),
            )

            _log.info(
                "publish: %s/%s (source=%s)",
                role, version_id, package.provenance.source,
            )
            self._conn.commit()
            return version_id

    async def publish_skills(
        self,
        role: str,
        skill_contents: dict[str, str],
        *,
        parent_id: str | None = None,
        source: str,
        run_id: str | None = None,
        proposal_ids: list[str] | None = None,
        version_id: str | None = None,
        set_as_baseline: bool = False,
        expected_current: str | None = None,
    ) -> str:
        """Publish a skill snapshot and optionally CAS it to baseline."""
        vid = version_id or self._next_version_id(role)
        normalized_skills: dict[str, str] = {}
        for rel_path, content in skill_contents.items():
            np = normalize_skill_path(rel_path)
            if np in normalized_skills:
                raise ValueError(f"Duplicate normalized skill path: {np}")
            normalized_skills[np] = normalize_skill_text(content)

        try:
            existing_skills = {
                normalize_skill_path(path): normalize_skill_text(content)
                for path, content in self.read_skill_contents(role, vid).items()
            }
        except FileNotFoundError:
            existing_skills = None

        if existing_skills is None:
            package = KnowledgePackage(
                version_id=vid,
                role=role,
                parent_id=parent_id,
                skills=[],
                patterns=[],
                provenance=ProvenanceRecord(
                    source=source,
                    run_id=run_id,
                    proposal_ids=proposal_ids or [],
                ),
                metrics=None,
                created_at=beijing_now_iso(),
            )
            await self.publish(package, skill_contents)
        elif existing_skills != normalized_skills:
            raise ValueError(f"Version {role}/{vid} already exists with different skill content")

        if set_as_baseline:
            current = self.get_baseline(role)
            if current != vid:
                ok = await self.set_baseline(
                    role=role,
                    version_id=vid,
                    expected_current=expected_current,
                )
                if not ok:
                    raise RuntimeError(
                        f"Failed to set baseline for {role}: expected {expected_current}"
                    )
        return vid

    async def ensure_default_baselines(self) -> None:
        """Create explicit empty baselines for every engine role."""
        from engine.models import Role

        empty_skills: dict[str, str] = {}
        for role in Role:
            role_name = role.value
            if self.get_baseline(role_name) is not None:
                continue
            await self.publish_skills(
                role_name,
                empty_skills,
                source="bootstrap_empty",
                set_as_baseline=True,
                expected_current=None,
            )

    async def initialize_from_skills(self, skills_root: Path) -> None:
        """DEPRECATED: Initialize role baselines from skill directories.

        This method is a no-op. Use ensure_default_baselines() for empty
        baselines, or seed_skills.py / bootstrap_registry.py for content.
        """
        import warnings
        warnings.warn(
            "initialize_from_skills() is deprecated and does nothing. "
            "Use ensure_default_baselines() for empty baselines, or "
            "scripts/bootstrap_registry.py for seeded content.",
            DeprecationWarning,
            stacklevel=2,
        )
        _log.warning(
            "initialize_from_skills() is deprecated and is now a no-op. "
            "Use ensure_default_baselines() or scripts/bootstrap_registry.py instead."
        )

    async def set_baseline(
        self,
        role: str,
        version_id: str,
        expected_current: str | None,
    ) -> bool:
        """CAS: set baseline if current matches expected_current.

        Returns True if the baseline was updated, False on mismatch.
        """
        self._validate_name(role, "role")
        self._validate_name(version_id, "version_id")

        async with self._lock_for(role):
            current = self._read_baseline(role)
            if current != expected_current:
                _log.warning(
                    "set_baseline: CAS mismatch for %s: expected=%s actual=%s",
                    role, expected_current, current,
                )
                return False

            # Verify the target version exists
            if not self._version_exists(version_id):
                _log.warning(
                    "set_baseline: version %s not found for %s",
                    version_id, role,
                )
                return False

            now = beijing_now_iso()
            self._conn.execute(
                """INSERT OR REPLACE INTO role_current_baseline
                   (role, version_id, updated_at) VALUES (?, ?, ?)""",
                (role, version_id, now),
            )

            self._conn.execute(
                """INSERT INTO role_baseline_history
                   (role, version_id, previous_version_id, reason, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (role, version_id, expected_current, "baseline_set", now),
            )
            self._conn.execute(
                "UPDATE role_versions SET status = 'promoted' WHERE id = ? AND role = ?",
                (version_id, role),
            )

            _log.info("set_baseline: %s -> %s", role, version_id)
            self._conn.commit()
            return True

    async def reject(
        self,
        role: str,
        version_id: str,
        reason: str,
    ) -> None:
        """Append 'rejected' event to history."""
        self._validate_name(role, "role")
        self._validate_name(version_id, "version_id")

        async with self._lock_for(role):
            now = beijing_now_iso()
            self._conn.execute(
                """INSERT INTO role_baseline_history
                   (role, version_id, reason, created_at)
                   VALUES (?, ?, ?, ?)""",
                (role, version_id, f"rejected: {reason}", now),
            )
            self._conn.execute(
                "UPDATE role_versions SET status = 'rejected' WHERE id = ? AND role = ?",
                (version_id, role),
            )
            _log.info("reject: %s/%s reason=%s", role, version_id, reason)
            self._conn.commit()

    async def save_rejected(
        self,
        role: str,
        proposals: list[dict],
        battle_result: dict | None,
    ) -> None:
        """Persist rejected proposals for future consolidation."""
        self._validate_name(role, "role")
        async with self._lock_for(role):
            row = self._conn.execute(
                "SELECT proposals_json FROM rejected_proposals WHERE role = ?",
                (role,),
            ).fetchone()
            existing: list[dict] = json.loads(row["proposals_json"]) if row else []

            metrics = self._extract_battle_delta(battle_result, role) if battle_result else {}
            for proposal in proposals:
                existing.append({
                    "target_file": proposal.get("target_file", ""),
                    "action_type": proposal.get("action_type", ""),
                    "content": proposal.get("content", ""),
                    "rationale": proposal.get("rationale", ""),
                    "confidence": proposal.get("confidence", 0.0),
                    "metrics_delta": metrics,
                    "rejected_at": beijing_now_iso(),
                })

            kept = existing[-10:]
            self._conn.execute(
                """INSERT OR REPLACE INTO rejected_proposals
                   (role, proposals_json) VALUES (?, ?)""",
                (role, json.dumps(kept, ensure_ascii=False)),
            )
            self._conn.commit()

    async def load_rejected(self, role: str) -> list[dict]:
        """Load rejected proposals for a role."""
        self._validate_name(role, "role")
        row = self._conn.execute(
            "SELECT proposals_json FROM rejected_proposals WHERE role = ?",
            (role,),
        ).fetchone()
        if not row:
            return []
        return json.loads(row["proposals_json"])

    # ------------------------------------------------------------------ #
    #  Read operations (battle system)                                    #
    # ------------------------------------------------------------------ #

    def get_baseline(self, role: str) -> str | None:
        """Get current baseline version_id for a role. None if no baseline."""
        self._validate_name(role, "role")
        return self._read_baseline(role)

    def get_package(self, role: str, version_id: str) -> KnowledgePackage:
        """Load a KnowledgePackage from the registry database."""
        self._validate_name(role, "role")
        self._validate_name(version_id, "version_id")

        row = self._conn.execute(
            "SELECT * FROM role_versions WHERE id = ? AND role = ?",
            (version_id, role),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(
                f"Package {role}/{version_id} not found in registry"
            )
        return KnowledgePackage.from_dict({
            "version_id": row["id"],
            "role": row["role"],
            "parent_id": row["parent_id"],
            "skills": json.loads(row["skills"]),
            "patterns": json.loads(row["patterns_json"]) if row["patterns_json"] else [],
            "provenance": json.loads(row["provenance_json"]) if row["provenance_json"] else {},
            "metrics": json.loads(row["metrics_json"]) if row["metrics_json"] else None,
            "created_at": row["created_at"],
        })

    def get_skill_dir(self, role: str, version_id: str) -> Path:
        """Return a directory path containing skill files for a role version.

        Creates a temporary directory populated from the database.  The
        caller (or test teardown) is responsible for cleanup.
        """
        self._validate_name(role, "role")
        self._validate_name(version_id, "version_id")

        # Ensure version exists and get package to check skill refs
        row = self._conn.execute(
            "SELECT id, skills FROM role_versions WHERE id = ? AND role = ?",
            (version_id, role),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(
                f"Version {role}/{version_id} not found in registry"
            )

        skill_rows = self._conn.execute(
            "SELECT file_path, content FROM skill_files WHERE version_id = ?",
            (version_id,),
        ).fetchall()

        # Detect corruption: package declares skill refs but none stored
        declared_skills = json.loads(row["skills"]) if row["skills"] else []
        if declared_skills and not skill_rows:
            raise FileNotFoundError(
                f"Skill files for {role}/{version_id} not found in registry "
                f"(package declares {len(declared_skills)} skill refs but no files stored)"
            )

        tmp = Path(tempfile.mkdtemp(prefix=f"wolf_skill_{role}_{version_id}_"))
        skills_dir = tmp / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)

        for sr in skill_rows:
            file_path = skills_dir / sr["file_path"]
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(sr["content"], encoding="utf-8")

        return skills_dir

    def read_skill_contents(self, role: str, version_id: str) -> dict[str, str]:
        """Read skill file contents for a role version."""
        self._validate_name(role, "role")
        self._validate_name(version_id, "version_id")

        # Verify version exists
        row = self._conn.execute(
            "SELECT id FROM role_versions WHERE id = ? AND role = ?",
            (version_id, role),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(
                f"Version {role}/{version_id} not found in registry"
            )

        skill_rows = self._conn.execute(
            "SELECT file_path, content FROM skill_files WHERE version_id = ?",
            (version_id,),
        ).fetchall()

        return {r["file_path"]: r["content"] for r in skill_rows}

    def list_versions(self, role: str) -> list[VersionSummary]:
        """List all versions for a role.

        Returns only active versions, in chronological order.
        """
        self._validate_name(role, "role")

        rows = self._conn.execute(
            """SELECT id, role, source, created_at
               FROM role_versions
               WHERE role = ?
               ORDER BY created_at""",
            (role,),
        ).fetchall()
        if not rows:
            return []

        current_baseline = self._read_baseline(role)

        return [
            VersionSummary(
                version_id=row["id"],
                role=row["role"],
                source=row["source"],
                created_at=row["created_at"],
                is_baseline=(row["id"] == current_baseline),
            )
            for row in rows
        ]

    def list_roles(self) -> list[str]:
        """List all roles that have entries in the registry."""
        rows = self._conn.execute(
            "SELECT DISTINCT role FROM role_versions ORDER BY role"
        ).fetchall()
        return [row["role"] for row in rows]

    # ------------------------------------------------------------------ #
    #  Diff                                                               #
    # ------------------------------------------------------------------ #

    def diff(
        self,
        role: str,
        old_id: str,
        new_id: str,
    ) -> KnowledgeDiff:
        """Compute structured diff between two versions."""
        self._validate_name(role, "role")
        self._validate_name(old_id, "version_id")
        self._validate_name(new_id, "version_id")

        old_pkg = self.get_package(role, old_id)
        new_pkg = self.get_package(role, new_id)

        # --- Skill file diffs ---
        skill_changes = self._diff_skills(role, old_pkg, new_pkg)

        # --- Pattern set diffs ---
        patterns_added, patterns_removed, patterns_updated = self._diff_patterns(
            old_pkg.patterns, new_pkg.patterns,
        )

        # --- Metrics delta ---
        metrics_delta = self._diff_metrics(old_pkg.metrics, new_pkg.metrics)

        return KnowledgeDiff(
            skill_changes=skill_changes,
            patterns_added=patterns_added,
            patterns_removed=patterns_removed,
            patterns_updated=patterns_updated,
            metrics_delta=metrics_delta,
        )

    # ------------------------------------------------------------------ #
    #  GC                                                                 #
    # ------------------------------------------------------------------ #

    def gc(self, role: str, keep: int = 10) -> int:
        """Garbage collect old versions.

        Keep: current baseline + its ancestor chain + last ``keep`` versions.
        Returns number of versions removed.  Deleted versions have their
        status set to 'gc' and skill_files rows removed.
        """
        self._validate_name(role, "role")

        versions = self.list_versions(role)
        if len(versions) <= keep:
            return 0

        # Determine the set of version_ids to keep
        keep_ids: set[str] = set()

        # 1. Always keep the current baseline and its ancestor chain
        baseline_id = self._read_baseline(role)
        if baseline_id:
            self._trace_ancestors(role, baseline_id, keep_ids)

        # 2. Keep the most recent ``keep`` versions
        for vs in versions[-keep:]:
            keep_ids.add(vs.version_id)

        # 3. Remove everything else
        removed = 0
        for vs in versions:
            if vs.version_id not in keep_ids:
                self._conn.execute(
                    "UPDATE role_versions SET status = 'gc' WHERE id = ?",
                    (vs.version_id,),
                )
                self._conn.execute(
                    "DELETE FROM skill_files WHERE version_id = ?",
                    (vs.version_id,),
                )
                removed += 1
                _log.debug("gc: removed %s/%s", role, vs.version_id)

        if removed:
            now = beijing_now_iso()
            self._conn.execute(
                """INSERT INTO role_baseline_history
                   (role, version_id, reason, created_at)
                   VALUES (?, ?, ?, ?)""",
                (role, "", f"gc: removed {removed}, kept {len(keep_ids)}", now),
            )
            _log.info("gc: %s removed %d versions, kept %d", role, removed, len(keep_ids))
            self._conn.commit()

        return removed

    # ------------------------------------------------------------------ #
    #  Skill directory building                                           #
    # ------------------------------------------------------------------ #

    def build_skill_dir(self, role_versions: dict[str, str]) -> Path:
        """Build a composite skill directory for engine consumption.

        Creates a temp directory with each role's skills copied into
        ``<role>/`` subdirs.  Caller is responsible for cleanup.

        Args:
            role_versions: mapping of role -> version_id.
        """
        tmp = Path(tempfile.mkdtemp(prefix="wolf_skills_"))

        for role, version_id in role_versions.items():
            self._validate_name(role, "role")
            self._validate_name(version_id, "version_id")

            src_skills = self.get_skill_dir(role, version_id)
            dst_role = tmp / role

            shutil.copytree(str(src_skills), str(dst_role))

        return tmp

    # ------------------------------------------------------------------ #
    #  Diff helpers                                                       #
    # ------------------------------------------------------------------ #

    def _diff_skills(
        self,
        role: str,
        old_pkg: KnowledgePackage,
        new_pkg: KnowledgePackage,
    ) -> list[dict[str, Any]]:
        """Compute per-file diffs between two packages' skill sets."""
        old_map: dict[str, SkillFileRef] = {s.path: s for s in old_pkg.skills}
        new_map: dict[str, SkillFileRef] = {s.path: s for s in new_pkg.skills}

        all_paths = sorted(set(old_map.keys()) | set(new_map.keys()))
        changes: list[dict[str, Any]] = []

        for path in all_paths:
            old_ref = old_map.get(path)
            new_ref = new_map.get(path)

            if old_ref and not new_ref:
                before_text = self._read_skill_file_from_db(role, old_pkg.version_id, path)
                changes.append({
                    "file": path,
                    "action": "removed",
                    "before_lines": before_text.splitlines(),
                    "after_lines": [],
                })
            elif new_ref and not old_ref:
                after_text = self._read_skill_file_from_db(role, new_pkg.version_id, path)
                changes.append({
                    "file": path,
                    "action": "added",
                    "before_lines": [],
                    "after_lines": after_text.splitlines(),
                })
            elif old_ref and new_ref and old_ref.content_hash != new_ref.content_hash:
                before_text = self._read_skill_file_from_db(role, old_pkg.version_id, path)
                after_text = self._read_skill_file_from_db(role, new_pkg.version_id, path)
                diff_lines = list(difflib.unified_diff(
                    before_text.splitlines(),
                    after_text.splitlines(),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                    lineterm="",
                ))
                changes.append({
                    "file": path,
                    "action": "modified",
                    "before_lines": before_text.splitlines(),
                    "after_lines": after_text.splitlines(),
                    "diff": diff_lines,
                })

        return changes

    def _read_skill_file_from_db(self, role: str, version_id: str, rel_path: str) -> str:
        """Read a single skill file from the registry database."""
        row = self._conn.execute(
            "SELECT content FROM skill_files WHERE version_id = ? AND file_path = ?",
            (version_id, rel_path),
        ).fetchone()
        return row["content"] if row else ""

    @staticmethod
    def _diff_patterns(
        old_patterns: list[dict[str, Any]],
        new_patterns: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Compute set-level diffs between two pattern lists.

        Returns (added, removed, updated) where each element is a list of
        pattern dicts.
        """
        old_by_id: dict[str, dict[str, Any]] = {
            p["pattern_id"]: p for p in old_patterns if "pattern_id" in p
        }
        new_by_id: dict[str, dict[str, Any]] = {
            p["pattern_id"]: p for p in new_patterns if "pattern_id" in p
        }

        old_ids = set(old_by_id.keys())
        new_ids = set(new_by_id.keys())

        added = [new_by_id[pid] for pid in sorted(new_ids - old_ids)]
        removed = [old_by_id[pid] for pid in sorted(old_ids - new_ids)]

        updated: list[dict[str, Any]] = []
        for pid in sorted(old_ids & new_ids):
            if old_by_id[pid] != new_by_id[pid]:
                updated.append(new_by_id[pid])

        return added, removed, updated

    @staticmethod
    def _diff_metrics(
        old_metrics: BattleMetrics | None,
        new_metrics: BattleMetrics | None,
    ) -> dict[str, float] | None:
        """Compute numeric deltas between two BattleMetrics snapshots."""
        if old_metrics is None and new_metrics is None:
            return None
        old = old_metrics or BattleMetrics()
        new = new_metrics or BattleMetrics()
        delta: dict[str, float] = {}
        for field_name in ("win_rate", "score", "speech_score", "vote_score", "skill_score"):
            old_val = getattr(old, field_name, 0.0)
            new_val = getattr(new, field_name, 0.0)
            d = round(new_val - old_val, 4)
            if d != 0.0:
                delta[field_name] = d
        games_delta = new.games_played - old.games_played
        if games_delta != 0:
            delta["games_played"] = float(games_delta)
        return delta if delta else None

    def _trace_ancestors(self, role: str, version_id: str, result: set[str]) -> None:
        """Walk the parent_id chain from version_id, adding each to result."""
        visited: set[str] = set()
        current = version_id
        while current and current not in visited:
            visited.add(current)
            result.add(current)
            row = self._conn.execute(
                "SELECT parent_id FROM role_versions WHERE id = ?",
                (current,),
            ).fetchone()
            if not row:
                break
            current = row["parent_id"] or ""
