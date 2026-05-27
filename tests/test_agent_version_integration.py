"""Integration test for agent version management flow."""
import json
import tempfile
from pathlib import Path

from agent.versioning.manifest import (
    AgentVersionManifest,
    VersionStatus,
    create_agent_version,
    load_manifest,
    save_manifest,
    evaluate_promotion,
    update_manifest_status,
    PromotionVerdict,
    PathConfig,
    ModelConfig,
    RuntimeConfig,
)
from agent.evaluation.leaderboard import LeaderboardEntry, aggregate_summaries


def _make_leaderboard_entry(
    version: str,
    *,
    games: int = 20,
    avg_score: float = 6.0,
    bad_case_count: float = 2.0,
    fallback_rate: float = 0.05,
    policy_adjusted_rate: float = 0.02,
    werewolf_win_rate: float = 0.45,
    villager_win_rate: float = 0.55,
) -> LeaderboardEntry:
    """Helper to build a LeaderboardEntry with sensible defaults."""
    return LeaderboardEntry(
        version=version,
        games=games,
        werewolf_win_rate=werewolf_win_rate,
        villager_win_rate=villager_win_rate,
        avg_score=avg_score,
        fallback_rate=fallback_rate,
        policy_adjusted_rate=policy_adjusted_rate,
        bad_case_count=bad_case_count,
    )


def test_full_version_lifecycle():
    """End-to-end: create baseline -> create candidate -> evaluate -> promote."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        versions_root = root / "agent_versions"

        # Setup: create source skills and memory
        source_skills = root / "skills" / "werewolf"
        source_skills.mkdir(parents=True)
        (source_skills / "test_skill.md").write_text(
            "---\nname: test_skill\nrole: werewolf\nevolvable: true\n---\n\noriginal body",
            encoding="utf-8",
        )
        source_memory = root / "memory"
        source_memory.mkdir()
        (source_memory / "werewolf.json").write_text('{"role":"werewolf"}', encoding="utf-8")

        # Step 1: Create baseline version.
        # create_agent_version requires a base with a manifest, so we build
        # the baseline manually first.
        baseline_dir = versions_root / "baseline"
        baseline_dir.mkdir(parents=True)
        (baseline_dir / "skills").mkdir()
        (baseline_dir / "memory").mkdir()
        baseline_manifest = AgentVersionManifest(
            version="baseline",
            status=VersionStatus.CANDIDATE,
            notes=["baseline version"],
            paths=PathConfig(skills="./skills", memory="./memory"),
        )
        save_manifest(baseline_manifest, baseline_dir / "manifest.json")

        # Copy source files into baseline
        import shutil
        shutil.copytree(source_skills, baseline_dir / "skills" / "werewolf", dirs_exist_ok=True)
        shutil.copytree(source_memory, baseline_dir / "memory", dirs_exist_ok=True)

        # Step 2: Create candidate version from baseline
        candidate_dir = create_agent_version(
            name="candidate_v2",
            base="baseline",
            versions_root=versions_root,
            source_skill_dir=source_skills,
            source_memory_dir=source_memory,
            notes="candidate with improvements",
        )
        assert candidate_dir == versions_root / "candidate_v2"
        candidate_manifest = load_manifest(candidate_dir / "manifest.json")
        assert candidate_manifest.version == "candidate_v2"
        assert candidate_manifest.status == VersionStatus.CANDIDATE
        assert candidate_manifest.base_version == "baseline"

        # Step 3: Simulate leaderboard results
        baseline_entry = _make_leaderboard_entry("baseline", avg_score=6.0, bad_case_count=3.0)
        candidate_entry = _make_leaderboard_entry(
            "candidate_v2",
            avg_score=6.5,
            bad_case_count=2.0,
            fallback_rate=0.04,
        )

        # Step 4: Evaluate promotion
        verdict = evaluate_promotion(candidate_entry, baseline_entry)
        assert isinstance(verdict, PromotionVerdict)
        # Score improved by 8.3% (6.5 vs 6.0), bad_case decreased, fallback decreased
        assert verdict.promoted is True, f"Should be promoted: {verdict.reasons}"

        # Step 5: Update manifest status
        candidate_path = candidate_dir / "manifest.json"
        update_manifest_status(
            candidate_path,
            status=VersionStatus.VALIDATED,
            evaluation_update={
                "score": candidate_entry.avg_score,
                "baseline_score": baseline_entry.avg_score,
                "win_rate": candidate_entry.werewolf_win_rate,
                "bad_case_count": candidate_entry.bad_case_count,
            },
        )

        # Verify final state
        final = load_manifest(candidate_path)
        assert final.status == VersionStatus.VALIDATED
        assert final.evaluation is not None
        assert final.evaluation["score"] == 6.5
        assert final.evaluation["baseline_score"] == 6.0


def test_promotion_reject_on_bad_case_increase():
    """Candidate with higher score but more bad cases should be rejected."""
    baseline = _make_leaderboard_entry("baseline", avg_score=6.0, bad_case_count=2.0)
    candidate = _make_leaderboard_entry("candidate", avg_score=6.5, bad_case_count=4.0)
    verdict = evaluate_promotion(candidate, baseline)
    assert verdict.promoted is False
    assert any("bad_case" in r for r in verdict.reasons)


def test_promotion_reject_on_fallback_increase():
    """Candidate with higher fallback rate should be rejected."""
    baseline = _make_leaderboard_entry("baseline", avg_score=6.0, fallback_rate=0.05)
    candidate = _make_leaderboard_entry("candidate", avg_score=6.5, fallback_rate=0.10)
    verdict = evaluate_promotion(candidate, baseline)
    assert verdict.promoted is False
    assert any("fallback" in r for r in verdict.reasons)


def test_version_spec_from_manifest():
    """Test building VersionSpec from manifest."""
    from agent.evaluation.version_battle import version_spec_from_manifest

    with tempfile.TemporaryDirectory() as td:
        manifest = AgentVersionManifest(
            version="test_v1",
            status=VersionStatus.CANDIDATE,
            notes=["test"],
            paths=PathConfig(skills="./skills"),
            model=ModelConfig(model="gpt-4o", temperature=0.3),
            runtime=RuntimeConfig(
                tot_enabled=True,
                got_enabled=False,
                got_trigger_policy="always",
                got_trigger_threshold=0.5,
            ),
        )
        manifest_path = Path(td) / "manifest.json"
        save_manifest(manifest, manifest_path)
        spec = version_spec_from_manifest(manifest_path)
        assert spec.name == "test_v1"
        assert spec.model_name == "gpt-4o"
        assert spec.temperature == 0.3
        assert spec.tot_enabled is True
        assert spec.got_enabled is False
        assert spec.got_trigger_policy == "always"
        assert spec.got_trigger_threshold == 0.5
