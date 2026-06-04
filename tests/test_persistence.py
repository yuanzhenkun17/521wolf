from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.infrastructure.decision_log import DecisionRecord
from agent.learning_v2.models import ExperienceCandidate
from engine.models import ActionType
from storage.runtime import GamePersistence
from storage.schema import get_connection


class TestGamePersistence(unittest.TestCase):
    def test_runtime_persistence_dual_writes_game_artifacts_and_sqlite(self):
        conn = get_connection(Path(":memory:"))
        with tempfile.TemporaryDirectory() as tmpdir:
            game_dir = Path(tmpdir)
            persistence = GamePersistence(game_id="g1", game_dir=game_dir, conn=conn)

            logger = persistence.create_event_logger(game_dir / "game_events.jsonl")
            logger.record(day=1, phase="night", event_type="seer_check", message="预言家查验")

            recorder = persistence.create_decision_recorder(game_dir / "agent_decisions.jsonl")
            recorder.record(
                DecisionRecord(
                    action_type=ActionType.SEER_CHECK,
                    decision_id="d1",
                    day=1,
                    phase="night",
                    player_id=1,
                    role="seer",
                    selected_target=2,
                    confidence=0.8,
                )
            )

            persistence.save_game_result(
                seed=7,
                player_roles={1: "seer", 2: "werewolf"},
                started_at="2026-06-04T00:00:00",
                winner="villagers",
                deaths=[{"player_id": 2, "cause": "exile", "day": 1}],
            )
            persistence.save_experience_candidates(
                [
                    ExperienceCandidate(
                        candidate_id="c1",
                        role="seer",
                        candidate_type="positive_pattern",
                        evidence_decision_ids=["d1"],
                    )
                ]
            )
            persistence.close()

            self.assertTrue((game_dir / "game_events.jsonl").exists())
            self.assertTrue((game_dir / "agent_decisions.jsonl").exists())

            event_line = json.loads((game_dir / "game_events.jsonl").read_text(encoding="utf-8").splitlines()[0])
            decision_line = json.loads((game_dir / "agent_decisions.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(event_line["event_type"], "seer_check")
            self.assertEqual(decision_line["decision_id"], "d1")

            self.assertEqual(conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM game_events").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM experience_candidates").fetchone()[0], 1)
            decision = conn.execute("SELECT id FROM decisions").fetchone()
            self.assertEqual(decision["id"], "g1::d1")
            candidate = conn.execute("SELECT evidence_decision_ids, raw_json FROM experience_candidates").fetchone()
            self.assertEqual(json.loads(candidate["evidence_decision_ids"]), ["g1::d1"])
            self.assertEqual(json.loads(candidate["raw_json"])["source_evidence_decision_ids"], ["d1"])
            game = conn.execute("SELECT config FROM games WHERE id = 'g1'").fetchone()
            self.assertEqual(json.loads(game["config"])["_storage"]["source_game_id"], "g1")
            player = conn.execute("SELECT role, alive FROM players WHERE seat = 2").fetchone()
            self.assertEqual(player["role"], "werewolf")
            self.assertEqual(player["alive"], 0)
        conn.close()

    def test_runtime_persistence_namespaces_duplicate_raw_selfplay_ids(self):
        conn = get_connection(Path(":memory:"))
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for run_id in ("run_a", "run_b"):
                storage_game_id = f"selfplay::{run_id}::games::game_001"
                game_dir = root / "runs" / "selfplay" / run_id / "games" / "game_001"
                persistence = GamePersistence(
                    game_id=storage_game_id,
                    source_game_id="game_001",
                    game_dir=game_dir,
                    conn=conn,
                )
                persistence.create_decision_recorder().record(
                    DecisionRecord(
                        action_type=ActionType.SEER_CHECK,
                        decision_id="d1",
                        day=1,
                        phase="night",
                        player_id=1,
                        role="seer",
                        selected_target=2,
                    )
                )
                persistence.save_game_result(
                    seed=7,
                    player_roles={1: "seer", 2: "werewolf"},
                    started_at="2026-06-04T00:00:00",
                    winner="villagers",
                )
                persistence.save_experience_candidates(
                    [
                        ExperienceCandidate(
                            candidate_id="c1",
                            role="seer",
                            candidate_type="positive_pattern",
                            evidence_decision_ids=["d1"],
                        )
                    ]
                )
                persistence.close()

            self.assertEqual(conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 2)
            decision_rows = conn.execute("SELECT id FROM decisions ORDER BY id").fetchall()
            self.assertEqual([row["id"] for row in decision_rows], [
                "selfplay::run_a::games::game_001::d1",
                "selfplay::run_b::games::game_001::d1",
            ])
            candidate_rows = conn.execute(
                "SELECT game_id, evidence_decision_ids FROM experience_candidates ORDER BY game_id"
            ).fetchall()
            self.assertEqual(len(candidate_rows), 2)
            for row in candidate_rows:
                self.assertEqual(json.loads(row["evidence_decision_ids"]), [f"{row['game_id']}::d1"])
        conn.close()


if __name__ == "__main__":
    unittest.main()
