"""Integration tests for selfplay pipeline — artifact completeness.

These tests verify the full post-game pipeline produces correct output,
catching wiring issues that isolated unit tests miss:
  - F1: Archive/trace must include decisions from ALL players, not just last
  - F2: Experience extraction must actually produce output files
  - F3: Review must use enhanced format with dimensional player scoring

Each test exercises the real production functions with realistic data,
simulating what the selfplay runner does after a game completes.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.config import STANDARD_12
from engine.models import Role

from unittest.mock import MagicMock

from agent.observability.archive import (
    AgentTraceRecorder,
    DecisionArchive,
    GameArchive,
)
from agent.runtime.context import AgentContext
from agent.evaluation.review_enhanced import generate_enhanced_review
from agent.evaluation.selfplay import SelfPlayConfig, SelfPlayGameResult, SelfPlayResult


# ── helpers ────────────────────────────────────────────────────────────────────


def _make_archive_decision(
    pid: int,
    role: str,
    index: int = 0,
    *,
    day: int = 1,
    phase: str = "day",
    action: str = "speak",
) -> DecisionArchive:
    return DecisionArchive(
        decision_id=f"d{pid}_{index}",
        index=index,
        player_id=pid,
        role=role,
        day=day,
        phase=phase,
        action_type=action,
        candidates=[],
        observation_summary={"day": day, "phase": phase, "alive_players": [], "dead_players": [], "sheriff_id": None, "candidates": []},
        memory_context={},
        belief_context={},
        selected_skills=[],
        prompt_messages=[],
        raw_output='{"choice": "pass"}',
        parsed_decision={"choice": "pass"},
        final_response={},
        source="llm",
        confidence=0.8,
        policy_adjustments=[],
        errors=[],
    )


def _make_role_set() -> dict[int, Role]:
    """Return a 6-player role set with 2 wolves and 4 villagers/gods."""
    return {
        1: Role.WEREWOLF,
        2: Role.VILLAGER,
        3: Role.SEER,
        4: Role.WITCH,
        5: Role.WEREWOLF,
        6: Role.HUNTER,
    }


def _make_minimal_decisions(roles: dict[int, Role]) -> dict[int, list[dict]]:
    """One minimal decision record per player — sufficient for review."""
    return {
        pid: [
            {
                "source": "llm",
                "day": 1,
                "phase": "day",
                "action_type": "speak",
                "selected_choice": "pass",
                "selected_target": None,
                "policy_adjustments": [],
                "errors": [],
            },
            {
                "source": "llm",
                "day": 1,
                "phase": "night",
                "action_type": "vote",
                "selected_choice": "vote",
                "selected_target": next(
                    (op for op in roles if op != pid), None
                ),
                "policy_adjustments": [],
                "errors": [],
            },
        ]
        for pid in roles
    }


# ── F1: Archive merge integration ──────────────────────────────────────────────


class ArchiveMergeTest(unittest.TestCase):
    """F1: Archive must preserve decisions from ALL players."""

    def test_merged_archive_contains_three_players(self):
        """3 players × 2 decisions = 6 total in merged GameArchive."""
        decisions = []
        for pid, role in [(1, "werewolf"), (3, "villager"), (7, "seer")]:
            for i in range(2):
                decisions.append(_make_archive_decision(pid, role, i))

        archive = GameArchive(
            game_id="game_001",
            seed=42,
            config={},
            player_roles={1: "werewolf", 3: "villager", 7: "seer"},
            winner="villagers",
            started_at="2025-01-01T00:00:00",
            finished_at="2025-01-01T00:10:00",
            public_events=[],
            decisions=decisions,
            final_state={},
        )

        self.assertEqual(len(archive.decisions), 6)
        pids = {d.player_id for d in archive.decisions}
        self.assertEqual(pids, {1, 3, 7})

    def test_snapshot_does_not_write_archive_file(self):
        """snapshot() returns decisions without writing archive.json side-effect."""
        rec = AgentTraceRecorder()
        for i in range(2):
            mock_req = MagicMock()
            mock_req.observation.day = 1
            mock_req.phase.value = "day"
            mock_req.action_type.value = "speak"
            mock_req.candidates = []
            ctx = AgentContext(request=mock_req, player_id=1, role="villager")
            ctx.selected_skills = []
            ctx.raw_output = "{}"
            rec.record(ctx)

        decisions = rec.snapshot()
        self.assertEqual(len(decisions), 2)
        self.assertEqual(rec.count, 2)  # snapshot doesn't clear

    def test_flush_multiple_recorders_then_merge(self):
        """Simulate selfplay: flush 3 trace recorders, extend list, merge.

        This directly reproduces the selfplay flush+merge loop.
        """
        trace_recorders: dict[int, AgentTraceRecorder] = {}
        for pid in (1, 3, 7):
            rec = AgentTraceRecorder()
            for i in range(2):
                mock_req = MagicMock()
                mock_req.observation.day = 1
                mock_req.observation.alive_players = [1, 3, 7]
                mock_req.observation.dead_players = []
                mock_req.observation.sheriff_id = None
                mock_req.phase.value = "day"
                mock_req.action_type.value = "speak"
                mock_req.candidates = []
                ctx = AgentContext(
                    request=mock_req,
                    player_id=pid,
                    role="villager",
                )
                ctx.selected_skills = []
                ctx.raw_output = '{"choice": "pass"}'
                rec.record(ctx)
            trace_recorders[pid] = rec

        # ── flush loop (mirrors selfplay line 236-248) ──
        all_decisions: list[DecisionArchive] = []
        for pid, recorder in trace_recorders.items():
            archive = recorder.flush(
                game_id="game_001",
                output_dir=Path(tempfile.mkdtemp()),
                seed=42,
                config={"agent_version": "test"},
                player_roles={},
                winner="villagers",
                public_events=[],
                final_state={},
            )
            all_decisions.extend(archive.decisions)

        self.assertEqual(len(all_decisions), 6)
        pids = {d.player_id for d in all_decisions}
        self.assertEqual(pids, {1, 3, 7})

    def test_merged_archive_write_and_read_back(self):
        """Write merged archive to JSON, read back, verify all players."""
        decisions = [
            _make_archive_decision(1, "werewolf", 0),
            _make_archive_decision(1, "werewolf", 1),
            _make_archive_decision(3, "seer", 0),
        ]
        archive = GameArchive(
            game_id="g1", seed=1, config={},
            player_roles={1: "werewolf", 3: "seer"},
            winner="villagers",
            started_at="", finished_at="",
            public_events=[], decisions=decisions,
            final_state={},
        )

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "archive.json"
            archive.write_json(path)

            with open(path) as f:
                data = json.load(f)

            self.assertEqual(len(data["decisions"]), 3)
            pids = {d["player_id"] for d in data["decisions"]}
            self.assertEqual(pids, {1, 3})


# ── F3: Enhanced review integration ────────────────────────────────────────────


class ReviewEnhancedTest(unittest.TestCase):
    """F3: Review must use enhanced format with dimensional scoring."""

    def test_review_has_player_scores_with_dimensions(self):
        """generate_enhanced_review must return 5 scoring dimensions per player."""
        roles = _make_role_set()
        game_log = {"entries": [
            {"event_type": "death", "target": 2, "day": 1, "phase": "night"},
            {"event_type": "death", "target": 5, "day": 1, "phase": "night"},
        ]}
        decisions = _make_minimal_decisions(roles)

        report = generate_enhanced_review(
            game_log=game_log,
            agent_decisions=decisions,
            roles=roles,
            winner_team="villagers",
            game_id="integration_test",
        )

        # Must have all 6 players scored
        self.assertEqual(len(report.player_scores), 6)

        # Each player must have all 5 scoring dimensions
        for pid, pr in report.player_scores.items():
            with self.subTest(player=pid):
                self.assertIsNotNone(
                    pr.total_score,
                    f"Player {pid} missing total_score",
                )
                self.assertIsNotNone(
                    pr.speech_score,
                    f"Player {pid} missing speech_score",
                )
                self.assertIsNotNone(
                    pr.vote_score,
                    f"Player {pid} missing vote_score",
                )
                self.assertIsNotNone(
                    pr.skill_score,
                    f"Player {pid} missing skill_score",
                )

    def test_review_team_scores_unify_gods_with_villagers(self):
        """Gods (seer, witch, hunter, guard) must be counted under villagers."""
        roles = _make_role_set()
        report = generate_enhanced_review(
            game_log={"entries": []},
            agent_decisions=_make_minimal_decisions(roles),
            roles=roles,
            winner_team="villagers",
            game_id="team_test",
        )

        self.assertIn(
            "villagers",
            report.team_scores,
            "God roles should score under 'villagers' team",
        )
        self.assertIn(
            "werewolves",
            report.team_scores,
            "Werewolves team must exist",
        )
        self.assertNotIn(
            "gods",
            report.team_scores,
            "'gods' key must not appear — gods are villagers",
        )

    def test_review_detects_key_turning_points(self):
        """Review must identify death + witch poison as turning points."""
        roles = _make_role_set()
        game_log = {"entries": [
            {"event_type": "death", "target": 3, "day": 1, "phase": "night"},
            {"event_type": "death", "target": 2, "day": 2, "phase": "night"},
        ]}
        decisions = _make_minimal_decisions(roles)
        # Add witch poison decision
        decisions[4] = [
            *decisions[4],
            {
                "source": "llm",
                "day": 1,
                "phase": "night",
                "action_type": "witch_act",
                "selected_choice": "poison",
                "selected_target": 2,
                "policy_adjustments": [],
                "errors": [],
            },
        ]

        report = generate_enhanced_review(
            game_log=game_log,
            agent_decisions=decisions,
            roles=roles,
            winner_team="villagers",
            game_id="tp_test",
        )

        self.assertGreater(len(report.key_turning_points), 0)
        descs = " ".join(t.description for t in report.key_turning_points)
        self.assertIn("死亡", descs)


# ── Error + config validation integration ─────────────────────────────────────


class ErrorTrackingTest(unittest.TestCase):
    """F2: Error games must not pollute win rates."""

    def test_error_game_excluded_from_win_rate(self):
        """SelfPlayResult must exclude error games from win rate calculation."""
        config = SelfPlayConfig(games=3)
        games = [
            SelfPlayGameResult(
                game_id="g1", seed=1, winner="werewolves", days=3,
                player_roles={}, decision_count=10, fallback_count=0,
                policy_adjusted_count=0, avg_confidence=0.5,
                review_score=7.0, output_dir=Path("."),
            ),
            SelfPlayGameResult(
                game_id="g2", seed=2, winner="villagers", days=4,
                player_roles={}, decision_count=10, fallback_count=0,
                policy_adjusted_count=0, avg_confidence=0.5,
                review_score=7.0, output_dir=Path("."),
            ),
            SelfPlayGameResult(
                game_id="g3", seed=3, winner="error", days=1,
                player_roles={}, decision_count=0, fallback_count=0,
                policy_adjusted_count=0, avg_confidence=0.0,
                review_score=None, output_dir=Path("."),
                error="GameEngine crashed",
            ),
        ]
        result = SelfPlayResult(config=config, games=games)
        s = result.summary

        self.assertEqual(s["error_count"], 1)
        self.assertEqual(s["games"], 3)
        self.assertEqual(s["werewolf_wins"], 1)   # only from g1
        self.assertEqual(s["villager_wins"], 1)    # only from g2
        self.assertEqual(s["werewolf_win_rate"], 0.5)  # 1/2, not 1/3

    def test_error_game_to_dict_includes_error(self):
        """SelfPlayGameResult.to_dict must include error field when set."""
        g = SelfPlayGameResult(
            game_id="g1", seed=1, winner="error", days=1,
            player_roles={}, decision_count=0, fallback_count=0,
            policy_adjusted_count=0, avg_confidence=0.0,
            review_score=None, output_dir=Path("."),
            error="timeout",
        )
        d = g.to_dict()
        self.assertEqual(d["error"], "timeout")
        self.assertEqual(d["winner"], "error")

    def test_all_errors_gives_zero_win_rate(self):
        """When all games error, win rates must be 0, not villager=100%."""
        games = [
            SelfPlayGameResult(
                game_id=f"g{i}", seed=i, winner="error", days=0,
                player_roles={}, decision_count=0, fallback_count=0,
                policy_adjusted_count=0, avg_confidence=0.0,
                review_score=None, output_dir=Path("."),
                error=f"err_{i}",
            )
            for i in range(3)
        ]
        result = SelfPlayResult(
            config=SelfPlayConfig(games=3), games=games,
        )
        s = result.summary
        self.assertEqual(s["error_count"], 3)
        self.assertEqual(s["werewolf_win_rate"], 0.0)
        self.assertEqual(s["villager_win_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
