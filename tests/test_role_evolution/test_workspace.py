"""Tests for temporary skill workspace assembly."""

from __future__ import annotations

import shutil

import pytest

from agent.learning_v2.evolution.config import build_baseline_config
from agent.learning_v2.evolution.models import SkillVersionConfig
from agent.learning_v2.evolution.store import VersionStore
from agent.learning_v2.evolution.config import build_composite_skill_dir


def test_build_composite_skill_dir_allows_bootstrap_empty_versions(tmp_path):
    """Explicit empty baseline versions become empty role directories."""
    store = VersionStore(tmp_path / "role_versions")
    store.ensure_default_baselines()
    config = build_baseline_config(store)

    composite_dir = build_composite_skill_dir(store, config)
    try:
        for role in config.role_versions:
            assert (composite_dir / role).is_dir()
            assert list((composite_dir / role).rglob("*.md")) == []
    finally:
        shutil.rmtree(composite_dir, ignore_errors=True)


@pytest.mark.asyncio
async def test_build_composite_skill_dir_raises_for_missing_non_empty_skill_dir(tmp_path):
    """Missing skill files for a non-empty version indicate corrupted storage."""
    store = VersionStore(tmp_path / "role_versions")
    role_hash = await store.save_version(
        "seer",
        {"claim.md": "# Claim\n"},
        parent_hash=None,
        source="test",
    )
    skill_dir = store.get_skill_dir("seer", role_hash)
    shutil.rmtree(skill_dir)

    config = SkillVersionConfig(
        name="broken",
        created_at="2026-01-01T00:00:00",
        role_versions={"seer": role_hash},
    )

    with pytest.raises(FileNotFoundError):
        build_composite_skill_dir(store, config)
