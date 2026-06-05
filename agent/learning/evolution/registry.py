"""Filesystem-based version registry.

Evolution system writes (publish, set_baseline, reject).
Battle system reads (get_baseline, get_package, list_versions).
The registry is the only bridge between the two systems.
"""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from agent.common import beijing_now_iso
from agent.common.json import write_json as _write_json, read_json as _read_json
from agent.learning.evolution.models import (
    KnowledgePackage, KnowledgeDiff, VersionSummary,
    SkillFileRef, ProvenanceRecord, BattleMetrics,
)
from storage.interfaces import compute_hash, normalize_skill_text, normalize_skill_path

_log = logging.getLogger(__name__)


class VersionRegistry:
    """
    On-disk layout:
        data/registry/
          <role>/
            baseline.json
            history.jsonl
            versions/
              <version_id>/
                package.json
                patterns.json
                metrics.json
                skills/
                  *.md
    """

    def __init__(self, registry_root: Path) -> None:
        self.root = registry_root
        self._locks: dict[str, asyncio.Lock] = {}

    # --- Name validation ---

    @staticmethod
    def _validate_name(name: str, label: str) -> None:
        """Reject path traversal in role/version_id names."""
        if not name or not name.strip():
            raise ValueError(f"Empty {label}")
        if "/" in name or "\\" in name or ".." in name or "\0" in name:
            raise ValueError(f"Unsafe {label}: {name}")
        if ":" in name:
            raise ValueError(f"Unsafe {label}: {name}")

    # --- Path helpers ---

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

    def _role_dir(self, role: str) -> Path:
        self._validate_name(role, "role")
        return self.root / role

    def _baseline_path(self, role: str) -> Path:
        return self._role_dir(role) / "baseline.json"

    def _history_path(self, role: str) -> Path:
        return self._role_dir(role) / "history.jsonl"

    def _version_dir(self, role: str, version_id: str) -> Path:
        self._validate_name(version_id, "version_id")
        return self._role_dir(role) / "versions" / version_id

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

        1. Create version directory
        2. Write skill .md files
        3. Write package.json, patterns.json, metrics.json
        4. Append 'created' event to history.jsonl
        Returns version_id.
        """
        role = package.role
        self._validate_name(role, "role")
        version_id = version_id or self._next_version_id(role)
        self._validate_name(version_id, "version_id")

        async with self._lock_for(role):
            vdir = self._version_dir(role, version_id)

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

            pkg_path = vdir / "package.json"
            if pkg_path.exists():
                existing = KnowledgePackage.from_dict(_read_json(pkg_path))
                if existing.to_dict() != package.to_dict():
                    raise ValueError(
                        f"Version {role}/{version_id} already exists with different metadata"
                    )
                existing_skills_dir = vdir / "skills"
                for rel_path, normalized_content in normalized_skills.items():
                    skill_file = existing_skills_dir / rel_path
                    if not skill_file.exists():
                        raise ValueError(
                            f"Version {role}/{version_id} is missing skill file {rel_path}"
                        )
                    if normalize_skill_text(skill_file.read_text(encoding="utf-8")) != normalized_content:
                        raise ValueError(
                            f"Version {role}/{version_id} already exists with different skill content"
                        )
                return version_id

            vdir.mkdir(parents=True, exist_ok=False)

            # Write skill .md files.  SkillFileRef entries are always generated
            # from these normalized files; caller-provided hashes are ignored.
            skills_dir = vdir / "skills"
            skills_dir.mkdir(parents=True, exist_ok=True)
            for rel_path, normalized_content in normalized_skills.items():
                skill_file = skills_dir / rel_path
                skill_file.parent.mkdir(parents=True, exist_ok=True)
                skill_file.write_text(normalized_content, encoding="utf-8")

            # Write package.json
            _write_json(vdir / "package.json", package.to_dict())

            # Write patterns.json (standalone copy for quick access)
            _write_json(vdir / "patterns.json", package.patterns)

            # Write metrics.json (standalone copy for quick access)
            if package.metrics is not None:
                _write_json(vdir / "metrics.json", package.metrics.to_dict())

            # Append 'created' event to history.jsonl
            self._append_history_event(role, {
                "event": "created",
                "version_id": version_id,
                "role": role,
                "source": package.provenance.source,
                "created_at": package.created_at,
            })

            _log.info(
                "publish: %s/%s (source=%s)",
                role, version_id, package.provenance.source,
            )
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
        """Initialize role baselines from ``skills/<role>/*.md`` directories."""
        if not skills_root.exists():
            _log.warning("initialize_from_skills: skills_root %s does not exist", skills_root)
            return

        for role_dir in sorted(p for p in skills_root.iterdir() if p.is_dir()):
            role = role_dir.name
            if self.get_baseline(role) is not None:
                _log.debug("initialize_from_skills: %s already has baseline, skipping", role)
                continue
            skills: dict[str, str] = {}
            for path in sorted(role_dir.rglob("*.md")):
                rel_path = path.relative_to(role_dir).as_posix()
                skills[rel_path] = path.read_text(encoding="utf-8")
            if not skills:
                _log.warning("initialize_from_skills: no .md files for role %s, skipping", role)
                continue
            await self.publish_skills(
                role,
                skills,
                source="initialize_from_skills",
                set_as_baseline=True,
                expected_current=None,
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
            pkg_path = self._version_dir(role, version_id) / "package.json"
            if not pkg_path.exists():
                _log.warning(
                    "set_baseline: version %s not found for %s",
                    version_id, role,
                )
                return False

            _write_json(self._baseline_path(role), {
                "version_id": version_id,
                "role": role,
                "updated_at": beijing_now_iso(),
            })

            self._append_history_event(role, {
                "event": "baseline_set",
                "version_id": version_id,
                "previous_baseline": expected_current,
                "updated_at": beijing_now_iso(),
            })

            _log.info("set_baseline: %s -> %s", role, version_id)
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
            self._append_history_event(role, {
                "event": "rejected",
                "version_id": version_id,
                "role": role,
                "reason": reason,
                "rejected_at": beijing_now_iso(),
            })
            _log.info("reject: %s/%s reason=%s", role, version_id, reason)

    async def save_rejected(
        self,
        role: str,
        proposals: list[dict],
        battle_result: dict | None,
    ) -> None:
        """Persist rejected proposals for future consolidation."""
        self._validate_name(role, "role")
        async with self._lock_for(role):
            rejected_path = self._role_dir(role) / "rejected.json"
            existing = _read_json(rejected_path) if rejected_path.exists() else []
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
            _write_json(rejected_path, existing[-10:])

    async def load_rejected(self, role: str) -> list[dict]:
        """Load rejected proposals for a role."""
        self._validate_name(role, "role")
        rejected_path = self._role_dir(role) / "rejected.json"
        if not rejected_path.exists():
            return []
        return _read_json(rejected_path)

    # ------------------------------------------------------------------ #
    #  Read operations (battle system)                                    #
    # ------------------------------------------------------------------ #

    def get_baseline(self, role: str) -> str | None:
        """Get current baseline version_id for a role. None if no baseline."""
        self._validate_name(role, "role")
        return self._read_baseline(role)

    def get_package(self, role: str, version_id: str) -> KnowledgePackage:
        """Load a KnowledgePackage from disk."""
        self._validate_name(role, "role")
        self._validate_name(version_id, "version_id")

        pkg_path = self._version_dir(role, version_id) / "package.json"
        if not pkg_path.exists():
            raise FileNotFoundError(
                f"Package {role}/{version_id} not found at {pkg_path}"
            )
        data = _read_json(pkg_path)
        return KnowledgePackage.from_dict(data)

    def get_skill_dir(self, role: str, version_id: str) -> Path:
        """Return the skill directory for a role version."""
        self.get_package(role, version_id)
        skills_dir = self._version_dir(role, version_id) / "skills"
        if not skills_dir.exists():
            raise FileNotFoundError(f"Skills dir for {role}/{version_id} not found")
        return skills_dir

    def read_skill_contents(self, role: str, version_id: str) -> dict[str, str]:
        """Read skill file contents for a role version."""
        package = self.get_package(role, version_id)
        skills_dir = self.get_skill_dir(role, version_id)
        result: dict[str, str] = {}
        for ref in package.skills:
            rel_path = normalize_skill_path(ref.path)
            skill_file = skills_dir / rel_path
            if not skill_file.exists():
                raise FileNotFoundError(
                    f"Skill file {role}/{version_id}/{rel_path} not found"
                )
            result[rel_path] = skill_file.read_text(encoding="utf-8")
        return result

    def list_versions(self, role: str) -> list[VersionSummary]:
        """List all versions for a role from history.jsonl.

        Returns only 'created' events, in chronological order.
        """
        self._validate_name(role, "role")
        history_path = self._history_path(role)
        if not history_path.exists():
            return []

        current_baseline = self._read_baseline(role)
        summaries: list[VersionSummary] = []
        seen_ids: set[str] = set()

        for line in history_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            event = json.loads(line)
            if event.get("event") != "created":
                continue
            vid = event.get("version_id", "")
            if vid in seen_ids:
                continue
            seen_ids.add(vid)
            summaries.append(VersionSummary(
                version_id=vid,
                role=event.get("role", role),
                source=event.get("source", "unknown"),
                created_at=event.get("created_at", ""),
                is_baseline=(vid == current_baseline),
            ))

        return summaries

    def list_roles(self) -> list[str]:
        """List all roles that have entries in the registry."""
        if not self.root.exists():
            return []
        roles: list[str] = []
        for entry in sorted(self.root.iterdir()):
            if entry.is_dir() and (entry / "history.jsonl").exists():
                roles.append(entry.name)
        return roles

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
        Returns number of versions removed.
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

        # 2. Keep the most recent ``keep`` versions (by list order, which is
        #    chronological from history.jsonl)
        for vs in versions[-keep:]:
            keep_ids.add(vs.version_id)

        # 3. Remove everything else
        removed = 0
        for vs in versions:
            if vs.version_id not in keep_ids:
                vdir = self._version_dir(role, vs.version_id)
                if vdir.exists():
                    shutil.rmtree(vdir)
                    removed += 1
                    _log.debug("gc: removed %s/%s", role, vs.version_id)

        if removed:
            self._append_history_event(role, {
                "event": "gc",
                "removed_count": removed,
                "kept_count": len(keep_ids),
                "gc_at": beijing_now_iso(),
            })
            _log.info("gc: %s removed %d versions, kept %d", role, removed, len(keep_ids))

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
    #  Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _append_history_event(self, role: str, event: dict[str, Any]) -> None:
        """Append a single JSON line to history.jsonl.

        This is append-only — no read-modify-write — so it is safe under
        concurrent readers.  The caller must hold the role lock for writes.
        """
        history_path = self._history_path(role)
        history_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False, default=str) + "\n"
        with history_path.open("a", encoding="utf-8") as f:
            f.write(line)

    def _read_baseline(self, role: str) -> str | None:
        """Read baseline.json, return version_id or None."""
        bp = self._baseline_path(role)
        if not bp.exists():
            return None
        try:
            data = _read_json(bp)
            return data.get("version_id")
        except Exception:
            _log.warning("_read_baseline: corrupt baseline.json for %s", role)
            return None

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

    # --- Diff helpers ---

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
                # File removed
                before_text = self._read_skill_file(role, old_pkg.version_id, path)
                changes.append({
                    "file": path,
                    "action": "removed",
                    "before_lines": before_text.splitlines(),
                    "after_lines": [],
                })
            elif new_ref and not old_ref:
                # File added
                after_text = self._read_skill_file(role, new_pkg.version_id, path)
                changes.append({
                    "file": path,
                    "action": "added",
                    "before_lines": [],
                    "after_lines": after_text.splitlines(),
                })
            elif old_ref and new_ref and old_ref.content_hash != new_ref.content_hash:
                # File modified
                before_text = self._read_skill_file(role, old_pkg.version_id, path)
                after_text = self._read_skill_file(role, new_pkg.version_id, path)
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
            # else: identical hash, no change

        return changes

    def _read_skill_file(self, role: str, version_id: str, rel_path: str) -> str:
        """Read a single skill file from a version's directory."""
        skill_file = self._version_dir(role, version_id) / "skills" / rel_path
        if not skill_file.exists():
            return ""
        return skill_file.read_text(encoding="utf-8")

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
            pkg_path = self._version_dir(role, current) / "package.json"
            if not pkg_path.exists():
                break
            try:
                data = _read_json(pkg_path)
                current = data.get("parent_id") or ""
            except Exception:
                break
