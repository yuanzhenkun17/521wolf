"""Role evolution — configuration builders for skill version routing.

Builds SkillVersionConfig objects that map each role to a version hash,
and resolves (role, config) pairs to on-disk skill directory paths.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from agent.common import beijing_now_iso
from agent.learning.evolution.models import SkillVersionConfig

if TYPE_CHECKING:
    from agent.learning.evolution.registry import VersionRegistry

_log = logging.getLogger(__name__)


def build_baseline_config(store: VersionRegistry) -> SkillVersionConfig:
    """All roles use their baseline hash. Returns a SkillVersionConfig."""
    role_versions: dict[str, str] = {}
    for role in store.list_roles():
        baseline = store.get_baseline(role)
        if baseline is not None:
            role_versions[role] = baseline
    return SkillVersionConfig(
        name="baseline",
        created_at=beijing_now_iso(),
        role_versions=role_versions,
        notes=["all roles at baseline"],
    )


def build_role_override_config(
    store: VersionRegistry, role: str, role_hash: str
) -> SkillVersionConfig:
    """Target role uses specified hash, all others use baseline."""
    role_versions: dict[str, str] = {}
    for r in store.list_roles():
        if r == role:
            role_versions[r] = role_hash
        else:
            baseline = store.get_baseline(r)
            if baseline is not None:
                role_versions[r] = baseline
    return SkillVersionConfig(
        name=f"override-{role}-{role_hash[:8]}",
        created_at=beijing_now_iso(),
        role_versions=role_versions,
        notes=[f"{role} overridden to {role_hash[:8]}"],
    )


def build_role_override_from_config(
    baseline_config: SkillVersionConfig,
    role: str,
    role_hash: str,
    *,
    name: str | None = None,
) -> SkillVersionConfig:
    """Return a config with one role hash replaced, preserving the baseline snapshot."""
    if role not in baseline_config.role_versions:
        raise KeyError(f"Role '{role}' not found in config '{baseline_config.name}'")
    role_versions = dict(baseline_config.role_versions)
    role_versions[role] = role_hash
    return SkillVersionConfig(
        name=name or f"override-{role}-{role_hash[:8]}",
        created_at=beijing_now_iso(),
        role_versions=role_versions,
        notes=[*baseline_config.notes, f"{role} overridden to {role_hash[:8]}"],
    )


def skill_dir_for_role(
    store: VersionRegistry, config: SkillVersionConfig, role: str
) -> Path:
    """Returns the skill directory path for a specific role.

    Used by _create_agents() to pass per-role skill_dir to AgentRuntime.
    Maps (role -> hash -> directory path) so selfplay can load versioned skills.
    """
    role_hash = config.role_versions.get(role)
    if role_hash is None:
        raise KeyError(f"Role '{role}' not found in config '{config.name}'")
    return store.get_skill_dir(role, role_hash)


def _is_explicit_empty_version(store: VersionRegistry, role: str, hash_value: str) -> bool:
    """Return True for intentional empty role versions that have no skill files."""
    try:
        version = store.get_package(role, hash_value)
    except FileNotFoundError:
        return False
    return (
        not version.skills
        and version.provenance.source in {"bootstrap_empty", "default_empty"}
    )


def build_composite_skill_dir(store: VersionRegistry, config: SkillVersionConfig) -> Path:
    """Assemble a temporary role skill directory from a version config."""
    tmpdir = Path(tempfile.mkdtemp(prefix="evo_skills_"))
    for role, hash_value in config.role_versions.items():
        dst = tmpdir / role
        try:
            src = store.get_skill_dir(role, hash_value)
        except FileNotFoundError:
            if _is_explicit_empty_version(store, role, hash_value):
                dst.mkdir(parents=True, exist_ok=True)
                continue
            raise
        shutil.copytree(src, dst)
    return tmpdir