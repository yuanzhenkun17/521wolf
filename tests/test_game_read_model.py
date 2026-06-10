from __future__ import annotations

import json
from typing import Any

from storage.game_read_payloads import player_row as read_model_player_row
from storage.game_read_model import GameReadRepository


class _Cursor:
    rowcount = 0

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = list(rows or [])
        self.rowcount = len(self._rows)

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


def test_load_game_detail_uses_single_bundle_query_when_supported() -> None:
    conn = _BundleConnection()
    detail = GameReadRepository(conn).load_game_detail("game-1")

    assert detail is not None
    assert len(conn.queries) == 1
    assert "jsonb_agg(to_jsonb(e) ORDER BY e.idx, e.id)" in conn.queries[0]
    assert "jsonb_agg(to_jsonb(d) ORDER BY d.created_at, d.id)" in conn.queries[0]
    assert detail["game_id"] == "game-1"
    assert detail["status"] == "completed"
    assert detail["logs"] == detail["events"]
    assert detail["events"][0]["message"] == "game started"
    assert detail["events"][0]["created_at"] == "2026-06-09T10:00:01+08:00"
    assert detail["players"][0]["role"] == "seer"
    assert detail["player_roles"] == {1: "seer"}
    assert detail["decisions"][0]["id"] == "decision-1"
    assert detail["decisions"][0]["actor_id"] == 1
    assert detail["decisions"][0]["selected_skills"] == ["seer/check.md"]
    assert detail["review"] == {"review_status": "ok"}
    assert detail["manifest"] == {
        "schema_version": 1,
        "run_type": "game",
        "game_id": "game-1",
        "status": "completed",
    }


def test_load_game_detail_fallback_does_not_probe_decision_schema() -> None:
    conn = _LegacyOnlyConnection()
    detail = GameReadRepository(conn).load_game_detail("game-1")

    assert detail is not None
    assert conn.table_columns_calls == 0
    assert [query for query in conn.queries if "FROM information_schema.columns" in query] == []
    assert any(
        query == "SELECT * FROM decisions WHERE game_id = ? ORDER BY created_at, id"
        for query in conn.queries
    )
    assert detail["decisions"][0]["id"] == "decision-1"
    assert detail["events"][0]["message"] == "game started"


def test_load_game_history_shell_excludes_heavy_fields_and_includes_index() -> None:
    shell = GameReadRepository(_HistoryLayerConnection()).load_game_history_shell("game-1")

    assert shell is not None
    assert shell["detail_view"] == "history-shell"
    assert "logs" not in shell
    assert "events" not in shell
    assert "decisions" not in shell
    assert "review" not in shell
    assert shell["players"] == [read_model_player_row(_player_row())]
    assert shell["event_count"] == 4
    assert shell["decision_count"] == 4
    assert {phase["key"] for phase in shell["phases"]} >= {
        "day-1-setup",
        "day-1-night",
        "day-1-speech",
        "day-2-night",
    }
    assert shell["default_phase_key"] == "day-1-setup"
    assert shell["capabilities"] == {
        "phase_detail": True,
        "replay": True,
        "flow_data": True,
        "archive": True,
        "review": True,
    }


def test_load_game_phase_detail_filters_by_day_phase_and_paginates_rows() -> None:
    detail = GameReadRepository(_HistoryLayerConnection()).load_game_phase_detail(
        "game-1",
        day=1,
        phase="speech",
        log_limit=1,
        decision_limit=1,
    )

    assert detail is not None
    assert detail["detail_view"] == "phase-detail"
    assert detail["phase_key"] == "day-1-speech"
    assert [log["idx"] for log in detail["logs"]] == [2]
    assert [decision["id"] for decision in detail["decisions"]] == ["decision-speech-1"]
    assert all(log["day"] == 1 and log["phase"] == "day_speech" for log in detail["logs"])
    assert all(decision["day"] == 1 and decision["phase"] == "day_speech" for decision in detail["decisions"])
    assert detail["summary"]["log_count"] == 2
    assert detail["summary"]["decision_count"] == 2
    assert detail["pagination"]["logs"] == {
        "total": 2,
        "offset": 0,
        "limit": 1,
        "returned": 1,
        "has_more": True,
    }
    assert detail["pagination"]["decisions"] == {
        "total": 2,
        "offset": 0,
        "limit": 1,
        "returned": 1,
        "has_more": True,
    }


def test_load_game_flow_data_trims_heavy_decision_fields_and_excludes_logs() -> None:
    flow_data = GameReadRepository(_HistoryLayerConnection()).load_game_flow_data("game-1")

    assert flow_data is not None
    assert flow_data["detail_view"] == "flow-data"
    assert "logs" not in flow_data
    assert "events" not in flow_data
    assert flow_data["decision_count"] == 4
    assert flow_data["players"] == [read_model_player_row(_player_row())]
    for decision in flow_data["decisions"]:
        assert "raw_output" not in decision
        assert "prompt_messages" not in decision
        assert "memory_context" not in decision
        assert "parsed_decision" not in decision
        assert "final_response" not in decision
    assert flow_data["decisions"][0] == {
        "id": "decision-night-1",
        "decision_id": "decision-night-1",
        "game_id": "game-1",
        "actor_id": 1,
        "player_id": 1,
        "target_id": 2,
        "selected_target": 2,
        "selected_choice": None,
        "day": 1,
        "phase": "night",
        "action": "seer_check",
        "action_type": "seer_check",
        "role": "seer",
        "public_summary": "night check",
        "public_text": "night check",
        "private_reasoning": "reason decision-night-1",
        "confidence": 0.7,
        "candidates": [2, 3],
        "source": "llm",
        "policy_adjustments": [],
        "errors": [],
        "created_at": "2026-06-09T02:00:02+00:00",
    }


def test_load_game_replay_chunks_events_and_scopes_decisions_to_event_window() -> None:
    repo = GameReadRepository(_HistoryLayerConnection())

    first_page = repo.load_game_replay("game-1", limit=2)
    assert first_page is not None
    assert first_page["detail_view"] == "replay"
    assert first_page["cursor"] == 0
    assert first_page["limit"] == 2
    assert first_page["next_cursor"] == 2
    assert first_page["has_more"] is True
    assert first_page["event_count"] == 4
    assert [event["idx"] for event in first_page["events"]] == [1, 2]
    assert [decision["id"] for decision in first_page["decisions"]] == [
        "decision-night-1",
        "decision-speech-1",
        "decision-speech-2",
    ]
    assert {
        (decision["day"], decision["phase"])
        for decision in first_page["decisions"]
    } == {(1, "night"), (1, "day_speech")}

    second_page = repo.load_game_replay("game-1", cursor=2, limit=2)
    assert second_page is not None
    assert second_page["cursor"] == 2
    assert second_page["limit"] == 2
    assert second_page["next_cursor"] == 4
    assert second_page["has_more"] is False
    assert [event["idx"] for event in second_page["events"]] == [3, 4]
    assert [decision["id"] for decision in second_page["decisions"]] == [
        "decision-speech-1",
        "decision-speech-2",
        "decision-night-2",
    ]
    assert {
        (decision["day"], decision["phase"])
        for decision in second_page["decisions"]
    } == {(1, "day_speech"), (2, "night")}

    single_phase_page = repo.load_game_replay("game-1", cursor=3, limit=1)
    assert single_phase_page is not None
    assert [event["idx"] for event in single_phase_page["events"]] == [4]
    assert [decision["id"] for decision in single_phase_page["decisions"]] == ["decision-night-2"]
    assert {
        (decision["day"], decision["phase"])
        for decision in single_phase_page["decisions"]
    } == {(2, "night")}

    default_page = repo.load_game_replay("game-1")
    assert default_page is not None
    assert default_page["limit"] == 500
    assert default_page["has_more"] is False
    assert len(default_page["events"]) == 4


def test_lab_history_detail_shell_and_replay_include_evidence_source_context() -> None:
    cases = [
        ("evaluation_batch", "benchmark", "bench_run_1", "battle", {"seer": "seer_canary"}),
        ("evolution_training", "evolution", "evolve_run_1", "training", {"wolf": "wolf_candidate"}),
    ]

    for run_type, source, run_id, source_phase, role_versions in cases:
        conn = _HistoryLayerConnection()
        game = _game_row()
        game.update(
            {
                "id": f"{source}-game-1",
                "seed": 9001,
                "run_type": run_type,
                "source_run_id": run_id,
                "config": {
                    "log_name": f"{source}-game-1",
                    "player_count": 1,
                    "role_versions": role_versions,
                },
                "final_state": {
                    **game["final_state"],
                    "source_phase": source_phase,
                },
            }
        )
        conn.games = [game]
        repo = GameReadRepository(conn)

        payloads = [
            repo.load_game_detail(game["id"]),
            repo.load_game_history_shell(game["id"]),
            repo.load_game_replay(game["id"], limit=1),
        ]

        for payload in payloads:
            assert payload is not None
            assert payload["log_source"] == source
            assert payload["source_run_id"] == run_id
            assert payload["source_phase"] == source_phase
            assert payload["seed"] == 9001
            assert payload["role_versions"] == role_versions
            assert payload["evidence_source"] == {
                "log_source": source,
                "log_source_label": "评测" if source == "benchmark" else "进化",
                "source_run_id": run_id,
                "source_phase": source_phase,
                "source_phase_label": "对战" if source_phase == "battle" else "训练",
                "seed": 9001,
                "role_versions": role_versions,
            }


class _BundleConnection:
    supports_game_detail_bundle = True

    def __init__(self) -> None:
        self.queries: list[str] = []

    def execute(self, sql: str, parameters: Any = ()) -> _Cursor:
        del parameters
        text = " ".join(sql.split())
        self.queries.append(text)
        if "LEFT JOIN LATERAL" not in text:
            raise AssertionError(f"unexpected SQL: {text}")
        game = _game_row()
        return _Cursor([
            {
                **game,
                "__event_rows": json.dumps([_event_row()], ensure_ascii=False),
                "__decision_rows": json.dumps([_decision_row()], ensure_ascii=False),
                "__player_rows": json.dumps([_player_row()], ensure_ascii=False),
            }
        ])

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None

    def __enter__(self) -> "_BundleConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


class _LegacyOnlyConnection:
    def __init__(self) -> None:
        self.queries: list[str] = []
        self.table_columns_calls = 0

    def execute(self, sql: str, parameters: Any = ()) -> _Cursor:
        del parameters
        text = " ".join(sql.split())
        self.queries.append(text)
        if "LEFT JOIN LATERAL" in text:
            raise RuntimeError("bundle query unavailable")
        if text == "SELECT * FROM games WHERE id = ?":
            return _Cursor([_game_row()])
        if text == "SELECT * FROM game_events WHERE game_id = ? ORDER BY idx, id":
            return _Cursor([_event_row()])
        if text == "SELECT * FROM decisions WHERE game_id = ? ORDER BY created_at, id":
            return _Cursor([_decision_row()])
        if text == "SELECT * FROM players WHERE game_id = ? ORDER BY seat":
            return _Cursor([_player_row()])
        raise AssertionError(f"unexpected SQL: {text}")

    def table_columns(self, table_name: str) -> list[str]:
        self.table_columns_calls += 1
        raise AssertionError(f"schema probe should not run for {table_name}")

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None

    def __enter__(self) -> "_LegacyOnlyConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


class _HistoryLayerConnection:
    def __init__(self) -> None:
        self.queries: list[tuple[str, Any]] = []
        self.games = [_game_row()]
        self.players = [_player_row()]
        self.events = [
            _event_row(id=1, idx=1, day=1, phase="night", event_type="night_start", message="night one"),
            _event_row(id=2, idx=2, day=1, phase="day_speech", event_type="speech", message="speech one"),
            _event_row(id=3, idx=3, day=1, phase="day_speech", event_type="speech", message="speech two"),
            _event_row(id=4, idx=4, day=2, phase="night", event_type="night_start", message="night two"),
        ]
        self.decisions = [
            _decision_row(id="decision-night-1", day=1, phase="night", action_type="seer_check", public_text="night check"),
            _decision_row(id="decision-speech-1", day=1, phase="day_speech", action_type="speak", public_text="speech one"),
            _decision_row(id="decision-speech-2", day=1, phase="day_speech", action_type="speak", public_text="speech two"),
            _decision_row(id="decision-night-2", day=2, phase="night", action_type="werewolf_kill", public_text="night two"),
        ]

    def execute(self, sql: str, parameters: Any = ()) -> _Cursor:
        text = " ".join(sql.split())
        self.queries.append((text, parameters))
        if text == "SELECT * FROM games WHERE id = ?":
            return _Cursor(self.games)
        if text == "SELECT * FROM players WHERE game_id = ? ORDER BY seat":
            return _Cursor(self.players)
        if text == "SELECT * FROM game_events WHERE game_id = ? ORDER BY idx, id":
            return _Cursor(self.events)
        if text == "SELECT * FROM decisions WHERE game_id = ? ORDER BY created_at, id":
            return _Cursor(self.decisions)
        if text.startswith("SELECT day, phase, event_type, COUNT(*) AS log_count"):
            return _Cursor(self._event_phase_rows())
        if text.startswith("SELECT day, phase, action_type, COUNT(*) AS decision_count"):
            return _Cursor(self._decision_phase_rows())
        if text.startswith("SELECT id, game_id, idx, day, phase, event_type, public, actor, target, payload, created_at"):
            return _Cursor([])
        if text == "SELECT * FROM game_events WHERE game_id = ? AND day = ? AND phase IN (?, ?, ?) ORDER BY idx, id":
            return _Cursor(self._events_for_day_phase(parameters[1], parameters[2:]))
        if text == "SELECT * FROM decisions WHERE game_id = ? AND day = ? AND phase IN (?, ?, ?) ORDER BY created_at, id":
            return _Cursor(self._decisions_for_day_phase(parameters[1], parameters[2:]))
        if text.startswith("SELECT id, game_id, player_id, seat, role, day, phase, action_type,"):
            return _Cursor(self.decisions)
        if text == "SELECT COUNT(*) AS total FROM game_events WHERE game_id = ?":
            return _Cursor([{"total": len(self.events)}])
        if text == "SELECT * FROM game_events WHERE game_id = ? ORDER BY idx, id LIMIT ? OFFSET ?":
            limit = int(parameters[1])
            offset = int(parameters[2])
            return _Cursor(self.events[offset:offset + limit])
        if text.startswith("SELECT * FROM decisions WHERE game_id = ? AND ("):
            return _Cursor(self._decisions_for_replay_filters(parameters[1:]))
        raise AssertionError(f"unexpected SQL: {text}")

    def _event_phase_rows(self) -> list[dict[str, Any]]:
        grouped: dict[tuple[int, str, str], dict[str, Any]] = {}
        for row in self.events:
            key = (int(row["day"]), str(row["phase"]), str(row["event_type"]))
            item = grouped.setdefault(
                key,
                {
                    "day": row["day"],
                    "phase": row["phase"],
                    "event_type": row["event_type"],
                    "log_count": 0,
                    "first_event_index": row["idx"],
                    "last_event_index": row["idx"],
                },
            )
            item["log_count"] += 1
            item["first_event_index"] = min(item["first_event_index"], row["idx"])
            item["last_event_index"] = max(item["last_event_index"], row["idx"])
        return sorted(grouped.values(), key=lambda item: (item["day"], item["phase"], item["event_type"]))

    def _decision_phase_rows(self) -> list[dict[str, Any]]:
        grouped: dict[tuple[int, str, str], dict[str, Any]] = {}
        for row in self.decisions:
            key = (int(row["day"]), str(row["phase"]), str(row["action_type"]))
            item = grouped.setdefault(
                key,
                {
                    "day": row["day"],
                    "phase": row["phase"],
                    "action_type": row["action_type"],
                    "decision_count": 0,
                },
            )
            item["decision_count"] += 1
        return sorted(grouped.values(), key=lambda item: (item["day"], item["phase"], item["action_type"]))

    def _events_for_day_phase(self, day: Any, phases: Any) -> list[dict[str, Any]]:
        phase_set = set(phases)
        return [row for row in self.events if row["day"] == day and row["phase"] in phase_set]

    def _decisions_for_day_phase(self, day: Any, phases: Any) -> list[dict[str, Any]]:
        phase_set = set(phases)
        return [row for row in self.decisions if row["day"] == day and row["phase"] in phase_set]

    def _decisions_for_replay_filters(self, parameters: Any) -> list[dict[str, Any]]:
        allowed: set[tuple[int, str]] = set()
        index = 0
        params = list(parameters)
        while index < len(params):
            day = int(params[index])
            index += 1
            while index < len(params) and not isinstance(params[index], int):
                allowed.add((day, str(params[index])))
                index += 1
        return [
            row for row in self.decisions
            if (int(row["day"]), str(row["phase"])) in allowed
        ]

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        return None

    def __enter__(self) -> "_HistoryLayerConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


def _game_row() -> dict[str, Any]:
    return {
        "id": "game-1",
        "seed": 42,
        "config": {"log_name": "game-1", "player_count": 1},
        "winner": "villagers",
        "started_at": "2026-06-09T10:00:00+08:00",
        "finished_at": "2026-06-09T10:30:00+08:00",
        "total_rounds": 1,
        "public_events": [],
        "final_state": {
            "status": "completed",
            "review": {"review_status": "ok"},
            "manifest": {
                "schema_version": 1,
                "run_type": "game",
                "game_id": "game-1",
                "status": "completed",
            },
        },
        "run_type": "ordinary_game",
        "mode": "watch",
    }


def _event_row(
    *,
    id: int = 1,
    idx: int = 1,
    day: int = 1,
    phase: str = "night",
    event_type: str = "game_init",
    message: str = "game started",
) -> dict[str, Any]:
    return {
        "id": id,
        "game_id": "game-1",
        "idx": idx,
        "day": day,
        "phase": phase,
        "event_type": event_type,
        "message": message,
        "public": True,
        "actor": None,
        "target": None,
        "payload": {"visible": True},
        "created_at": f"2026-06-09T02:00:{idx:02d}+00:00",
    }


def _decision_row(
    *,
    id: str = "decision-1",
    day: int = 1,
    phase: str = "night",
    action_type: str = "seer_check",
    public_text: str = "checked 2",
) -> dict[str, Any]:
    return {
        "id": id,
        "game_id": "game-1",
        "player_id": 1,
        "seat": 1,
        "role": "seer",
        "day": day,
        "phase": phase,
        "action_type": action_type,
        "candidates": "[2, 3]",
        "observation_summary": "{}",
        "memory_context": '{"memory": "large"}',
        "selected_skills": '["seer/check.md"]',
        "prompt_messages": '[{"role": "user", "content": "large"}]',
        "raw_output": '{"raw": "large"}',
        "parsed_decision": '{"public_text": "parsed text"}',
        "final_response": '{"text": "final text"}',
        "selected_target": 2,
        "selected_choice": None,
        "public_text": public_text,
        "private_reasoning": f"reason {id}",
        "confidence": 0.7,
        "alternatives": "[]",
        "rejected_reasons": "[]",
        "source": "llm",
        "policy_adjustments": "[]",
        "errors": "[]",
        "created_at": "2026-06-09T02:00:02+00:00",
    }


def _player_row() -> dict[str, Any]:
    return {
        "id": 1,
        "game_id": "game-1",
        "seat": 1,
        "role": "seer",
        "team": "villagers",
        "alive": True,
        "killed_day": None,
        "killed_cause": None,
        "role_version_id": "seer_v1",
        "skill_package_hash": "hash",
    }
