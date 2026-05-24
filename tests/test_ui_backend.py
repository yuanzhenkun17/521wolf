import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ui.backend.app import app
from ui.backend.game_runner import GameManager


class UiBackendTests(unittest.TestCase):
    def test_health_endpoint(self):
        client = TestClient(app)

        response = client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_missing_game_returns_404(self):
        client = TestClient(app)

        response = client.get("/api/games/not-a-game")

        self.assertEqual(response.status_code, 404)

    def test_list_games_reads_completed_jsonl_logs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            init_event = {
                "index": 1,
                "day": 0,
                "phase": "setup",
                "event_type": "game_init",
                "message": "游戏初始化",
                "level": "info",
                "visibility": "god",
                "actor": None,
                "target": None,
                "payload": {"roles": {"1": "werewolf", "2": "villager"}},
            }
            death_event = {
                "index": 2,
                "day": 1,
                "phase": "night",
                "event_type": "death",
                "message": "2 号死亡，原因：werewolf",
                "level": "info",
                "visibility": "god",
                "actor": None,
                "target": 2,
                "payload": {"cause": "werewolf"},
            }
            end_event = {
                "index": 1,
                "day": 2,
                "phase": "finished",
                "event_type": "game_end",
                "message": "游戏结束，胜利方：werewolves",
                "level": "info",
                "visibility": "god",
                "actor": None,
                "target": None,
                "payload": {"winner": "werewolves"},
            }
            events = [init_event, death_event, end_event]
            content = "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n"
            (log_dir / "game1.jsonl").write_text(content, encoding="utf-8")
            (log_dir / "game1.agent.jsonl").write_text(
                json.dumps(
                    {
                        "day": 1,
                        "phase": "night",
                        "player_id": 1,
                        "role": "werewolf",
                        "action_type": "werewolf_kill",
                        "candidates": [2],
                        "selected_target": 2,
                        "selected_choice": None,
                        "public_text": "",
                        "private_reasoning": "夜间优先刀 2 号。",
                        "alternatives": [],
                        "rejected_reasons": [],
                        "belief_snapshot": {},
                        "memory_summary": [],
                        "source": "llm",
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
            manager = GameManager(log_dir=log_dir)

            games = manager.list_games()

            self.assertEqual(len(games), 1)
            self.assertEqual(games[0]["game_id"], "game1")
            self.assertEqual(games[0]["winner"], "werewolves")
            self.assertEqual(games[0]["event_count"], 3)
            self.assertEqual(games[0]["players"][0]["team"], "werewolves")
            self.assertFalse(games[0]["players"][1]["alive"])

            snapshot = manager.get_game("game1")
            self.assertIsNotNone(snapshot)
            detailed = manager.snapshot(snapshot)
            self.assertEqual(len(detailed["decisions"]), 1)
            self.assertEqual(detailed["decisions"][0]["index"], 1)
            self.assertEqual(detailed["decisions"][0]["private_reasoning"], "夜间优先刀 2 号。")


if __name__ == "__main__":
    unittest.main()
