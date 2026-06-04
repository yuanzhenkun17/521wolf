from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from storage.replay import read_decisions_for_artifact, read_events_for_artifact
from storage.schema import get_connection


class TestStorageReplay(unittest.TestCase):
    def test_reads_namespaced_game_by_source_path_and_restores_public_decision_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            db_path = root / "data" / "wolf.db"
            game_dir = root / "runs" / "selfplay" / "run_a" / "games" / "game_001"
            game_dir.mkdir(parents=True)
            game_id = "selfplay::run_a::games::game_001"

            conn = get_connection(db_path)
            conn.execute(
                "INSERT INTO games (id, seed, config, started_at) VALUES (?, ?, ?, ?)",
                (
                    game_id,
                    7,
                    json.dumps({"_storage": {"source_path": str(game_dir)}}, ensure_ascii=False),
                    "2026-06-04T00:00:00",
                ),
            )
            conn.execute(
                "INSERT INTO game_events "
                "(game_id, idx, day, phase, event_type, message, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    game_id,
                    1,
                    1,
                    "night",
                    "seer_result",
                    "DB event",
                    json.dumps({"decision_id": "d1"}, ensure_ascii=False),
                ),
            )
            conn.execute(
                "INSERT INTO decisions "
                "(id, game_id, seat, role, day, phase, action_type, selected_target, "
                "public_text, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{game_id}::d1",
                    game_id,
                    1,
                    "seer",
                    1,
                    "night",
                    "seer_check",
                    2,
                    "查验 2 号",
                    "2026-06-04T00:00:00",
                ),
            )
            conn.commit()
            conn.close()

            events = read_events_for_artifact(db_path, game_dir, root=root / "runs")
            decisions = read_decisions_for_artifact(db_path, game_dir, root=root / "runs")

            self.assertIsNotNone(events)
            self.assertEqual(events[0]["event_type"], "seer_result")
            self.assertEqual(events[0]["payload"]["decision_id"], "d1")
            self.assertIsNotNone(decisions)
            self.assertEqual(decisions[0]["decision_id"], "d1")
            self.assertEqual(decisions[0]["selected_target"], 2)


if __name__ == "__main__":
    unittest.main()
