"""Tests for agent.leaderboard — LeaderboardEntry, aggregation, markdown output."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.learning.leaderboard import (
    LeaderboardEntry,
    aggregate_summaries,
    build_leaderboard,
    leaderboard_to_markdown,
    leaderboard_detail_markdown,
    load_summaries_from_runs,
    write_leaderboard,
)


class LeaderboardEntryTests(unittest.TestCase):
    """Test LeaderboardEntry defaults and serialization."""

    def test_default_construction(self):
        entry = LeaderboardEntry(version="v2_base")
        self.assertEqual(entry.games, 0)
        self.assertEqual(entry.version, "v2_base")
        self.assertEqual(entry.werewolf_win_rate, 0.0)

    def test_to_dict(self):
        entry = LeaderboardEntry(
            version="v2_base", games=20,
            werewolf_win_rate=0.5, villager_win_rate=0.5,
            avg_days=3.5, avg_score=7.0,
            avg_speech_score=6.0, avg_vote_score=7.0,
            avg_skill_score=7.5, vote_accuracy=0.6,
            skill_accuracy=0.65, fallback_rate=0.04,
            policy_adjusted_rate=0.06, avg_confidence=0.75,
            notes="baseline",
            run_ids=["run_001"],
        )
        d = entry.to_dict()
        self.assertEqual(d["version"], "v2_base")
        self.assertEqual(d["games"], 20)
        self.assertAlmostEqual(d["werewolf_win_rate"], 0.5)

    def test_to_dict_json_serializable(self):
        entry = LeaderboardEntry(version="test")
        json_str = json.dumps(entry.to_dict(), ensure_ascii=False)
        loaded = json.loads(json_str)
        self.assertEqual(loaded["version"], "test")


class AggregateSummariesTests(unittest.TestCase):
    """Test aggregation from multiple summary dicts."""

    def test_empty_list(self):
        entry = aggregate_summaries([], version="empty")
        self.assertEqual(entry.games, 0)

    def test_single_summary(self):
        summaries = [{
            "run_id": "run_001",
            "games": 10,
            "werewolf_wins": 4,
            "villager_wins": 6,
            "avg_days": 3.5,
            "avg_decision_score": 7.0,
            "avg_speech_score": 6.0,
            "avg_vote_score": 7.0,
            "avg_skill_score": 7.5,
            "vote_accuracy": 0.6,
            "skill_accuracy": 0.65,
            "fallback_count": 4,
            "policy_adjusted_count": 6,
            "total_decisions": 100,
            "avg_confidence": 0.75,
        }]
        entry = aggregate_summaries(summaries, version="v2_base")
        self.assertEqual(entry.games, 10)
        self.assertEqual(entry.werewolf_win_rate, 0.4)
        self.assertEqual(entry.villager_win_rate, 0.6)
        self.assertEqual(entry.run_ids, ["run_001"])

    def test_multiple_summaries(self):
        summaries = [
            {
                "games": 10, "werewolf_wins": 4, "villager_wins": 6,
                "avg_days": 3.0, "avg_decision_score": 6.0,
                "avg_speech_score": 5.0, "avg_vote_score": 6.0,
                "avg_skill_score": 6.5, "vote_accuracy": 0.5,
                "skill_accuracy": 0.55, "fallback_count": 2,
                "policy_adjusted_count": 3, "total_decisions": 50,
                "avg_confidence": 0.7, "run_id": "r1",
            },
            {
                "games": 10, "werewolf_wins": 6, "villager_wins": 4,
                "avg_days": 4.0, "avg_decision_score": 8.0,
                "avg_speech_score": 7.0, "avg_vote_score": 8.0,
                "avg_skill_score": 8.5, "vote_accuracy": 0.7,
                "skill_accuracy": 0.75, "fallback_count": 1,
                "policy_adjusted_count": 2, "total_decisions": 50,
                "avg_confidence": 0.8, "run_id": "r2",
            },
        ]
        entry = aggregate_summaries(summaries, version="combined")
        self.assertEqual(entry.games, 20)
        self.assertAlmostEqual(entry.werewolf_win_rate, 0.5)
        self.assertAlmostEqual(entry.avg_days, 3.5)
        self.assertAlmostEqual(entry.avg_score, 7.0)
        self.assertEqual(len(entry.run_ids), 2)

    def test_handles_missing_fields(self):
        summaries = [{"games": 5, "werewolf_wins": 2, "villager_wins": 3}]
        entry = aggregate_summaries(summaries, version="minimal")
        self.assertEqual(entry.games, 5)
        self.assertEqual(entry.avg_days, 0.0)
        self.assertEqual(entry.fallback_rate, 0.0)

    def test_zero_games_skipped(self):
        summaries = [
            {"games": 0},
            {"games": 10, "werewolf_wins": 5, "villager_wins": 5,
             "avg_days": 3.0, "avg_decision_score": 7.0,
             "avg_speech_score": 6.0, "avg_vote_score": 6.0,
             "avg_skill_score": 7.0, "vote_accuracy": 0.6,
             "skill_accuracy": 0.6, "fallback_count": 2,
             "policy_adjusted_count": 3, "total_decisions": 50,
             "avg_confidence": 0.7},
        ]
        entry = aggregate_summaries(summaries, version="filtered")
        self.assertEqual(entry.games, 10)

    def test_label_alias(self):
        summaries = [{
            "games": 5, "werewolf_wins": 2, "villager_wins": 3,
            "avg_days": 3.0, "avg_decision_score": 7.0,
            "avg_speech_score": 6.0, "avg_vote_score": 6.0,
            "avg_skill_score": 7.0, "vote_accuracy": 0.6,
            "skill_accuracy": 0.6, "fallback_count": 1,
            "policy_adjusted_count": 2, "total_decisions": 25,
            "avg_confidence": 0.7,
        }]
        entry = aggregate_summaries(summaries, label="via_label")
        self.assertEqual(entry.version, "via_label")


class BuildLeaderboardTests(unittest.TestCase):
    """Test leaderboard sorting."""

    def test_sort_by_score_descending(self):
        entries = [
            LeaderboardEntry(version="low", avg_score=5.0, games=1),
            LeaderboardEntry(version="high", avg_score=9.0, games=1),
            LeaderboardEntry(version="mid", avg_score=7.0, games=1),
        ]
        sorted_entries = build_leaderboard(entries)
        self.assertEqual(sorted_entries[0].version, "high")
        self.assertEqual(sorted_entries[1].version, "mid")
        self.assertEqual(sorted_entries[2].version, "low")

    def test_empty_list(self):
        self.assertEqual(build_leaderboard([]), [])


class MarkdownOutputTests(unittest.TestCase):
    """Test markdown table generation."""

    def test_table_headers(self):
        entries = [
            LeaderboardEntry(
                version="v2_base", games=10,
                werewolf_win_rate=0.5, villager_win_rate=0.5,
                avg_score=7.0, avg_speech_score=6.0,
                avg_vote_score=7.0, avg_skill_score=7.5,
                fallback_rate=0.04, policy_adjusted_rate=0.06,
                avg_confidence=0.75,
            ),
        ]
        md = leaderboard_to_markdown(entries)
        self.assertIn("版本", md)
        self.assertIn("v2_base", md)
        self.assertIn("50.0%", md)  # 0.5 as percent

    def test_empty_table(self):
        md = leaderboard_to_markdown([])
        self.assertIn("No data", md)

    def test_detail_table_includes_extra_columns(self):
        entries = [
            LeaderboardEntry(
                version="v2", games=5,
                werewolf_win_rate=0.4, villager_win_rate=0.6,
                avg_days=3.0, avg_score=7.0,
                avg_speech_score=6.0, avg_vote_score=7.0,
                avg_skill_score=7.5, vote_accuracy=0.6,
                skill_accuracy=0.65, fallback_rate=0.02,
                policy_adjusted_rate=0.04, avg_confidence=0.8,
            ),
        ]
        md = leaderboard_detail_markdown(entries)
        self.assertIn("平均天数", md)
        self.assertIn("投票准确率", md)
        self.assertIn("技能准确率", md)
        self.assertIn("v2", md)


class WriteLeaderboardTests(unittest.TestCase):
    """Test writing leaderboard to disk."""

    def test_writes_json_and_markdown(self):
        entries = [LeaderboardEntry(version="test", games=5)]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_leaderboard(entries, output)
            self.assertTrue((output / "leaderboard.json").exists())
            self.assertTrue((output / "leaderboard.md").exists())
            self.assertTrue((output / "leaderboard_detail.md").exists())

    def test_json_content(self):
        entries = [
            LeaderboardEntry(version="v1", games=10, avg_score=7.0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_leaderboard(entries, output)
            with open(output / "leaderboard.json", "r") as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["version"], "v1")

    def test_empty_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            write_leaderboard([], output)
            with open(output / "leaderboard.json", "r") as f:
                data = json.load(f)
            self.assertEqual(data, [])


class LoadSummariesTests(unittest.TestCase):
    """Test loading summaries from disk."""

    def test_load_from_existing_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run_test"
            run_dir.mkdir()
            summary = {"games": 5, "werewolf_wins": 2, "villager_wins": 3}
            with open(run_dir / "summary.json", "w") as f:
                json.dump(summary, f)

            summaries = load_summaries_from_runs([run_dir])
            self.assertEqual(len(summaries), 1)
            self.assertEqual(summaries[0]["games"], 5)

    def test_skip_missing_summary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run_missing"
            run_dir.mkdir()
            summaries = load_summaries_from_runs([run_dir])
            self.assertEqual(summaries, [])


if __name__ == "__main__":
    unittest.main()
