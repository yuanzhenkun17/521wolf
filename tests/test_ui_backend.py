import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import ui.backend.app as app_module
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

    def test_list_games_reads_completed_game_directories(self):
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
            game_dir = log_dir / "game1"
            game_dir.mkdir()
            (game_dir / "events.jsonl").write_text(content, encoding="utf-8")
            (game_dir / "agent_decisions.jsonl").write_text(
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

    def test_read_archive_requires_game_specific_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            (log_dir / "archive.json").write_text(
                json.dumps({"game_id": "other", "decisions": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            manager = GameManager(log_dir=log_dir)

            self.assertIsNone(manager.read_archive("game1"))

            game_dir = log_dir / "game1"
            game_dir.mkdir()
            (game_dir / "archive.json").write_text(
                json.dumps({"game_id": "game1", "decisions": [{"index": 1}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            archive = manager.read_archive("game1")

            self.assertIsNotNone(archive)
            self.assertEqual(archive["game_id"], "game1")

    def test_start_selfplay_endpoint_passes_agent_version(self):
        class FakeRun:
            def snapshot(self):
                return {
                    "run_id": "selfplay_fake",
                    "status": "running",
                    "agent_version": "v1-baseline",
                }

        class FakeSelfplayManager:
            async def start_run(self, **kwargs):
                self.kwargs = kwargs
                return FakeRun()

        client = TestClient(app)
        old_manager = app_module.selfplay_manager
        fake_manager = FakeSelfplayManager()
        try:
            app_module.selfplay_manager = fake_manager

            response = client.post(
                "/api/selfplay",
                json={
                    "num_games": 2,
                    "agent_version": "v1-baseline",
                    "max_days": 5,
                },
            )

            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()["run_id"], "selfplay_fake")
            self.assertEqual(fake_manager.kwargs["agent_version"], "v1-baseline")
            self.assertEqual(fake_manager.kwargs["num_games"], 2)
            self.assertEqual(fake_manager.kwargs["max_days"], 5)
        finally:
            app_module.selfplay_manager = old_manager


if __name__ == "__main__":
    unittest.main()
