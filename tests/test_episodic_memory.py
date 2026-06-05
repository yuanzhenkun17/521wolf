"""Tests for agent.core.episodic_memory — cross-game episodic memory."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from agent.core.episodic_memory import (
    DecisionOutcome,
    EpisodicMemoryWriter,
    SituationalRecord,
    _team_for_role,
    _team_won,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_situational_record(**overrides) -> SituationalRecord:
    defaults = dict(
        id="sr-001",
        game_id="g1",
        role="seer",
        seat=1,
        day=3,
        phase="night",
        alive_players=[1, 2, 3],
        key_events=[{"event": "checked wolf"}],
        outcome="win",
        created_at="2026-01-01T00:00:00+08:00",
    )
    defaults.update(overrides)
    return SituationalRecord(**defaults)


def _make_decision_outcome(**overrides) -> DecisionOutcome:
    defaults = dict(
        decision_id="d1",
        game_id="g1",
        player_seat=1,
        role="seer",
        action_type="seer_check",
        day=1,
        phase="night",
        quality="good",
        reason="found wolf",
        created_at="2026-01-01T00:00:00+08:00",
    )
    defaults.update(overrides)
    return DecisionOutcome(**defaults)


def _make_mock_memory(
    alive_players=None,
    day=None,
    phase=None,
    pinned_facts=None,
    events=None,
):
    """Build a mock AgentMemory with field_notes / events / pinned_facts."""
    mem = MagicMock()
    game_state = {}
    if alive_players is not None:
        game_state["alive_players"] = alive_players
    if day is not None:
        game_state["day"] = day
    if phase is not None:
        game_state["phase"] = phase

    mem.field_notes = SimpleNamespace(game_state=game_state)
    mem.pinned_facts = pinned_facts or []
    mem.events = events or []
    return mem


# ---------------------------------------------------------------------------
# SituationalRecord.to_dict() round-trip
# ---------------------------------------------------------------------------


def test_situational_record_to_dict_round_trip():
    record = _make_situational_record()
    d = record.to_dict()

    assert d["id"] == "sr-001"
    assert d["game_id"] == "g1"
    assert d["role"] == "seer"
    assert d["seat"] == 1
    assert d["day"] == 3
    assert d["phase"] == "night"
    assert d["alive_players"] == [1, 2, 3]
    assert d["key_events"] == [{"event": "checked wolf"}]
    assert d["outcome"] == "win"
    assert d["created_at"] == "2026-01-01T00:00:00+08:00"

    # All expected keys present, no extras
    expected_keys = {
        "id", "game_id", "role", "seat", "day", "phase",
        "alive_players", "key_events", "outcome", "created_at",
    }
    assert set(d.keys()) == expected_keys


def test_situational_record_to_dict_with_none_fields():
    record = _make_situational_record(day=None, phase=None)
    d = record.to_dict()
    assert d["day"] is None
    assert d["phase"] is None


# ---------------------------------------------------------------------------
# DecisionOutcome.to_dict() round-trip
# ---------------------------------------------------------------------------


def test_decision_outcome_to_dict_round_trip():
    outcome = _make_decision_outcome()
    d = outcome.to_dict()

    assert d["decision_id"] == "d1"
    assert d["game_id"] == "g1"
    assert d["player_seat"] == 1
    assert d["role"] == "seer"
    assert d["action_type"] == "seer_check"
    assert d["day"] == 1
    assert d["phase"] == "night"
    assert d["quality"] == "good"
    assert d["reason"] == "found wolf"
    assert d["created_at"] == "2026-01-01T00:00:00+08:00"

    expected_keys = {
        "decision_id", "game_id", "player_seat", "role",
        "action_type", "day", "phase", "quality", "reason", "created_at",
    }
    assert set(d.keys()) == expected_keys


def test_decision_outcome_to_dict_quality_values():
    for quality in ("good", "bad", "neutral", "uncertain"):
        outcome = _make_decision_outcome(quality=quality)
        assert outcome.to_dict()["quality"] == quality


# ---------------------------------------------------------------------------
# _extract_situational_record with mock AgentMemory
# ---------------------------------------------------------------------------


def test_extract_situational_record_basic():
    writer = EpisodicMemoryWriter()
    mem = _make_mock_memory(
        alive_players=[1, 3, 5],
        day=4,
        phase="day",
        pinned_facts=[
            {"event": "P2 is wolf", "_stable_key": "k1"},
            {"event": "P5 is seer"},
        ],
    )

    record = writer._extract_situational_record(
        game_id="g1",
        player_id=1,
        memory=mem,
        role="seer",
        outcome="win",
    )

    assert record.game_id == "g1"
    assert record.role == "seer"
    assert record.seat == 1
    assert record.day == 4
    assert record.phase == "day"
    assert record.alive_players == [1, 3, 5]
    assert record.outcome == "win"
    # _stable_key should be stripped
    assert len(record.key_events) == 2
    assert "_stable_key" not in record.key_events[0]
    assert record.key_events[0] == {"event": "P2 is wolf"}
    assert record.key_events[1] == {"event": "P5 is seer"}


def test_extract_situational_record_fallback_day_from_events():
    """When field_notes.game_state has no day, fall back to last event."""
    writer = EpisodicMemoryWriter()
    mem = MagicMock()
    mem.field_notes = SimpleNamespace(game_state={})
    mem.pinned_facts = []
    last_event = SimpleNamespace(day=5, phase="night")
    mem.events = [last_event]

    record = writer._extract_situational_record(
        game_id="g2", player_id=2, memory=mem, role="witch", outcome="loss",
    )

    assert record.day == 5
    assert record.phase == "night"


def test_extract_situational_record_no_field_notes():
    """Gracefully handle memory with no field_notes attribute."""
    writer = EpisodicMemoryWriter()
    mem = MagicMock(spec=[])  # no attributes at all
    mem.field_notes = None
    mem.pinned_facts = []
    mem.events = []

    record = writer._extract_situational_record(
        game_id="g3", player_id=3, memory=mem, role="villager", outcome="loss",
    )

    assert record.day is None
    assert record.phase is None
    assert record.alive_players == []
    assert record.key_events == []


# ---------------------------------------------------------------------------
# label_decision — role / action / outcome combos
# ---------------------------------------------------------------------------


def test_label_seer_checking_wolf_is_good():
    writer = EpisodicMemoryWriter()
    decision = {
        "decision_id": "d1",
        "player_id": 1,
        "action_type": "seer_check",
        "day": 1,
        "phase": "night",
        "selected_target": 2,
    }
    player_roles = {1: "seer", 2: "werewolf", 3: "villager"}

    result = writer.label_decision(
        decision,
        player_role="seer",
        winner="villagers",
        game_events=[],
        player_roles=player_roles,
    )

    assert result.quality == "good"
    assert "查验到狼人" in result.reason


def test_label_witch_saving_seer_is_good():
    writer = EpisodicMemoryWriter()
    decision = {
        "decision_id": "d2",
        "player_id": 3,
        "action_type": "witch_act",
        "day": 1,
        "phase": "night",
        "selected_target": 1,
        "selected_choice": "save",
    }
    player_roles = {1: "seer", 2: "werewolf", 3: "witch"}

    result = writer.label_decision(
        decision,
        player_role="witch",
        winner="villagers",
        game_events=[],
        player_roles=player_roles,
    )

    assert result.quality == "good"
    assert "救了神职" in result.reason


def test_label_witch_poisoning_teammate_is_bad():
    writer = EpisodicMemoryWriter()
    decision = {
        "decision_id": "d3",
        "player_id": 3,
        "action_type": "witch_act",
        "day": 2,
        "phase": "night",
        "selected_target": 1,
        "selected_choice": "poison",
    }
    player_roles = {1: "seer", 2: "werewolf", 3: "witch"}

    result = writer.label_decision(
        decision,
        player_role="witch",
        winner="werewolves",
        game_events=[],
        player_roles=player_roles,
    )

    assert result.quality == "bad"
    assert "毒杀了队友" in result.reason


def test_label_werewolf_killing_seer_is_good_for_wolves():
    writer = EpisodicMemoryWriter()
    decision = {
        "decision_id": "d4",
        "player_id": 2,
        "action_type": "werewolf_kill",
        "day": 1,
        "phase": "night",
        "selected_target": 1,
    }
    player_roles = {1: "seer", 2: "werewolf", 3: "villager"}

    result = writer.label_decision(
        decision,
        player_role="werewolf",
        winner="werewolves",
        game_events=[],
        player_roles=player_roles,
    )

    assert result.quality == "good"
    assert "击杀了神职" in result.reason


def test_label_villager_voting_out_wolf_is_good():
    writer = EpisodicMemoryWriter()
    decision = {
        "decision_id": "d5",
        "player_id": 3,
        "action_type": "exile_vote",
        "day": 2,
        "phase": "day",
        "selected_target": 2,
    }
    player_roles = {1: "seer", 2: "werewolf", 3: "villager"}

    result = writer.label_decision(
        decision,
        player_role="villager",
        winner="villagers",
        game_events=[],
        player_roles=player_roles,
    )

    assert result.quality == "good"
    assert "投票放逐了狼人" in result.reason


def test_label_villager_voting_out_teammate_is_bad():
    writer = EpisodicMemoryWriter()
    decision = {
        "decision_id": "d6",
        "player_id": 3,
        "action_type": "exile_vote",
        "day": 2,
        "phase": "day",
        "selected_target": 1,
    }
    player_roles = {1: "seer", 2: "werewolf", 3: "villager"}

    result = writer.label_decision(
        decision,
        player_role="villager",
        winner="werewolves",
        game_events=[],
        player_roles=player_roles,
    )

    assert result.quality == "bad"
    assert "投票放逐了队友" in result.reason


def test_label_hunter_shooting_wolf_is_good():
    writer = EpisodicMemoryWriter()
    decision = {
        "decision_id": "d7",
        "player_id": 4,
        "action_type": "hunter_shoot",
        "day": 3,
        "phase": "day",
        "selected_target": 2,
    }
    player_roles = {1: "villager", 2: "werewolf", 4: "hunter"}

    result = writer.label_decision(
        decision,
        player_role="hunter",
        winner="villagers",
        game_events=[],
        player_roles=player_roles,
    )

    assert result.quality == "good"
    assert "猎人带走了狼人" in result.reason


def test_label_speech_action_is_uncertain():
    writer = EpisodicMemoryWriter()
    decision = {
        "decision_id": "d8",
        "player_id": 1,
        "action_type": "speak",
        "day": 1,
        "phase": "day",
    }
    player_roles = {1: "villager"}

    result = writer.label_decision(
        decision,
        player_role="villager",
        winner="villagers",
        game_events=[],
        player_roles=player_roles,
    )

    # Speech actions fall back to uncertain/generic
    assert result.quality in ("neutral", "uncertain")


# ---------------------------------------------------------------------------
# persist_game with mock data
# ---------------------------------------------------------------------------


def test_persist_game_returns_records_and_outcomes():
    writer = EpisodicMemoryWriter()

    mem1 = _make_mock_memory(alive_players=[1, 2], day=3, phase="day")
    mem2 = _make_mock_memory(alive_players=[1, 2], day=3, phase="day")

    decisions = [
        {
            "decision_id": "d1",
            "player_id": 1,
            "action_type": "seer_check",
            "day": 1,
            "phase": "night",
            "selected_target": 2,
            "role": "seer",
        },
    ]

    srs, dos = writer.persist_game(
        "game-100",
        player_memories={1: mem1, 2: mem2},
        player_roles={1: "seer", 2: "werewolf"},
        winner="villagers",
        decisions=decisions,
        game_events=[],
    )

    # Two situational records (one per player)
    assert len(srs) == 2
    assert srs[0].role == "seer"
    assert srs[0].outcome == "win"
    assert srs[1].role == "werewolf"
    assert srs[1].outcome == "loss"

    # One decision outcome
    assert len(dos) == 1
    assert dos[0].quality == "good"
    assert dos[0].action_type == "seer_check"


def test_persist_game_skips_decisions_without_player_id():
    writer = EpisodicMemoryWriter()
    mem = _make_mock_memory(day=1, phase="day")

    decisions = [
        {"action_type": "speak", "day": 1, "phase": "day"},  # no player_id
    ]

    srs, dos = writer.persist_game(
        "g2",
        player_memories={1: mem},
        player_roles={1: "villager"},
        winner="villagers",
        decisions=decisions,
        game_events=[],
    )

    assert len(srs) == 1
    assert len(dos) == 0


# ---------------------------------------------------------------------------
# Team helpers
# ---------------------------------------------------------------------------


def test_team_for_role():
    assert _team_for_role("werewolf") == "werewolves"
    assert _team_for_role("white_wolf_king") == "werewolves"
    assert _team_for_role("seer") == "gods"
    assert _team_for_role("witch") == "gods"
    assert _team_for_role("villager") == "villagers"
    assert _team_for_role("unknown") == "villagers"  # fallback


def test_team_won():
    assert _team_won("werewolves", "werewolves") is True
    assert _team_won("werewolves", "villagers") is False
    assert _team_won("villagers", "villagers") is True
    assert _team_won("gods", "villagers") is True
    assert _team_won("gods", "werewolves") is False
