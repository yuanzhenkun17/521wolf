"""Tests for agent.version_battle."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from agent.evaluation.selfplay import SelfPlayConfig, SelfPlayGameResult, SelfPlayResult
from agent.evaluation.version_battle import (
    VersionBattleConfig,
    VersionSpec,
    run_version_battle,
)


class VersionBattleTests(unittest.TestCase):
    def test_version_spec_to_dict(self):
        spec = VersionSpec(
            name="v2_exp",
            skill_dir=Path("skillsets/v2/skills"),
            model_name="demo-model",
            temperature=0.3,
            notes="experiment",
        )
        data = spec.to_dict()

        self.assertEqual(data["name"], "v2_exp")
        self.assertEqual(data["model_name"], "demo-model")
        self.assertEqual(data["temperature"], 0.3)
        self.assertIn("skillsets", data["skill_dir"])

    def test_run_version_battle_uses_same_seed_range_and_writes_leaderboard(self):
        calls: list[SelfPlayConfig] = []

        async def fake_runner(config: SelfPlayConfig, **kwargs):
            calls.append(config)
            winner = "werewolves" if config.agent_version == "v1" else "villagers"
            score = 5.0 if config.agent_version == "v1" else 8.0
            game = SelfPlayGameResult(
                game_id="game_001",
                seed=config.seed_start,
                winner=winner,
                days=3,
                player_roles={},
                decision_count=10,
                fallback_count=0,
                policy_adjusted_count=0,
                avg_confidence=0.7,
                review_score=score,
                output_dir=config.output_dir / "fake",
                avg_speech_score=score,
                avg_vote_score=score,
                avg_skill_score=score,
                vote_accuracy=score / 10,
                skill_accuracy=score / 10,
            )
            return SelfPlayResult(
                config=config,
                games=[game],
                run_id=f"run_{config.agent_version}",
            )

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            result = asyncio.run(run_version_battle(
                VersionBattleConfig(
                    versions=[
                        VersionSpec(name="v1", notes="baseline"),
                        VersionSpec(name="v2", skill_dir=Path("skills")),
                    ],
                    games_per_version=1,
                    seed_start=42,
                    output_dir=output,
                ),
                runner=fake_runner,
            ))

            self.assertEqual(len(calls), 2)
            self.assertEqual({call.seed_start for call in calls}, {42})
            self.assertEqual({call.games for call in calls}, {1})
            self.assertEqual(result.leaderboard[0].version, "v2")
            self.assertTrue((output / "leaderboard.json").exists())
            self.assertTrue((output / "leaderboard.md").exists())
            self.assertTrue((output / "version_battle_result.json").exists())


if __name__ == "__main__":
    unittest.main()
