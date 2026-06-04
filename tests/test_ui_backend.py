import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import ui.backend.app as app_module
from agent.common.paths import PathConfig
from storage.schema import get_connection
from ui.backend.app import app
from ui.backend.game_runner import GameManager, RunningGame
from ui.backend.batch_role_evolution_runner import RoleBatchEvolutionRun
from ui.backend.role_evolution_runner import RoleEvolutionRun
from engine.models import ActionRequest, ActionResponse, ActionType, Observation, Phase, Role
from engine.players import HumanPlayer


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

    def test_start_game_endpoint_passes_human_player_id(self):
        class FakeGameManager:
            async def start_game(self, **kwargs):
                self.kwargs = kwargs
                return SimpleNamespace(game_id="human_game")

            def snapshot(self, game, include_events=True):
                return {
                    "game_id": game.game_id,
                    "log_name": game.game_id,
                    "status": "starting",
                    "winner": None,
                    "seed": None,
                    "human_player_id": self.kwargs["human_player_id"],
                    "day": 0,
                    "phase": "setup",
                    "sheriff_id": None,
                    "players": [],
                    "event_count": 0,
                    "events": [],
                    "decisions": [],
                    "error": None,
                }

        client = TestClient(app)
        old_manager = app_module.manager
        fake_manager = FakeGameManager()
        try:
            app_module.manager = fake_manager

            response = client.post("/api/games", json={"seed": 7, "human_player_id": 3})
        finally:
            app_module.manager = old_manager

        self.assertEqual(response.status_code, 201)
        self.assertEqual(fake_manager.kwargs["seed"], 7)
        self.assertEqual(fake_manager.kwargs["human_player_id"], 3)
        self.assertEqual(response.json()["human_player_id"], 3)

    def test_human_action_endpoints_poll_and_submit(self):
        class FakeGameManager:
            def __init__(self):
                self.pending = {
                    "player_id": 3,
                    "action_type": "seer_check",
                    "phase": "night",
                    "day": 1,
                    "role": "seer",
                    "alive_players": [1, 2, 3],
                    "candidates": [1, 2],
                    "metadata": {},
                    "observation": {"role": "seer", "day": 1, "alive_players": [1, 2, 3]},
                }
                self.submitted = None

            def get_game(self, game_id):
                return SimpleNamespace(game_id=game_id) if game_id == "human_game" else None

            def pending_human_action(self, game_id):
                return self.pending

            def submit_human_action(self, game_id, **kwargs):
                self.submitted = {"game_id": game_id, **kwargs}
                return True

        client = TestClient(app)
        old_manager = app_module.manager
        fake_manager = FakeGameManager()
        try:
            app_module.manager = fake_manager

            pending = client.get("/api/games/human_game/human-action")
            submitted = client.post(
                "/api/games/human_game/action",
                json={"action_type": "seer_check", "target": 2, "text": "查 2"},
            )
            fake_manager.pending = None
            no_pending = client.get("/api/games/human_game/human-action")
        finally:
            app_module.manager = old_manager

        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json()["player_id"], 3)
        self.assertEqual(submitted.status_code, 204)
        self.assertEqual(fake_manager.submitted["game_id"], "human_game")
        self.assertEqual(fake_manager.submitted["target"], 2)
        self.assertEqual(fake_manager.submitted["text"], "查 2")
        self.assertEqual(no_pending.status_code, 204)

    def test_game_manager_human_action_pending_and_submit(self):
        async def run_scenario(log_dir: Path):
            manager = GameManager(log_dir=log_dir)
            human = HumanPlayer(player_id=3)
            game = RunningGame(
                game_id="human_game",
                log_name="human_game",
                seed=None,
                status="running",
                human_player_id=3,
            )
            game.engine = SimpleNamespace(agents={3: human})
            manager._games[game.game_id] = game

            observation = Observation(
                player_id=3,
                self_role=Role.SEER,
                phase=Phase.NIGHT,
                day=1,
                alive_players=(1, 2, 3),
                dead_players=(),
                sheriff_id=None,
                public_log=("昨夜平安夜",),
            )
            request = ActionRequest(
                player_id=3,
                action_type=ActionType.SEER_CHECK,
                phase=Phase.NIGHT,
                observation=observation,
                candidates=(1, 2),
                metadata={"prompt": "check"},
            )

            task = asyncio.create_task(human.act(request))
            await asyncio.sleep(0)

            pending = manager.pending_human_action("human_game")
            self.assertIsNotNone(pending)
            assert pending is not None
            self.assertEqual(pending["action_type"], "seer_check")
            self.assertEqual(pending["candidates"], [1, 2])
            self.assertEqual(pending["observation"]["role"], "seer")

            class FakeLogEntry:
                def to_dict(self):
                    return {
                        "index": 1,
                        "event_type": "action_request",
                        "actor": 3,
                        "payload": {"action_type": "seer_check"},
                    }

            game.engine.logger = SimpleNamespace(entries=[FakeLogEntry()])
            queue: asyncio.Queue[dict] = asyncio.Queue()
            game.subscribers.add(queue)
            cursor = await manager._publish_new_entries(game, 0)
            log_item = await asyncio.wait_for(queue.get(), timeout=1)
            decision_item = await asyncio.wait_for(queue.get(), timeout=1)
            game.subscribers.clear()

            self.assertEqual(cursor, 1)
            self.assertEqual(log_item["kind"], "log")
            self.assertEqual(decision_item["kind"], "decision_needed")
            self.assertEqual(decision_item["payload"]["action_type"], "seer_check")

            accepted = manager.submit_human_action(
                "human_game",
                action_type="seer_check",
                target=2,
                text="查验 2 号",
            )
            response = await task

            self.assertTrue(accepted)
            self.assertEqual(response, ActionResponse(ActionType.SEER_CHECK, target=2, text="查验 2 号"))
            self.assertIsNone(manager.pending_human_action("human_game"))

        with tempfile.TemporaryDirectory() as temp_dir:
            asyncio.run(run_scenario(Path(temp_dir)))

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
            game_dir = log_dir / "20260529_143052_1"
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
            self.assertEqual(games[0]["game_id"], "20260529_143052_1")
            self.assertEqual(games[0]["winner"], "werewolves")
            self.assertEqual(games[0]["event_count"], 3)
            self.assertEqual(games[0]["players"][0]["team"], "werewolves")
            self.assertFalse(games[0]["players"][1]["alive"])

            snapshot = manager.get_game("20260529_143052_1")
            self.assertIsNotNone(snapshot)
            detailed = manager.snapshot(snapshot)
            self.assertEqual(len(detailed["decisions"]), 1)
            self.assertEqual(detailed["decisions"][0]["index"], 1)
            self.assertEqual(detailed["decisions"][0]["private_reasoning"], "夜间优先刀 2 号。")

            review = manager.build_review("20260529_143052_1")
            self.assertIsNotNone(review)
            review_path = game_dir / "review.json"
            self.assertTrue(review_path.exists())
            review_path.write_text(
                json.dumps({"game_id": "20260529_143052_1", "winner": "cached"}, ensure_ascii=False),
                encoding="utf-8",
            )
            cached_review = manager.build_review("20260529_143052_1")
            self.assertEqual(cached_review["winner"], "cached")

    def test_completed_game_detail_prefers_sqlite_replay_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            game_id = "20260604_120000_1"
            game_dir = root / "runs" / "games" / game_id
            game_dir.mkdir(parents=True)
            (game_dir / "game_events.jsonl").write_text(
                json.dumps({"event_type": "file_event", "payload": {}}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (game_dir / "archive.json").write_text(
                json.dumps(
                    {"game_id": game_id, "decisions": [{"decision_id": "file_dec"}]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            db_path = root / "data" / "wolf.db"
            conn = get_connection(db_path)
            conn.execute(
                "INSERT INTO games (id, seed, config, winner, started_at) VALUES (?, ?, ?, ?, ?)",
                (
                    game_id,
                    11,
                    json.dumps({"_storage": {"source_path": str(game_dir)}}, ensure_ascii=False),
                    "villagers",
                    "2026-06-04T12:00:00",
                ),
            )
            conn.execute(
                "INSERT INTO game_events "
                "(game_id, idx, day, phase, event_type, message, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    game_id,
                    1,
                    0,
                    "setup",
                    "game_init",
                    "DB init",
                    json.dumps({"roles": {"1": "seer", "2": "werewolf"}}, ensure_ascii=False),
                ),
            )
            conn.execute(
                "INSERT INTO game_events "
                "(game_id, idx, day, phase, event_type, message, payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    game_id,
                    2,
                    1,
                    "finished",
                    "game_end",
                    "DB end",
                    json.dumps({"winner": "villagers"}, ensure_ascii=False),
                ),
            )
            conn.execute(
                "INSERT INTO decisions "
                "(id, game_id, seat, role, day, phase, action_type, selected_target, "
                "public_text, confidence, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{game_id}::db_dec",
                    game_id,
                    1,
                    "seer",
                    1,
                    "night",
                    "seer_check",
                    2,
                    "查验 2 号",
                    0.9,
                    "2026-06-04T12:00:00",
                ),
            )
            conn.commit()
            conn.close()

            manager = GameManager(paths=PathConfig(root=root))

            games = manager.list_games()
            loaded = manager.get_game(game_id)
            self.assertIsNotNone(loaded)
            snapshot = manager.snapshot(loaded)
            review = manager.build_review(game_id)

            self.assertEqual(games[0]["game_id"], game_id)
            self.assertEqual(games[0]["event_count"], 2)
            self.assertEqual(games[0]["winner"], "villagers")
            self.assertEqual(snapshot["events"][0]["event_type"], "game_init")
            self.assertEqual(snapshot["decisions"][0]["decision_id"], "db_dec")
            self.assertEqual(snapshot["decisions"][0]["selected_target"], 2)
            self.assertIsNotNone(review)
            self.assertEqual(review["game_id"], game_id)
            self.assertEqual(review["winner"], "villagers")

    def test_read_archive_requires_game_specific_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            (log_dir / "archive.json").write_text(
                json.dumps({"game_id": "other", "decisions": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            manager = GameManager(log_dir=log_dir)

            self.assertIsNone(manager.read_archive("20260529_143052_1"))

            game_dir = log_dir / "20260529_143052_1"
            game_dir.mkdir()
            (game_dir / "archive.json").write_text(
                json.dumps({"game_id": "20260529_143052_1", "decisions": [{"index": 1}]}, ensure_ascii=False),
                encoding="utf-8",
            )
            archive = manager.read_archive("20260529_143052_1")

            self.assertIsNotNone(archive)
            self.assertEqual(archive["game_id"], "20260529_143052_1")

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

    def test_list_leaderboards_prefers_sqlite_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "data" / "wolf.db"
            conn = get_connection(db_path)
            conn.execute(
                "INSERT INTO leaderboard "
                "(version_id, role, games_played, wins, losses, win_rate, "
                "avg_survival_rounds, target_side_win_rate, win_rate_ci_low, "
                "win_rate_ci_high, scores, is_baseline, data_sufficient, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "sqlite_version",
                    "seer",
                    20,
                    13,
                    7,
                    0.65,
                    4.2,
                    0.7,
                    0.5,
                    0.85,
                    json.dumps({"role_weighted_score": 0.81}, ensure_ascii=False),
                    0,
                    1,
                    "2026-06-04T00:00:00",
                ),
            )
            conn.commit()
            conn.close()

            json_path = root / "data" / "leaderboard.json"
            json_path.write_text(
                json.dumps([{"version": "json_version"}], ensure_ascii=False),
                encoding="utf-8",
            )

            old_paths = app_module.DEFAULT_PATHS
            old_leaderboard_paths = app_module._LEADERBOARD_PATHS
            app_module.DEFAULT_PATHS = PathConfig(root=root)
            app_module._LEADERBOARD_PATHS = [json_path]
            client = TestClient(app)
            try:
                response = client.get("/api/leaderboards")
            finally:
                app_module.DEFAULT_PATHS = old_paths
                app_module._LEADERBOARD_PATHS = old_leaderboard_paths

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["source_type"], "sqlite")
            self.assertEqual(payload["entries"][0]["version"], "sqlite_version")
            self.assertEqual(payload["entries"][0]["scores"]["role_weighted_score"], 0.81)

    def test_list_role_batch_evolution_runs_endpoint(self):
        client = TestClient(app)

        response = client.get("/api/role-evolution/batches")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["kind"], "role_batch_evolution_runs")
        self.assertIn("batches", response.json())

    def test_evolution_runs_alias_lists_status_and_actions(self):
        run = RoleEvolutionRun(run_id="evo_alias", role="seer", status="running", stage="training")
        batch = RoleBatchEvolutionRun(batch_id="batch_alias", roles=["seer"], status="running", stage="training")
        role_runs = app_module.role_evolution_runner._active_runs
        batch_runs = app_module.role_batch_evolution_runner._active_batches
        old_role_run = role_runs.get(run.run_id)
        old_batch_run = batch_runs.get(batch.batch_id)
        role_runs[run.run_id] = run
        batch_runs[batch.batch_id] = batch
        client = TestClient(app)
        try:
            listing = client.get("/api/evolution-runs")
            role_status = client.get("/api/evolution-runs/evo_alias")
            batch_status = client.get("/api/evolution-runs/batch_alias")
            role_action = client.post("/api/evolution-runs/evo_alias/actions", json={"action": "stop"})
            batch_action = client.post("/api/evolution-runs/batch_alias/actions", json={"action": "stop"})
        finally:
            if old_role_run is None:
                role_runs.pop(run.run_id, None)
            else:
                role_runs[run.run_id] = old_role_run
            if old_batch_run is None:
                batch_runs.pop(batch.batch_id, None)
            else:
                batch_runs[batch.batch_id] = old_batch_run

        self.assertEqual(listing.status_code, 200)
        self.assertIn("runs", listing.json())
        self.assertIn("batches", listing.json())
        self.assertEqual(role_status.status_code, 200)
        self.assertEqual(role_status.json()["run_id"], "evo_alias")
        self.assertEqual(batch_status.status_code, 200)
        self.assertEqual(batch_status.json()["batch_id"], "batch_alias")
        self.assertEqual(role_action.status_code, 200)
        self.assertEqual(role_action.json()["status"], "paused")
        self.assertEqual(batch_action.status_code, 200)
        self.assertEqual(batch_action.json()["status"], "paused")

    def test_role_evolution_training_game_endpoints_read_nested_selfplay_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            evo_dir = Path(temp_dir) / "runs" / "evolution" / "evo_test"
            game_dir = evo_dir / "run_training" / "games" / "game_001"
            game_dir.mkdir(parents=True)
            (evo_dir / "state.json").write_text(
                json.dumps(
                    {
                        "run_id": "evo_test",
                        "training_run_id": "run_training",
                        "training_output_dir": str(evo_dir / "run_training"),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            event = {
                "index": 1,
                "day": 1,
                "phase": "day_speech",
                "event_type": "action_response",
                "message": "1 号发言",
                "level": "info",
                "visibility": "god",
                "actor": 1,
                "target": None,
                "payload": {
                    "action_type": "speak",
                    "text": "我是一张好人牌",
                    "decision_id": "dec_001",
                },
            }
            decision = {
                "decision_id": "dec_001",
                "day": 1,
                "phase": "day_speech",
                "player_id": 1,
                "role": "villager",
                "action_type": "speak",
                "candidates": [],
                "selected_target": None,
                "selected_choice": None,
                "public_text": "我是一张好人牌",
                "private_reasoning": "先表水",
                "confidence": 0.8,
                "alternatives": [],
                "rejected_reasons": [],
                "selected_skills": [],
                "belief_snapshot": {},
                "memory_summary": [],
                "raw_output": "{}",
                "errors": [],
                "policy_adjustments": [],
                "source": "llm",
            }
            (game_dir / "game_events.jsonl").write_text(
                json.dumps(event, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (game_dir / "agent_decisions.jsonl").write_text(
                json.dumps(decision, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (game_dir / "archive.json").write_text(
                json.dumps(
                    {
                        "game_id": "game_001",
                        "player_roles": {"1": "villager"},
                        "winner": "villagers",
                        "decisions": [{"index": 1, "decision_id": "dec_001"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            old_store = app_module.version_store
            app_module.version_store = SimpleNamespace(base_dir=Path(temp_dir))
            client = TestClient(app)
            try:
                games = client.get("/api/role-evolution/evo_test/games")
                events = client.get("/api/role-evolution/evo_test/games/game_001/events")
                decisions = client.get("/api/role-evolution/evo_test/games/game_001/decisions")
                archive = client.get("/api/role-evolution/evo_test/games/game_001/archive")
                alias_games = client.get("/api/evolution-runs/evo_test/games?phase=training")
                alias_events = client.get(
                    "/api/evolution-runs/evo_test/games/game_001/events?phase=training"
                )
                alias_decisions = client.get(
                    "/api/evolution-runs/evo_test/games/game_001/decisions?phase=training"
                )
            finally:
                app_module.version_store = old_store

            self.assertEqual(games.status_code, 200)
            self.assertEqual(games.json()["games"][0]["game_id"], "game_001")
            self.assertEqual(events.status_code, 200)
            self.assertEqual(events.json()["events"][0]["payload"]["decision_id"], "dec_001")
            self.assertEqual(decisions.status_code, 200)
            self.assertEqual(decisions.json()["decisions"][0]["index"], 1)
            self.assertEqual(decisions.json()["decisions"][0]["decision_id"], "dec_001")
            self.assertEqual(archive.status_code, 200)
            self.assertEqual(archive.json()["decisions"][0]["decision_id"], "dec_001")
            self.assertEqual(alias_games.status_code, 200)
            self.assertEqual(alias_games.json()["games"][0]["game_id"], "game_001")
            self.assertEqual(alias_events.status_code, 200)
            self.assertEqual(alias_events.json()["events"][0]["payload"]["decision_id"], "dec_001")
            self.assertEqual(alias_decisions.status_code, 200)
            self.assertEqual(alias_decisions.json()["decisions"][0]["decision_id"], "dec_001")

    def test_role_evolution_game_detail_prefers_sqlite_replay_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evo_dir = root / "runs" / "evolution" / "evo_test"
            game_dir = evo_dir / "run_training" / "games" / "game_001"
            game_dir.mkdir(parents=True)
            (evo_dir / "state.json").write_text(
                json.dumps(
                    {
                        "run_id": "evo_test",
                        "training_run_id": "run_training",
                        "training_output_dir": str(evo_dir / "run_training"),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (game_dir / "game_events.jsonl").write_text(
                json.dumps({"event_type": "file_event", "payload": {}}, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (game_dir / "archive.json").write_text(
                json.dumps({"game_id": "game_001", "decisions": [{"decision_id": "file_dec"}]}, ensure_ascii=False),
                encoding="utf-8",
            )

            db_path = root / "data" / "wolf.db"
            game_id = "evolution::evo_test::run_training::games::game_001"
            conn = get_connection(db_path)
            conn.execute(
                "INSERT INTO games (id, seed, config, started_at) VALUES (?, ?, ?, ?)",
                (
                    game_id,
                    1,
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
                    "db_event",
                    "from sqlite",
                    json.dumps({"decision_id": "db_dec"}, ensure_ascii=False),
                ),
            )
            conn.execute(
                "INSERT INTO decisions "
                "(id, game_id, seat, role, day, phase, action_type, public_text, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    f"{game_id}::db_dec",
                    game_id,
                    1,
                    "villager",
                    1,
                    "day_speech",
                    "speak",
                    "DB decision",
                    "2026-06-04T00:00:00",
                ),
            )
            conn.commit()
            conn.close()

            old_paths = app_module.DEFAULT_PATHS
            old_store = app_module.version_store
            app_module.DEFAULT_PATHS = PathConfig(root=root)
            app_module.version_store = SimpleNamespace(base_dir=root)
            client = TestClient(app)
            try:
                games = client.get("/api/role-evolution/evo_test/games")
                events = client.get("/api/role-evolution/evo_test/games/game_001/events")
                decisions = client.get("/api/role-evolution/evo_test/games/game_001/decisions")
            finally:
                app_module.DEFAULT_PATHS = old_paths
                app_module.version_store = old_store

            self.assertEqual(games.status_code, 200)
            self.assertEqual(games.json()["games"][0]["event_count"], 1)
            self.assertEqual(events.status_code, 200)
            self.assertEqual(events.json()["events"][0]["event_type"], "db_event")
            self.assertEqual(decisions.status_code, 200)
            self.assertEqual(decisions.json()["decisions"][0]["decision_id"], "db_dec")

    def test_role_leaderboard_prefers_sqlite_battle_summaries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "data" / "wolf.db"
            summary = {
                "role": "seer",
                "candidate_hash": "cand_hash",
                "battle_games": 12,
                "games_played": 12,
                "baseline_config": {"role_versions": {"seer": "base_hash"}},
                "candidate_config": {"role_versions": {"seer": "cand_hash"}},
                "baseline_metrics": {
                    "seer": {
                        "role_weighted_score": 0.6,
                        "speech_score": 0.6,
                        "vote_score": 0.6,
                        "skill_score": 0.6,
                        "information_score": 0.6,
                        "cooperation_score": 0.6,
                        "fallback_rate": 0.1,
                        "bad_case_rate": 0.1,
                    },
                    "villagers": {"win_rate": 0.5},
                },
                "candidate_metrics": {
                    "seer": {
                        "role_weighted_score": 0.8,
                        "speech_score": 0.8,
                        "vote_score": 0.8,
                        "skill_score": 0.8,
                        "information_score": 0.8,
                        "cooperation_score": 0.8,
                        "fallback_rate": 0.02,
                        "bad_case_rate": 0.01,
                    },
                    "villagers": {"win_rate": 0.7},
                },
            }
            conn = get_connection(db_path)
            conn.execute(
                "INSERT INTO evolution_runs "
                "(id, role, parent_hash, status, training_games, battle_games, "
                "config, candidate_hash, battle_result, errors, started_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "evo_db",
                    "seer",
                    "base_hash",
                    "reviewing",
                    2,
                    12,
                    json.dumps({"role_versions": {"seer": "base_hash"}}, ensure_ascii=False),
                    "cand_hash",
                    json.dumps(summary, ensure_ascii=False),
                    "[]",
                    "2026-06-04T00:00:00",
                ),
            )
            conn.commit()
            conn.close()

            old_paths = app_module.DEFAULT_PATHS
            app_module.DEFAULT_PATHS = PathConfig(root=root)
            client = TestClient(app)
            try:
                response = client.get("/api/roles/seer/leaderboard")
            finally:
                app_module.DEFAULT_PATHS = old_paths

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["source"], "sqlite")
            self.assertEqual(
                {entry["hash"] for entry in payload["entries"]},
                {"base_hash", "cand_hash"},
            )


if __name__ == "__main__":
    unittest.main()
