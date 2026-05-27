"""Tests for agent.selfplay — SelfPlayConfig, run_selfplay, result aggregation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.evaluation.selfplay import (
    SelfPlayConfig,
    SelfPlayGameResult,
    SelfPlayResult,
)


class SelfPlayConfigTests(unittest.TestCase):
    """Test SelfPlayConfig defaults and serialization."""

    def test_default_config(self):
        config = SelfPlayConfig(games=10)
        self.assertEqual(config.games, 10)
        self.assertEqual(config.seed_start, 1)
        self.assertEqual(config.max_days, 20)
        self.assertTrue(config.enable_review)
        self.assertTrue(config.enable_experience)
        self.assertEqual(config.temperature, 0.2)

    def test_custom_config(self):
        config = SelfPlayConfig(
            games=5,
            seed_start=100,
            max_days=15,
            temperature=0.5,
            enable_review=False,
        )
        self.assertEqual(config.games, 5)
        self.assertEqual(config.seed_start, 100)
        self.assertEqual(config.max_days, 15)
        self.assertEqual(config.temperature, 0.5)
        self.assertFalse(config.enable_review)


class SelfPlayGameResultTests(unittest.TestCase):
    """Test single game result."""

    def test_to_dict_includes_all_fields(self):
        result = SelfPlayGameResult(
            game_id="game_001",
            seed=42,
            winner="villagers",
            days=4,
            player_roles={1: "werewolf", 5: "villager"},
            decision_count=50,
            fallback_count=2,
            policy_adjusted_count=3,
            avg_confidence=0.75,
            review_score=7.5,
            output_dir=Path("logs/game_001"),
        )
        d = result.to_dict()
        self.assertEqual(d["game_id"], "game_001")
        self.assertEqual(d["winner"], "villagers")
        self.assertEqual(d["days"], 4)
        self.assertEqual(d["decision_count"], 50)
        self.assertEqual(d["fallback_count"], 2)
        self.assertEqual(d["review_score"], 7.5)

    def test_to_dict_none_review_score(self):
        result = SelfPlayGameResult(
            game_id="g1", seed=1, winner="wolves", days=3,
            player_roles={}, decision_count=10, fallback_count=0,
            policy_adjusted_count=0, avg_confidence=0.5,
            review_score=None, output_dir=Path("."),
        )
        d = result.to_dict()
        self.assertIsNone(d["review_score"])

    def test_to_dict_json_serializable(self):
        result = SelfPlayGameResult(
            game_id="g1", seed=1, winner="villagers", days=4,
            player_roles={1: "werewolf"}, decision_count=20,
            fallback_count=1, policy_adjusted_count=2,
            avg_confidence=0.8, review_score=6.0,
            output_dir=Path("logs/game_001"),
        )
        json_str = json.dumps(result.to_dict(), ensure_ascii=False)
        loaded = json.loads(json_str)
        self.assertEqual(loaded["game_id"], "g1")


class SelfPlayResultTests(unittest.TestCase):
    """Test SelfPlayResult aggregation."""

    def test_empty_result_summary(self):
        config = SelfPlayConfig(games=0)
        result = SelfPlayResult(config=config, games=[])
        s = result.summary
        self.assertEqual(s["games"], 0)

    def test_single_game_summary(self):
        config = SelfPlayConfig(games=1)
        g = SelfPlayGameResult(
            game_id="g1", seed=1, winner="werewolves", days=3,
            player_roles={}, decision_count=10,
            fallback_count=1, policy_adjusted_count=2,
            avg_confidence=0.7, review_score=6.0,
            output_dir=Path("."),
        )
        result = SelfPlayResult(config=config, games=[g])
        s = result.summary
        self.assertEqual(s["games"], 1)
        self.assertEqual(s["werewolf_wins"], 1)
        self.assertEqual(s["villager_wins"], 0)
        self.assertEqual(s["werewolf_win_rate"], 1.0)
        self.assertEqual(s["avg_days"], 3.0)
        self.assertEqual(s["avg_decision_score"], 6.0)

    def test_mixed_games_summary(self):
        config = SelfPlayConfig(games=3)
        games = [
            SelfPlayGameResult(
                game_id=f"g{i}", seed=i, winner=w, days=d,
                player_roles={}, decision_count=10,
                fallback_count=0, policy_adjusted_count=0,
                avg_confidence=0.5, review_score=7.0,
                output_dir=Path("."),
            )
            for i, (w, d) in enumerate(
                [("werewolves", 3), ("werewolves", 4), ("villagers", 5)], 1
            )
        ]
        result = SelfPlayResult(config=config, games=games)
        s = result.summary
        self.assertEqual(s["games"], 3)
        self.assertEqual(s["werewolf_wins"], 2)
        self.assertEqual(s["villager_wins"], 1)
        self.assertAlmostEqual(s["werewolf_win_rate"], round(2 / 3, 3))
        self.assertAlmostEqual(s["avg_days"], 4.0)

    def test_summary_handles_no_review_scores(self):
        config = SelfPlayConfig(games=2)
        games = [
            SelfPlayGameResult(
                game_id=f"g{i}", seed=i, winner="werewolves", days=3,
                player_roles={}, decision_count=5, fallback_count=0,
                policy_adjusted_count=0, avg_confidence=0.5,
                review_score=None, output_dir=Path("."),
            )
            for i in range(1, 3)
        ]
        result = SelfPlayResult(config=config, games=games)
        s = result.summary
        self.assertEqual(s["avg_decision_score"], 0.0)

    def test_summary_computes_fallback_rate(self):
        g = SelfPlayGameResult(
            game_id="g1", seed=1, winner="villagers", days=3,
            player_roles={}, decision_count=100,
            fallback_count=5, policy_adjusted_count=10,
            avg_confidence=0.8, review_score=8.0,
            output_dir=Path("."),
        )
        result = SelfPlayResult(config=SelfPlayConfig(games=1), games=[g])
        s = result.summary
        self.assertEqual(s["fallback_count"], 5)
        self.assertEqual(s["policy_adjusted_count"], 10)
        self.assertEqual(s["fallback_rate"], 0.05)
        self.assertEqual(s["policy_adjusted_rate"], 0.1)

    def test_summary_markdown_output(self):
        g = SelfPlayGameResult(
            game_id="game_001", seed=1, winner="werewolves", days=3,
            player_roles={}, decision_count=10, fallback_count=1,
            policy_adjusted_count=2, avg_confidence=0.7,
            review_score=6.0, output_dir=Path("."),
        )
        result = SelfPlayResult(
            config=SelfPlayConfig(games=1),
            games=[g],
            run_id="run_test",
        )
        md = result.summary_markdown()
        self.assertIn("Selfplay Run", md)
        self.assertIn("run_test", md)
        self.assertIn("game_001", md)
        self.assertIn("werewolves", md)

    def test_write_summary_creates_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            g = SelfPlayGameResult(
                game_id="g1", seed=1, winner="werewolves", days=3,
                player_roles={}, decision_count=10, fallback_count=0,
                policy_adjusted_count=0, avg_confidence=0.5,
                review_score=7.0, output_dir=output / "game_001",
            )
            result = SelfPlayResult(
                config=SelfPlayConfig(games=1),
                games=[g],
                run_id="run_write",
            )
            result.write_summary(output)
            self.assertTrue((output / "summary.json").exists())
            self.assertTrue((output / "summary.md").exists())

    def test_write_summary_json_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            g = SelfPlayGameResult(
                game_id="g1", seed=1, winner="villagers", days=4,
                player_roles={1: "werewolf", 5: "seer"},
                decision_count=20, fallback_count=2,
                policy_adjusted_count=3, avg_confidence=0.75,
                review_score=8.0, output_dir=output / "g1",
            )
            result = SelfPlayResult(
                config=SelfPlayConfig(games=1),
                games=[g],
                run_id="run_json",
            )
            result.write_summary(output)
            with open(output / "summary.json", "r") as f:
                data = json.load(f)
            self.assertEqual(data["games"], 1)
            self.assertEqual(data["villager_wins"], 1)


if __name__ == "__main__":
    unittest.main()
