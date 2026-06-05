"""Tests for agent.evolution.registry -- SQLite-backed version registry."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.learning.evolution.models import (
    BattleMetrics,
    KnowledgePackage,
    ProvenanceRecord,
    SkillFileRef,
)
from agent.learning.evolution.registry import VersionRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_package(
    version_id: str,
    role: str = "seer",
    parent_id: str | None = None,
    skills: list[SkillFileRef] | None = None,
    patterns: list | None = None,
    metrics: BattleMetrics | None = None,
) -> KnowledgePackage:
    return KnowledgePackage(
        version_id=version_id,
        role=role,
        parent_id=parent_id,
        skills=skills or [],
        patterns=patterns or [],
        provenance=ProvenanceRecord(source="seed"),
        metrics=metrics,
        created_at="2026-01-01T00:00:00+08:00",
    )


async def _publish(
    reg: VersionRegistry,
    pkg: KnowledgePackage,
    skill_contents: dict | None = None,
) -> str:
    """Publish with explicit version_id from the package."""
    return await reg.publish(pkg, skill_contents or {}, version_id=pkg.version_id)


# ---------------------------------------------------------------------------
# publish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_stores_version_in_database(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        pkg = _make_package("v1")
        skill_contents = {"strategy.md": "# Seer Strategy\nCheck wolves first."}

        await _publish(reg, pkg, skill_contents)

        # Verify version exists in the database
        loaded = reg.get_package("seer", "v1")
        assert loaded.version_id == "v1"
        assert loaded.role == "seer"

        # Verify skill file content is stored
        contents = reg.read_skill_contents("seer", "v1")
        assert "strategy.md" in contents
        assert "Check wolves first." in contents["strategy.md"]
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_publish_writes_skill_content(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        pkg = _make_package("v1")
        skill_contents = {"tips.md": "# Tips\nBe careful at night."}

        await _publish(reg, pkg, skill_contents)

        contents = reg.read_skill_contents("seer", "v1")
        assert "tips.md" in contents
        assert "Be careful at night." in contents["tips.md"]
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_publish_writes_package_metadata(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        pkg = _make_package("v1", role="witch")

        await _publish(reg, pkg, {})

        loaded = reg.get_package("witch", "v1")
        assert loaded.version_id == "v1"
        assert loaded.role == "witch"
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_publish_records_history_event(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        pkg = _make_package("v1")

        await _publish(reg, pkg, {})

        # Verify the version is listed
        versions = reg.list_versions("seer")
        assert len(versions) == 1
        assert versions[0].version_id == "v1"
        assert versions[0].source == "seed"
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_publish_writes_metrics_metadata(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        metrics = BattleMetrics(win_rate=0.65, games_played=10)
        pkg = _make_package("v1", metrics=metrics)

        await _publish(reg, pkg, {})

        loaded = reg.get_package("seer", "v1")
        assert loaded.metrics is not None
        assert loaded.metrics.win_rate == 0.65
        assert loaded.metrics.games_played == 10
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_publish_returns_version_id(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        pkg = _make_package("v42")

        result = await _publish(reg, pkg, {})
        assert result == "v42"
    finally:
        reg.close()


# ---------------------------------------------------------------------------
# get_baseline
# ---------------------------------------------------------------------------


def test_get_baseline_returns_none_initially(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        assert reg.get_baseline("seer") is None
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_get_baseline_returns_id_after_set(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        pkg = _make_package("v1")
        await _publish(reg, pkg, {})
        await reg.set_baseline("seer", "v1", expected_current=None)

        assert reg.get_baseline("seer") == "v1"
    finally:
        reg.close()


# ---------------------------------------------------------------------------
# set_baseline -- CAS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_baseline_cas_success(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        pkg = _make_package("v1")
        await _publish(reg, pkg, {})

        result = await reg.set_baseline("seer", "v1", expected_current=None)
        assert result is True
        assert reg.get_baseline("seer") == "v1"
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_set_baseline_cas_mismatch(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        pkg1 = _make_package("v1")
        pkg2 = _make_package("v2")
        await _publish(reg, pkg1, {})
        await _publish(reg, pkg2, {})
        await reg.set_baseline("seer", "v1", expected_current=None)

        result = await reg.set_baseline("seer", "v2", expected_current="v_wrong")
        assert result is False
        assert reg.get_baseline("seer") == "v1"
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_set_baseline_cas_update(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        pkg1 = _make_package("v1")
        pkg2 = _make_package("v2")
        await _publish(reg, pkg1, {})
        await _publish(reg, pkg2, {})
        await reg.set_baseline("seer", "v1", expected_current=None)

        result = await reg.set_baseline("seer", "v2", expected_current="v1")
        assert result is True
        assert reg.get_baseline("seer") == "v2"
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_set_baseline_nonexistent_version(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        result = await reg.set_baseline("seer", "v_nonexistent", expected_current=None)
        assert result is False
    finally:
        reg.close()


# ---------------------------------------------------------------------------
# list_versions
# ---------------------------------------------------------------------------


def test_list_versions_empty(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        assert reg.list_versions("seer") == []
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_list_versions_returns_published(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        await _publish(reg, _make_package("v1"), {})
        await _publish(reg, _make_package("v2"), {})
        await _publish(reg, _make_package("v3"), {})

        versions = reg.list_versions("seer")
        assert len(versions) == 3
        ids = [v.version_id for v in versions]
        assert ids == ["v1", "v2", "v3"]
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_list_versions_marks_baseline(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        await _publish(reg, _make_package("v1"), {})
        await _publish(reg, _make_package("v2"), {})
        await reg.set_baseline("seer", "v2", expected_current=None)

        versions = reg.list_versions("seer")
        baseline_flags = {v.version_id: v.is_baseline for v in versions}
        assert baseline_flags["v1"] is False
        assert baseline_flags["v2"] is True
    finally:
        reg.close()


# ---------------------------------------------------------------------------
# list_roles
# ---------------------------------------------------------------------------


def test_list_roles_empty(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        assert reg.list_roles() == []
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_list_roles_returns_published(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        await _publish(reg, _make_package("v1", role="seer"), {})
        await _publish(reg, _make_package("v1", role="witch"), {})
        await _publish(reg, _make_package("v1", role="werewolf"), {})

        roles = reg.list_roles()
        assert sorted(roles) == ["seer", "werewolf", "witch"]
    finally:
        reg.close()


# ---------------------------------------------------------------------------
# reject
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_appends_event(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        await _publish(reg, _make_package("v1"), {})

        await reg.reject("seer", "v1", "low win rate")

        # Verify the rejection is recorded in history (the latest event for this version)
        rows = reg._conn.execute(
            "SELECT * FROM role_baseline_history WHERE role = 'seer' AND version_id = 'v1' ORDER BY id DESC"
        ).fetchall()
        assert len(rows) >= 2  # created + rejected
        rejection = rows[0]  # most recent
        assert "rejected" in rejection["reason"]
        assert "low win rate" in rejection["reason"]
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_reject_does_not_affect_list_versions(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        await _publish(reg, _make_package("v1"), {})
        await reg.reject("seer", "v1", "bad")

        versions = reg.list_versions("seer")
        assert len(versions) == 1
    finally:
        reg.close()


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_diff_patterns_added(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        old_patterns = [{"pattern_id": "p1", "confidence": 0.5}]
        new_patterns = [
            {"pattern_id": "p1", "confidence": 0.5},
            {"pattern_id": "p2", "confidence": 0.8},
        ]

        pkg_old = _make_package("v1", patterns=old_patterns)
        pkg_new = _make_package("v2", patterns=new_patterns, parent_id="v1")
        await _publish(reg, pkg_old, {})
        await _publish(reg, pkg_new, {})

        diff = reg.diff("seer", "v1", "v2")

        assert len(diff.patterns_added) == 1
        assert diff.patterns_added[0]["pattern_id"] == "p2"
        assert len(diff.patterns_removed) == 0
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_diff_patterns_removed(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        old_patterns = [
            {"pattern_id": "p1", "confidence": 0.5},
            {"pattern_id": "p2", "confidence": 0.3},
        ]
        new_patterns = [{"pattern_id": "p1", "confidence": 0.5}]

        pkg_old = _make_package("v1", patterns=old_patterns)
        pkg_new = _make_package("v2", patterns=new_patterns, parent_id="v1")
        await _publish(reg, pkg_old, {})
        await _publish(reg, pkg_new, {})

        diff = reg.diff("seer", "v1", "v2")

        assert len(diff.patterns_removed) == 1
        assert diff.patterns_removed[0]["pattern_id"] == "p2"
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_diff_patterns_updated(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        old_patterns = [{"pattern_id": "p1", "confidence": 0.5}]
        new_patterns = [{"pattern_id": "p1", "confidence": 0.8}]

        pkg_old = _make_package("v1", patterns=old_patterns)
        pkg_new = _make_package("v2", patterns=new_patterns, parent_id="v1")
        await _publish(reg, pkg_old, {})
        await _publish(reg, pkg_new, {})

        diff = reg.diff("seer", "v1", "v2")

        assert len(diff.patterns_updated) == 1
        assert diff.patterns_updated[0]["confidence"] == 0.8
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_diff_metrics_delta(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        old_metrics = BattleMetrics(win_rate=0.5, score=0.6, games_played=10)
        new_metrics = BattleMetrics(win_rate=0.7, score=0.6, games_played=20)

        pkg_old = _make_package("v1", metrics=old_metrics)
        pkg_new = _make_package("v2", metrics=new_metrics, parent_id="v1")
        await _publish(reg, pkg_old, {})
        await _publish(reg, pkg_new, {})

        diff = reg.diff("seer", "v1", "v2")

        assert diff.metrics_delta is not None
        assert diff.metrics_delta["win_rate"] == 0.2
        assert diff.metrics_delta["games_played"] == 10.0
        assert "score" not in diff.metrics_delta
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_diff_skill_changes(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        pkg_old = _make_package("v1", skills=[SkillFileRef("tips.md", "hash_a")])
        pkg_new = _make_package(
            "v2",
            skills=[SkillFileRef("tips.md", "hash_b")],
            parent_id="v1",
        )
        await _publish(reg, pkg_old, {"tips.md": "# Old tips"})
        await _publish(reg, pkg_new, {"tips.md": "# New tips"})

        diff = reg.diff("seer", "v1", "v2")

        assert len(diff.skill_changes) == 1
        assert diff.skill_changes[0]["file"] == "tips.md"
        assert diff.skill_changes[0]["action"] == "modified"
    finally:
        reg.close()


# ---------------------------------------------------------------------------
# gc
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gc_keeps_recent_versions(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        for i in range(5):
            await _publish(reg, _make_package(f"v{i}"), {})

        removed = reg.gc("seer", keep=10)
        assert removed == 0
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_gc_removes_old_versions(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        for i in range(15):
            await _publish(reg, _make_package(f"v{i:02d}"), {})

        removed = reg.gc("seer", keep=5)
        assert removed > 0

        versions = reg.list_versions("seer")
        remaining_ids = [v.version_id for v in versions]
        assert "v14" in remaining_ids
        assert "v13" in remaining_ids
    finally:
        reg.close()


@pytest.mark.asyncio
async def test_gc_keeps_baseline(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        for i in range(15):
            parent = f"v{i-1:02d}" if i > 0 else None
            await _publish(reg, _make_package(f"v{i:02d}", parent_id=parent), {})

        await reg.set_baseline("seer", "v05", expected_current=None)

        removed = reg.gc("seer", keep=3)
        assert removed > 0

        versions = reg.list_versions("seer")
        remaining_ids = {v.version_id for v in versions}
        assert "v05" in remaining_ids
    finally:
        reg.close()


def test_gc_with_no_versions(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        removed = reg.gc("seer", keep=10)
        assert removed == 0
    finally:
        reg.close()


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------


def test_validate_name_rejects_empty():
    with pytest.raises(ValueError, match="Empty"):
        VersionRegistry._validate_name("", "role")


def test_validate_name_rejects_path_traversal():
    with pytest.raises(ValueError, match="Unsafe"):
        VersionRegistry._validate_name("../etc", "role")
    with pytest.raises(ValueError, match="Unsafe"):
        VersionRegistry._validate_name("foo/bar", "version_id")


# ---------------------------------------------------------------------------
# get_package
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_package_loads_published(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        pkg = _make_package("v1", role="witch")
        await _publish(reg, pkg, {})

        loaded = reg.get_package("witch", "v1")
        assert loaded.version_id == "v1"
        assert loaded.role == "witch"
    finally:
        reg.close()


def test_get_package_not_found(tmp_path: Path):
    reg = VersionRegistry(tmp_path)
    try:
        with pytest.raises(FileNotFoundError):
            reg.get_package("seer", "v_nonexistent")
    finally:
        reg.close()
