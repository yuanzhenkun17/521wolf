"""Tests for role evolution config builders.

Verifies build_baseline_config, build_role_override_config, and skill_dir_for_role
using a lightweight mock VersionStore (the real store may not expose list_histories /
version_dir yet).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from agent.role_evolution.config import (
    build_baseline_config,
    build_role_override_config,
    skill_dir_for_role,
)


# ---------------------------------------------------------------------------
# Lightweight mock — just enough for the three config functions
# ---------------------------------------------------------------------------


@dataclass
class _MockHistory:
    role: str
    baseline: str
    versions: list[str] = field(default_factory=list)


class MockVersionStore:
    """Minimal stand-in for VersionStore that config.py needs."""

    def __init__(self, base_dir: Path, histories: list[_MockHistory]) -> None:
        self._base = base_dir
        self._histories = {h.role: h for h in histories}

    def list_histories(self) -> list[_MockHistory]:
        return list(self._histories.values())

    def get_skill_dir(self, role: str, hash: str) -> Path:
        """Map (role, hash) to agent_versions/<role>/<hash>/skills."""
        return self._base / role / hash / "skills"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROLES = {
    "werewolf": "aabbccdd",
    "seer": "11223344",
    "villager": "deadbeef",
}


def _make_store(tmp_path: Path, roles: dict[str, str] | None = None) -> MockVersionStore:
    """Build a mock store with one baseline hash per role."""
    roles = roles or ROLES
    histories = [
        _MockHistory(role=r, baseline=h, versions=[h])
        for r, h in roles.items()
    ]
    return MockVersionStore(base_dir=tmp_path / "agent_versions", histories=histories)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_baseline_config_maps_all_roles(tmp_path: Path) -> None:
    """build_baseline_config maps every role to its baseline hash."""
    store = _make_store(tmp_path)
    config = build_baseline_config(store)

    assert config.name == "baseline"
    assert len(config.role_versions) == len(ROLES)
    for role, expected_hash in ROLES.items():
        assert role in config.role_versions, f"missing role {role}"
        assert config.role_versions[role] == expected_hash


def test_override_config_changes_only_target_role(tmp_path: Path) -> None:
    """Overriding one role changes only that role's hash; others stay baseline."""
    store = _make_store(tmp_path)
    baseline = build_baseline_config(store)

    target_role = "seer"
    new_hash = "cafebabe"
    override = build_role_override_config(store, target_role, new_hash)

    # The target role should carry the new hash.
    assert override.role_versions[target_role] == new_hash

    # Every other role should remain at its baseline hash.
    for role, expected_hash in ROLES.items():
        if role == target_role:
            continue
        assert override.role_versions[role] == expected_hash
        assert override.role_versions[role] == baseline.role_versions[role]


def test_skill_dir_for_role_returns_correct_path(tmp_path: Path) -> None:
    """skill_dir_for_role resolves to agent_versions/<role>/<hash>/skills/."""
    store = _make_store(tmp_path)
    config = build_baseline_config(store)

    for role, expected_hash in ROLES.items():
        result = skill_dir_for_role(store, config, role)
        expected = tmp_path / "agent_versions" / role / expected_hash / "skills"
        assert result == expected


def test_no_cross_role_skill_leakage(tmp_path: Path) -> None:
    """Different roles get different skill directories (unless hashes collide)."""
    store = _make_store(tmp_path)
    config = build_baseline_config(store)

    dirs = {role: skill_dir_for_role(store, config, role) for role in ROLES}
    # Every pair of distinct roles must resolve to distinct paths.
    roles_list = list(dirs.keys())
    for i in range(len(roles_list)):
        for j in range(i + 1, len(roles_list)):
            a, b = roles_list[i], roles_list[j]
            assert dirs[a] != dirs[b], (
                f"roles '{a}' and '{b}' share the same skill directory: {dirs[a]}"
            )


def test_override_preserves_config_metadata(tmp_path: Path) -> None:
    """Override config has expected name and notes."""
    store = _make_store(tmp_path)
    target_role = "werewolf"
    new_hash = "ff00ff00"
    config = build_role_override_config(store, target_role, new_hash)

    assert target_role in config.name
    assert new_hash[:8] in config.name
    assert len(config.notes) > 0
    assert target_role in config.notes[0]


def test_skill_dir_for_role_unknown_role_raises(tmp_path: Path) -> None:
    """skill_dir_for_role raises KeyError for a role not in the config."""
    store = _make_store(tmp_path)
    config = build_baseline_config(store)

    with pytest.raises(KeyError, match="nonexistent"):
        skill_dir_for_role(store, config, "nonexistent")
