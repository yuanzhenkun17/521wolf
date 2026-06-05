"""Tests for the SQLite storage layer."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from storage.schema import get_connection
from storage.shared.connection import get_evolution_connection
from storage.registry.connection import get_registry_connection
from storage.game_store import GameStore
from storage.decision_store import DecisionStore
from storage.version_store import VersionStoreDB
from storage.evolution_store import EvolutionStore
from storage.evolution.experience_repo import ExperienceCandidateStore
from storage.leaderboard_store import LeaderboardStore
from agent.infrastructure.archive import DecisionArchive
from agent.learning.models import ExperienceCandidate
from agent.learning.evolution.models import (
    EvolutionRun,
    RoleVersion,
    SkillProposal,
)


class TestGameStore(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection(Path(":memory:"))
        self.store = GameStore(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_insert_and_get_game(self):
        game_id = self.store.insert_game(
            game_id="test_001",
            seed=42,
            config={"max_rounds": 10},
            winner="werewolves",
            started_at="2026-01-01T00:00:00",
        )
        self.assertEqual(game_id, "test_001")

        game = self.store.get_game("test_001")
        self.assertIsNotNone(game)
        self.assertEqual(game["seed"], 42)
        self.assertEqual(game["winner"], "werewolves")
        self.assertEqual(json.loads(game["config"]), {"max_rounds": 10})

    def test_get_nonexistent_game(self):
        self.assertIsNone(self.store.get_game("nope"))

    def test_insert_players(self):
        self.store.insert_game("g1", seed=1)
        self.store.insert_players(
            "g1",
            {0: "werewolf", 1: "seer", 2: "villager"},
            final_alive={0: True, 1: False, 2: True},
            role_version_ids={1: "seer_v1"},
            skill_package_hashes={1: "hash_001"},
        )

        rows = self.conn.execute(
            "SELECT * FROM players WHERE game_id = 'g1' ORDER BY seat"
        ).fetchall()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["role"], "seer")
        self.assertEqual(rows[1]["alive"], 0)
        self.assertEqual(rows[1]["role_version_id"], "seer_v1")
        self.assertEqual(rows[1]["skill_package_hash"], "hash_001")

    def test_list_games(self):
        self.store.insert_game("g1", seed=1, winner="werewolves", started_at="2026-01-01")
        self.store.insert_game("g2", seed=2, winner="villagers", started_at="2026-01-02")

        games = self.store.list_games()
        self.assertEqual(len(games), 2)

        # Filter by winner
        games = self.store.list_games(winner="werewolves")
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0]["id"], "g1")

    def test_count_games(self):
        self.store.insert_game("g1", seed=1)
        self.store.insert_game("g2", seed=2)
        self.assertEqual(self.store.count_games(), 2)


class TestDecisionStore(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection(Path(":memory:"))
        self.store = DecisionStore(self.conn)
        GameStore(self.conn).insert_game("g1", seed=1)

    def tearDown(self):
        self.conn.close()

    def test_insert_archive(self):
        archive = DecisionArchive(
            decision_id="d1",
            index=1,
            player_id=3,
            role="seer",
            day=1,
            phase="night",
            action_type="seer_check",
            candidates=[1, 2],
            observation_summary={"day": 1},
            memory_context={},
            selected_skills=["check.md"],
            prompt_messages=[{"role": "user", "content": "test"}],
            raw_output="check player 1",
            parsed_decision={"target": 1},
            final_response={"target": 1, "text": ""},
            source="llm",
            confidence=0.9,
            policy_adjustments=[],
            errors=[],
        )
        did = self.store.insert_archive("g1", archive, player_id=3)
        self.assertEqual(did, "d1")

        rows = self.store.query(game_id="g1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["role"], "seer")
        self.assertEqual(rows[0]["action_type"], "seer_check")

    def test_query_by_role(self):
        for i, role in enumerate(["seer", "werewolf", "seer"]):
            archive = DecisionArchive(
                decision_id=f"d_{role}_{i}",
                index=i,
                player_id=1,
                role=role,
                day=1,
                phase="night",
                action_type="seer_check",
                candidates=[],
                observation_summary={},
                memory_context={},
                selected_skills=[],
                prompt_messages=[],
                raw_output="",
                parsed_decision={},
                final_response={},
                source="llm",
                confidence=0.5,
                policy_adjustments=[],
                errors=[],
            )
            self.store.insert_archive("g1", archive)

        rows = self.store.query(role="seer")
        self.assertEqual(len(rows), 2)

    def test_count_by_role(self):
        archive = DecisionArchive(
            decision_id="d1", index=1, player_id=1, role="seer",
            day=1, phase="night", action_type="seer_check",
            candidates=[], observation_summary={}, memory_context={},
            selected_skills=[], prompt_messages=[], raw_output="",
            parsed_decision={"target": 1}, final_response={},
            source="llm", confidence=0.9, policy_adjustments=[], errors=[],
        )
        self.store.insert_archive("g1", archive)
        counts = self.store.count_by_role("seer")
        self.assertEqual(counts["total"], 1)
        self.assertEqual(counts["with_target"], 1)


class TestExperienceCandidateStore(unittest.TestCase):
    def setUp(self):
        self.conn = get_evolution_connection(Path(":memory:"))
        # Create minimal games table for game_id references
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS games (id TEXT PRIMARY KEY, seed INTEGER, config TEXT)"
        )
        self.conn.execute(
            "INSERT INTO games (id, seed) VALUES ('g1', 1)"
        )
        self.conn.commit()
        self.store = ExperienceCandidateStore(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_save_and_list_candidates(self):
        candidate = ExperienceCandidate(
            candidate_id="cand_001",
            role="seer",
            faction="villagers",
            candidate_type="positive_pattern",
            topic="night_check",
            sample_source="single_game",
            evidence_decision_ids=["d1"],
            scenario="首夜查验高影响发言位",
            conditions=["警上强势带队"],
            recommendation="优先查验能改变归票的信息位",
            confidence="medium",
            validation_need={"needs_multi_game_validation": True},
        )

        saved = self.store.save_candidates(
            "g1",
            [candidate],
            run_type="evolution_training",
            learning_eligible=True,
            mode="formal",
            created_at="2026-01-01T00:00:00",
        )
        self.assertEqual(saved, ["cand_001"])

        rows = self.store.list_candidates(role="seer")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["candidate_id"], "cand_001")
        self.assertEqual(rows[0]["conditions"], ["警上强势带队"])
        self.assertEqual(rows[0]["raw_json"]["recommendation"], "优先查验能改变归票的信息位")

    def test_count_by_role(self):
        self.store.save_candidates(
            "g1",
            [
                {"candidate_id": "a", "role": "seer"},
                {"candidate_id": "b", "role": "witch"},
                {"candidate_id": "c", "role": "seer"},
            ],
            run_type="evolution_training",
            learning_eligible=True,
            mode="formal",
        )

        counts = self.store.count_by_role()
        self.assertEqual(counts["seer"], 2)
        self.assertEqual(counts["witch"], 1)


class TestVersionStoreDB(unittest.TestCase):
    def setUp(self):
        self.conn = get_registry_connection(Path(":memory:"))
        self.store = VersionStoreDB(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_save_and_load(self):
        skills = {"protect.md": "# Guard\nProtect the village."}
        h = self.store.save_version(
            role="guard",
            skills=skills,
            parent_hash=None,
            source="bootstrap",
        )
        self.assertEqual(len(h), 12)  # 12-char hash

        loaded = self.store.load_version(h)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.role, "guard")
        self.assertEqual(loaded.skills, skills)

    def test_idempotent_save(self):
        skills = {"test.md": "content"}
        h1 = self.store.save_version("guard", skills, None, "test")
        h2 = self.store.save_version("guard", skills, None, "test")
        self.assertEqual(h1, h2)

    def test_list_versions(self):
        skills = {"a.md": "a"}
        self.store.save_version("guard", skills, None, "test")
        skills2 = {"a.md": "a", "b.md": "b"}
        self.store.save_version("guard", skills2, None, "test2")

        versions = self.store.list_versions("guard")
        self.assertEqual(len(versions), 2)

    def test_get_baseline(self):
        skills = {"base.md": "baseline"}
        h = self.store.save_version("guard", skills, None, "bootstrap")
        baseline = self.store.get_baseline("guard")
        self.assertEqual(baseline.hash, h)


class TestEvolutionStore(unittest.TestCase):
    def setUp(self):
        self.conn = get_evolution_connection(Path(":memory:"))
        self.store = EvolutionStore(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_save_and_get_run(self):
        run = EvolutionRun(
            run_id="run_001",
            role="guard",
            parent_hash="abc12345",
            status="training",
            training_games=10,
        )
        self.store.save_run(run)

        loaded = self.store.get_run("run_001")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.role, "guard")
        self.assertEqual(loaded.status, "training")

    def test_update_run(self):
        run = EvolutionRun(run_id="r1", role="guard", parent_hash="h1", status="training")
        self.store.save_run(run)
        self.store.update_run("r1", status="battling", battle_games=5)

        loaded = self.store.get_run("r1")
        self.assertEqual(loaded.status, "battling")
        self.assertEqual(loaded.battle_games, 5)

    def test_list_runs(self):
        for i, status in enumerate(["training", "battling", "promoted"]):
            run = EvolutionRun(run_id=f"r{i}", role="guard", parent_hash="h", status=status)
            self.store.save_run(run)

        runs = self.store.list_runs(role="guard")
        self.assertEqual(len(runs), 3)

        runs = self.store.list_runs(status="promoted")
        self.assertEqual(len(runs), 1)

    def test_list_battle_summaries_filters_by_role(self):
        guard_summary = {
            "role": "guard",
            "baseline_config": {"role_versions": {"guard": "base"}},
            "candidate_config": {"role_versions": {"guard": "candidate"}},
            "games_played": 12,
        }
        self.store.save_run(
            EvolutionRun(
                run_id="r_guard",
                role="guard",
                parent_hash="base",
                status="reviewing",
                battle_result=guard_summary,
            )
        )
        self.store.save_run(
            EvolutionRun(
                run_id="r_seer",
                role="seer",
                parent_hash="base",
                status="reviewing",
                battle_result={"role": "seer"},
            )
        )
        self.store.save_run(
            EvolutionRun(run_id="r_empty", role="guard", parent_hash="base", status="training")
        )

        summaries = self.store.list_battle_summaries(role="guard")

        self.assertEqual(summaries, [guard_summary])

    def test_save_proposals(self):
        proposal = SkillProposal(
            proposal_id="p1",
            target_file="protect.md",
            action_type="modify",
            content="new content",
            rationale="better",
            confidence=0.8,
            risk="low",
            expected_metric="win_rate",
            expected_direction="up",
            status="proposed",
        )
        self.store.save_proposals([proposal], source_version_id="v1")

        results = self.store.list_proposals(source_version_id="v1")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["target_file"], "protect.md")


class TestLeaderboardStore(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection(Path(":memory:"))
        self.store = LeaderboardStore(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_list_entries_maps_leaderboard_rows(self):
        self.conn.execute(
            "INSERT INTO leaderboard "
            "(version_id, role, games_played, wins, losses, win_rate, "
            "avg_survival_rounds, target_side_win_rate, win_rate_ci_low, "
            "win_rate_ci_high, scores, is_baseline, data_sufficient, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "v1",
                "seer",
                12,
                8,
                4,
                0.667,
                3.5,
                0.7,
                0.4,
                0.9,
                json.dumps({"role_weighted_score": 0.82}, ensure_ascii=False),
                1,
                1,
                "2026-06-04T00:00:00",
            ),
        )
        self.conn.commit()

        entries = self.store.list_entries()

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["version"], "v1")
        self.assertEqual(entries[0]["role"], "seer")
        self.assertEqual(entries[0]["games"], 12)
        self.assertEqual(entries[0]["target_side_win_rate_ci"], [0.4, 0.9])
        self.assertEqual(entries[0]["scores"]["role_weighted_score"], 0.82)
        self.assertTrue(entries[0]["is_baseline"])
        self.assertTrue(entries[0]["data_sufficient"])


class TestGameEventStore(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection(Path(":memory:"))
        from storage.game_event_store import GameEventStore
        self.store = GameEventStore(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_count_by_type_empty(self):
        result = self.store.count_by_type()
        self.assertEqual(result, {})

    def test_count_by_type(self):
        for evt_type in ["kill", "death", "kill"]:
            self.conn.execute(
                "INSERT INTO game_events "
                "(game_id, idx, day, phase, event_type, message) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("g1", 1, 1, "night", evt_type, "test"),
            )
        self.conn.commit()

        counts = self.store.count_by_type("g1")
        self.assertEqual(counts["kill"], 2)
        self.assertEqual(counts["death"], 1)

    def test_search(self):
        self.conn.execute(
            "INSERT INTO game_events "
            "(game_id, idx, day, phase, event_type, message) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("g1", 1, 1, "night", "kill", "werewolf kills player 1"),
        )
        self.conn.execute(
            "INSERT INTO game_events "
            "(game_id, idx, day, phase, event_type, message) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("g1", 2, 1, "day", "speech", "player 2 speaks"),
        )
        self.conn.commit()

        results = self.store.search("werewolf")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["event_type"], "kill")


class TestGameLoggerSink(unittest.TestCase):
    """Test that GameLogger can stream to files and a generic sink."""

    def test_record_writes_to_sink(self):
        from engine.logging import GameLogger

        class Sink:
            def __init__(self):
                self.entries = []

            def record_event(self, entry):
                self.entries.append(entry)

        sink = Sink()
        logger = GameLogger(sink=sink)

        logger.record(day=1, phase="night", event_type="kill", message="狼人杀了1号")
        logger.record(day=1, phase="night", event_type="death", message="1号死亡",
                       payload={"cause": "werewolf"})

        self.assertEqual(len(sink.entries), 2)
        self.assertEqual(sink.entries[0].type, "kill")
        self.assertEqual(sink.entries[1].payload["cause"], "werewolf")

    def test_record_without_conn_still_works(self):
        from engine.logging import GameLogger

        logger = GameLogger()
        entry = logger.record(day=1, phase="night", event_type="kill", message="test")
        self.assertEqual(entry.index, 1)
        self.assertEqual(len(logger.entries), 1)

    def test_record_with_both_stream_and_sink(self):
        import tempfile
        from engine.logging import GameLogger

        class Sink:
            def __init__(self):
                self.entries = []

            def record_event(self, entry):
                self.entries.append(entry)

        sink = Sink()
        with tempfile.TemporaryDirectory() as tmpdir:
            stream = Path(tmpdir) / "events.jsonl"
            logger = GameLogger(stream_path=str(stream), sink=sink)
            logger.record(day=1, phase="night", event_type="kill", message="test")

            # JSONL file should exist
            self.assertTrue(stream.exists())
            lines = stream.read_text().strip().split("\n")
            self.assertEqual(len(lines), 1)

            # Sink should also receive it
            self.assertEqual(len(sink.entries), 1)


class TestDecisionRecorderSink(unittest.TestCase):
    """Test that AgentDecisionRecorder can write to a generic sink."""

    def test_record_writes_to_sink(self):
        from agent.infrastructure.decision_log import AgentDecisionRecorder, DecisionRecord
        from engine.models import ActionType

        class Sink:
            def __init__(self):
                self.records = []

            def record_decision(self, decision):
                self.records.append(decision)

        sink = Sink()
        recorder = AgentDecisionRecorder(sink=sink)

        record = DecisionRecord(
            action_type=ActionType.SEER_CHECK,
            day=1,
            phase="night",
            player_id=1,
            role="seer",
            selected_target=3,
            confidence=0.9,
            source="llm",
        )
        recorder.record(record)

        self.assertEqual(len(sink.records), 1)
        self.assertEqual(sink.records[0].role, "seer")
        self.assertEqual(sink.records[0].action_type.value, "seer_check")
        self.assertAlmostEqual(sink.records[0].confidence, 0.9)

    def test_record_without_conn_still_works(self):
        from agent.infrastructure.decision_log import AgentDecisionRecorder, DecisionRecord
        from engine.models import ActionType

        recorder = AgentDecisionRecorder()
        record = DecisionRecord(
            action_type=ActionType.SEER_CHECK,
            day=1, phase="night", player_id=1, role="seer",
        )
        recorder.record(record)
        self.assertEqual(len(recorder.records), 1)


if __name__ == "__main__":
    unittest.main()
