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


def test_evidence_uses_target_id_when_target_is_absent(tmp_path: Path):
    from app.lib.evidence import GameEvidenceBundle, normalize_decisions, select_key_decisions

    bundle = GameEvidenceBundle(
        game_dir=tmp_path,
        game_id="g_target_id",
        archive={
            "winner": "villagers",
            "player_roles": {"1": "seer", "2": "werewolf"},
            "decisions": [
                {
                    "decision_id": "d_target_id",
                    "index": 1,
                    "player_id": 1,
                    "day": 1,
                    "phase": "night",
                    "action_type": "seer_check",
                    "target_id": "2",
                    "source": "llm",
                }
            ],
        },
        agent_decisions=[],
        game_events=[
            {"event_type": "game_init", "payload": {"roles": {"1": "seer", "2": "werewolf"}}},
            {"event_type": "death_result", "day": 1, "phase": "night", "target_id": "2"},
        ],
        meta={},
    )

    item = normalize_decisions(bundle)[0]
    assert item.decision_result.selected_target == 2
    assert item.god_view_after_game.target_true_role == "werewolf"

    key_decision = select_key_decisions([item], bundle)[0]
    assert key_decision.decision_id == "d_target_id"
    assert key_decision.turning_point_id == "death_turning_point_day_1_target_2"


def test_evidence_white_wolf_pass_is_not_highest_key_decision(tmp_path: Path):
    from app.lib.evidence import GameEvidenceBundle, normalize_decisions, select_key_decisions

    bundle = GameEvidenceBundle(
        game_dir=tmp_path,
        game_id="g_white_wolf_pass",
        archive={
            "player_roles": {"1": "white_wolf_king", "2": "seer"},
            "decisions": [
                {
                    "decision_id": "d_pass",
                    "player_id": 1,
                    "day": 1,
                    "phase": "day_speech",
                    "action_type": "white_wolf_explode",
                    "selected_choice": "pass",
                    "selected_target": None,
                    "source": "llm",
                    "confidence": 0.8,
                },
                {
                    "decision_id": "d_explode",
                    "player_id": 1,
                    "day": 1,
                    "phase": "day_speech",
                    "action_type": "white_wolf_explode",
                    "selected_choice": "explode",
                    "selected_target": 2,
                    "source": "llm",
                    "confidence": 0.8,
                },
            ],
        },
        agent_decisions=[],
        game_events=[
            {"event_type": "game_init", "payload": {"roles": {"1": "white_wolf_king", "2": "seer"}}},
        ],
        meta={},
    )

    inputs = normalize_decisions(bundle)
    key_decisions = select_key_decisions(inputs, bundle)

    assert [item.decision_id for item in key_decisions] == ["d_explode"]
    assert key_decisions[0].action_type == "white_wolf_explode"
    assert key_decisions[0].key_reason == "rule_natural_key_action"
    assert key_decisions[0].impact_level == "highest"


def test_evidence_selector_prioritizes_high_impact_actions_before_speech(tmp_path: Path):
    from app.lib.evidence import GameEvidenceBundle, normalize_decisions, select_key_decisions

    bundle = GameEvidenceBundle(
        game_dir=tmp_path,
        game_id="g_key_priority",
        archive={
            "winner": "villagers",
            "player_roles": {
                "1": "seer",
                "2": "werewolf",
                "3": "villager",
                "4": "guard",
            },
            "decisions": [
                {
                    "decision_id": "d_speak_wolf",
                    "index": 1,
                    "player_id": 2,
                    "day": 1,
                    "phase": "day_speech",
                    "action_type": "speak",
                    "public_text": "我先听一轮。",
                    "source": "llm",
                    "confidence": 0.8,
                },
                {
                    "decision_id": "d_check",
                    "index": 2,
                    "player_id": 1,
                    "day": 1,
                    "phase": "night",
                    "action_type": "seer_check",
                    "selected_target": 2,
                    "source": "llm",
                    "confidence": 0.8,
                },
                {
                    "decision_id": "d_speak_villager",
                    "index": 3,
                    "player_id": 3,
                    "day": 1,
                    "phase": "day_speech",
                    "action_type": "speak",
                    "public_text": "暂时不强打。",
                    "source": "llm",
                    "confidence": 0.8,
                },
                {
                    "decision_id": "d_kill",
                    "index": 4,
                    "player_id": 2,
                    "day": 1,
                    "phase": "night",
                    "action_type": "werewolf_kill",
                    "selected_target": 1,
                    "source": "llm",
                    "confidence": 0.8,
                },
                {
                    "decision_id": "d_vote",
                    "index": 5,
                    "player_id": 3,
                    "day": 1,
                    "phase": "exile_vote",
                    "action_type": "exile_vote",
                    "selected_target": 2,
                    "source": "llm",
                    "confidence": 0.8,
                },
            ],
        },
        agent_decisions=[],
        game_events=[
            {
                "event_type": "game_init",
                "payload": {
                    "roles": {
                        "1": "seer",
                        "2": "werewolf",
                        "3": "villager",
                        "4": "guard",
                    }
                },
            },
            {"event_type": "death_result", "day": 1, "phase": "night", "target_id": "1"},
            {"event_type": "exile_result", "day": 1, "phase": "day", "target_id": "2"},
        ],
        meta={},
    )

    inputs = normalize_decisions(bundle)
    key_decisions = select_key_decisions(inputs, bundle)

    assert [item.decision_id for item in key_decisions[:3]] == ["d_kill", "d_vote", "d_check"]
    assert all(item.action_type != "speak" for item in key_decisions[:3])
    assert {item.decision_id for item in key_decisions[3:]} >= {"d_speak_wolf", "d_speak_villager"}


def test_evidence_selector_diversifies_same_action_type(tmp_path: Path):
    from app.lib.evidence import GameEvidenceBundle, normalize_decisions, select_key_decisions

    bundle = GameEvidenceBundle(
        game_dir=tmp_path,
        game_id="g_key_diversity",
        archive={
            "winner": "villagers",
            "player_roles": {
                "1": "seer",
                "2": "werewolf",
                "3": "werewolf",
                "4": "white_wolf_king",
                "5": "villager",
            },
            "decisions": [
                {
                    "decision_id": "d_kill_1",
                    "index": 1,
                    "player_id": 2,
                    "day": 1,
                    "phase": "night",
                    "action_type": "werewolf_kill",
                    "selected_target": 1,
                    "source": "llm",
                    "confidence": 0.8,
                },
                {
                    "decision_id": "d_kill_2",
                    "index": 2,
                    "player_id": 3,
                    "day": 1,
                    "phase": "night",
                    "action_type": "werewolf_kill",
                    "selected_target": 1,
                    "source": "llm",
                    "confidence": 0.8,
                },
                {
                    "decision_id": "d_kill_3",
                    "index": 3,
                    "player_id": 4,
                    "day": 1,
                    "phase": "night",
                    "action_type": "werewolf_kill",
                    "selected_target": 1,
                    "source": "llm",
                    "confidence": 0.8,
                },
                {
                    "decision_id": "d_vote",
                    "index": 4,
                    "player_id": 5,
                    "day": 1,
                    "phase": "exile_vote",
                    "action_type": "exile_vote",
                    "selected_target": 2,
                    "source": "llm",
                    "confidence": 0.8,
                },
                {
                    "decision_id": "d_check",
                    "index": 5,
                    "player_id": 1,
                    "day": 1,
                    "phase": "night",
                    "action_type": "seer_check",
                    "selected_target": 2,
                    "source": "llm",
                    "confidence": 0.8,
                },
            ],
        },
        agent_decisions=[],
        game_events=[
            {
                "event_type": "game_init",
                "payload": {
                    "roles": {
                        "1": "seer",
                        "2": "werewolf",
                        "3": "werewolf",
                        "4": "white_wolf_king",
                        "5": "villager",
                    }
                },
            },
            {"event_type": "death_result", "day": 1, "phase": "night", "target_id": "1"},
            {"event_type": "exile_result", "day": 1, "phase": "day", "target_id": "2"},
        ],
        meta={},
    )

    key_decisions = select_key_decisions(normalize_decisions(bundle), bundle)

    assert [item.action_type for item in key_decisions[:3]] == [
        "werewolf_kill",
        "exile_vote",
        "seer_check",
    ]
    assert [item.decision_id for item in key_decisions[:3]] == ["d_kill_1", "d_vote", "d_check"]


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
    request_event = next(row for row in engine.records if row["event_type"] == "action_request")
    assert action_event["public"] is False
    assert request_event["message"] == "请狼人开始行动"


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
    prompt_event = next(row for row in engine.records if row["event_type"] == "speech_prompt")
    assert action_event["public"] is True
    assert prompt_event["public"] is True
    assert prompt_event["actor"] == 1
    assert prompt_event["payload"]["action_type"] == "speak"


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

    assert request_event["message"] == "请11号开始警长投票"
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


def test_public_events_only_filters_private_events_and_redacts_secret_payloads():
    from storage.public_events import public_events_only

    events = [
        {
            "event_type": "game_init",
            "visibility": "public",
            "payload": {"roles": {"1": "seer", "2": "werewolf"}, "seat_count": 12},
        },
        {"event_type": "day_speech_start", "public": False, "payload": {"message": "hidden by flag"}},
        {"event_type": "seer_result", "visibility": "private", "payload": {"target": 2, "role": "werewolf"}},
        {"event_type": "night_debug", "visibility": "god", "payload": {"roles": {"1": "seer"}}},
        {
            "event_type": "night_end",
            "phase": "night",
            "payload": {
                "killed_target": 2,
                "protected_target": 2,
                "saved": False,
                "death_ids": [2],
                "deaths": [{"id": 2, "role": "seer", "team": "villagers"}],
                "dead_players": [{"player_id": 3, "role": "villager"}],
            },
        },
    ]

    public_events = public_events_only(events)

    assert [event["event_type"] for event in public_events] == ["game_init", "night_end"]
    assert public_events[0]["payload"] == {"seat_count": 12}
    assert public_events[1]["payload"] == {"death_ids": [2], "deaths": [2], "dead_players": [3]}


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


def test_review_uses_target_id_when_target_is_absent():
    from app.lib.review import analyze_game
    from engine.models import Role, Team

    review = analyze_game(
        game_log=[
            {"event_type": "death", "payload": {"target_id": "2"}},
        ],
        agent_decisions={
            1: [
                {
                    "day": 1,
                    "action_type": "exile_vote",
                    "target_id": "3",
                    "source": "llm",
                    "confidence": None,
                }
            ],
            2: [
                {
                    "day": 1,
                    "action_type": "witch_act",
                    "selected_choice": "poison",
                    "target_id": "1",
                    "source": "llm",
                }
            ],
            3: [
                {
                    "day": 1,
                    "action_type": "werewolf_kill",
                    "target_id": "2",
                    "source": "llm",
                }
            ],
        },
        roles={1: Role.VILLAGER, 2: Role.WITCH, 3: Role.WEREWOLF},
        winner_team=Team.VILLAGERS,
        game_id="g_review_target_id",
    )

    assert review.agent_scores[2].survived is False
    assert review.agent_scores[1].vote_accuracy == 10.0
    assert "投票放逐狼人 P3" in review.agent_scores[1].highlights[0]
    assert review.agent_scores[2].skill_accuracy == 0.0
    assert "毒杀了 P1 (villager)" in review.agent_scores[2].mistakes[0]
    assert "狼人首刀 P2" in review.key_turning_points
    assert "女巫 P2 使用毒药毒杀 P1" in review.key_turning_points


def test_review_white_wolf_pass_is_not_successful_night_skill():
    from app.lib.review import analyze_game
    from engine.models import Role, Team

    review = analyze_game(
        game_log=[],
        agent_decisions={
            1: [
                {
                    "day": 1,
                    "phase": "day_speech",
                    "action_type": "white_wolf_explode",
                    "selected_choice": "pass",
                    "selected_target": None,
                    "source": "llm",
                }
            ]
        },
        roles={1: Role.WHITE_WOLF_KING, 2: Role.SEER},
        winner_team=Team.WEREWOLVES,
        game_id="g_white_wolf_pass",
    )

    assert review.agent_scores[1].skill_accuracy == 5.0


class _StorageCursor:
    rowcount = 0

    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _StorageConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.commits = 0
        self.closed = False

    def execute(self, sql: str, params=()):
        self.calls.append((sql, tuple(params)))
        return _StorageCursor()

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


def test_database_decision_sink_rejects_missing_player_id():
    from storage.interfaces import DecisionRecordData
    from storage.runtime import DatabaseDecisionSink

    conn = _StorageConn()
    sink = DatabaseDecisionSink(conn, "g1", commit_every=1)
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
    assert conn.calls[0][1][0] == "g1::d1"
    assert conn.calls[0][1][2] == 3
    assert conn.calls[0][1][-1].endswith("+08:00")

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


def test_database_decision_sink_batches_commits():
    from storage.interfaces import DecisionRecordData
    from storage.runtime import DatabaseDecisionSink

    conn = _StorageConn()
    sink = DatabaseDecisionSink(conn, "g1", commit_every=2)
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
    assert conn.commits == 0

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
    assert conn.commits == 1


def test_game_persistence_commit_flushes_pending_sink_writes():
    from storage.interfaces import DecisionRecordData
    from storage.runtime import GamePersistence

    conn = _StorageConn()
    persistence = GamePersistence(game_id="g_flush", conn=conn, commit_every=100)
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
        assert conn.commits == 0

        persistence.commit()
        assert conn.commits == 2
    finally:
        persistence.close()


def test_database_event_sink_records_project_timezone_created_at():
    from engine.models import GameEvent, Phase
    from storage.runtime import DatabaseEventSink

    conn = _StorageConn()
    sink = DatabaseEventSink(conn, "g1", commit_every=1)
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

    assert conn.calls[0][1][0] == "g1"
    assert conn.calls[0][1][-1].endswith("+08:00")
