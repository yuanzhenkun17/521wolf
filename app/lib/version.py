"""Version management — role version registry + promotion logic."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Iterator

from app.util.json import read_json, write_json
from app.util.time import beijing_now_iso
from storage.interfaces import normalize_skill_path

_log = logging.getLogger(__name__)

DEFAULT_SCRATCH_MAX_AGE_SECONDS = 24 * 60 * 60
_SCRATCH_DIR_PREFIXES = ("wolf_skill_", "wolf_skills_")
_SKILL_STATUS_VALUES = {"active", "deprecated"}
_EVOLUTION_ALLOWED_ACTIONS = {"append_rule", "rewrite_section", "deprecate_rule"}
_REJECTED_BUFFER_LIMIT = 50


@dataclass
class SkillVersionConfig:
    """Snapshot of role→version_id mappings for a single baseline."""
    name: str = ""
    created_at: str = ""
    role_versions: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "created_at": self.created_at,
            "role_versions": dict(self.role_versions),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SkillVersionConfig:
        if data is None:
            return cls()
        return cls(
            name=str(data.get("name", "")),
            created_at=str(data.get("created_at", "")),
            role_versions=dict(data.get("role_versions", {})),
            notes=[str(n) for n in data.get("notes", [])],
        )


@dataclass
class VersionSummary:
    """Lightweight summary for one role skill version."""
    version_id: str
    role: str
    source: str = ""
    created_at: str = ""
    is_baseline: bool = False
    status: str = "active"

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "role": self.role,
            "source": self.source,
            "created_at": self.created_at,
            "is_baseline": self.is_baseline,
            "status": self.status,
        }


class VersionRegistry:
    """Filesystem-backed registry for role skill versions."""

    def __init__(self, registry_dir: Path | str) -> None:
        self._dir = Path(registry_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / "versions").mkdir(exist_ok=True)
        self._scratch_dir().mkdir(exist_ok=True)
        self._cleanup_scratch_best_effort()

    @property
    def registry_dir(self) -> Path:
        return self._dir

    def close(self) -> None:
        return None

    def cleanup_scratch(self, max_age_seconds: int = DEFAULT_SCRATCH_MAX_AGE_SECONDS) -> int:
        """Delete expired registry-owned scratch directories and return the count removed."""
        if max_age_seconds < 0:
            raise ValueError("max_age_seconds must be non-negative")

        scratch_dir = self._scratch_dir()
        if not scratch_dir.exists():
            return 0

        try:
            entries = list(scratch_dir.iterdir())
        except OSError as exc:
            _log.warning("cleanup_scratch: failed to scan %s: %s", scratch_dir, exc)
            return 0

        now = time.time()
        deleted = 0
        for entry in entries:
            if not self._is_registry_scratch_dir(entry):
                continue
            try:
                age_seconds = now - entry.stat().st_mtime
            except OSError as exc:
                _log.warning("cleanup_scratch: failed to stat %s: %s", entry, exc)
                continue
            if age_seconds <= max_age_seconds:
                continue
            try:
                shutil.rmtree(entry)
            except OSError as exc:
                _log.warning("cleanup_scratch: failed to remove %s: %s", entry, exc)
                continue
            deleted += 1
        return deleted

    def publish_skills(
        self,
        role: str,
        skill_contents: dict[str, str],
        *,
        parent_id: str | None = None,
        source: str = "manual",
        run_id: str | None = None,
        proposal_ids: list[str] | None = None,
        version_id: str | None = None,
        set_as_baseline: bool = False,
        expected_current: str | None = None,
    ) -> str:
        """Publish a role skill snapshot and optionally promote it to baseline."""
        _validate_name(role, "role")
        normalized = {normalize_skill_path(path): str(content) for path, content in skill_contents.items()}
        _raise_for_skill_manifest_issues(validate_skill_manifests(role, normalized))

        with self._locked():
            version_id = version_id or self._next_version_id(role)
            _validate_name(version_id, "version_id")

            role_dir = self._role_dir(role)
            version_dir = role_dir / version_id

            if version_dir.exists():
                existing = self._read_skill_contents_unlocked(role, version_id)
                if existing != normalized:
                    raise ValueError(f"Version {role}/{version_id} already exists with different skill content")
            else:
                self._write_version_dir_atomic(
                    role=role,
                    version_id=version_id,
                    normalized=normalized,
                    meta={
                        "version_id": version_id,
                        "role": role,
                        "parent_id": parent_id,
                        "source": source,
                        "run_id": run_id,
                        "proposal_ids": list(proposal_ids or []),
                        "skills": [
                            {
                                "path": rel_path,
                                "content_hash": _content_hash(content),
                            }
                            for rel_path, content in sorted(normalized.items())
                        ],
                        "status": "active",
                        "created_at": beijing_now_iso(),
                    },
                )

            if set_as_baseline:
                ok = self._set_baseline_unlocked(role, version_id, expected_current=expected_current)
                if not ok:
                    raise RuntimeError(f"Failed to set baseline for {role}: expected {expected_current!r}")
            return version_id

    def _write_version_dir_atomic(
        self,
        *,
        role: str,
        version_id: str,
        normalized: dict[str, str],
        meta: dict[str, Any],
    ) -> None:
        """Write a complete version in staging, validate it, then finalize."""
        role_dir = self._role_dir(role)
        role_dir.mkdir(parents=True, exist_ok=True)
        version_dir = role_dir / version_id
        staging_dir: Path | None = Path(tempfile.mkdtemp(prefix=f".{version_id}.staging_", dir=role_dir))
        try:
            files_dir = staging_dir / "skills"
            files_dir.mkdir(parents=True, exist_ok=True)
            for rel_path, content in sorted(normalized.items()):
                output = files_dir / rel_path
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(content, encoding="utf-8")
            _raise_for_skill_manifest_issues(validate_skill_dir(files_dir, expected_role=role))
            write_json(staging_dir / "meta.json", meta)
            if version_dir.exists():
                raise FileExistsError(f"Version {role}/{version_id} appeared during publish")
            staging_dir.rename(version_dir)
            staging_dir = None
        finally:
            if staging_dir is not None and staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Cross-process registry lock for read-modify-write operations."""
        lock_path = self._dir / ".registry.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as lock_file:
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
                lock_file.flush()
            _lock_file(lock_file)
            try:
                yield
            finally:
                _unlock_file(lock_file)

    def _read_skill_contents_unlocked(self, role: str, version_id: str) -> dict[str, str]:
        files_dir = self._role_dir(role) / version_id / "skills"
        if not files_dir.exists():
            raise FileNotFoundError(f"Version {role}/{version_id} not found")
        contents: dict[str, str] = {}
        for path in sorted(files_dir.rglob("*")):
            if path.is_file():
                contents[path.relative_to(files_dir).as_posix()] = path.read_text(encoding="utf-8")
        return contents

    def _set_baseline_unlocked(
        self,
        role: str,
        version_id: str,
        expected_current: str | None = None,
    ) -> bool:
        if not (self._role_dir(role) / version_id / "meta.json").exists():
            return False
        baselines = self._baselines()
        current = baselines.get(role)
        if current != expected_current:
            return False
        baselines[role] = version_id
        write_json(self._baselines_path(), baselines)
        self._update_status(role, version_id, "promoted")
        self._append_history(role, version_id, "baseline_set", previous_version_id=current)
        return True

    def get_baseline(self, role: str) -> str | None:
        """Return the current baseline version id for a role."""
        _validate_name(role, "role")
        return self._baselines().get(role)

    def set_baseline(
        self,
        role: str,
        version_id: str,
        expected_current: str | None = None,
    ) -> bool:
        """Compare-and-set the baseline for a role."""
        _validate_name(role, "role")
        _validate_name(version_id, "version_id")
        with self._locked():
            return self._set_baseline_unlocked(role, version_id, expected_current=expected_current)

    def reject(self, role: str, version_id: str, reason: str = "") -> None:
        """Mark a version as rejected and append registry history."""
        _validate_name(role, "role")
        _validate_name(version_id, "version_id")
        with self._locked():
            if not (self._role_dir(role) / version_id / "meta.json").exists():
                raise FileNotFoundError(f"Version {role}/{version_id} not found")
            self._update_status(role, version_id, "rejected")
            self._append_history(role, version_id, f"rejected: {reason}" if reason else "rejected")

    def read_skill_contents(self, role: str, version_id: str) -> dict[str, str]:
        """Read all skill file contents for a role version."""
        _validate_name(role, "role")
        _validate_name(version_id, "version_id")
        return self._read_skill_contents_unlocked(role, version_id)

    def get_skill_dir(self, role: str, version_id: str) -> Path:
        """Return a temporary directory populated with a role version's skills."""
        self._cleanup_scratch_best_effort()
        contents = self.read_skill_contents(role, version_id)
        tmp = Path(tempfile.mkdtemp(prefix=f"wolf_skill_{role}_{version_id}_", dir=self._scratch_dir()))
        for rel_path, content in contents.items():
            output = tmp / rel_path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(content, encoding="utf-8")
        return tmp

    def build_skill_dir(self, role_versions: dict[str, str]) -> Path:
        """Build a temporary composite skill directory keyed by role."""
        self._cleanup_scratch_best_effort()
        tmp = Path(tempfile.mkdtemp(prefix="wolf_skills_", dir=self._scratch_dir()))
        for role, version_id in role_versions.items():
            role_dst = tmp / role
            contents = self.read_skill_contents(role, version_id)
            for rel_path, content in contents.items():
                output = role_dst / _strip_role_prefix(rel_path, role)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(content, encoding="utf-8")
        return tmp

    def list_versions(self, role: str) -> list[VersionSummary]:
        """List all known versions for a role."""
        _validate_name(role, "role")
        role_dir = self._role_dir(role)
        baseline = self.get_baseline(role)
        summaries: list[VersionSummary] = []
        if not role_dir.exists():
            return []
        for meta_path in sorted(role_dir.glob("*/meta.json")):
            try:
                meta = read_json(meta_path)
            except (OSError, TypeError, ValueError) as exc:
                _log.warning("list_versions: skipping unreadable metadata %s: %s", meta_path, exc)
                continue
            if not isinstance(meta, dict):
                _log.warning("list_versions: skipping non-object metadata %s", meta_path)
                continue
            version_id = str(meta.get("version_id") or meta_path.parent.name)
            summaries.append(
                VersionSummary(
                    version_id=version_id,
                    role=role,
                    source=str(meta.get("source", "")),
                    created_at=str(meta.get("created_at", "")),
                    is_baseline=version_id == baseline,
                    status=str(meta.get("status", "active")),
                )
            )
        return summaries

    def list_roles(self) -> list[str]:
        """List roles with at least one published version."""
        versions_dir = self._dir / "versions"
        return sorted(path.name for path in versions_dir.iterdir() if path.is_dir()) if versions_dir.exists() else []

    def save_rejected(
        self,
        role: str,
        proposals: list[dict[str, Any]],
        battle_result: dict[str, Any] | None = None,
    ) -> None:
        """Persist rejected proposals for future dedup/consolidation."""
        _validate_name(role, "role")
        with self._locked():
            path = self._role_dir(role) / "rejected.json"
            existing_raw = read_json(path).get("proposals", []) if path.exists() else []
            existing = _dedupe_rejected_rows(
                [dict(item) for item in existing_raw if isinstance(item, dict)]
            )
            seen = {_rejected_proposal_key(item) for item in existing}
            for proposal in proposals:
                row = dict(proposal)
                key = _rejected_proposal_key(row)
                if key in seen:
                    continue
                row["battle_result"] = battle_result
                row["rejected_at"] = beijing_now_iso()
                row["dedupe_key"] = key
                existing.append(row)
                seen.add(key)
            write_json(path, {"role": role, "proposals": existing[-_REJECTED_BUFFER_LIMIT:]})

    def load_rejected(self, role: str) -> list[dict[str, Any]]:
        """Load rejected proposals for a role."""
        _validate_name(role, "role")
        path = self._role_dir(role) / "rejected.json"
        if not path.exists():
            return []
        return list(read_json(path).get("proposals", []))

    def _next_version_id(self, role: str) -> str:
        max_index = 0
        prefix = f"{role}_v"
        role_dir = self._role_dir(role)
        if role_dir.exists():
            for version_dir in role_dir.iterdir():
                if not version_dir.is_dir():
                    continue
                version_id = version_dir.name
                if version_id.startswith(prefix) and version_id[len(prefix):].isdigit():
                    max_index = max(max_index, int(version_id[len(prefix):]))
        return f"{role}_v{max_index + 1}"

    def _role_dir(self, role: str) -> Path:
        return self._dir / "versions" / role

    def _scratch_dir(self) -> Path:
        return self._dir / "scratch"

    def _cleanup_scratch_best_effort(self) -> None:
        try:
            self.cleanup_scratch()
        except Exception as exc:
            _log.warning("cleanup_scratch: ignored failure: %s", exc)

    def _is_registry_scratch_dir(self, path: Path) -> bool:
        if path.parent != self._scratch_dir():
            return False
        if not path.name.startswith(_SCRATCH_DIR_PREFIXES):
            return False
        if path.is_symlink():
            return False
        return path.is_dir()

    def _baselines_path(self) -> Path:
        return self._dir / "baselines.json"

    def _baselines(self) -> dict[str, str]:
        path = self._baselines_path()
        if not path.exists():
            return {}
        try:
            data = read_json(path)
        except (OSError, TypeError, ValueError) as exc:
            _log.warning("baselines: ignoring unreadable baseline file %s: %s", path, exc)
            return {}
        if not isinstance(data, dict):
            _log.warning("baselines: ignoring non-object baseline file %s", path)
            return {}
        return {str(k): str(v) for k, v in data.items()}

    def _update_status(self, role: str, version_id: str, status: str) -> None:
        meta_path = self._role_dir(role) / version_id / "meta.json"
        meta = read_json(meta_path)
        meta["status"] = status
        meta["updated_at"] = beijing_now_iso()
        write_json(meta_path, meta)

    def _append_history(
        self,
        role: str,
        version_id: str,
        reason: str,
        *,
        previous_version_id: str | None = None,
    ) -> None:
        history_path = self._dir / "history.jsonl"
        history_path.parent.mkdir(parents=True, exist_ok=True)
        row = {
            "role": role,
            "version_id": version_id,
            "previous_version_id": previous_version_id,
            "reason": reason,
            "created_at": beijing_now_iso(),
        }
        with _path_locked(self._dir / ".history.lock"):
            with history_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build_baseline_config(registry: VersionRegistry) -> SkillVersionConfig:
    """Build a baseline config from the current registry state."""
    role_versions = {
        role: baseline
        for role in registry.list_roles()
        if (baseline := registry.get_baseline(role)) is not None
    }
    return SkillVersionConfig(
        name="baseline",
        created_at=beijing_now_iso(),
        role_versions=role_versions,
    )


def build_composite_skill_dir(registry: VersionRegistry, config: SkillVersionConfig) -> Path | None:
    """Build a composite skill directory from a SkillVersionConfig.

    Copies skill files from each version hash into a temporary directory.
    """
    if not config.role_versions:
        return None
    return registry.build_skill_dir(config.role_versions)


def promote_version(registry: VersionRegistry, role: str, version_id: str) -> None:
    """Promote a version to be the new baseline for a role."""
    current = registry.get_baseline(role)
    if current == version_id:
        return
    if not registry.set_baseline(role, version_id, expected_current=current):
        raise RuntimeError(f"Failed to promote {role}/{version_id}")


def reject_version(registry: VersionRegistry, role: str, version_id: str) -> None:
    """Mark a version as rejected for a role."""
    registry.reject(role, version_id)


def validate_skill_dir(root: Path | str, *, expected_role: str | None = None) -> list[str]:
    """Validate every Markdown skill manifest under a directory."""
    root_path = Path(root)
    if not root_path.is_dir():
        return [f"{root_path}: skill directory does not exist"]
    issues: list[str] = []
    files = sorted(path for path in root_path.rglob("*.md") if path.is_file())
    if not files:
        return [f"{root_path}: no .md skill files found"]
    for path in files:
        rel_path = path.relative_to(root_path).as_posix()
        try:
            normalize_skill_path(rel_path)
            content = path.read_text(encoding="utf-8")
        except (OSError, ValueError) as exc:
            issues.append(f"{rel_path}: {exc}")
            continue
        issues.extend(validate_skill_manifest(rel_path, content, expected_role=expected_role))
    return issues


def validate_skill_manifests(
    role: str,
    skill_contents: dict[str, str],
) -> list[str]:
    """Validate a role skill snapshot before it can enter the registry."""
    if not skill_contents:
        return [f"{role}: no skill files provided"]
    issues: list[str] = []
    for rel_path, content in sorted(skill_contents.items()):
        issues.extend(validate_skill_manifest(rel_path, content, expected_role=role))
    return issues


def validate_skill_manifest(
    rel_path: str,
    content: str,
    *,
    expected_role: str | None = None,
) -> list[str]:
    """Validate required skill front matter fields for registry publication."""
    from app.util.action_types import AGENT_ACTION_TYPES
    from app.util.text import parse_yaml_front_matter
    from engine import Role

    issues: list[str] = []
    try:
        normalized_path = normalize_skill_path(rel_path)
    except ValueError as exc:
        return [f"{rel_path}: unsafe skill path: {exc}"]

    front, _body = parse_yaml_front_matter(str(content or ""))
    if not front:
        return [f"{normalized_path}: missing YAML front matter"]

    name = str(front.get("name", "")).strip()
    if not name:
        issues.append(f"{normalized_path}: missing required front matter field 'name'")

    if "role" not in front:
        issues.append(f"{normalized_path}: missing required front matter field 'role'")
    role_value = str(front.get("role", "")).strip()
    valid_roles = {item.value for item in Role}
    if role_value and role_value not in valid_roles:
        issues.append(f"{normalized_path}: unknown role '{role_value}'")
    if expected_role is not None and role_value != expected_role:
        issues.append(f"{normalized_path}: role must be '{expected_role}', got '{role_value}'")

    if "status" not in front:
        issues.append(f"{normalized_path}: missing required front matter field 'status'")
    status = str(front.get("status", "")).strip().lower()
    if status and status not in _SKILL_STATUS_VALUES:
        issues.append(f"{normalized_path}: status must be one of {sorted(_SKILL_STATUS_VALUES)}, got '{status}'")

    actions = _as_str_list(front.get("applicable_actions", []))
    if not actions:
        issues.append(f"{normalized_path}: applicable_actions must contain at least one action")
    else:
        invalid_actions = sorted(set(actions) - AGENT_ACTION_TYPES - {"vote"})
        if invalid_actions:
            issues.append(f"{normalized_path}: unknown applicable_actions: {invalid_actions}")

    if "evolution" not in front:
        issues.append(f"{normalized_path}: missing required front matter field 'evolution'")
        return issues
    evolution = front.get("evolution")
    if not isinstance(evolution, dict):
        issues.append(f"{normalized_path}: evolution must be a mapping")
        return issues
    if "enabled" not in evolution:
        issues.append(f"{normalized_path}: evolution.enabled is required")
    allowed_actions = _as_str_list(evolution.get("allowed_actions", []))
    if "allowed_actions" not in evolution:
        issues.append(f"{normalized_path}: evolution.allowed_actions is required")
    elif not allowed_actions:
        issues.append(f"{normalized_path}: evolution.allowed_actions must contain at least one action")
    else:
        invalid_allowed = sorted(set(allowed_actions) - _EVOLUTION_ALLOWED_ACTIONS)
        if invalid_allowed:
            issues.append(f"{normalized_path}: invalid evolution.allowed_actions: {invalid_allowed}")
    return issues


def _strip_role_prefix(rel_path: str, role: str) -> str:
    path = PurePosixPath(normalize_skill_path(rel_path))
    parts = path.parts
    if len(parts) > 1 and parts[0] == role:
        return PurePosixPath(*parts[1:]).as_posix()
    return path.as_posix()


def _validate_name(name: str, label: str) -> None:
    if not name or not name.strip():
        raise ValueError(f"Empty {label}")
    if "/" in name or "\\" in name or ".." in name or "\0" in name or ":" in name:
        raise ValueError(f"Unsafe {label}: {name}")


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


def _as_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _raise_for_skill_manifest_issues(issues: list[str]) -> None:
    if issues:
        raise ValueError("Invalid skill manifest: " + "; ".join(issues))


def _rejected_proposal_key(proposal: dict[str, Any]) -> str:
    payload = {
        "target_file": str(proposal.get("target_file", "")),
        "action_type": str(proposal.get("action_type", "")),
        "rationale": str(proposal.get("rationale", "")),
        "content_hash": hashlib.sha256(str(proposal.get("content", "")).encode("utf-8")).hexdigest()[:16],
    }
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _dedupe_rejected_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        key = str(row.get("dedupe_key") or _rejected_proposal_key(row))
        if key in seen:
            continue
        item = dict(row)
        item.setdefault("dedupe_key", key)
        result.append(item)
        seen.add(key)
    return result


@contextmanager
def _path_locked(lock_path: Path) -> Iterator[None]:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        lock_file.seek(0, os.SEEK_END)
        if lock_file.tell() == 0:
            lock_file.write(b"\0")
            lock_file.flush()
        _lock_file(lock_file)
        try:
            yield
        finally:
            _unlock_file(lock_file)


def _lock_file(file_obj: Any) -> None:
    if os.name == "nt":
        import msvcrt

        file_obj.seek(0)
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_LOCK, 1)
        return

    import fcntl

    fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX)


def _unlock_file(file_obj: Any) -> None:
    if os.name == "nt":
        import msvcrt

        file_obj.seek(0)
        msvcrt.locking(file_obj.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(file_obj.fileno(), fcntl.LOCK_UN)
