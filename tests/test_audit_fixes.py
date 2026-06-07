"""Focused regression tests for the audit-driven fixes."""

from __future__ import annotations

import asyncio
from pathlib import Path
import json

import pytest


def test_evidence_normalizer_and_selector_ported_from_agent(tmp_path: Path):
    from app.lib.evidence import GameEvidenceBundle, normalize_decisions, select_key_decisions

    bundle = GameEvidenceBundle(
        game_dir=tmp_path,
        game_id="g1",
        archive={
            "winner": "villagers",
            "player_roles": {"1": "seer", "2": "werewolf"},
            "decisions": [
                {
                    "decision_id": "d1",
                    "index": 1,
                    "player_id": 1,
                    "day": 1,
                    "phase": "night",
                    "action_type": "seer_check",
                    "candidates": [2],
                    "final_response": {"target": 2},
                    "parsed_decision": {"public_text": "查验 2 号"},
                    "confidence": 0.75,
                    "selected_skills": ["seer_check_basic"],
                }
            ],
        },
        agent_decisions=[
            {
                "decision_id": "d1",
                "selected_target": 2,
                "private_reasoning": "2号发言有冲突，优先查验。",
                "source": "llm",
            }
        ],
        game_events=[
            {"event_type": "game_init", "payload": {"roles": {"1": "seer", "2": "werewolf"}}},
            {"event_type": "night_end", "day": 1, "phase": "night"},
        ],
        meta={},
    )

    inputs = normalize_decisions(bundle)
    assert len(inputs) == 1
    item = inputs[0]
    assert item.decision_id == "d1"
    assert item.player_view.role == "seer"
    assert item.decision_result.selected_target == 2
    assert item.agent_reasoning.private_reasoning == "2号发言有冲突，优先查验。"
    assert item.god_view_after_game.target_true_role == "werewolf"

    key_decisions = select_key_decisions(inputs, bundle)
    assert [k.decision_id for k in key_decisions] == ["d1"]
    assert key_decisions[0].key_reason == "rule_natural_key_action"
    assert key_decisions[0].impact_level == "high"
    assert item.to_dict()["player_view"]["role"] == "seer"


def test_evidence_normalizer_accepts_json_string_fields(tmp_path: Path):
    from app.lib.evidence import GameEvidenceBundle, normalize_decisions

    bundle = GameEvidenceBundle(
        game_dir=tmp_path,
        game_id="g_json",
        archive={},
        agent_decisions=[
            {
                "decision_id": "d_json",
                "player_id": "4",
                "day": "2",
                "phase": "night",
                "action_type": "witch_act",
                "selected_choice": "poison",
                "selected_target": "8",
                "candidates": "[7, 8, 9]",
                "parsed_decision": json.dumps({"private_reasoning": "8号像狼", "public_text": ""}, ensure_ascii=False),
                "errors": '["parse_retry"]',
                "policy_adjustments": '["target_validated"]',
            }
        ],
        game_events=[
            {
                "event_type": "game_init",
                "payload": json.dumps({"roles": {"4": "witch", "8": "werewolf"}}, ensure_ascii=False),
            }
        ],
        meta={},
    )

    item = normalize_decisions(bundle)[0]
    assert item.player_view.player_id == 4
    assert item.player_view.role == "witch"
    assert item.player_view.candidates == [7, 8, 9]
    assert item.agent_reasoning.private_reasoning == "8号像狼"
    assert item.decision_result.errors == ["parse_retry"]
    assert item.decision_result.policy_adjustments == ["target_validated"]
    assert item.god_view_after_game.target_true_role == "werewolf"


def test_evidence_node_produces_outputs_when_game_dir_present(tmp_path: Path):
    from app.graphs.shared.nodes.review import evidence_node

    async def _run():
        return await evidence_node(
            {
                "game_dir": tmp_path,
                "game_id": "g_node",
                "roles": {"1": "seer", "2": "werewolf"},
                "review": {"winner": "villagers", "player_roles": {"1": "seer", "2": "werewolf"}},
                "game_events": [
                    {"event_type": "night_end", "day": 1, "phase": "night"},
                ],
                "decisions": [
                    {
                        "decision_id": "d_node",
                        "player_id": 1,
                        "role": "seer",
                        "day": 1,
                        "phase": "night",
                        "action_type": "seer_check",
                        "selected_target": 2,
                    }
                ],
            }
        )

    result = asyncio.run(_run())
    assert result["evidence"]["status"] == "ok"
    assert result["evidence"]["evidence_inputs"] == 1
    assert result["evidence_inputs"][0].decision_id == "d_node"
    assert result["key_decisions"][0].decision_id == "d_node"


def test_private_night_action_log_is_not_public():
    from engine.actions import ask
    from engine.models import ActionResponse, ActionType, Phase

    class Agent:
        def act(self, request):
            return ActionResponse(request.action_type, target=2)

    class Engine:
        def __init__(self):
            self.state = type("State", (), {"phase": Phase.NIGHT})()
            self.agents = {1: Agent()}
            self.records = []

        def observation_for(self, player_id, metadata):
            return object()

        def _record(self, event_type, **kwargs):
            self.records.append({"event_type": event_type, **kwargs})

    engine = Engine()
    asyncio.run(ask(engine, 1, ActionType.WEREWOLF_KILL, candidates=(2,)))

    action_event = next(row for row in engine.records if row["event_type"] == "werewolf_kill")
    assert action_event["public"] is False


def test_public_speech_action_remains_public():
    from engine.actions import ask
    from engine.models import ActionResponse, ActionType, Phase

    class Agent:
        def act(self, request):
            return ActionResponse(request.action_type, text="我认为2号偏狼。")

    class Engine:
        def __init__(self):
            self.state = type("State", (), {"phase": Phase.DAY_SPEECH})()
            self.agents = {1: Agent()}
            self.records = []

        def observation_for(self, player_id, metadata):
            return object()

        def _record(self, event_type, **kwargs):
            self.records.append({"event_type": event_type, **kwargs})

    engine = Engine()
    asyncio.run(ask(engine, 1, ActionType.SPEAK))

    action_event = next(row for row in engine.records if row["event_type"] == "speak")
    assert action_event["public"] is True


def test_speech_action_ignores_target_and_choice_noise():
    from engine.actions import ask, response_message
    from engine.models import ActionResponse, ActionType, Phase

    class Agent:
        def act(self, request):
            return ActionResponse(
                request.action_type,
                target=4,
                choice="werewolf_kill",
                text="我的遗言",
                decision_id="d7",
            )

    class Engine:
        def __init__(self):
            self.state = type("State", (), {"phase": Phase.DAY_SPEECH})()
            self.agents = {7: Agent()}
            self.records = []

        def observation_for(self, player_id, metadata):
            return object()

        def _record(self, event_type, **kwargs):
            self.records.append({"event_type": event_type, **kwargs})

    engine = Engine()
    response = asyncio.run(ask(engine, 7, ActionType.LAST_WORD))

    action_event = next(row for row in engine.records if row["event_type"] == "last_word")
    response_event = next(row for row in engine.records if row["event_type"] == "action_response")

    assert response.target is None
    assert response.choice is None
    assert response.text == "我的遗言"
    assert action_event["target"] is None
    assert action_event["payload"]["choice"] is None
    assert response_event["target"] is None
    assert response_event["payload"]["choice"] is None
    assert response_event["message"] == "7号响应遗言，发言：我的遗言"
    assert "目标4号" not in response_event["message"]
    assert "狼人夜刀" not in response_event["message"]
    assert (
        response_message(
            7,
            ActionResponse(
                ActionType.LAST_WORD,
                target=4,
                choice="werewolf_kill",
                text="我的遗言",
            ),
        )
        == "7号响应遗言，发言：我的遗言"
    )


def test_action_logs_use_chinese_action_labels():
    from engine.actions import ask, response_message
    from engine.models import ActionResponse, ActionType, Phase

    class Agent:
        def act(self, request):
            return ActionResponse(request.action_type, target=3, text="我投3号。")

    class Engine:
        def __init__(self):
            self.state = type("State", (), {"phase": Phase.SHERIFF_ELECTION})()
            self.agents = {11: Agent()}
            self.records = []

        def observation_for(self, player_id, metadata):
            return object()

        def _record(self, event_type, **kwargs):
            self.records.append({"event_type": event_type, **kwargs})

    engine = Engine()
    asyncio.run(ask(engine, 11, ActionType.SHERIFF_VOTE, candidates=(1, 2, 3)))

    request_event = next(row for row in engine.records if row["event_type"] == "action_request")
    response_event = next(row for row in engine.records if row["event_type"] == "action_response")

    assert request_event["message"] == "请求11号执行警长投票"
    assert response_event["message"].startswith("11号响应警长投票")
    assert response_message(11, ActionResponse(ActionType.SHERIFF_VOTE, target=3, choice="stay")) == "11号响应警长投票，目标3号，选择留警上"
    assert "sheriff_vote" not in request_event["message"]
    assert "sheriff_vote" not in response_event["message"]


def test_night_event_without_explicit_visibility_defaults_private():
    from engine.logging import GameLogger
    from engine.models import Phase

    logger = GameLogger()

    event = logger.record(
        day=1,
        phase=Phase.NIGHT,
        event_type="future_private_night_result",
        message="新增夜晚私有结果",
    )

    assert event.public is False


def test_night_public_reveal_events_remain_public_by_default():
    from engine.logging import GameLogger
    from engine.models import Phase

    logger = GameLogger()

    night_end = logger.record(
        day=1,
        phase=Phase.NIGHT,
        event_type="night_end",
        message="天亮公布昨夜死亡玩家",
    )
    death = logger.record(
        day=1,
        phase=Phase.NIGHT,
        event_type="death",
        message="2 号死亡",
        target=2,
    )

    assert night_end.public is True
    assert death.public is True


def test_day_public_event_remains_public_by_default():
    from engine.logging import GameLogger
    from engine.models import Phase

    logger = GameLogger()

    event = logger.record(
        day=1,
        phase=Phase.DAY_SPEECH,
        event_type="day_speech_start",
        message="白天发言开始",
    )

    assert event.public is True


def test_review_handles_missing_confidence_in_highlight():
    from app.lib.review import analyze_game
    from engine.models import Role, Team

    review = analyze_game(
        game_log=[],
        agent_decisions={
            1: [
                {
                    "day": 1,
                    "action_type": "exile_vote",
                    "selected_target": 2,
                    "source": "llm",
                    "confidence": None,
                }
            ]
        },
        roles={1: Role.VILLAGER, 2: Role.WEREWOLF},
        winner_team=Team.VILLAGERS,
        game_id="g1",
    )

    assert "投票放逐狼人 P2" in review.agent_scores[1].highlights[0]


def test_sqlite_decision_sink_rejects_missing_player_id(tmp_path: Path):
    from storage.interfaces import DecisionRecordData
    from storage.runtime import SQLiteDecisionSink
    from storage.schema import get_connection

    conn = get_connection(tmp_path / "wolf.db")
    try:
        sink = SQLiteDecisionSink(conn, "g1")
        sink.record_decision(
            DecisionRecordData(
                decision_id="d1",
                player_id=3,
                role="seer",
                day=1,
                phase="night",
                action_type="seer_check",
            )
        )
        row = conn.execute("SELECT seat, created_at FROM decisions WHERE id = ?", ("g1::d1",)).fetchone()
        assert row["seat"] == 3
        assert row["created_at"].endswith("+08:00")

        with pytest.raises(ValueError, match="player_id is required"):
            sink.record_decision(
                DecisionRecordData(
                    decision_id="d2",
                    player_id=None,
                    role="seer",
                    day=1,
                    phase="night",
                    action_type="seer_check",
                )
            )
    finally:
        conn.close()


def test_sqlite_decision_sink_batches_commits(tmp_path: Path):
    from storage.interfaces import DecisionRecordData
    from storage.runtime import SQLiteDecisionSink
    from storage.schema import get_connection

    db_path = tmp_path / "wolf.db"
    conn = get_connection(db_path)
    reader = get_connection(db_path)
    try:
        sink = SQLiteDecisionSink(conn, "g1", commit_every=2)
        sink.record_decision(
            DecisionRecordData(
                decision_id="d1",
                player_id=1,
                role="seer",
                day=1,
                phase="night",
                action_type="seer_check",
            )
        )
        assert reader.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"] == 0

        sink.record_decision(
            DecisionRecordData(
                decision_id="d2",
                player_id=2,
                role="villager",
                day=1,
                phase="day",
                action_type="speak",
            )
        )
        assert reader.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"] == 2
    finally:
        reader.close()
        conn.close()


def test_game_persistence_commit_flushes_pending_sink_writes(tmp_path: Path):
    from storage.interfaces import DecisionRecordData
    from storage.runtime import GamePersistence
    from storage.schema import get_connection

    db_path = tmp_path / "wolf.db"
    persistence = GamePersistence(game_id="g_flush", db_path=db_path, commit_every=100)
    reader = get_connection(db_path)
    try:
        sink = persistence.create_decision_sink()
        assert sink is not None
        sink.record_decision(
            DecisionRecordData(
                decision_id="d1",
                player_id=1,
                role="seer",
                day=1,
                phase="night",
                action_type="seer_check",
            )
        )
        assert reader.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"] == 0

        persistence.commit()
        assert reader.execute("SELECT COUNT(*) AS n FROM decisions").fetchone()["n"] == 1
    finally:
        reader.close()
        persistence.close()


def test_sqlite_event_sink_records_project_timezone_created_at(tmp_path: Path):
    from engine.models import GameEvent, Phase
    from storage.runtime import SQLiteEventSink
    from storage.schema import get_connection

    conn = get_connection(tmp_path / "wolf.db")
    try:
        sink = SQLiteEventSink(conn, "g1", commit_every=1)
        sink.record_event(
            GameEvent(
                type="death",
                day=1,
                phase=Phase.NIGHT,
                target=2,
                payload={"cause": "werewolf"},
                message="2 died",
            )
        )

        row = conn.execute("SELECT created_at FROM game_events WHERE game_id = ?", ("g1",)).fetchone()
        assert row["created_at"].endswith("+08:00")
    finally:
        conn.close()
