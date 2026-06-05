"""Tests for temporary skill workspace assembly."""

from __future__ import annotations

import shutil

import pytest

from agent.learning.evolution.config import build_baseline_config
from agent.learning.evolution.models import SkillVersionConfig
from agent.learning.evolution.registry import VersionRegistry
from agent.learning.evolution.config import build_composite_skill_dir


@pytest.mark.asyncio
async def test_build_composite_skill_dir_allows_bootstrap_empty_versions(tmp_path):
    """Explicit empty baseline versions become empty role directories."""
    store = VersionRegistry(tmp_path / "role_versions")
    try:
        await store.ensure_default_baselines()
        config = build_baseline_config(store)

        composite_dir = build_composite_skill_dir(store, config)
        try:
            for role in config.role_versions:
                assert (composite_dir / role).is_dir()
                assert list((composite_dir / role).rglob("*.md")) == []
        finally:
            shutil.rmtree(composite_dir, ignore_errors=True)
    finally:
        store.close()


@pytest.mark.asyncio
async def test_build_composite_skill_dir_raises_for_missing_non_empty_skill_dir(tmp_path):
    """Missing skill files for a non-empty version indicate corrupted storage."""
    store = VersionRegistry(tmp_path / "role_versions")
    try:
        role_hash = await store.publish_skills(
            "seer",
            {"claim.md": "# Claim\n"},
            source="test",
        )
        # Simulate storage corruption: delete skill file records from the database
        store._conn.execute(
            "DELETE FROM skill_files WHERE version_id = ?", (role_hash,)
        )
        store._conn.commit()

        config = SkillVersionConfig(
            name="broken",
            created_at="2026-01-01T00:00:00",
            role_versions={"seer": role_hash},
        )

        with pytest.raises(FileNotFoundError):
            build_composite_skill_dir(store, config)
    finally:
        store.close()
