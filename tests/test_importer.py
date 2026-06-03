"""Tests for the archive importer."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.infrastructure.storage.schema import get_connection
from agent.infrastructure.storage.importer import ArchiveImporter
from agent.infrastructure.storage.game_store import GameStore
from agent.infrastructure.storage.decision_store import DecisionStore


class TestArchiveImporter(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection(Path(":memory:"))
        self.importer = ArchiveImporter(self.conn)
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)

    def tearDown(self):
        self.conn.close()
        self._tmp.cleanup()

    def _make_archive(self, game_id: str = "test_game") -> dict:
        return {
            "game_id": game_id,
            "seed": 42,
            "config": {"roles": ["werewolf", "seer", "villager"]},
            "player_roles": {"0": "werewolf", "1": "seer", "2": "villager"},
            "winner": "werewolves",
            "started_at": "2026-01-01T00:00:00",
            "finished_at": "2026-01-01T00:05:00",
            "public_events": [
                {"type": "kill", "day": 1, "target": 1},
                {"type": "death", "day": 1, "player_id": 1, "cause": "werewolf"},
            ],
            "decisions": [
                {
                    "decision_id": "d1",
                    "index": 1,
                    "player_id": 0,
                    "role": "werewolf",
                    "day": 1,
                    "phase": "night",
                    "action_type": "werewolf_kill",
                    "candidates": [1, 2],
                    "observation_summary": {"day": 1},
                    "memory_context": {},
                    "selected_skills": ["kill.md"],
                    "prompt_messages": [{"role": "user", "content": "choose target"}],
                    "raw_output": "kill player 1",
                    "parsed_decision": {"target": 1},
                    "final_response": {"target": 1},
                    "source": "llm",
                    "confidence": 0.95,
                    "policy_adjustments": [],
                    "errors": [],
                },
                {
                    "decision_id": "d2",
                    "index": 2,
                    "player_id": 1,
                    "role": "seer",
                    "day": 1,
                    "phase": "night",
                    "action_type": "seer_check",
                    "candidates": [0, 2],
                    "observation_summary": {"day": 1},
                    "memory_context": {},
                    "selected_skills": ["check.md"],
                    "prompt_messages": [],
                    "raw_output": "check player 0",
                    "parsed_decision": {"target": 0},
                    "final_response": {"target": 0},
                    "source": "llm",
                    "confidence": 0.88,
                    "policy_adjustments": [],
                    "errors": [],
                },
            ],
            "final_state": {
                "players": {
                    "0": {"alive": True, "role": "werewolf"},
                    "1": {"alive": False, "role": "seer"},
                    "2": {"alive": True, "role": "villager"},
                }
            },
        }

    def test_import_archive(self):
        archive = self._make_archive()
        archive_path = self.tmp_path / "archive.json"
        archive_path.write_text(json.dumps(archive), encoding="utf-8")

        game_id = self.importer.import_archive(archive_path)
        self.assertEqual(game_id, "test_game")

        game = GameStore(self.conn).get_game("test_game")
        self.assertIsNotNone(game)
        self.assertEqual(game["winner"], "werewolves")

        rows = self.conn.execute(
            "SELECT * FROM players WHERE game_id = 'test_game' ORDER BY seat"
        ).fetchall()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["alive"], 0)  # seer died

        decisions = DecisionStore(self.conn).query(game_id="test_game")
        self.assertEqual(len(decisions), 2)

    def test_import_idempotent(self):
        archive = self._make_archive()
        archive_path = self.tmp_path / "archive.json"
        archive_path.write_text(json.dumps(archive), encoding="utf-8")

        g1 = self.importer.import_archive(archive_path)
        g2 = self.importer.import_archive(archive_path)
        self.assertEqual(g1, g2)
        self.assertEqual(GameStore(self.conn).count_games(), 1)

    def test_import_directory(self):
        for i, game_id in enumerate(["game_a", "game_b"]):
            archive = self._make_archive(game_id=game_id)
            subdir = self.tmp_path / f"run_{i}"
            subdir.mkdir()
            (subdir / "archive.json").write_text(
                json.dumps(archive), encoding="utf-8"
            )

        count = self.importer.import_directory(self.tmp_path)
        self.assertEqual(count, 2)
        self.assertEqual(GameStore(self.conn).count_games(), 2)

    def test_import_nonexistent(self):
        count = self.importer.import_directory(self.tmp_path / "nope")
        self.assertEqual(count, 0)

    def test_import_invalid_json(self):
        bad_file = self.tmp_path / "archive.json"
        bad_file.write_text("not json {{{", encoding="utf-8")

        result = self.importer.import_archive(bad_file)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
