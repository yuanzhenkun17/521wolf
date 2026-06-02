"""Tests for agent.archive — DecisionArchive, GameArchive, AgentTraceRecorder."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.actions import ActionType
from engine.models import ActionRequest, Observation, Phase, Role

from agent.observability.archive import (
    AgentTraceRecorder,
    DecisionArchive,
    GameArchive,
)
from agent.observability.decision_log import DecisionRecord
from agent.runtime.context import AgentContext


def _make_vote_context() -> AgentContext:
    request = ActionRequest(
        player_id=5,
        action_type=ActionType.EXILE_VOTE,
        phase=Phase.EXILE_VOTE,
        observation=Observation(
            player_id=5,
            self_role=Role.VILLAGER,
            phase=Phase.EXILE_VOTE,
            day=2,
            alive_players=(1, 2, 3, 5, 6, 8, 9, 10),
            dead_players=(4, 7),
            sheriff_id=5,
            public_log=["P8 发言怀疑 P3"],
            known_roles={},
            seer_checks={},
            metadata={},
        ),
        candidates=(3, 7, 9),
        retry_count=0,
        metadata={},
    )
    ctx = AgentContext(request=request, player_id=5, role="villager")
    ctx.memory_context = {"memory_events": ["P8发言"], "private_facts": {}}
    ctx.belief_context = {"top_suspicions": [{"player_id": 7, "reason": "可疑"}]}
    ctx.selected_skills = ["output_schema", "villager_vote_analysis"]
    ctx.messages = [{"role": "system", "content": "你是一个村民"}, {"role": "user", "content": "请投票"}]
    ctx.raw_output = '{"target": 7, "choice": null, "text": "出7号", "reasoning": "7号可疑"}'
    ctx.parsed_decision = {"target": 7, "choice": None, "text": "出7号", "reasoning": "7号可疑"}
    ctx.source = "llm"
    ctx.confidence = 0.85
    ctx.policy_adjustments = []
    ctx.errors = []
    return ctx


class DecisionArchiveTests(unittest.TestCase):
    """Test DecisionArchive construction from AgentContext."""

    def test_from_context_builds_archive(self):
        ctx = _make_vote_context()
        archive = DecisionArchive.from_context(ctx, index=1)
        self.assertEqual(archive.player_id, 5)
        self.assertEqual(archive.role, "villager")
        self.assertEqual(archive.day, 2)
        self.assertEqual(archive.action_type, "exile_vote")
        self.assertEqual(archive.source, "llm")
        self.assertEqual(archive.confidence, 0.85)

    def test_from_context_includes_skills(self):
        ctx = _make_vote_context()
        archive = DecisionArchive.from_context(ctx)
        self.assertIn("output_schema", archive.selected_skills)

    def test_from_context_includes_raw_output(self):
        ctx = _make_vote_context()
        archive = DecisionArchive.from_context(ctx)
        self.assertIn("target", archive.raw_output)
        self.assertIn("7号", archive.raw_output)

    def test_from_context_includes_prompt_messages(self):
        ctx = _make_vote_context()
        archive = DecisionArchive.from_context(ctx)
        self.assertGreater(len(archive.prompt_messages), 0)
        self.assertEqual(archive.prompt_messages[0]["role"], "system")

    def test_from_context_includes_observation_summary(self):
        ctx = _make_vote_context()
        archive = DecisionArchive.from_context(ctx)
        self.assertIn("day", archive.observation_summary)
        self.assertEqual(archive.observation_summary["day"], 2)

    def test_from_context_includes_belief_context(self):
        ctx = _make_vote_context()
        archive = DecisionArchive.from_context(ctx)
        self.assertIn("top_suspicions", archive.belief_context)

    def test_from_context_includes_parsed_decision(self):
        ctx = _make_vote_context()
        archive = DecisionArchive.from_context(ctx)
        self.assertEqual(archive.parsed_decision["target"], 7)

    def test_from_context_reuses_decision_record_id(self):
        ctx = _make_vote_context()
        ctx.decision_record = DecisionRecord(
            action_type=ActionType.EXILE_VOTE,
            decision_id="dec_fixed_001",
        )
        archive = DecisionArchive.from_context(ctx)
        self.assertEqual(archive.decision_id, "dec_fixed_001")

    def test_to_dict_serializes_all_fields(self):
        ctx = _make_vote_context()
        archive = DecisionArchive.from_context(ctx)
        d = archive.to_dict()
        self.assertEqual(d["player_id"], 5)
        self.assertEqual(d["source"], "llm")
        self.assertIn("prompt_messages", d)
        self.assertIn("raw_output", d)
        self.assertIn("policy_adjustments", d)
        self.assertEqual(d["parsed_decision"]["target"], 7)

    def test_to_dict_json_serializable(self):
        ctx = _make_vote_context()
        archive = DecisionArchive.from_context(ctx)
        d = archive.to_dict()
        json_str = json.dumps(d, ensure_ascii=False)
        self.assertIn("villager", json_str)
        loaded = json.loads(json_str)
        self.assertEqual(loaded["player_id"], 5)


class GameArchiveTests(unittest.TestCase):
    """Test GameArchive creation and serialization."""

    def setUp(self):
        self.ctx = _make_vote_context()
        self.decision = DecisionArchive.from_context(self.ctx, index=0)

    def test_game_archive_holds_decisions(self):
        archive = GameArchive(
            game_id="game_001",
            seed=42,
            config={"agent_version": "agent"},
            player_roles={5: "villager"},
            winner="villagers",
            started_at="2026-01-01T00:00:00",
            finished_at="2026-01-01T00:10:00",
            public_events=[{"event_type": "death", "target": 4}],
            decisions=[self.decision],
            final_state={"player_roles": {5: "villager"}, "winner": "villagers"},
        )
        self.assertEqual(archive.game_id, "game_001")
        self.assertEqual(len(archive.decisions), 1)
        self.assertEqual(archive.winner, "villagers")

    def test_game_archive_writes_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "archive.json"
            archive = GameArchive(
                game_id="game_001",
                seed=42,
                config={},
                player_roles={5: "villager"},
                winner="villagers",
                started_at="2026-01-01T00:00:00",
                finished_at="2026-01-01T00:10:00",
                public_events=[],
                decisions=[self.decision],
                final_state={},
            )
            archive.write_json(path)
            self.assertTrue(path.exists())
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["game_id"], "game_001")
            self.assertEqual(len(loaded["decisions"]), 1)

    def test_game_archive_read_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "archive.json"
            archive = GameArchive(
                game_id="game_002",
                seed=99,
                config={},
                player_roles={1: "werewolf", 5: "villager"},
                winner="werewolves",
                started_at="2026-01-01T00:00:00",
                finished_at=None,
                public_events=[{"event_type": "death", "target": 5}],
                decisions=[self.decision],
                final_state={"winner": "werewolves"},
            )
            archive.write_json(path)
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["game_id"], "game_002")
            self.assertEqual(loaded["winner"], "werewolves")
            self.assertEqual(loaded["player_roles"]["5"], "villager")

    def test_game_archive_final_state_separate(self):
        """final_state should be separate from decision observation."""
        archive = GameArchive(
            game_id="game_001",
            seed=1,
            config={},
            player_roles={1: "werewolf", 2: "villager"},
            winner="villagers",
            started_at="",
            finished_at="",
            public_events=[],
            decisions=[self.decision],
            final_state={"player_roles": {1: "werewolf", 2: "villager"}},
        )
        d = archive.to_dict()
        self.assertIn("final_state", d)
        self.assertIn("player_roles", d["final_state"])

    def test_game_archive_multiple_decisions(self):
        ctx2 = _make_vote_context()
        ctx2.raw_output = '{"target": 9, "choice": null, "text": "出9号", "reasoning": "9号可疑"}'
        d2 = DecisionArchive.from_context(ctx2, index=1)
        archive = GameArchive(
            game_id="game_multi",
            seed=1, config={}, player_roles={5: "villager"},
            winner="villagers", started_at="", finished_at="",
            public_events=[], decisions=[self.decision, d2], final_state={},
        )
        self.assertEqual(len(archive.decisions), 2)


class AgentTraceRecorderTests(unittest.TestCase):
    """Test AgentTraceRecorder collection and flush."""

    def test_record_increases_count(self):
        recorder = AgentTraceRecorder()
        ctx = _make_vote_context()
        self.assertEqual(recorder.count, 0)
        recorder.record(ctx)
        self.assertEqual(recorder.count, 1)
        self.assertEqual(recorder.snapshot()[0].index, 1)

    def test_multiple_records(self):
        recorder = AgentTraceRecorder()
        ctx = _make_vote_context()
        recorder.record(ctx)
        recorder.record(ctx)
        recorder.record(ctx)
        self.assertEqual(recorder.count, 3)
        self.assertEqual([trace.index for trace in recorder.snapshot()], [1, 2, 3])

    def test_flush_creates_game_archive(self):
        recorder = AgentTraceRecorder()
        ctx = _make_vote_context()
        recorder.record(ctx)
        with tempfile.TemporaryDirectory() as tmp:
            game_dir = Path(tmp)
            archive = recorder.flush(
                game_id="game_001",
                output_dir=game_dir,
                seed=42,
                config={"agent_version": "agent"},
                player_roles={5: "villager"},
                winner="villagers",
                public_events=[],
                final_state={"winner": "villagers"},
            )
            self.assertIsInstance(archive, GameArchive)
            self.assertEqual(len(archive.decisions), 1)
            self.assertTrue((game_dir / "archive.json").exists())

    def test_flush_empty_recorder(self):
        recorder = AgentTraceRecorder()
        with tempfile.TemporaryDirectory() as tmp:
            archive = recorder.flush(
                game_id="empty", output_dir=Path(tmp),
                seed=0, config={}, player_roles={}, winner=None,
                public_events=[], final_state={},
            )
            self.assertEqual(len(archive.decisions), 0)

    def test_clear_resets_recorder(self):
        recorder = AgentTraceRecorder()
        ctx = _make_vote_context()
        recorder.record(ctx)
        self.assertEqual(recorder.count, 1)
        recorder.clear()
        self.assertEqual(recorder.count, 0)
        self.assertEqual(recorder._index, 1)

    def test_record_after_clear(self):
        recorder = AgentTraceRecorder()
        ctx = _make_vote_context()
        recorder.record(ctx)
        recorder.clear()
        recorder.record(ctx)
        self.assertEqual(recorder.count, 1)
        self.assertEqual(recorder.snapshot()[0].index, 1)


if __name__ == "__main__":
    unittest.main()
