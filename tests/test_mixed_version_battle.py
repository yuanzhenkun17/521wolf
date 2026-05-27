from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.evaluation.mixed_version_battle import (
    MixedGameResult,
    MixedVersionBattleConfig,
    TeamVersionMatchup,
    run_team_mixed_version_battle,
)
from agent.evaluation.version_battle import VersionSpec


class MixedVersionBattleTests(unittest.IsolatedAsyncioTestCase):
    async def test_team_battle_runs_mirrored_games_and_writes_leaderboard(self):
        calls = []

        async def fake_game_runner(config, **_kwargs):
            calls.append(config)
            winner = "werewolves" if config.wolves_version.name == "v2" else "villagers"
            return MixedGameResult(
                game_id=config.game_id,
                seed=config.seed,
                wolves_version=config.wolves_version.name,
                villagers_version=config.villagers_version.name,
                winner=winner,
                days=3,
                player_roles={1: "werewolf", 2: "villager"},
                player_versions={
                    1: config.wolves_version.name,
                    2: config.villagers_version.name,
                },
                decision_count_by_version={
                    config.wolves_version.name: 2,
                    config.villagers_version.name: 2,
                },
                confidence_by_version={
                    config.wolves_version.name: 0.7,
                    config.villagers_version.name: 0.6,
                },
                review_score_by_version={
                    config.wolves_version.name: 8.0 if config.wolves_version.name == "v2" else 5.0,
                    config.villagers_version.name: 8.0 if config.villagers_version.name == "v2" else 5.0,
                },
                output_dir=config.output_dir,
            )

        with tempfile.TemporaryDirectory() as tmp:
            result = await run_team_mixed_version_battle(
                MixedVersionBattleConfig(
                    matchup=TeamVersionMatchup(
                        version_a=VersionSpec(name="v1"),
                        version_b=VersionSpec(name="v2"),
                    ),
                    games_per_side=2,
                    seed_start=42,
                    output_dir=Path(tmp),
                ),
                game_runner=fake_game_runner,
            )

            self.assertEqual(len(calls), 4)
            self.assertEqual([call.seed for call in calls], [42, 42, 43, 43])
            self.assertEqual(calls[0].wolves_version.name, "v1")
            self.assertEqual(calls[0].villagers_version.name, "v2")
            self.assertEqual(calls[1].wolves_version.name, "v2")
            self.assertEqual(calls[1].villagers_version.name, "v1")
            self.assertEqual(result.leaderboard[0].version, "v2")
            self.assertEqual(result.leaderboard[0].games, 4)
            self.assertEqual(result.leaderboard[0].werewolf_win_rate, 1.0)
            self.assertEqual(result.leaderboard[0].villager_win_rate, 1.0)
            self.assertTrue((Path(tmp) / "leaderboard.json").exists())
            self.assertTrue((Path(tmp) / "mixed_version_battle_result.json").exists())


if __name__ == "__main__":
    unittest.main()
