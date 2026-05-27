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

    def test_start_evolution_endpoint_uses_ui_manager(self):
        class FakeRun:
            def snapshot(self):
                return {
                    "run_id": "evolution_fake",
                    "status": "running",
                    "stage": "queued",
                    "config": {
                        "base_version": "baseline",
                        "candidate_version": "dream_v1",
                    },
                }

        class FakeEvolutionManager:
            async def start_run(self, **kwargs):
                self.kwargs = kwargs
                return FakeRun()

        client = TestClient(app)
        old_manager = app_module.evolution_manager
        old_find_manifest = app_module._find_manifest_for_version
        fake_manager = FakeEvolutionManager()
        try:
            app_module.evolution_manager = fake_manager
            app_module._find_manifest_for_version = lambda version: Path("manifest.json") if version == "baseline" else None

            response = client.post(
                "/api/evolution",
                json={
                    "base_version": "baseline",
                    "candidate_version": "dream_v1",
                    "training_games": 1,
                    "battle_games": 2,
                },
            )

            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()["run_id"], "evolution_fake")
            self.assertEqual(fake_manager.kwargs["training_games"], 1)
            self.assertEqual(fake_manager.kwargs["battle_games"], 2)
        finally:
            app_module.evolution_manager = old_manager
            app_module._find_manifest_for_version = old_find_manifest

    def test_start_mixed_battle_endpoint_uses_ui_manager(self):
        class FakeRun:
            def snapshot(self):
                return {
                    "run_id": "mixed_fake",
                    "status": "running",
                    "config": {},
                }

        class FakeMixedBattleManager:
            async def start_run(self, **kwargs):
                self.kwargs = kwargs
                return FakeRun()

        client = TestClient(app)
        old_manager = app_module.mixed_battle_manager
        old_find_manifest = app_module._find_manifest_for_version
        fake_manager = FakeMixedBattleManager()
        try:
            app_module.mixed_battle_manager = fake_manager
            app_module._find_manifest_for_version = lambda version: Path(f"{version}/manifest.json")

            response = client.post(
                "/api/mixed-battles",
                json={
                    "wolves_version": "v2",
                    "villagers_version": "v1",
                    "games_per_side": 3,
                    "seed_start": 10,
                },
            )

            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.json()["run_id"], "mixed_fake")
            self.assertEqual(fake_manager.kwargs["games_per_side"], 3)
            self.assertEqual(fake_manager.kwargs["seed_start"], 10)
            self.assertEqual(fake_manager.kwargs["wolves_manifest_path"], Path("v2/manifest.json"))
            self.assertEqual(fake_manager.kwargs["villagers_manifest_path"], Path("v1/manifest.json"))
        finally:
            app_module.mixed_battle_manager = old_manager
            app_module._find_manifest_for_version = old_find_manifest


if __name__ == "__main__":
    unittest.main()
