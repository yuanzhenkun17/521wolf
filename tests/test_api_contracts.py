"""Stable API shape contracts for the UI backend.

These tests intentionally check small response shapes instead of large snapshots.
They should fail when frontend-facing field names or basic types drift.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import PathConfig
import ui.backend.app as ui_backend_app


class FakeModel:
    async def ainvoke(self, messages: Any) -> Any:
        return type(
            "Result",
            (),
            {
                "content": (
                    '{"choice":null,"target":null,"public_text":"ok",'
                    '"private_reasoning":"api contract fake model",'
                    '"confidence":1,"alternatives":[],"rejected_reasons":[],"selected_skills":[]}'
                )
            },
        )()


def _client(tmp_path: Path) -> TestClient:
    app = ui_backend_app.create_app(paths=PathConfig(root=tmp_path), model=FakeModel())
    return TestClient(app)


def _assert_shape(payload: dict[str, Any], shape: dict[str, type | tuple[type, ...]]) -> None:
    missing = [key for key in shape if key not in payload]
    assert missing == []
    for key, expected in shape.items():
        assert isinstance(payload[key], expected), f"{key} expected {expected}, got {type(payload[key])}"


def _assert_pagination(payload: dict[str, Any]) -> None:
    _assert_shape(
        payload["pagination"],
        {
            "total": int,
            "offset": int,
            "limit": (int, type(None)),
            "returned": int,
            "has_more": bool,
        },
    )


def _assert_task_progress(progress: dict[str, Any]) -> None:
    _assert_shape(
        progress,
        {
            "stage": str,
            "percent": (int, float),
            "updated_at": str,
        },
    )


def _assert_error_detail(response: Any, status_code: int, detail: str) -> None:
    assert response.status_code == status_code
    payload = response.json()
    _assert_shape(payload, {"detail": str, "error": dict})
    assert payload["detail"] == detail
    _assert_shape(payload["error"], {"code": str, "message": str, "diagnostics": list})
    assert payload["error"]["message"] == detail


def _assert_validation_error(response: Any, loc: list[str], error_type: str) -> None:
    assert response.status_code == 422
    payload = response.json()
    _assert_shape(payload, {"detail": list, "error": dict})
    assert payload["detail"]
    _assert_shape(payload["error"], {"code": str, "message": str, "diagnostics": list})
    assert payload["error"]["code"] == "validation_error"
    assert payload["error"]["diagnostics"] == payload["detail"]
    error = payload["detail"][0]
    _assert_shape(error, {"type": str, "loc": list, "msg": str})
    assert error["type"] == error_type
    assert error["loc"] == loc


def _operation(doc: dict[str, Any], path: str, method: str) -> dict[str, Any]:
    return doc["paths"][path][method]


def _request_ref(operation: dict[str, Any]) -> str | None:
    request_body = operation.get("requestBody")
    if not request_body:
        return None
    return request_body["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]


def _parameters(operation: dict[str, Any]) -> list[tuple[str, str, bool]]:
    return [
        (parameter["name"], parameter["in"], parameter["required"])
        for parameter in operation.get("parameters", [])
    ]


def _schema_properties(doc: dict[str, Any], schema_name: str) -> dict[str, Any]:
    return doc["components"]["schemas"][schema_name]["properties"]


def _sse_frames(text: str) -> list[dict[str, Any]]:
    frames: list[dict[str, Any]] = []
    for chunk in text.strip().split("\n\n"):
        if not chunk.strip():
            continue
        frame: dict[str, Any] = {}
        for line in chunk.splitlines():
            if line.startswith("id: "):
                frame["id"] = int(line.removeprefix("id: "))
            elif line.startswith("event: "):
                frame["event"] = line.removeprefix("event: ")
            elif line.startswith("data: "):
                frame["data"] = json.loads(line.removeprefix("data: "))
        frames.append(frame)
    return frames


def _valid_seer_skill() -> str:
    return (
        "---\n"
        "name: contract seer check\n"
        "role: seer\n"
        "applicable_actions:\n"
        "  - seer_check\n"
        "status: active\n"
        "evolution:\n"
        "  enabled: true\n"
        "  allowed_actions:\n"
        "    - append_rule\n"
        "---\n"
        "Prefer checking players whose claims affect the vote split.\n"
    )


def _seed_game(store: ui_backend_app.BackendStore) -> str:
    game_id = "ui_contract_game"
    store.games[game_id] = {
        "game_id": game_id,
        "log_name": game_id,
        "status": "completed",
        "stop_requested": False,
        "cancelled": False,
        "interrupted": False,
        "failed": False,
        "mode": "watch",
        "seed": 11,
        "started_at": "2026-01-01T00:00:00+08:00",
        "finished_at": "2026-01-01T00:00:10+08:00",
        "log_time": "2026-01-01T00:00:10+08:00",
        "max_days": 2,
        "enable_sheriff": True,
        "player_count": 12,
        "players": [
            {
                "id": 1,
                "seat": 1,
                "name": "1号",
                "role": "seer",
                "team": "good",
                "alive": True,
                "is_sheriff": False,
                "is_human": False,
                "role_state": {},
            }
        ],
        "logs": [{"sequence": 1, "event_type": "game_init", "message": "started"}],
        "events": [{"sequence": 1, "event_type": "game_init", "message": "started"}],
        "decisions": [{"id": "d1", "action_type": "speak", "player_id": 1, "source": "fake"}],
        "review": {"game_id": game_id, "winner": "good", "notes": []},
        "waiting_for": "none",
        "pending_human_action": None,
        "role_skill_dirs": {},
        "config": {"seed": 11, "max_days": 2, "player_count": 12},
        "manifest": {
            "schema_version": 1,
            "run_type": "game",
            "game_id": game_id,
            "status": "completed",
            "paths": {"game_dir": "contract"},
        },
    }
    return game_id


def _seed_in_progress_player_game(store: ui_backend_app.BackendStore) -> str:
    game_id = "ui_contract_player_view"
    logs = [
        {
            "sequence": 1,
            "event_type": "game_init",
            "message": "started",
            "visibility": "public",
            "payload": {"roles": {"1": "villager", "2": "seer", "3": "werewolf"}, "seed": 17},
        },
        {
            "sequence": 2,
            "event_type": "speech",
            "actor_id": 2,
            "message": "2号公开发言",
            "visibility": "public",
        },
        {
            "sequence": 3,
            "event_type": "seer_check",
            "actor_id": 2,
            "target_id": 3,
            "message": "预言家查验",
            "visibility": "public",
            "payload": {"target_id": 3},
        },
        {
            "sequence": 4,
            "event_type": "speech",
            "actor_id": 2,
            "message": "2号私密视角",
            "visibility": "private",
        },
        {
            "sequence": 5,
            "event_type": "speech",
            "actor_id": 1,
            "message": "1号自己的私密视角",
            "visibility": "private",
        },
        {
            "sequence": 6,
            "event_type": "debug_roles",
            "message": "god-only role table",
            "visibility": "god",
        },
        {
            "sequence": 7,
            "event_type": "night_result",
            "message": "夜晚结果",
            "visibility": "public",
            "payload": {
                "killed_target": 2,
                "protected_target": None,
                "saved": False,
                "deaths": [{"id": 2, "role": "seer", "team": "villagers"}],
                "roles": {"2": "seer"},
            },
        },
    ]
    store.games[game_id] = {
        "game_id": game_id,
        "log_name": game_id,
        "status": "running",
        "stop_requested": False,
        "cancelled": False,
        "interrupted": False,
        "failed": False,
        "mode": "play",
        "human_player_id": 1,
        "seed": 17,
        "started_at": "2026-01-01T00:00:00+08:00",
        "max_days": 2,
        "enable_sheriff": True,
        "player_count": 3,
        "players": [
            {
                "id": 1,
                "seat": 1,
                "name": "1号",
                "role": "villager",
                "role_hint": "平民",
                "team": "villagers",
                "alive": True,
                "is_human": True,
                "role_state": {"private_note": "human only"},
            },
            {
                "id": 2,
                "seat": 2,
                "name": "2号",
                "role": "seer",
                "role_hint": "预言家",
                "team": "villagers",
                "alive": True,
                "is_human": False,
                "role_state": {"checks": {"3": "werewolves"}},
            },
            {
                "id": 3,
                "seat": 3,
                "name": "3号",
                "role": "werewolf",
                "role_hint": "狼人",
                "team": "werewolves",
                "alive": True,
                "is_human": False,
                "role_state": {"wolf_chat": ["kill 2"]},
            },
        ],
        "logs": logs,
        "events": list(logs),
        "decisions": [
            {
                "id": "d-hidden",
                "action_type": "seer_check",
                "player_id": 2,
                "actor_id": 2,
                "target_id": 3,
                "role": "seer",
                "private_reasoning": "2号查验了狼人",
                "public_summary": "完成查验",
                "source": "fake",
            },
            {
                "id": "d-public",
                "action_type": "speak",
                "player_id": 2,
                "actor_id": 2,
                "role": "seer",
                "private_reasoning": "2号公开发言前的私密推理",
                "public_summary": "2号发言",
                "source": "fake",
            },
            {
                "id": "d-human",
                "action_type": "speak",
                "player_id": 1,
                "actor_id": 1,
                "role": "villager",
                "private_reasoning": "1号自己的私密推理",
                "public_summary": "1号发言",
                "source": "human",
            },
        ],
        "review": {"game_id": game_id, "agent_scores": {"2": {"role": "seer"}}},
        "waiting_for": "speech",
        "pending_human_action": {
            "action_type": "speak",
            "type": "speak",
            "player_id": 1,
            "candidate_ids": [],
            "candidates": [],
            "metadata": {},
            "observation": {"known_roles": {}, "role_state": {"private_note": "human only"}},
        },
        "pending_action": None,
        "role_skill_dirs": {},
        "config": {"seed": 17, "max_days": 2, "player_count": 3},
    }
    game_dir = store.paths.games_dir / game_id
    game_dir.mkdir(parents=True, exist_ok=True)
    (game_dir / "archive.json").write_text(
        json.dumps(
            {
                "title": "stored archive",
                "review": {"game_id": game_id, "agent_scores": {"2": {"role": "seer"}}},
                "events": [{"event_type": "debug_roles", "payload": {"roles": {"2": "seer"}}}],
            }
        ),
        encoding="utf-8",
    )
    return game_id


def _seed_evolution(store: ui_backend_app.BackendStore) -> tuple[str, str]:
    run_id = "evolve_contract"
    batch_id = "bench_contract"
    training_game_dir = store.paths.evolution_dir / run_id / "training" / "training_001"
    store.evolution_runs[run_id] = {
        "kind": "role_evolution_run",
        "schema_version": 1,
        "run_id": run_id,
        "role": "seer",
        "roles": ["seer"],
        "status": "reviewing",
        "stop_requested": False,
        "cancelled": False,
        "interrupted": False,
        "failed": False,
        "started_at": "2026-01-01T00:01:00+08:00",
        "finished_at": "2026-01-01T00:02:00+08:00",
        "last_heartbeat_at": "2026-01-01T00:02:00+08:00",
        "current_stage": "reviewing",
        "progress": {
            "stage": "reviewing",
            "percent": 1.0,
            "updated_at": "2026-01-01T00:02:00+08:00",
        },
        "diagnostics": [
            {
                "kind": "contract_note",
                "stage": "reviewing",
                "level": "info",
                "message": "contract sample",
            }
        ],
        "manifest": {
            "schema_version": 1,
            "run_type": "evolve",
            "run_id": run_id,
            "status": "reviewing",
        },
        "config": {"roles": ["seer"], "training_games": 1, "battle_games": 0, "max_days": 1},
        "training_games": [
            {
                "game_id": "train_contract_1",
                "status": "completed",
                "seed": 101,
                "winner": "good",
                "phase": "training",
                "game_dir": str(training_game_dir),
                "events": [{"sequence": 1, "event_type": "game_init", "message": "train"}],
                "decisions": [{"decision_id": "d1", "action_type": "seer_check"}],
            }
        ],
        "battle_games": [],
        "proposals": [{"proposal_id": "p1", "target_file": "seer.md"}],
        "diff": [
            {
                "target_file": "seer.md",
                "action": "append_rule",
                "before": "",
                "after": "Prefer decisive checks.",
            }
        ],
        "errors": [],
        "warnings": [],
    }
    store.evolution_batches[batch_id] = {
        "kind": "benchmark_batch",
        "schema_version": 1,
        "batch_id": batch_id,
        "roles": ["seer"],
        "status": "completed",
        "stop_requested": False,
        "cancelled": False,
        "interrupted": False,
        "failed": False,
        "started_at": "2026-01-01T00:03:00+08:00",
        "finished_at": "2026-01-01T00:03:10+08:00",
        "last_heartbeat_at": "2026-01-01T00:03:10+08:00",
        "current_stage": "completed",
        "progress": {
            "stage": "completed",
            "percent": 1.0,
            "completed_roles": 1,
            "role_count": 1,
            "total_roles": 1,
            "updated_at": "2026-01-01T00:03:10+08:00",
        },
        "diagnostics": [],
        "config": {"roles": ["seer"], "battle_games": 0, "max_days": 1},
        "result": {
            "batch_id": batch_id,
            "config": {"roles": ["seer"], "battle_games": 0, "max_days": 1},
            "game_count": 0,
            "completed": 0,
            "errored": 0,
            "rankable": False,
            "rankable_reason": "contract sample",
        },
    }
    return run_id, batch_id


def test_openapi_frontend_snapshot_contract(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.get("/openapi.json")

    assert response.status_code == 200
    doc = response.json()
    assert doc["info"] == {"title": "521wolf UI Backend", "version": "0.1.0"}

    expected_operations = {
        "/api/benchmark": {
            "post": ("start_benchmark_api_benchmark_post", "BenchmarkRequest", []),
        },
        "/api/benchmark/batch": {
            "post": ("start_benchmark_batch_api_benchmark_batch_post", "BenchmarkRequest", []),
        },
        "/api/benchmark/batch/{batch_id}/stop": {
            "post": (
                "stop_benchmark_api_benchmark_batch__batch_id__stop_post",
                None,
                [("batch_id", "path", True)],
            ),
        },
        "/api/benchmark/batch/{batch_id}/events": {
            "get": (
                "benchmark_events_api_benchmark_batch__batch_id__events_get",
                None,
                [("batch_id", "path", True)],
            ),
        },
        "/api/evolution-runs": {
            "get": (
                "list_evolution_runs_api_evolution_runs_get",
                None,
                [
                    ("limit", "query", False),
                    ("offset", "query", False),
                    ("source", "query", False),
                    ("status", "query", False),
                ],
            ),
            "post": ("start_evolution_api_evolution_runs_post", "EvolutionStartRequest", []),
        },
        "/api/evolution-runs/{run_id}": {
            "get": ("get_evolution_run_api_evolution_runs__run_id__get", None, [("run_id", "path", True)]),
        },
        "/api/evolution-runs/{run_id}/actions": {
            "post": (
                "evolution_action_api_evolution_runs__run_id__actions_post",
                "EvolutionActionRequest",
                [("run_id", "path", True)],
            ),
        },
        "/api/evolution-runs/{run_id}/diff": {
            "get": ("evolution_diff_api_evolution_runs__run_id__diff_get", None, [("run_id", "path", True)]),
        },
        "/api/evolution-runs/{run_id}/events": {
            "get": ("evolution_events_api_evolution_runs__run_id__events_get", None, [("run_id", "path", True)]),
        },
        "/api/evolution-runs/{run_id}/games": {
            "get": (
                "evolution_games_api_evolution_runs__run_id__games_get",
                None,
                [
                    ("run_id", "path", True),
                    ("phase", "query", False),
                    ("side", "query", False),
                    ("limit", "query", False),
                    ("offset", "query", False),
                    ("status", "query", False),
                ],
            ),
        },
        "/api/evolution-runs/{run_id}/games/{game_id}/{detail_type}": {
            "get": (
                "evolution_game_detail_api_evolution_runs__run_id__games__game_id___detail_type__get",
                None,
                [
                    ("run_id", "path", True),
                    ("game_id", "path", True),
                    ("detail_type", "path", True),
                    ("phase", "query", False),
                    ("side", "query", False),
                ],
            ),
        },
        "/api/games": {
            "get": (
                "list_games_api_games_get",
                None,
                [
                    ("limit", "query", False),
                    ("offset", "query", False),
                    ("source", "query", False),
                    ("status", "query", False),
                ],
            ),
            "post": ("start_game_api_games_post", "GameStartRequest", []),
        },
        "/api/games/{game_id}": {
            "get": (
                "get_game_api_games__game_id__get",
                None,
                [("game_id", "path", True), ("advance", "query", False)],
            ),
        },
        "/api/games/{game_id}/action": {
            "post": (
                "submit_human_action_api_games__game_id__action_post",
                "HumanActionRequest",
                [("game_id", "path", True)],
            ),
        },
        "/api/games/{game_id}/archive": {
            "get": ("get_game_archive_api_games__game_id__archive_get", None, [("game_id", "path", True)]),
        },
        "/api/games/{game_id}/events": {
            "get": ("game_events_api_games__game_id__events_get", None, [("game_id", "path", True)]),
        },
        "/api/games/{game_id}/human-action": {
            "get": ("get_human_action_api_games__game_id__human_action_get", None, [("game_id", "path", True)]),
        },
        "/api/games/{game_id}/review": {
            "get": ("get_game_review_api_games__game_id__review_get", None, [("game_id", "path", True)]),
        },
        "/api/games/{game_id}/stop": {
            "post": ("stop_game_api_games__game_id__stop_post", None, [("game_id", "path", True)]),
        },
        "/api/health": {
            "get": ("health_api_health_get", None, []),
        },
        "/api/leaderboards": {
            "get": ("leaderboards_api_leaderboards_get", None, []),
        },
        "/api/roles": {
            "get": ("list_roles_api_roles_get", None, []),
        },
        "/api/roles/{role}/leaderboard": {
            "get": ("role_leaderboard_api_roles__role__leaderboard_get", None, [("role", "path", True)]),
        },
        "/api/roles/{role}/rollback/{version_id}": {
            "post": (
                "rollback_api_roles__role__rollback__version_id__post",
                None,
                [("role", "path", True), ("version_id", "path", True)],
            ),
        },
        "/api/roles/{role}/versions": {
            "get": ("list_versions_api_roles__role__versions_get", None, [("role", "path", True)]),
        },
        "/api/roles/{role}/versions/{version_id}": {
            "get": (
                "get_version_api_roles__role__versions__version_id__get",
                None,
                [("role", "path", True), ("version_id", "path", True)],
            ),
        },
        "/api/tts/speech": {
            "post": ("tts_speech_api_tts_speech_post", "TtsSpeechRequest", []),
        },
    }

    assert set(doc["paths"]) == set(expected_operations)
    for path, expected_methods in expected_operations.items():
        assert set(doc["paths"][path]) == set(expected_methods)
        for method, (operation_id, request_schema, parameters) in expected_methods.items():
            operation = _operation(doc, path, method)
            assert operation["operationId"] == operation_id
            assert _request_ref(operation) == request_schema
            assert _parameters(operation) == parameters
            expected_responses = {"200"} if parameters == [] and request_schema is None else {"200", "422"}
            assert set(operation["responses"]) == expected_responses

    assert set(doc["components"]["schemas"]) == {
        "BenchmarkRequest",
        "EvolutionActionRequest",
        "EvolutionStartRequest",
        "GameStartRequest",
        "HTTPValidationError",
        "HumanActionRequest",
        "TtsSpeechRequest",
        "ValidationError",
    }

    game_start = _schema_properties(doc, "GameStartRequest")
    assert game_start["max_days"]["default"] == 20
    assert game_start["max_days"]["minimum"] == 1
    assert game_start["max_days"]["maximum"] == 100
    assert game_start["player_count"]["default"] == 12
    assert game_start["player_count"]["minimum"] == 12
    assert game_start["player_count"]["maximum"] == 12
    assert game_start["enable_sheriff"]["default"] is True
    assert game_start["role_versions"]["additionalProperties"] == {"type": "string"}
    assert game_start["skill_dir"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert game_start["human_player_id"]["anyOf"] == [{"type": "integer"}, {"type": "null"}]

    human_action = _schema_properties(doc, "HumanActionRequest")
    assert human_action["action_type"]["default"] == ""
    assert human_action["target"]["anyOf"] == [{"type": "integer"}, {"type": "null"}]
    assert human_action["choice"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert human_action["text"]["default"] == ""

    evolution_start = _schema_properties(doc, "EvolutionStartRequest")
    assert evolution_start["roles"]["items"] == {"type": "string"}
    assert evolution_start["training_games"]["default"] == 20
    assert evolution_start["training_games"]["minimum"] == 0
    assert evolution_start["training_games"]["maximum"] == 200
    assert evolution_start["battle_games"]["default"] == 10
    assert evolution_start["battle_games"]["minimum"] == 0
    assert evolution_start["battle_games"]["maximum"] == 200
    assert evolution_start["max_days"]["default"] == 5
    assert evolution_start["auto_promote"]["default"] is False

    benchmark = _schema_properties(doc, "BenchmarkRequest")
    assert benchmark["roles"]["items"] == {"type": "string"}
    assert benchmark["battle_games"]["default"] == 10
    assert benchmark["battle_games"]["minimum"] == 0
    assert benchmark["battle_games"]["maximum"] == 200
    assert benchmark["max_days"]["default"] == 5
    assert benchmark["max_days"]["minimum"] == 1
    assert benchmark["max_days"]["maximum"] == 100

    evolution_action = _schema_properties(doc, "EvolutionActionRequest")
    assert evolution_action["action"]["default"] == ""

    tts = _schema_properties(doc, "TtsSpeechRequest")
    assert tts["text"]["default"] == ""
    assert tts["text"]["maxLength"] == 2000
    assert tts["speaker"]["default"] == ""
    assert tts["speaker"]["maxLength"] == 64
    assert tts["seat"]["anyOf"] == [{"maximum": 12, "minimum": 1, "type": "integer"}, {"type": "null"}]


def test_ui_backend_error_response_api_contract(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        game_id = _seed_game(store)

        missing_game_response = client.get("/api/games/missing_contract_game")
        missing_game_events_response = client.get("/api/games/missing_contract_game/events")
        stale_human_action_response = client.post(
            f"/api/games/{game_id}/action",
            json={"action_type": "speak", "text": "not waiting"},
        )
        missing_human_action_response = client.get("/api/games/missing_contract_game/human-action")
        invalid_game_start_response = client.post("/api/games", json={"max_days": 0})

        missing_evolution_response = client.get("/api/evolution-runs/missing_contract_run")
        missing_evolution_action_response = client.post(
            "/api/evolution-runs/missing_contract_run/actions",
            json={"action": "stop"},
        )
        missing_evolution_games_response = client.get("/api/evolution-runs/missing_contract_run/games")
        invalid_evolution_start_response = client.post("/api/evolution-runs", json={"training_games": 201})

        missing_benchmark_stop_response = client.post("/api/benchmark/batch/missing_contract_batch/stop")
        invalid_benchmark_response = client.post("/api/benchmark", json={"max_days": 0})

        missing_role_version_response = client.get("/api/roles/seer/versions/missing_contract_version")
        missing_role_rollback_response = client.post("/api/roles/seer/rollback/missing_contract_version")

    _assert_error_detail(missing_game_response, 404, "game not found")
    _assert_error_detail(missing_game_events_response, 404, "game not found")
    _assert_error_detail(missing_human_action_response, 404, "game not found")
    _assert_error_detail(stale_human_action_response, 409, "game is not waiting for human input")
    _assert_validation_error(invalid_game_start_response, ["body", "max_days"], "greater_than_equal")

    _assert_error_detail(missing_evolution_response, 404, "run not found")
    _assert_error_detail(missing_evolution_action_response, 404, "run not found")
    _assert_error_detail(missing_evolution_games_response, 404, "run not found")
    _assert_validation_error(invalid_evolution_start_response, ["body", "training_games"], "less_than_equal")

    _assert_error_detail(missing_benchmark_stop_response, 404, "batch not found")
    _assert_validation_error(invalid_benchmark_response, ["body", "max_days"], "greater_than_equal")

    _assert_error_detail(missing_role_version_response, 404, "version not found")
    _assert_error_detail(missing_role_rollback_response, 404, "version not found")


def test_games_list_and_detail_api_contract(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        game_id = _seed_game(store)

        list_response = client.get("/api/games?limit=10&offset=0&source=normal&status=completed")
        detail_response = client.get(f"/api/games/{game_id}")

    assert list_response.status_code == 200
    listed_payload = list_response.json()
    _assert_shape(listed_payload, {"games": list, "pagination": dict, "counts": dict, "facets": dict})
    _assert_pagination(listed_payload)
    assert listed_payload["pagination"]["returned"] == 1
    assert listed_payload["counts"] == {"all": 1, "normal": 1, "benchmark": 0, "evolution": 0}
    assert listed_payload["facets"]["source"] == listed_payload["counts"]
    game_summary = listed_payload["games"][0]
    _assert_shape(
        game_summary,
        {
            "game_id": str,
            "log_name": str,
            "log_source": str,
            "log_source_label": str,
            "status": str,
            "stop_requested": bool,
            "cancelled": bool,
            "interrupted": bool,
            "failed": bool,
            "event_count": int,
            "decision_count": int,
            "player_count": int,
            "config": dict,
        },
    )

    assert detail_response.status_code == 200
    detail = detail_response.json()
    _assert_shape(
        detail,
        {
            "game_id": str,
            "status": str,
            "players": list,
            "logs": list,
            "events": list,
            "decisions": list,
            "review": dict,
            "manifest": dict,
            "config": dict,
        },
    )
    _assert_shape(detail["manifest"], {"schema_version": int, "run_type": str, "game_id": str, "status": str})


def test_game_events_sse_id_and_resume_api_contract(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        game_id = _seed_game(store)
        store.games[game_id]["events"].append({"sequence": 2, "event_type": "phase", "message": "day starts"})

        full_response = client.get(f"/api/games/{game_id}/events")
        header_resume_response = client.get(f"/api/games/{game_id}/events", headers={"Last-Event-ID": "2"})
        query_resume_response = client.get(f"/api/games/{game_id}/events?last_event_id=3")

    assert full_response.status_code == 200
    full_frames = _sse_frames(full_response.text)
    assert [frame["id"] for frame in full_frames] == [1, 2, 3, 4]
    assert [frame["event"] for frame in full_frames] == ["log", "log", "decision", "done"]
    assert full_frames[0]["data"]["event_type"] == "game_init"
    assert full_frames[2]["data"]["action_type"] == "speak"
    assert full_frames[3]["data"]["game_id"] == game_id

    assert header_resume_response.status_code == 200
    header_frames = _sse_frames(header_resume_response.text)
    assert [frame["id"] for frame in header_frames] == [3, 4]
    assert [frame["event"] for frame in header_frames] == ["decision", "done"]

    assert query_resume_response.status_code == 200
    query_frames = _sse_frames(query_resume_response.text)
    assert [frame["id"] for frame in query_frames] == [4]
    assert query_frames[0]["event"] == "done"


def test_in_progress_player_game_responses_hide_private_information(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        game_id = _seed_in_progress_player_game(store)

        read_response = client.get(f"/api/games/{game_id}")
        human_action_response = client.get(f"/api/games/{game_id}/human-action")
        events_response = client.get(f"/api/games/{game_id}/events")
        archive_response = client.get(f"/api/games/{game_id}/archive")
        review_response = client.get(f"/api/games/{game_id}/review")

    assert read_response.status_code == 200
    payload = read_response.json()
    players = {player["id"]: player for player in payload["players"]}
    assert players[1]["role"] == "villager"
    assert players[1]["role_hint"] == "平民"
    assert players[2]["role"] == "unknown"
    assert players[2]["role_hint"] == "未知"
    assert players[2]["team"] == "unknown"
    assert players[2]["role_state"] == {}
    assert players[3]["role"] == "unknown"

    assert [log["sequence"] for log in payload["logs"]] == [1, 2, 5, 7]
    init_payload = payload["logs"][0]["payload"]
    assert "roles" not in init_payload
    night_payload = payload["logs"][-1]["payload"]
    assert night_payload == {"deaths": [2]}
    assert all("2号私密视角" not in log.get("message", "") for log in payload["logs"])
    assert all(log.get("visibility") != "god" for log in payload["logs"])

    decisions = payload["decisions"]
    assert [decision["id"] for decision in decisions] == ["d-public", "d-human"]
    assert decisions[0]["role"] == "unknown"
    assert decisions[0]["reason"] == "2号发言"
    assert decisions[1]["role"] == "villager"
    assert "private_reasoning" not in decisions[0]
    assert payload["review"] is None

    assert human_action_response.status_code == 200
    human_action = human_action_response.json()
    assert human_action["player_id"] == 1
    assert human_action["observation"]["role_state"]["private_note"] == "human only"

    assert events_response.status_code == 200
    frames = _sse_frames(events_response.text)
    assert [frame["event"] for frame in frames] == ["log", "log", "log", "log", "decision", "decision", "done"]
    assert all(frame["data"] is not None for frame in frames)
    assert "2号私密视角" not in events_response.text
    assert "god-only role table" not in events_response.text
    assert "seer_check" not in events_response.text
    assert "private_reasoning" not in events_response.text
    assert frames[-1]["data"]["players"][2]["role"] == "unknown"

    assert archive_response.status_code == 200
    archive = archive_response.json()
    assert archive["review"] is None
    assert archive["decision_count"] == 2
    assert all(event.get("visibility") != "god" for event in archive["events"])
    assert "roles" not in json.dumps(archive, ensure_ascii=False)
    assert "seer" not in json.dumps(archive["events"], ensure_ascii=False)

    assert review_response.status_code == 200
    review = review_response.json()
    assert review["review_status"] == "暂无复盘报告"


def test_completed_player_game_responses_keep_review_information(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        game_id = _seed_in_progress_player_game(store)
        store.games[game_id]["status"] = "completed"
        store.games[game_id]["winner"] = "villagers"

        read_response = client.get(f"/api/games/{game_id}")
        review_response = client.get(f"/api/games/{game_id}/review")

    assert read_response.status_code == 200
    payload = read_response.json()
    assert payload["players"][1]["role"] == "seer"
    assert payload["review"]["agent_scores"]["2"]["role"] == "seer"

    assert review_response.status_code == 200
    assert review_response.json()["agent_scores"]["2"]["role"] == "seer"


def test_evolution_events_sse_id_and_resume_api_contract(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        run_id, _ = _seed_evolution(store)

        full_response = client.get(f"/api/evolution-runs/{run_id}/events")
        header_resume_response = client.get(f"/api/evolution-runs/{run_id}/events", headers={"Last-Event-ID": "1"})
        query_resume_response = client.get(f"/api/evolution-runs/{run_id}/events?lastEventId=1")

    assert full_response.status_code == 200
    full_frames = _sse_frames(full_response.text)
    assert len(full_frames) == 1
    assert full_frames[0]["id"] == 1
    assert full_frames[0]["event"] == "reviewing"
    _assert_shape(full_frames[0]["data"], {"run_id": str, "status": str, "progress": dict, "diagnostics": list})
    assert full_frames[0]["data"]["run_id"] == run_id

    assert header_resume_response.status_code == 200
    assert header_resume_response.text == ""
    assert query_resume_response.status_code == 200
    assert query_resume_response.text == ""


def test_benchmark_events_sse_id_and_resume_api_contract(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        _, batch_id = _seed_evolution(store)

        full_response = client.get(f"/api/benchmark/batch/{batch_id}/events")
        header_resume_response = client.get(f"/api/benchmark/batch/{batch_id}/events", headers={"Last-Event-ID": "1"})
        query_resume_response = client.get(f"/api/benchmark/batch/{batch_id}/events?lastEventId=1")
        missing_response = client.get("/api/benchmark/batch/missing_contract_batch/events")

    assert full_response.status_code == 200
    full_frames = _sse_frames(full_response.text)
    assert len(full_frames) == 1
    assert full_frames[0]["id"] == 1
    assert full_frames[0]["event"] == "completed"
    _assert_shape(full_frames[0]["data"], {"batch_id": str, "status": str, "progress": dict, "diagnostics": list})
    assert full_frames[0]["data"]["batch_id"] == batch_id
    assert full_frames[0]["data"]["source"] == "benchmark"

    assert header_resume_response.status_code == 200
    assert header_resume_response.text == ""
    assert query_resume_response.status_code == 200
    assert query_resume_response.text == ""
    _assert_error_detail(missing_response, 404, "batch not found")


def test_game_stop_cancel_api_contract(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        game_id = _seed_game(store)

        response = client.post(f"/api/games/{game_id}/stop")
        missing_response = client.post("/api/games/missing_contract_game/stop")

    assert response.status_code == 200
    payload = response.json()
    _assert_shape(
        payload,
        {
            "game_id": str,
            "status": str,
            "stop_requested": bool,
            "cancelled": bool,
            "interrupted": bool,
            "failed": bool,
            "cancelled_at": str,
            "finished_at": str,
            "error": str,
            "players": list,
            "logs": list,
            "decisions": list,
        },
    )
    assert payload["game_id"] == game_id
    assert payload["status"] == "cancelled"
    assert payload["stop_requested"] is True
    assert payload["cancelled"] is True
    assert payload["interrupted"] is False
    assert payload["failed"] is False
    assert payload["error"] == "cancelled"

    assert missing_response.status_code == 200
    missing = missing_response.json()
    assert missing["game_id"] == "missing_contract_game"
    assert missing["status"] == "cancelled"
    assert missing["stop_requested"] is True
    assert missing["cancelled"] is True
    assert missing["players"] == []


def test_roles_and_versions_api_contract(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        store.registry.publish_skills(
            "seer",
            {"contract.md": _valid_seer_skill()},
            version_id="seer_contract_v1",
            source="contract-test",
            set_as_baseline=True,
            expected_current=None,
        )

        roles_response = client.get("/api/roles")
        versions_response = client.get("/api/roles/seer/versions")

    assert roles_response.status_code == 200
    roles_payload = roles_response.json()
    _assert_shape(roles_payload, {"roles": list})
    assert "seer" in roles_payload["roles"]

    assert versions_response.status_code == 200
    versions_payload = versions_response.json()
    _assert_shape(versions_payload, {"role": str, "versions": list})
    assert versions_payload["role"] == "seer"
    version = next(item for item in versions_payload["versions"] if item["version_id"] == "seer_contract_v1")
    _assert_shape(
        version,
        {
            "version_id": str,
            "role": str,
            "source": str,
            "created_at": str,
            "is_baseline": bool,
            "status": str,
            "metrics": dict,
        },
    )
    _assert_shape(version["metrics"], {"score": (int, float), "win_rate": (int, float), "games_played": int})


def test_evolution_run_list_diff_games_and_manifest_api_contract(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        run_id, batch_id = _seed_evolution(store)

        list_response = client.get("/api/evolution-runs?limit=20&offset=0")
        detail_response = client.get(f"/api/evolution-runs/{run_id}")
        diff_response = client.get(f"/api/evolution-runs/{run_id}/diff")
        games_response = client.get(f"/api/evolution-runs/{run_id}/games?phase=training&limit=10&offset=0")

    assert list_response.status_code == 200
    list_payload = list_response.json()
    _assert_shape(list_payload, {"kind": str, "schema_version": int, "runs": list, "batches": list, "pagination": dict})
    _assert_pagination(list_payload)

    run_summary = next(item for item in list_payload["runs"] if item["run_id"] == run_id)
    _assert_shape(
        run_summary,
        {
            "kind": str,
            "schema_version": int,
            "run_id": str,
            "source": str,
            "role": str,
            "status": str,
            "current_stage": str,
            "progress": dict,
            "diagnostics": list,
            "config": dict,
            "training_game_count": int,
            "battle_game_count": int,
            "proposal_count": int,
            "diff_count": int,
            "error_count": int,
        },
    )
    _assert_task_progress(run_summary["progress"])
    _assert_shape(run_summary["diagnostics"][0], {"kind": str, "stage": str, "level": str, "message": str})

    batch_summary = next(item for item in list_payload["batches"] if item["batch_id"] == batch_id)
    _assert_shape(
        batch_summary,
        {
            "kind": str,
            "schema_version": int,
            "batch_id": str,
            "source": str,
            "roles": list,
            "status": str,
            "current_stage": str,
            "progress": dict,
            "diagnostics": list,
            "config": dict,
            "result": dict,
        },
    )
    _assert_task_progress(batch_summary["progress"])

    assert detail_response.status_code == 200
    detail = detail_response.json()
    _assert_shape(detail, {"run_id": str, "manifest": dict, "progress": dict, "diagnostics": list})
    _assert_shape(detail["manifest"], {"schema_version": int, "run_type": str, "run_id": str, "status": str})

    assert diff_response.status_code == 200
    diff = diff_response.json()
    _assert_shape(diff, {"kind": str, "schema_version": int, "run_id": str, "diffs": list})
    _assert_shape(diff["diffs"][0], {"target_file": str, "action": str, "before": str, "after": str})

    assert games_response.status_code == 200
    games = games_response.json()
    _assert_shape(games, {"kind": str, "schema_version": int, "run_id": str, "phase": str, "games": list, "pagination": dict})
    _assert_pagination(games)
    game = games["games"][0]
    _assert_shape(
        game,
        {
            "game_id": str,
            "id": str,
            "status": str,
            "phase": str,
            "history_game_id": str,
            "event_count": int,
            "decision_count": int,
            "in_progress": bool,
        },
    )
    assert game["history_game_id"] == f"evolution:{run_id}:training:training_001"


def test_evolution_actions_promote_reject_stop_api_contract(tmp_path: Path) -> None:
    proposal = {
        "proposal_id": "p1",
        "target_file": "seer.md",
        "section": "Strategy",
        "content": "Prefer checking players who drive split votes.",
        "rationale": "Observed in training games.",
    }

    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        store.evolution_runs["evolve_contract_promote"] = {
            "kind": "role_evolution_run",
            "schema_version": 1,
            "run_id": "evolve_contract_promote",
            "role": "seer",
            "status": "reviewing",
            "stop_requested": False,
            "cancelled": False,
            "interrupted": False,
            "failed": False,
            "parent_hash": "baseline_seer",
            "candidate_hash": "candidate_seer_contract",
            "proposals": [proposal],
            "diff": [],
            "battle_result": {"completed": 1, "candidate_win_rate": 1.0},
        }
        promote_response = client.post(
            "/api/evolution-runs/evolve_contract_promote/actions",
            json={"action": "promote"},
        )
        versions_response = client.get("/api/roles/seer/versions")
        version_detail_response = client.get("/api/roles/seer/versions/candidate_seer_contract")

        store.evolution_runs["evolve_contract_reject"] = {
            "kind": "role_evolution_run",
            "schema_version": 1,
            "run_id": "evolve_contract_reject",
            "role": "seer",
            "status": "reviewing",
            "stop_requested": False,
            "cancelled": False,
            "interrupted": False,
            "failed": False,
            "proposals": [proposal],
            "battle_result": {"completed": 1, "candidate_win_rate": 0.0},
        }
        reject_response = client.post(
            "/api/evolution-runs/evolve_contract_reject/actions",
            json={"action": "reject"},
        )
        rejected = store.registry.load_rejected("seer")

        store.evolution_runs["evolve_contract_stop"] = {
            "kind": "role_evolution_run",
            "schema_version": 1,
            "run_id": "evolve_contract_stop",
            "role": "seer",
            "status": "training",
            "started_at": "2026-01-01T00:00:00+08:00",
        }
        stop_response = client.post(
            "/api/evolution-runs/evolve_contract_stop/actions",
            json={"action": "stop"},
        )

    assert promote_response.status_code == 200
    promoted = promote_response.json()
    _assert_shape(
        promoted,
        {
            "run_id": str,
            "role": str,
            "status": str,
            "candidate_hash": str,
            "published_version_id": str,
            "promoted_version_id": str,
            "finished_at": str,
            "last_heartbeat_at": str,
        },
    )
    assert promoted["status"] == "promoted"
    assert promoted["candidate_hash"] == "candidate_seer_contract"
    assert promoted["published_version_id"] == "candidate_seer_contract"
    assert promoted["promoted_version_id"] == "candidate_seer_contract"

    assert versions_response.status_code == 200
    published = next(
        item for item in versions_response.json()["versions"] if item["version_id"] == "candidate_seer_contract"
    )
    assert published["is_baseline"] is True
    assert published["source"] == "evolution"

    assert version_detail_response.status_code == 200
    version_detail = version_detail_response.json()
    _assert_shape(version_detail, {"role": str, "version_id": str, "files": list, "status": str})
    assert version_detail["version_id"] == "candidate_seer_contract"
    assert version_detail["files"][0]["path"] == "evolution.md"
    assert "Prefer checking players" in version_detail["files"][0]["content"]

    assert reject_response.status_code == 200
    rejected_payload = reject_response.json()
    _assert_shape(
        rejected_payload,
        {
            "run_id": str,
            "role": str,
            "status": str,
            "rejected_at": str,
            "finished_at": str,
            "last_heartbeat_at": str,
        },
    )
    assert rejected_payload["status"] == "rejected"
    assert rejected[-1]["proposal_id"] == "p1"
    assert rejected[-1]["battle_result"]["candidate_win_rate"] == 0.0

    assert stop_response.status_code == 200
    stopped = stop_response.json()
    _assert_shape(
        stopped,
        {
            "run_id": str,
            "role": str,
            "status": str,
            "stop_requested": bool,
            "cancelled": bool,
            "interrupted": bool,
            "failed": bool,
            "cancelled_at": str,
            "finished_at": str,
            "last_heartbeat_at": str,
            "error": str,
        },
    )
    assert stopped["status"] == "failed"
    assert stopped["stop_requested"] is True
    assert stopped["cancelled"] is True
    assert stopped["interrupted"] is False
    assert stopped["failed"] is False
    assert stopped["error"] == "stopped"


def test_benchmark_post_api_contract(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = client.post("/api/benchmark", json={"roles": ["seer"], "battle_games": 0, "max_days": 1})

    assert response.status_code == 200
    payload = response.json()
    _assert_shape(
        payload,
        {
            "kind": str,
            "schema_version": int,
            "batch_id": str,
            "roles": list,
            "status": str,
            "stop_requested": bool,
            "cancelled": bool,
            "interrupted": bool,
            "failed": bool,
            "started_at": str,
            "last_heartbeat_at": str,
            "current_stage": str,
            "progress": dict,
            "diagnostics": list,
            "config": dict,
        },
    )
    assert payload["batch_id"].startswith("bench_")
    assert payload["roles"] == ["seer"]
    _assert_task_progress(payload["progress"])
    assert payload["diagnostics"] == []


def test_benchmark_stop_api_contract(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        _, batch_id = _seed_evolution(store)
        batch = store.evolution_batches[batch_id]
        batch["status"] = "running"
        batch["current_stage"] = "running"
        batch["progress"] = {
            "stage": "running",
            "percent": 0.25,
            "completed_roles": 0,
            "role_count": 1,
            "total_roles": 1,
            "updated_at": "2026-01-01T00:03:10+08:00",
        }
        batch["diagnostics"] = []
        batch["error"] = None

        response = client.post(f"/api/benchmark/batch/{batch_id}/stop")
        list_response = client.get("/api/evolution-runs?source=benchmark&status=failed&limit=10")

    assert response.status_code == 200
    payload = response.json()
    _assert_shape(
        payload,
        {
            "kind": str,
            "schema_version": int,
            "batch_id": str,
            "roles": list,
            "status": str,
            "stop_requested": bool,
            "cancelled": bool,
            "interrupted": bool,
            "failed": bool,
            "cancelled_at": str,
            "finished_at": str,
            "last_heartbeat_at": str,
            "current_stage": str,
            "progress": dict,
            "diagnostics": list,
            "error": str,
        },
    )
    assert payload["batch_id"] == batch_id
    assert payload["status"] == "failed"
    assert payload["stop_requested"] is True
    assert payload["cancelled"] is True
    assert payload["interrupted"] is False
    assert payload["failed"] is False
    assert payload["current_stage"] == "stopped"
    assert payload["error"] == "stopped"
    assert payload["progress"]["stage"] == "stopped"
    assert payload["progress"]["completed_roles"] == 0
    assert payload["progress"]["role_count"] == 1
    assert payload["diagnostics"][0]["kind"] == "benchmark_stopped"
    assert payload["diagnostics"][0]["message"] == "stopped"

    assert list_response.status_code == 200
    listed_payload = list_response.json()
    _assert_pagination(listed_payload)
    listed = next(item for item in listed_payload["batches"] if item["batch_id"] == batch_id)
    assert listed["status"] == "failed"
    assert listed["source"] == "benchmark"
    assert listed["stop_requested"] is True
    assert listed["cancelled"] is True
    assert listed["current_stage"] == "stopped"
    assert listed["progress"]["stage"] == "stopped"
    assert listed["diagnostics"][0]["kind"] == "benchmark_stopped"
