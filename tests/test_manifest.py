"""Tests for AgentVersionManifest."""
import json
from pathlib import Path
from agent.versioning.manifest import (
    AgentVersionManifest, VersionStatus, RuntimeConfig, ModelConfig,
    load_manifest, save_manifest, resolve_manifest_path,
    create_agent_version, evaluate_promotion, PromotionVerdict,
    update_manifest_status, rollback_version,
)
from agent.evaluation.leaderboard import LeaderboardEntry


def test_manifest_roundtrip(tmp_path):
    m = AgentVersionManifest(version="test_v1", status=VersionStatus.CANDIDATE)
    save_manifest(m, tmp_path / "manifest.json")
    loaded = load_manifest(tmp_path / "manifest.json")
    assert loaded.version == "test_v1"
    assert loaded.status == VersionStatus.CANDIDATE


def test_resolve_relative_path(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    resolved = resolve_manifest_path(manifest_path, "./skills")
    assert resolved == tmp_path / "skills"


def test_resolve_absolute_path(tmp_path):
    abs_path = tmp_path / "absolute_skills"
    resolved = resolve_manifest_path(tmp_path / "manifest.json", str(abs_path))
    assert resolved == abs_path


def test_create_agent_version(tmp_path):
    versions_root = tmp_path / "agent_versions"
    base_dir = versions_root / "baseline"
    (base_dir / "skills" / "werewolf").mkdir(parents=True)
    (base_dir / "skills" / "werewolf" / "fake_seer.md").write_text(
        "---" + chr(10) + "name: fake_seer" + chr(10) + "---" + chr(10) + "body",
        encoding="utf-8")
    (base_dir / "memory").mkdir()
    (base_dir / "memory" / "werewolf.json").write_text("{}", encoding="utf-8")
    save_manifest(AgentVersionManifest(version="baseline", status=VersionStatus.VALIDATED), base_dir / "manifest.json")
    candidate = create_agent_version(name="dream_v1", base="baseline", versions_root=versions_root)
    assert (candidate / "skills" / "werewolf" / "fake_seer.md").exists()
    assert (candidate / "memory" / "werewolf.json").exists()
    m = load_manifest(candidate / "manifest.json")
    assert m.base_version == "baseline"
    assert m.status == VersionStatus.CANDIDATE


def test_promotion_pass():
    base = LeaderboardEntry(version="base", games=20, avg_score=6.0, bad_case_count=3, fallback_rate=0.05, policy_adjusted_rate=0.1, werewolf_win_rate=0.5)
    cand = LeaderboardEntry(version="v1", games=20, avg_score=7.0, bad_case_count=2, fallback_rate=0.04, policy_adjusted_rate=0.08, werewolf_win_rate=0.48)
    verdict = evaluate_promotion(cand, base)
    assert verdict.promoted is True


def test_promotion_fail_bad_case():
    base = LeaderboardEntry(version="base", games=20, avg_score=6.0, bad_case_count=2, fallback_rate=0.05, policy_adjusted_rate=0.1, werewolf_win_rate=0.5)
    cand = LeaderboardEntry(version="v1", games=20, avg_score=7.0, bad_case_count=5, fallback_rate=0.04, policy_adjusted_rate=0.08, werewolf_win_rate=0.5)
    verdict = evaluate_promotion(cand, base)
    assert verdict.promoted is False
    assert any("bad_case" in r for r in verdict.reasons)


def test_rollback_version(tmp_path):
    versions_root = tmp_path / "agent_versions"
    for name in ["v1", "v2"]:
        d = versions_root / name
        d.mkdir(parents=True)
        (d / "skills").mkdir()
        (d / "memory").mkdir()
        save_manifest(AgentVersionManifest(version=name, status=VersionStatus.VALIDATED if name == "v2" else VersionStatus.ARCHIVED), d / "manifest.json")
    rollback_version("v2", "v1", versions_root=versions_root, reason="regression")
    m1 = load_manifest(versions_root / "v1" / "manifest.json")
    m2 = load_manifest(versions_root / "v2" / "manifest.json")
    assert m1.status == VersionStatus.VALIDATED
    assert m2.status == VersionStatus.ARCHIVED
