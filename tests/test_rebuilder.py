from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from storage.rebuilder import StorageRebuilder
from storage.schema import get_connection


class TestStorageRebuilder(unittest.TestCase):
    def test_rebuild_directory_namespaces_duplicate_selfplay_game_ids(self):
        conn = get_connection(Path(":memory:"))
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "runs"
            game_a = root / "selfplay" / "run_a" / "games" / "game_001"
            game_b = root / "selfplay" / "run_b" / "games" / "game_001"
            self._write_game(game_a, winner="villagers", target=2)
            self._write_game(game_b, winner="werewolves", target=3)

            report = StorageRebuilder(conn).rebuild_directory(root)

            self.assertEqual(report.scanned, 2)
            self.assertEqual(report.imported, 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM game_events").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM experience_candidates").fetchone()[0], 2)

            decision_ids = [
                row["id"]
                for row in conn.execute("SELECT id FROM decisions ORDER BY id").fetchall()
            ]
            self.assertEqual(len(set(decision_ids)), 2)
            self.assertTrue(all(item.endswith("::d1") for item in decision_ids))

            candidate_rows = conn.execute(
                "SELECT game_id, evidence_decision_ids, raw_json FROM experience_candidates ORDER BY game_id"
            ).fetchall()
            for row in candidate_rows:
                evidence_ids = json.loads(row["evidence_decision_ids"])
                raw_json = json.loads(row["raw_json"])
                self.assertEqual(evidence_ids, [f"{row['game_id']}::d1"])
                self.assertEqual(raw_json["source_evidence_decision_ids"], ["d1"])

            # Rebuild is idempotent for the same canonical game IDs.
            second = StorageRebuilder(conn).rebuild_directory(root)
            self.assertEqual(second.imported, 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM games").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0], 2)
        conn.close()

    def test_import_interactive_game_directory(self):
        conn = get_connection(Path(":memory:"))
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "runs"
            game_dir = root / "games" / "20260604_120000_1"
            self._write_game(game_dir, winner="villagers", target=2)

            game_id = StorageRebuilder(conn).import_game_dir(game_dir, root=root)

            self.assertEqual(game_id, "games::20260604_120000_1")
            game = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
            self.assertIsNotNone(game)
            config = json.loads(game["config"])
            self.assertEqual(config["_storage"]["source_game_id"], "game_001")
        conn.close()

    def test_rebuild_directory_imports_evolution_battle_summary(self):
        conn = get_connection(Path(":memory:"))
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "runs"
            evo_dir = root / "evolution" / "evo_001"
            evo_dir.mkdir(parents=True)
            state = {
                "run_id": "evo_001",
                "role": "seer",
                "parent_hash": "base_hash",
                "candidate_hash": "cand_hash",
                "status": "reviewing",
                "training_games": 2,
                "battle_games": 12,
                "baseline_config": {
                    "name": "baseline",
                    "created_at": "2026-06-04T00:00:00",
                    "role_versions": {"seer": "base_hash"},
                    "notes": [],
                },
            }
            summary = {
                "role": "seer",
                "candidate_hash": "cand_hash",
                "battle_games": 12,
                "games_played": 12,
                "baseline_config": {"role_versions": {"seer": "base_hash"}},
                "candidate_config": {"role_versions": {"seer": "cand_hash"}},
                "baseline_metrics": {"seer": {"role_weighted_score": 0.5}},
                "candidate_metrics": {"seer": {"role_weighted_score": 0.7}},
            }
            (evo_dir / "state.json").write_text(
                json.dumps(state, ensure_ascii=False),
                encoding="utf-8",
            )
            (evo_dir / "battle_summary.json").write_text(
                json.dumps(summary, ensure_ascii=False),
                encoding="utf-8",
            )

            report = StorageRebuilder(conn).rebuild_directory(root)

            self.assertEqual(report.evolution_scanned, 1)
            self.assertEqual(report.evolution_imported, 1)
            row = conn.execute(
                "SELECT role, battle_games, battle_result FROM evolution_runs WHERE id = ?",
                ("evo_001",),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["role"], "seer")
            self.assertEqual(row["battle_games"], 12)
            self.assertEqual(json.loads(row["battle_result"])["candidate_hash"], "cand_hash")
        conn.close()

    def _write_game(self, game_dir: Path, *, winner: str, target: int) -> None:
        game_dir.mkdir(parents=True)
        archive = {
            "game_id": "game_001",
            "seed": 7,
            "config": {"agent_version": "test"},
            "player_roles": {"1": "seer", str(target): "werewolf"},
            "winner": winner,
            "started_at": "2026-06-04T00:00:00",
            "finished_at": "2026-06-04T00:01:00",
            "public_events": [{"type": "death", "day": 1, "player_id": target}],
            "decisions": [
                {
                    "decision_id": "d1",
                    "index": 1,
                    "player_id": 1,
                    "role": "seer",
                    "day": 1,
                    "phase": "night",
                    "action_type": "seer_check",
                    "candidates": [target],
                    "selected_target": target,
                    "parsed_decision": {"target": target},
                    "final_response": {"target": target},
                    "source": "llm",
                    "confidence": 0.8,
                }
            ],
            "final_state": {
                "players": {
                    "1": {"alive": True, "role": "seer"},
                    str(target): {"alive": False, "role": "werewolf"},
                }
            },
        }
        event = {
            "index": 1,
            "day": 1,
            "phase": "night",
            "event_type": "seer_result",
            "message": "查验完成",
            "actor": 1,
            "target": target,
            "payload": {"decision_id": "d1"},
        }
        candidate = {
            "candidate_id": "c1",
            "role": "seer",
            "candidate_type": "positive_pattern",
            "evidence_decision_ids": ["d1"],
            "recommendation": "优先查验高影响位",
        }
        (game_dir / "archive.json").write_text(
            json.dumps(archive, ensure_ascii=False),
            encoding="utf-8",
        )
        (game_dir / "game_events.jsonl").write_text(
            json.dumps(event, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        candidates_dir = game_dir / "learning_v2"
        candidates_dir.mkdir()
        (candidates_dir / "experience_candidates.jsonl").write_text(
            json.dumps(candidate, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
