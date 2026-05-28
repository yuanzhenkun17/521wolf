from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.evaluation.evolution import EvolutionPipelineConfig, run_evolution_pipeline
from agent.evaluation.leaderboard import LeaderboardEntry
from agent.evaluation.selfplay import SelfPlayGameResult, SelfPlayResult
from agent.evaluation.version_battle import VersionBattleResult
from agent.versioning.manifest import (
    AgentVersionManifest,
    ModelConfig,
    VersionStatus,
    load_manifest,
    save_manifest,
)


def _write_base_version(root: Path) -> None:
    base_dir = root / "baseline"
    skill_dir = base_dir / "skills" / "werewolf"
    memory_dir = base_dir / "memory"
    skill_dir.mkdir(parents=True)
    memory_dir.mkdir(parents=True)
    (skill_dir / "fake_seer.md").write_text(
        "---\nname: fake_seer\nrole: werewolf\nevolvable: true\n---\n\nbase skill\n",
        encoding="utf-8",
    )
    (memory_dir / "werewolf.json").write_text('{"role":"werewolf"}', encoding="utf-8")
    save_manifest(
        AgentVersionManifest(
            version="baseline",
            status=VersionStatus.VALIDATED,
            model=ModelConfig(model="stub-model", temperature=0.3),
        ),
        base_dir / "manifest.json",
    )


def _training_result(config) -> SelfPlayResult:
    run_dir = config.output_dir / "train_run"
    memory_dir = run_dir / "memory_candidate"
    memory_dir.mkdir(parents=True)
    (memory_dir / "werewolf.json").write_text('{"role":"werewolf","source_card_count":1}', encoding="utf-8")
    game = SelfPlayGameResult(
        game_id="game_001",
        seed=config.seed_start,
        winner="werewolves",
        days=3,
        player_roles={1: "werewolf"},
        decision_count=4,
        fallback_count=0,
        policy_adjusted_count=0,
        avg_confidence=0.8,
        review_score=6.0,
        output_dir=run_dir / "games" / "game_001",
    )
    return SelfPlayResult(config=config, games=[game], run_id="train_run")


class EvolutionPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_pipeline_creates_candidate_and_promotes_when_better(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            versions_root = root / "agent_versions"
            _write_base_version(versions_root)

            async def fake_selfplay(config, **_kwargs):
                self.assertTrue(config.enable_mid_memory)
                return _training_result(config)

            async def fake_battle(config, **_kwargs):
                leaderboard = [
                    LeaderboardEntry(version="baseline", games=2, avg_score=5.0, werewolf_win_rate=0.5),
                    LeaderboardEntry(version="dream_v1", games=2, avg_score=6.0, werewolf_win_rate=0.5),
                ]
                return VersionBattleResult(
                    config=config,
                    runs={},
                    leaderboard=leaderboard,
                    output_dir=config.output_dir,
                )

            result = await run_evolution_pipeline(
                EvolutionPipelineConfig(
                    base_version="baseline",
                    candidate_version="dream_v1",
                    training_games=1,
                    battle_games=2,
                    output_dir=root / "runs" / "evolution",
                    versions_root=versions_root,
                    auto_apply_skill_proposals=False,
                ),
                selfplay_runner=fake_selfplay,
                battle_runner=fake_battle,
            )

            manifest_path = versions_root / "dream_v1" / "manifest.json"
            manifest = load_manifest(manifest_path)
            self.assertTrue(result.promoted)
            self.assertEqual(manifest.status, VersionStatus.VALIDATED)
            self.assertEqual(manifest.training_source["training_run_id"], "train_run")
            self.assertTrue((versions_root / "dream_v1" / "skills" / "werewolf" / "fake_seer.md").exists())
            self.assertTrue((versions_root / "dream_v1" / "memory" / "werewolf.json").exists())
            self.assertTrue((result.output_dir / "result.json").exists())

    async def test_pipeline_rejects_candidate_when_score_does_not_improve(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            versions_root = root / "agent_versions"
            _write_base_version(versions_root)

            async def fake_selfplay(config, **_kwargs):
                self.assertTrue(config.enable_mid_memory)
                return _training_result(config)

            async def fake_battle(config, **_kwargs):
                leaderboard = [
                    LeaderboardEntry(version="baseline", games=2, avg_score=5.0, werewolf_win_rate=0.5),
                    LeaderboardEntry(version="dream_v1", games=2, avg_score=5.0, werewolf_win_rate=0.5),
                ]
                return VersionBattleResult(
                    config=config,
                    runs={},
                    leaderboard=leaderboard,
                    output_dir=config.output_dir,
                )

            result = await run_evolution_pipeline(
                EvolutionPipelineConfig(
                    base_version="baseline",
                    candidate_version="dream_v1",
                    training_games=1,
                    battle_games=2,
                    output_dir=root / "runs" / "evolution",
                    versions_root=versions_root,
                ),
                selfplay_runner=fake_selfplay,
                battle_runner=fake_battle,
            )

            manifest = load_manifest(versions_root / "dream_v1" / "manifest.json")
            self.assertFalse(result.promoted)
            self.assertEqual(manifest.status, VersionStatus.REJECTED)
            self.assertTrue(result.reasons)


if __name__ == "__main__":
    unittest.main()
