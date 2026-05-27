import json
import tempfile
import unittest
from pathlib import Path

from helpers import agents_with, run, standard_roles
from engine.engine import GameEngine
from engine.logging import GameLogger, LogVisibility, next_game_log_name
from engine.models import ActionResponse, ActionType, DeathCause
from engine.actions import response_message


class LoggingTests(unittest.TestCase):
    def test_logger_exports_jsonl_text_and_files(self):
        logger = GameLogger()
        logger.record(
            day=1,
            phase="night",
            event_type="night_start",
            message="第 1 夜开始",
            visibility=LogVisibility.GOD,
            payload={"alive": [1, 2, 3]},
        )

        jsonl = logger.to_jsonl()
        text = logger.to_text()
        parsed = json.loads(jsonl.splitlines()[0])

        self.assertEqual(parsed["event_type"], "night_start")
        self.assertEqual(parsed["visibility"], "god")
        self.assertIn("第 1 夜开始", text)

        with tempfile.TemporaryDirectory() as temp_dir:
            json_path = Path(temp_dir) / "game.jsonl"
            text_path = Path(temp_dir) / "game.txt"

            logger.write_jsonl(json_path)
            logger.write_text(text_path)

            self.assertIn("night_start", json_path.read_text(encoding="utf-8"))
            self.assertIn("第 1 夜开始", text_path.read_text(encoding="utf-8"))

    def test_next_game_log_name_uses_next_numbered_game(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)

            self.assertEqual(next_game_log_name(log_dir), "game1")

            (log_dir / "game1.txt").write_text("第一局", encoding="utf-8")
            (log_dir / "game2.jsonl").write_text("{}", encoding="utf-8")
            (log_dir / "latest.txt").write_text("旧日志", encoding="utf-8")

            self.assertEqual(next_game_log_name(log_dir), "game3")

    def test_engine_logs_night_cycle_and_role_actions(self):
        agents = agents_with()
        agents[8].push(ActionResponse(ActionType.GUARD_PROTECT, target=7))
        for wolf_id in [1, 2, 3, 4]:
            agents[wolf_id].push(ActionResponse(ActionType.WEREWOLF_KILL, target=7))
        agents[5].push(ActionResponse(ActionType.SEER_CHECK, target=1))
        agents[6].push(ActionResponse(ActionType.WITCH_ACT, choice="none"))
        engine = GameEngine(standard_roles(), agents)

        run(engine.run_night())

        event_types = [entry.event_type for entry in engine.logger.entries]
        text_log = engine.logger.to_text()

        self.assertIn("night_start", event_types)
        self.assertIn("guard_result", event_types)
        self.assertIn("werewolf_result", event_types)
        self.assertIn("seer_result", event_types)
        self.assertIn("witch_result", event_types)
        self.assertIn("night_end", event_types)
        self.assertIn("守卫 8 号守护 7 号", text_log)
        self.assertIn("狼人最终击杀目标 7 号", text_log)
        self.assertIn("预言家 5 号查验 1 号", text_log)

    def test_night_action_text_is_logged_as_decision_note_not_speech(self):
        message = response_message(
            8,
            ActionResponse(ActionType.WITCH_ACT, choice="save", text="我选择用解药"),
        )

        self.assertIn("决策说明：我选择用解药", message)
        self.assertNotIn("发言：我选择用解药", message)

    def test_public_speech_text_is_still_logged_as_speech(self):
        message = response_message(8, ActionResponse(ActionType.SPEAK, text="我是好人"))

        self.assertIn("发言：我是好人", message)

    def test_engine_logs_hunter_shot_after_exile(self):
        agents = agents_with()
        for voter in range(1, 13):
            agents[voter].push(ActionResponse(ActionType.EXILE_VOTE, target=7))
        agents[7].push(ActionResponse(ActionType.LAST_WORD, text="猎人遗言"))
        agents[7].push(ActionResponse(ActionType.HUNTER_SHOOT, target=4))
        engine = GameEngine(standard_roles(), agents)

        run(engine.run_exile_vote())

        event_types = [entry.event_type for entry in engine.logger.entries]
        text_log = engine.logger.to_text()

        self.assertIn("hunter_shot", event_types)
        self.assertIn("猎人 7 号开枪带走 4 号", text_log)

    def test_non_hunter_death_does_not_log_hunter_no_shot(self):
        engine = GameEngine(standard_roles(), agents_with())
        engine.kill_player(5, DeathCause.WEREWOLF)

        run(engine.resolve_death_triggers([5]))

        event_types = [entry.event_type for entry in engine.logger.entries]
        self.assertNotIn("hunter_no_shot", event_types)


if __name__ == "__main__":
    unittest.main()
