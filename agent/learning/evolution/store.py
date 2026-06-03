"""Version store for role evolution.

Manages immutable snapshots of role skill sets, version history,
and baseline tracking on disk.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path, PurePosixPath

from agent.common import beijing_now_iso
from agent.common.json import write_json as _write_json
from agent.common.paths import DEFAULT as DEFAULT_PATHS

from agent.learning.evolution.models import RoleHistory, RoleVersion

_log = logging.getLogger(__name__)


# Errors
class HashCollisionError(Exception):
    """Raised when two different skill sets produce the same hash."""


# Hash helpers
def normalize_skill_text(text: str) -> str:
    """Normalize skill file content: CRLF to LF, strip trailing whitespace per line, ensure final newline."""
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")
    lines = [line.rstrip() for line in lines]
    result = "\n".join(lines)
    if not result.endswith("\n"):
        result += "\n"
    return result


def normalize_skill_path(path: str) -> str:
    """Normalize a skill file path using PurePosixPath rules.

    Returns the normalized path string.
    Raises ValueError for invalid paths: empty, absolute, containing '..',
    drive paths, or non-.md extension.
    """
    # Normalize backslashes to forward slashes before PurePosixPath
    path = path.replace("\\", "/")
    p = PurePosixPath(path)

    # Reject empty
    if not path or not str(p):
        raise ValueError("Empty path")

    # Reject absolute paths
    if p.is_absolute():
        raise ValueError(f"Absolute path not allowed: {path}")

    # Reject drive paths (e.g. C:/...)
    if p.drive:
        raise ValueError(f"Drive path not allowed: {path}")

    # Reject '..' components
    parts = list(p.parts)
    if ".." in parts:
        raise ValueError(f"Path traversal ('..') not allowed: {path}")

    # Reject non-.md extension
    if p.suffix != ".md":
        raise ValueError(f"Only .md files allowed, got: {path}")

    # Normalize: collapse redundant separators via PurePosixPath
    normalized = str(p)
    return normalized


def compute_hash(skills: dict[str, str]) -> str:
    """Compute a content hash for a set of skills.

    Normalizes paths and content, detects duplicate normalized paths,
    then produces a sha256 hash of the manifest.
    Returns first 8 hex characters prefixed with schema version.
    """
    normalized: dict[str, str] = {}
    for raw_path, content in skills.items():
        np = normalize_skill_path(raw_path)
        if np in normalized:
            raise ValueError(f"Duplicate normalized path: {np} (from {raw_path})")
        normalized[np] = normalize_skill_text(content)

    # Build deterministic manifest
    manifest = {
        "hash_schema": 1,
        "skills": {k: normalized[k] for k in sorted(normalized)},
    }
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    full_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return full_hash[:8]


# JSON helper
def _read_json(path: Path) -> dict:
    """Read JSON data from a file."""
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_battle_delta(battle_result: dict, role: str) -> dict:
    """Extract the role-specific metrics delta from a battle result."""
    base = battle_result.get("baseline_metrics", {})
    cand = battle_result.get("candidate_metrics", {})
    role_base = base.get(role, {})
    role_cand = cand.get(role, {})
    return {
        "role_score_delta": round(
            (role_cand.get("role_weighted_score", 0) or 0)
            - (role_base.get("role_weighted_score", 0) or 0), 3,
        ),
        "win_rate_delta": round(
            (role_cand.get("win_rate", 0) or 0)
            - (role_base.get("win_rate", 0) or 0), 3,
        ),
        "games": battle_result.get("games_played", 0),
    }


# Version store
class VersionStore:
    """Persistent store for role skill versions.

    Layout:
        data/versions/
          <role>/
            <hash>/
              skills/*.md
              meta.json
            history.json
    """

    def __init__(self, base_dir: Path = DEFAULT_PATHS.versions_dir) -> None:
        self._base = base_dir
        self._locks: dict[str, asyncio.Lock] = {}

    @property
    def base_dir(self) -> Path:
        """Public access to the store's base directory."""
        return self._base

    @staticmethod
    def _validate_name(name: str, label: str) -> None:
        """Reject path traversal in role/hash names."""
        if not name or not name.strip():
            raise ValueError(f"Empty {label}")
        if "/" in name or "\\" in name or ".." in name or "\0" in name:
            raise ValueError(f"Unsafe {label}: {name}")
        if ":" in name:
            raise ValueError(f"Unsafe {label}: {name}")

    def _role_dir(self, role: str) -> Path:
        self._validate_name(role, "role")
        return self._base / role

    def _version_dir(self, role: str, hash: str) -> Path:
        self._validate_name(hash, "hash")
        return self._role_dir(role) / hash

    def _history_path(self, role: str) -> Path:
        return self._role_dir(role) / "history.json"

    def _meta_path(self, role: str, hash: str) -> Path:
        return self._version_dir(role, hash) / "meta.json"

    def _skills_dir(self, role: str, hash: str) -> Path:
        return self._version_dir(role, hash) / "skills"

    def _lock_for(self, role: str) -> asyncio.Lock:
        if role not in self._locks:
            self._locks[role] = asyncio.Lock()
        return self._locks[role]

    # Core operations

    async def save_version(
        self,
        role: str,
        skills: dict[str, str],
        parent_hash: str | None,
        source: str,
        source_run_id: str | None = None,
        notes: list[str] | None = None,
    ) -> str:
        """Save a new version, returning its hash.

        Idempotent: same hash+content returns immediately.
        Same hash with different content raises HashCollisionError.
        If history already records this hash, no duplicate append occurs.
        """
        h = compute_hash(skills)
        meta_path = self._meta_path(role, h)

        async with self._lock_for(role):
            # Check for existing version with same hash
            if meta_path.exists():
                existing = RoleVersion.from_dict(_read_json(meta_path))
                # Verify content matches
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
                # Same content — idempotent, ensure history has it
                self._ensure_history_has(role, h)
                _log.debug("save_version: idempotent hit for %s/%s", role, h)
                return h

            # Write skill files atomically
            skills_dir = self._skills_dir(role, h)
            skills_dir.mkdir(parents=True, exist_ok=True)
            for raw_path, content in skills.items():
                np = normalize_skill_path(raw_path)
                normalized_content = normalize_skill_text(content)
                skill_file = skills_dir / np
                skill_file.parent.mkdir(parents=True, exist_ok=True)
                skill_file.write_text(normalized_content, encoding="utf-8")

            # Write meta.json
            now = beijing_now_iso()
            version = RoleVersion(
                hash=h,
                role=role,
                skills=dict(skills),
                created_at=now,
                source=source,
                parent_hash=parent_hash,
                source_run_id=source_run_id,
                notes=notes or [],
            )
            _write_json(meta_path, version.to_dict())

            # Append to history
            self._ensure_history_has(role, h)

            _log.info("save_version: saved %s/%s (source=%s)", role, h, source)
            return h

    async def set_baseline(
        self,
        role: str,
        target_hash: str,
        expected_current: str,
    ) -> bool:
        """Set baseline using compare-and-swap.

        Returns True if baseline was updated, False if expected_current didn't match.
        """
        history_path = self._history_path(role)
        async with self._lock_for(role):
            if not history_path.exists():
                _log.warning("set_baseline: no history for role %s", role)
                return False

            history = RoleHistory.from_dict(_read_json(history_path))
            if history.baseline != expected_current:
                _log.warning(
                    "set_baseline: CAS mismatch for %s: expected=%s actual=%s",
                    role, expected_current, history.baseline,
                )
                return False

            # Verify target hash exists
            meta_path = self._meta_path(role, target_hash)
            if not meta_path.exists():
                _log.warning("set_baseline: target hash %s not found for %s", target_hash, role)
                return False

            history.baseline = target_hash
            _write_json(history_path, history.to_dict())
            _log.info("set_baseline: %s → %s", role, target_hash)
            return True

    def load_version(self, role: str, hash: str) -> RoleVersion:
        """Load a specific version by role and hash."""
        meta_path = self._meta_path(role, hash)
        if not meta_path.exists():
            raise FileNotFoundError(f"Version {role}/{hash} not found")
        return RoleVersion.from_dict(_read_json(meta_path))

    def get_history(self, role: str) -> RoleHistory:
        """Get the version history for a role."""
        history_path = self._history_path(role)
        if not history_path.exists():
            raise FileNotFoundError(f"No history for role {role}")
        return RoleHistory.from_dict(_read_json(history_path))

    def get_baseline(self, role: str) -> RoleVersion:
        """Load the baseline version for a role."""
        history = self.get_history(role)
        return self.load_version(role, history.baseline)

    def list_roles(self) -> list[str]:
        """List all roles that have stored versions."""
        if not self._base.exists():
            return []
        return sorted(
            d.name for d in self._base.iterdir()
            if d.is_dir() and (d / "history.json").exists()
        )

    def list_histories(self) -> list[RoleHistory]:
        """List all role histories."""
        result: list[RoleHistory] = []
        for role in self.list_roles():
            try:
                result.append(self.get_history(role))
            except FileNotFoundError:
                _log.warning("list_histories: missing history for %s", role)
        return result

    def list_versions(self, role: str) -> list[RoleVersion]:
        """List all versions for a role, in history order."""
        history = self.get_history(role)
        versions = []
        for h in history.versions:
            try:
                versions.append(self.load_version(role, h))
            except FileNotFoundError:
                _log.warning("list_versions: missing version %s/%s", role, h)
        return versions

    def get_skill_dir(self, role: str, hash: str) -> Path:
        """Get the skills directory for a specific version."""
        d = self._skills_dir(role, hash)
        if not d.exists():
            raise FileNotFoundError(f"Skills dir for {role}/{hash} not found")
        return d

    # First-run initialization

    def ensure_default_baselines(self) -> None:
        """Create an explicit empty bootstrap baseline for roles with no history."""
        from engine.models import Role

        for role in Role:
            role_name = role.value
            history_path = self._history_path(role_name)
            if history_path.exists():
                continue

            skills: dict[str, str] = {}
            h = compute_hash(skills)
            version_dir = self._version_dir(role_name, h)
            version_dir.mkdir(parents=True, exist_ok=True)

            skills_dir = self._skills_dir(role_name, h)
            skills_dir.mkdir(parents=True, exist_ok=True)

            now = beijing_now_iso()
            version = RoleVersion(
                hash=h,
                role=role_name,
                skills=skills,
                created_at=now,
                source="bootstrap_empty",
                notes=["intentional empty baseline"],
            )
            _write_json(self._meta_path(role_name, h), version.to_dict())
            history = RoleHistory(role=role_name, baseline=h, versions=[h])
            _write_json(history_path, history.to_dict())
            _log.info("ensure_default_baselines: created empty baseline for %s/%s", role_name, h)

    def initialize_from_skills(self, skills_root: Path) -> None:
        """Create baseline versions from existing skills/<role>/ directories.

        Reads each role subdirectory under skills_root, creates an initial
        version and history for roles that don't yet have one.
        """
        if not skills_root.exists():
            _log.warning("initialize_from_skills: skills_root %s does not exist", skills_root)
            return

        for role_dir in sorted(skills_root.iterdir()):
            if not role_dir.is_dir():
                continue
            role = role_dir.name
            history_path = self._history_path(role)
            if history_path.exists():
                _log.debug("initialize_from_skills: %s already has history, skipping", role)
                continue

            # Read all .md files for this role
            skills: dict[str, str] = {}
            for md_file in sorted(role_dir.rglob("*.md")):
                rel = md_file.relative_to(role_dir)
                skills[str(rel)] = md_file.read_text(encoding="utf-8")

            if not skills:
                _log.warning("initialize_from_skills: no .md files for role %s, skipping", role)
                continue

            # Compute hash and create version
            h = compute_hash(skills)
            version_dir = self._version_dir(role, h)
            version_dir.mkdir(parents=True, exist_ok=True)

            # Write skill files
            skills_dir = self._skills_dir(role, h)
            skills_dir.mkdir(parents=True, exist_ok=True)
            for raw_path, content in skills.items():
                np = normalize_skill_path(raw_path)
                normalized_content = normalize_skill_text(content)
                skill_file = skills_dir / np
                skill_file.parent.mkdir(parents=True, exist_ok=True)
                skill_file.write_text(normalized_content, encoding="utf-8")

            # Write meta.json
            now = beijing_now_iso()
            version = RoleVersion(
                hash=h,
                role=role,
                skills=dict(skills),
                created_at=now,
                source="initialize_from_skills",
            )
            _write_json(self._meta_path(role, h), version.to_dict())

            # Write history.json
            history = RoleHistory(role=role, baseline=h, versions=[h])
            _write_json(history_path, history.to_dict())

            _log.info("initialize_from_skills: created baseline %s/%s", role, h)

    # Rejected-proposal buffer
    _MAX_REJECTED = 10

    def save_rejected(
        self, role: str,
        proposals: list[dict],
        battle_result: dict | None,
    ) -> None:
        """Append rejected proposals to the role's rejected buffer.

        Keeps at most ``_MAX_REJECTED`` entries by dropping the oldest.
        Each entry records the proposal, battle metrics delta, and timestamp.
        """
        rejected_path = self._role_dir(role) / "rejected.json"
        existing = _read_json(rejected_path) if rejected_path.exists() else []
        metrics = _extract_battle_delta(battle_result, role) if battle_result else {}
        for p in proposals:
            existing.append({
                "target_file": p.get("target_file", ""),
                "action_type": p.get("action_type", ""),
                "content": p.get("content", ""),
                "rationale": p.get("rationale", ""),
                "confidence": p.get("confidence", 0.0),
                "metrics_delta": metrics,
                "rejected_at": beijing_now_iso(),
            })
        if len(existing) > self._MAX_REJECTED:
            existing = existing[-self._MAX_REJECTED:]
        _write_json(rejected_path, existing)

    def load_rejected(self, role: str) -> list[dict]:
        """Load the rejected-proposal buffer for *role*, newest last."""
        rejected_path = self._role_dir(role) / "rejected.json"
        if not rejected_path.exists():
            return []
        return _read_json(rejected_path)

    # Internal helpers

    def _ensure_history_has(self, role: str, hash: str) -> None:
        """Ensure the hash is recorded in history; create history if needed."""
        history_path = self._history_path(role)
        if history_path.exists():
            history = RoleHistory.from_dict(_read_json(history_path))
            if hash in history.versions:
                return
            history.versions.append(hash)
            _write_json(history_path, history.to_dict())
        else:
            history = RoleHistory(role=role, baseline=hash, versions=[hash])
            _write_json(history_path, history.to_dict())
