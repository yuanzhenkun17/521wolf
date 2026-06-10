"""Stable API shape contracts for the UI backend.

These tests intentionally check small response shapes instead of large snapshots.
They should fail when frontend-facing field names or basic types drift.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import PathConfig
from app.lib.benchmark_reproducibility import verify_benchmark_reproducibility_manifest
import ui.backend.app as ui_backend_app


@dataclass
class _FakeVersionSummary:
    version_id: str
    role: str
    source: str = ""
    created_at: str = "2026-01-01T00:00:00+08:00"
    is_baseline: bool = False
    status: str = "active"
    release_stage: str = "draft"
    provenance: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "role": self.role,
            "source": self.source,
            "created_at": self.created_at,
            "is_baseline": self.is_baseline,
            "status": self.status,
            "release_stage": self.release_stage,
            "provenance": dict(self.provenance or {}),
        }


class FakeVersionRegistry:
    def __init__(self, root: Path) -> None:
        self._registry_dir = root / "registry"
        self._registry_dir.mkdir(parents=True, exist_ok=True)
        self._versions: dict[str, dict[str, dict[str, Any]]] = {}
        self._baselines: dict[str, str] = {}
        self._rejected: dict[str, list[dict[str, Any]]] = {}
        self._scratch: list[Path] = []

    @property
    def registry_dir(self) -> Path:
        return self._registry_dir

    def close(self) -> None:
        return None

    def publish_skills(
        self,
        role: str,
        skill_contents: dict[str, str],
        *,
        parent_id: str | None = None,
        source: str = "manual",
        run_id: str | None = None,
        proposal_ids: list[str] | None = None,
        version_id: str | None = None,
        set_as_baseline: bool = False,
        expected_current: str | None = None,
        release_stage: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> str:
        del parent_id
        role_versions = self._versions.setdefault(role, {})
        version_id = version_id or f"{role}_v{len(role_versions) + 1}"
        stage = "baseline" if set_as_baseline else str(release_stage or "draft")
        status = "active" if stage == "draft" else stage
        role_versions[version_id] = {
            "summary": _FakeVersionSummary(
                version_id=version_id,
                role=role,
                source=source,
                is_baseline=False,
                status=status,
                release_stage=stage,
                provenance={
                    **dict(provenance or {}),
                    "source": source,
                    "run_id": run_id,
                    "proposal_ids": list(proposal_ids or []),
                    "release_stage": stage,
                },
            ),
            "contents": dict(skill_contents),
        }
        if set_as_baseline and not self.set_baseline(role, version_id, expected_current=expected_current):
            raise RuntimeError(f"Failed to set baseline for {role}")
        return version_id

    def get_baseline(self, role: str) -> str | None:
        return self._baselines.get(role)

    def set_baseline(
        self,
        role: str,
        version_id: str,
        expected_current: str | None = None,
    ) -> bool:
        if version_id not in self._versions.get(role, {}):
            return False
        if self._baselines.get(role) != expected_current:
            return False
        previous = self._baselines.get(role)
        if previous in self._versions.get(role, {}):
            self._versions[role][previous]["summary"].is_baseline = False
        self._baselines[role] = version_id
        summary = self._versions[role][version_id]["summary"]
        summary.is_baseline = True
        summary.status = "promoted"
        summary.release_stage = "baseline"
        summary.provenance = {**dict(summary.provenance or {}), "release_stage": "baseline"}
        return True

    def reject(self, role: str, version_id: str, reason: str = "") -> None:
        del reason
        if version_id not in self._versions.get(role, {}):
            raise FileNotFoundError(f"Version {role}/{version_id} not found")
        self._versions[role][version_id]["summary"].status = "rejected"

    def read_skill_contents(self, role: str, version_id: str) -> dict[str, str]:
        try:
            return dict(self._versions[role][version_id]["contents"])
        except KeyError as exc:
            raise FileNotFoundError(f"Version {role}/{version_id} not found") from exc

    def get_skill_dir(self, role: str, version_id: str) -> Path:
        root = Path(tempfile.mkdtemp(prefix="api_contract_skills_"))
        self._scratch.append(root)
        for rel_path, content in self.read_skill_contents(role, version_id).items():
            output = root / rel_path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(content, encoding="utf-8")
        return root

    def build_skill_dir(self, role_versions: dict[str, str]) -> Path:
        root = Path(tempfile.mkdtemp(prefix="api_contract_skillset_"))
        self._scratch.append(root)
        for role, version_id in role_versions.items():
            for rel_path, content in self.read_skill_contents(role, version_id).items():
                output = root / role / rel_path
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(content, encoding="utf-8")
        return root

    def list_versions(self, role: str) -> list[_FakeVersionSummary]:
        return [
            item["summary"]
            for item in self._versions.get(role, {}).values()
        ]

    def list_roles(self) -> list[str]:
        return sorted(self._versions)

    def save_rejected(
        self,
        role: str,
        proposals: list[dict[str, Any]],
        battle_result: dict[str, Any] | None = None,
    ) -> None:
        rows = self._rejected.setdefault(role, [])
        for proposal in proposals:
            row = dict(proposal)
            row["battle_result"] = battle_result
            row["rejected_at"] = "2026-01-01T00:00:00+08:00"
            rows.append(row)

    def load_rejected(self, role: str) -> list[dict[str, Any]]:
        return list(self._rejected.get(role, []))


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
    store = app.state.backend_store
    store._registry = FakeVersionRegistry(tmp_path)
    store._postgres_history_fingerprint = lambda: {
        "total": 0,
        "max_finished_at": None,
        "max_started_at": None,
    }
    store._load_game_from_pg = lambda game_id: store.games.get(game_id)
    store._list_games_from_pg = lambda: [
        store._game_list_row(game)
        for game in store.games.values()
        if str(game.get("status") or "").lower() in {"completed", "cancelled", "interrupted", "failed"}
    ]

    persisted_snapshots: list[dict[str, Any]] = []

    def persist_snapshot(snapshot: dict[str, Any], **_kwargs: Any) -> None:
        persisted_snapshots.append(dict(snapshot))

    store._persisted_snapshots_for_test = persisted_snapshots
    store._persist_snapshot_to_pg = persist_snapshot
    deleted_games: list[str] = []
    store._deleted_games_for_test = deleted_games
    store._delete_game_from_pg = lambda game_id: deleted_games.append(str(game_id))
    return TestClient(app)


def _install_sqlite_eval_storage(monkeypatch: Any, tmp_path: Path) -> None:
    import app.lib.score as score_lib

    db_path = tmp_path / "benchmark_eval.sqlite3"

    class _SqliteEvalConnection:
        def __init__(self, conn: sqlite3.Connection) -> None:
            self._conn = conn

        def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
            return self._conn.execute(sql, parameters)

        def begin_write(self) -> None:
            self._conn.execute("BEGIN")

        def commit(self) -> None:
            self._conn.commit()

        def rollback(self) -> None:
            self._conn.rollback()

        def close(self) -> None:
            self._conn.close()

        def __enter__(self) -> "_SqliteEvalConnection":
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
            return False

    def open_conn(paths: Any = None) -> _SqliteEvalConnection:
        del paths
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        _initialize_sqlite_benchmark_eval_schema(conn)
        return _SqliteEvalConnection(conn)

    monkeypatch.setattr(score_lib, "open_eval_connection", open_conn)


def _initialize_sqlite_benchmark_eval_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS benchmark_leaderboard_snapshots (
            snapshot_id text PRIMARY KEY,
            title text NOT NULL,
            release_notes text,
            scope text NOT NULL,
            benchmark_id text,
            benchmark_version text,
            evaluation_set_id text NOT NULL,
            seed_set_id text,
            benchmark_config_hash text,
            target_role text,
            source_filter jsonb,
            view_config jsonb,
            rows_json jsonb NOT NULL,
            summary_json jsonb NOT NULL,
            row_count integer DEFAULT 0,
            content_hash text NOT NULL,
            created_at timestamptz NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bench_snapshot_scope_eval "
        "ON benchmark_leaderboard_snapshots(scope, evaluation_set_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bench_snapshot_benchmark "
        "ON benchmark_leaderboard_snapshots(benchmark_id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS benchmark_saved_views (
            view_key text PRIMARY KEY,
            name text NOT NULL,
            scope text NOT NULL,
            benchmark_id text,
            evaluation_set_id text,
            target_role text,
            view_config jsonb NOT NULL,
            created_at timestamptz NOT NULL,
            updated_at timestamptz NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bench_view_scope_eval "
        "ON benchmark_saved_views(scope, evaluation_set_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_bench_view_benchmark "
        "ON benchmark_saved_views(benchmark_id)"
    )
    conn.commit()


def _write_benchmark_spec(root: Path) -> None:
    spec_dir = root / "data" / "benchmarks"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "role-baseline-v1.yaml").write_text(
        """
id: role-baseline-v1
version: 1
name: Role Baseline Benchmark
description: Fixed-seed role version evaluation benchmark
target_type: role_version
roles: [seer, witch]
game_count: 3
max_days: 5
paired_seed: true
seed_set_id: role-baseline-quick-202606
seed_start: 260600
metrics:
  primary: avg_role_score
  secondary: [target_side_win_rate, fallback_rate, llm_error_rate]
gates:
  min_completed_games: 1
  min_valid_game_rate: 0.5
  max_fallback_rate: 0.5
  max_llm_error_rate: 0.5
judge:
  enable_decision_judge: true
  judge_max_decisions: 10
  judge_concurrency: 2
  judge_timeout_seconds: 60
""",
        encoding="utf-8",
    )
    seed_dir = root / "data" / "benchmark_seed_sets"
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / "role-baseline-quick-202606.yaml").write_text(
        """
id: role-baseline-quick-202606
purpose: role_leaderboard_smoke
version: 1
target_type: role_version
seeds: [260600, 260607, 260619]
enabled: true
""",
        encoding="utf-8",
    )


def _write_deprecated_benchmark_spec(root: Path) -> None:
    spec_dir = root / "data" / "benchmarks"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "role-deprecated-v1.yaml").write_text(
        """
id: role-deprecated-v1
version: 1
name: Role Deprecated Benchmark
description: Deprecated fixed-seed role benchmark retained for audit.
target_type: role_version
roles: [seer]
game_count: 3
max_days: 5
paired_seed: true
seed_set_id: role-baseline-quick-202606
seed_start: 260600
metrics:
  primary: avg_role_score
  secondary: [target_side_win_rate, fallback_rate, llm_error_rate]
gates:
  min_completed_games: 1
  min_valid_game_rate: 0.5
  max_fallback_rate: 0.5
  max_llm_error_rate: 0.5
judge:
  enable_decision_judge: true
  judge_max_decisions: 10
  judge_concurrency: 2
  judge_timeout_seconds: 60
status: deprecated
""",
        encoding="utf-8",
    )


def _write_benchmark_spec_v2(root: Path) -> None:
    spec_dir = root / "data" / "benchmarks"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "role-baseline-v2.yaml").write_text(
        """
id: role-baseline-v2
version: 2
name: Role Baseline Benchmark V2
description: Draft next-version role benchmark retained in the suite lineage.
target_type: role_version
roles: [seer, witch]
game_count: 3
max_days: 5
paired_seed: true
seed_set_id: role-baseline-quick-202606
seed_start: 260600
metrics:
  primary: avg_role_score
  secondary: [target_side_win_rate, fallback_rate, llm_error_rate]
gates:
  min_completed_games: 1
  min_valid_game_rate: 0.5
  max_fallback_rate: 0.5
  max_llm_error_rate: 0.5
judge:
  enable_decision_judge: true
  judge_max_decisions: 10
  judge_concurrency: 2
  judge_timeout_seconds: 60
status: draft
""",
        encoding="utf-8",
    )


def _write_model_benchmark_spec(root: Path) -> None:
    spec_dir = root / "data" / "benchmarks"
    spec_dir.mkdir(parents=True, exist_ok=True)
    (spec_dir / "model-baseline-v1.yaml").write_text(
        """
id: model-baseline-v1
version: 1
name: Model Baseline Benchmark
description: Fixed-seed model/runtime evaluation benchmark
target_type: model
roles: [seer, witch]
game_count: 3
max_days: 5
paired_seed: true
seed_set_id: model-baseline-quick-202606
seed_start: 270600
metrics:
  primary: strength_score
  secondary: [avg_role_score, fallback_rate, llm_error_rate]
gates:
  min_completed_games: 1
  min_valid_game_rate: 0.5
  max_fallback_rate: 0.5
  max_llm_error_rate: 0.5
judge:
  enable_decision_judge: true
  judge_max_decisions: 10
  judge_concurrency: 2
  judge_timeout_seconds: 60
""",
        encoding="utf-8",
    )
    seed_dir = root / "data" / "benchmark_seed_sets"
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / "model-baseline-quick-202606.yaml").write_text(
        """
id: model-baseline-quick-202606
purpose: model_leaderboard_smoke
version: 1
target_type: model
seeds: [270600, 270611, 270623]
enabled: true
""",
        encoding="utf-8",
    )


def _write_benchmark_seed_set(root: Path, filename: str, body: str) -> None:
    seed_dir = root / "data" / "benchmark_seed_sets"
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / filename).write_text(body, encoding="utf-8")


def _assert_shape(payload: dict[str, Any], shape: dict[str, type | tuple[type, ...]]) -> None:
    missing = [key for key in shape if key not in payload]
    assert missing == []
    for key, expected in shape.items():
        assert isinstance(payload[key], expected), f"{key} expected {expected}, got {type(payload[key])}"


def _assert_leaderboard_statistics_contract(payload: dict[str, Any]) -> None:
    _assert_shape(
        payload,
        {
            "sample_size": int,
            "paired_sample_size": int,
            "win_rate_ci": dict,
            "ci_low": (int, float),
            "ci_high": (int, float),
            "standard_error": (int, float),
            "paired_delta": (int, float, type(None)),
            "significant": bool,
            "significance_label": str,
            "warnings": list,
        },
    )
    _assert_shape(
        payload["win_rate_ci"],
        {
            "low": (int, float),
            "high": (int, float),
            "level": (int, float),
        },
    )
    assert payload["ci_low"] == payload["win_rate_ci"]["low"]
    assert payload["ci_high"] == payload["win_rate_ci"]["high"]
    assert payload["sample_size"] >= 0
    assert payload["paired_sample_size"] >= 0
    assert 0 <= payload["ci_low"] <= payload["ci_high"] <= 1
    assert set(payload["warnings"]).issubset({"low_sample", "unpaired_seeds", "insufficient_overlap"})


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


def _assert_snapshot_release_gate_error(response: Any, detail_fragment: str) -> None:
    assert response.status_code == 422
    payload = response.json()
    _assert_shape(payload, {"detail": str, "error": dict})
    assert detail_fragment in payload["detail"]
    _assert_shape(payload["error"], {"code": str, "message": str, "diagnostics": list})
    assert detail_fragment in payload["error"]["message"]
    assert payload["error"]["code"] == "benchmark_snapshot_release_gate_failed"
    assert payload["error"]["diagnostics"]
    diagnostic = payload["error"]["diagnostics"][0]
    assert diagnostic["kind"] == "benchmark_snapshot_release_gate_failed"
    assert diagnostic["release_gate_ok"] is False
    assert diagnostic["blockers"]
    assert detail_fragment in diagnostic["blockers"][0]["message"]


def _assert_domain_error(
    response: Any,
    status_code: int,
    code: str,
    *,
    detail_contains: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    assert response.status_code == status_code
    payload = response.json()
    _assert_shape(payload, {"detail": str, "error": dict})
    if detail_contains is not None:
        assert detail_contains in payload["detail"]
    _assert_shape(payload["error"], {"code": str, "message": str, "diagnostics": list})
    assert payload["error"]["code"] == code
    assert payload["error"]["diagnostics"]
    if kind is not None:
        assert payload["error"]["diagnostics"][0]["kind"] == kind
    return payload


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


_FORBIDDEN_CONTRACT_KEYS = {
    "belief_snapshot",
    "god_view",
    "god_view_after_game",
    "memory_refs",
    "private_payload",
    "private_reasoning",
    "role_map",
    "roles",
    "roles_by_player",
    "player_roles",
}
_PRIVATE_NIGHT_PAYLOAD_KEYS = {
    "checked_role",
    "checked_team",
    "check_result",
    "guarded_target",
    "killed_target",
    "poisoned",
    "poisoned_target",
    "protected_target",
    "saved",
    "target_role",
    "target_team",
}
_PRIVATE_ACTION_TYPES = {
    "debug_roles",
    "god_debug",
    "guard_protect",
    "guard_result",
    "seer_check",
    "seer_result",
    "werewolf_kill",
    "werewolf_result",
    "witch_act",
    "witch_result",
}
_REDACTED_ROLE_VALUES = {"", None, "unknown", "未知"}


def _walk_json(value: Any, path: str = "$") -> list[tuple[str, Any]]:
    items = [(path, value)]
    if isinstance(value, dict):
        for key, child in value.items():
            items.extend(_walk_json(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            items.extend(_walk_json(child, f"{path}[{index}]"))
    return items


def _is_allowed_forbidden_key_path(path: str, key: str) -> bool:
    if key == "roles":
        return path.endswith(".config.roles")
    return False


def _assert_no_forbidden_contract_fields(payload: Any) -> None:
    leaked_paths: list[str] = []
    for path, value in _walk_json(payload):
        if not isinstance(value, dict):
            continue
        for key in value:
            key_text = str(key)
            key_path = f"{path}.{key_text}"
            if key_text in _FORBIDDEN_CONTRACT_KEYS and not _is_allowed_forbidden_key_path(key_path, key_text):
                leaked_paths.append(key_path)
    assert leaked_paths == []


def _assert_no_private_night_payload(payload: Any) -> None:
    leaked_paths: list[str] = []
    leaked_events: list[str] = []
    for path, value in _walk_json(payload):
        if not isinstance(value, dict):
            continue
        for key in value:
            key_text = str(key)
            if key_text in _PRIVATE_NIGHT_PAYLOAD_KEYS:
                leaked_paths.append(f"{path}.{key_text}")
        event_type = str(
            value.get("event_type")
            or value.get("type")
            or value.get("action_type")
            or value.get("action")
            or ""
        )
        if event_type in _PRIVATE_ACTION_TYPES:
            leaked_events.append(f"{path}:{event_type}")
    assert leaked_paths == []
    assert leaked_events == []


def _assert_hidden_roles_redacted(
    payload: dict[str, Any],
    *,
    visible_player_ids: set[int],
) -> None:
    players = payload.get("players")
    if not isinstance(players, list):
        return
    for player in players:
        if not isinstance(player, dict):
            continue
        player_id = player.get("id")
        if player_id in visible_player_ids:
            continue
        assert player.get("role") in _REDACTED_ROLE_VALUES
        assert player.get("role_hint") in _REDACTED_ROLE_VALUES
        assert player.get("team") in _REDACTED_ROLE_VALUES
        assert player.get("role_state") in ({}, None)


def _assert_decision_roles_redacted(
    payload: dict[str, Any],
    *,
    visible_player_ids: set[int],
) -> None:
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        return
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        actor_id = decision.get("actor_id", decision.get("player_id"))
        if actor_id in visible_player_ids:
            continue
        assert decision.get("role") in _REDACTED_ROLE_VALUES


def _assert_review_redacted(payload: Any) -> None:
    leaked_paths = [
        path
        for path, value in _walk_json(payload)
        if path.endswith(".agent_scores")
        or path.endswith(".player_evaluations")
        or path.endswith(".player_scores")
        or path.endswith(".player_roles")
        or (path.endswith(".review") and isinstance(value, dict) and value)
    ]
    assert leaked_paths == []


def _assert_player_view_contract(
    payload: dict[str, Any],
    *,
    visible_player_ids: set[int],
    expect_review_redacted: bool = True,
) -> None:
    _assert_no_forbidden_contract_fields(payload)
    _assert_no_private_night_payload(payload)
    _assert_hidden_roles_redacted(payload, visible_player_ids=visible_player_ids)
    _assert_decision_roles_redacted(payload, visible_player_ids=visible_player_ids)
    if expect_review_redacted:
        _assert_review_redacted(payload)


def _assert_public_archive_contract(
    payload: dict[str, Any],
    *,
    visible_player_ids: set[int],
) -> None:
    _assert_no_forbidden_contract_fields(payload)
    _assert_no_private_night_payload(payload)
    _assert_decision_roles_redacted(payload, visible_player_ids=visible_player_ids)
    _assert_review_redacted(payload)
    assert all(event.get("visibility") != "god" for event in payload.get("events", []) if isinstance(event, dict))


def _assert_sse_replay_contract(
    frames: list[dict[str, Any]],
    *,
    visible_player_ids: set[int],
) -> None:
    assert frames
    for frame in frames:
        data = frame.get("data")
        assert data is not None
        _assert_no_forbidden_contract_fields(data)
        _assert_no_private_night_payload(data)
        if frame.get("event") == "done":
            _assert_player_view_contract(data, visible_player_ids=visible_player_ids)
        elif frame.get("event") == "decision":
            _assert_decision_roles_redacted({"decisions": [data]}, visible_player_ids=visible_player_ids)
        elif frame.get("event") == "log":
            assert data.get("visibility") != "god"


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
    return game_id


def _seed_abnormal_terminal_player_game(store: ui_backend_app.BackendStore, status: str = "failed") -> str:
    source_game_id = _seed_in_progress_player_game(store)
    game = json.loads(json.dumps(store.games.pop(source_game_id), ensure_ascii=False))
    game_id = f"ui_contract_abnormal_{status}"
    game.update(
        {
            "game_id": game_id,
            "log_name": game_id,
            "status": status,
            "stop_requested": status in {"cancelled", "interrupted"},
            "cancelled": status == "cancelled",
            "interrupted": status == "interrupted",
            "failed": status == "failed",
            "finished_at": "2026-01-01T00:00:20+08:00",
            "error": status,
            "winner": "werewolves",
            "review": {
                "game_id": game_id,
                "winner": "werewolves",
                "agent_scores": {
                    "2": {
                        "role": "seer",
                        "mistakes": ["checked wolf"],
                    }
                },
                "player_roles": {"1": "villager", "2": "seer", "3": "werewolf"},
            },
        }
    )
    store.games[game_id] = game
    return game_id


def _seed_evolution(store: ui_backend_app.BackendStore) -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:8]
    run_id = f"evolve_contract_{suffix}"
    batch_id = f"bench_contract_{suffix}"
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
        "/api/benchmarks": {
            "get": ("list_benchmarks_api_benchmarks_get", None, []),
        },
        "/api/benchmarks/{benchmark_id}": {
            "get": (
                "get_benchmark_api_benchmarks__benchmark_id__get",
                None,
                [("benchmark_id", "path", True)],
            ),
        },
        "/api/benchmarks/{benchmark_id}/lifecycle": {
            "patch": (
                "update_benchmark_lifecycle_api_benchmarks__benchmark_id__lifecycle_patch",
                "BenchmarkLifecycleRequest",
                [("benchmark_id", "path", True)],
            ),
        },
        "/api/benchmark/seed-sets": {
            "get": ("list_benchmark_seed_sets_api_benchmark_seed_sets_get", None, []),
        },
        "/api/benchmark/seed-sets/{seed_set_id}": {
            "get": (
                "get_benchmark_seed_set_api_benchmark_seed_sets__seed_set_id__get",
                None,
                [("seed_set_id", "path", True)],
            ),
        },
        "/api/benchmark": {
            "post": ("start_benchmark_api_benchmark_post", "BenchmarkRequest", []),
        },
        "/api/benchmark/plan": {
            "post": ("plan_benchmark_api_benchmark_plan_post", "BenchmarkRequest", []),
        },
        "/api/benchmark/snapshots": {
            "get": (
                "list_benchmark_snapshots_api_benchmark_snapshots_get",
                None,
                [
                    ("scope", "query", False),
                    ("evaluation_set_id", "query", False),
                    ("benchmark_id", "query", False),
                    ("target_role", "query", False),
                    ("limit", "query", False),
                ],
            ),
            "post": ("create_benchmark_snapshot_api_benchmark_snapshots_post", "BenchmarkSnapshotRequest", []),
        },
        "/api/benchmark/snapshots/{snapshot_id}": {
            "get": (
                "get_benchmark_snapshot_api_benchmark_snapshots__snapshot_id__get",
                None,
                [("snapshot_id", "path", True)],
            ),
        },
        "/api/benchmark/snapshots/{snapshot_id}/export": {
            "get": (
                "export_benchmark_snapshot_api_benchmark_snapshots__snapshot_id__export_get",
                None,
                [("snapshot_id", "path", True), ("format", "query", False)],
            ),
        },
        "/api/benchmark/snapshots/{snapshot_id}/compare": {
            "get": (
                "compare_benchmark_snapshot_api_benchmark_snapshots__snapshot_id__compare_get",
                None,
                [("snapshot_id", "path", True), ("against_snapshot_id", "query", False), ("limit", "query", False)],
            ),
        },
        "/api/benchmark/views": {
            "get": (
                "list_benchmark_views_api_benchmark_views_get",
                None,
                [
                    ("scope", "query", False),
                    ("evaluation_set_id", "query", False),
                    ("benchmark_id", "query", False),
                    ("target_role", "query", False),
                    ("view_key", "query", False),
                    ("limit", "query", False),
                ],
            ),
            "post": ("save_benchmark_view_api_benchmark_views_post", "BenchmarkViewRequest", []),
        },
        "/api/benchmark/views/{view_key}": {
            "get": (
                "get_benchmark_view_api_benchmark_views__view_key__get",
                None,
                [("view_key", "path", True)],
            ),
            "delete": (
                "delete_benchmark_view_api_benchmark_views__view_key__delete",
                None,
                [("view_key", "path", True)],
            ),
        },
        "/api/benchmark/diagnostics": {
            "get": (
                "benchmark_diagnostics_api_benchmark_diagnostics_get",
                None,
                [
                    ("scope", "query", False),
                    ("evaluation_set_id", "query", False),
                    ("benchmark_id", "query", False),
                    ("target_role", "query", False),
                    ("model_id", "query", False),
                    ("model_config_hash", "query", False),
                    ("kind", "query", False),
                    ("level", "query", False),
                    ("status", "query", False),
                    ("stage", "query", False),
                    ("seed", "query", False),
                    ("limit", "query", False),
                    ("offset", "query", False),
                ],
            ),
        },
        "/api/benchmark/batch": {
            "post": ("start_benchmark_batch_api_benchmark_batch_post", "BenchmarkRequest", []),
        },
        "/api/benchmark/batch/{batch_id}": {
            "get": (
                "benchmark_batch_detail_api_benchmark_batch__batch_id__get",
                None,
                [("batch_id", "path", True)],
            ),
        },
        "/api/benchmark/batch/{batch_id}/diagnostics": {
            "get": (
                "benchmark_batch_diagnostics_api_benchmark_batch__batch_id__diagnostics_get",
                None,
                [
                    ("batch_id", "path", True),
                    ("target_role", "query", False),
                    ("kind", "query", False),
                    ("level", "query", False),
                    ("status", "query", False),
                    ("stage", "query", False),
                    ("seed", "query", False),
                ],
            ),
        },
        "/api/benchmark/batch/{batch_id}/report": {
            "get": (
                "benchmark_batch_report_api_benchmark_batch__batch_id__report_get",
                None,
                [("batch_id", "path", True), ("format", "query", False)],
            ),
        },
        "/api/benchmark/reports": {
            "get": (
                "benchmark_reports_api_benchmark_reports_get",
                None,
                [
                    ("scope", "query", False),
                    ("evaluation_set_id", "query", False),
                    ("benchmark_id", "query", False),
                    ("target_role", "query", False),
                    ("model_id", "query", False),
                    ("model_config_hash", "query", False),
                    ("status", "query", False),
                    ("limit", "query", False),
                    ("offset", "query", False),
                ],
            ),
        },
        "/api/benchmark/batch/{batch_id}/stop": {
            "post": (
                "stop_benchmark_api_benchmark_batch__batch_id__stop_post",
                None,
                [("batch_id", "path", True)],
            ),
        },
        "/api/benchmark/batch/{batch_id}/games": {
            "get": (
                "benchmark_batch_games_api_benchmark_batch__batch_id__games_get",
                None,
                [
                    ("batch_id", "path", True),
                    ("result_batch_id", "query", False),
                    ("target_role", "query", False),
                    ("status", "query", False),
                    ("seed", "query", False),
                    ("limit", "query", False),
                    ("offset", "query", False),
                ],
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
        "/api/evolution-runs/{run_id}/proposals": {
            "get": (
                "evolution_proposals_api_evolution_runs__run_id__proposals_get",
                None,
                [("run_id", "path", True)],
            ),
        },
        "/api/evolution-runs/{run_id}/trust-bundle": {
            "get": (
                "evolution_trust_bundle_api_evolution_runs__run_id__trust_bundle_get",
                None,
                [("run_id", "path", True)],
            ),
        },
        "/api/evolution-runs/{run_id}/proposals/apply-accepted": {
            "post": (
                "apply_accepted_evolution_run_proposals_api_evolution_runs__run_id__proposals_apply_accepted_post",
                None,
                [("run_id", "path", True)],
            ),
        },
        "/api/evolution-runs/{run_id}/proposals/{proposal_id}/accept": {
            "post": (
                "accept_evolution_run_proposal_api_evolution_runs__run_id__proposals__proposal_id__accept_post",
                None,
                [("run_id", "path", True), ("proposal_id", "path", True)],
            ),
        },
        "/api/evolution-runs/{run_id}/proposals/{proposal_id}/reject": {
            "post": (
                "reject_evolution_run_proposal_api_evolution_runs__run_id__proposals__proposal_id__reject_post",
                "EvolutionProposalRejectRequest",
                [("run_id", "path", True), ("proposal_id", "path", True)],
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
            "delete": (
                "delete_game_api_games__game_id__delete",
                None,
                [("game_id", "path", True), ("force", "query", False)],
            ),
            "get": (
                "get_game_api_games__game_id__get",
                None,
                [("game_id", "path", True), ("advance", "query", False), ("view", "query", False)],
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
        "/api/games/{game_id}/flow-data": {
            "get": ("get_game_flow_data_api_games__game_id__flow_data_get", None, [("game_id", "path", True)]),
        },
        "/api/games/{game_id}/human-action": {
            "get": ("get_human_action_api_games__game_id__human_action_get", None, [("game_id", "path", True)]),
        },
        "/api/games/{game_id}/phase": {
            "get": (
                "get_game_phase_detail_api_games__game_id__phase_get",
                None,
                [
                    ("game_id", "path", True),
                    ("day", "query", False),
                    ("phase", "query", False),
                    ("log_offset", "query", False),
                    ("log_limit", "query", False),
                    ("decision_offset", "query", False),
                    ("decision_limit", "query", False),
                ],
            ),
        },
        "/api/games/{game_id}/replay": {
            "get": (
                "get_game_replay_api_games__game_id__replay_get",
                None,
                [("game_id", "path", True), ("cursor", "query", False), ("limit", "query", False)],
            ),
        },
        "/api/games/{game_id}/review": {
            "get": ("get_game_review_api_games__game_id__review_get", None, [("game_id", "path", True)]),
        },
        "/api/games/{game_id}/stop": {
            "post": ("stop_game_api_games__game_id__stop_post", None, [("game_id", "path", True)]),
        },
        "/api/langfuse/verification-tasks": {
            "post": (
                "create_langfuse_verification_task_api_langfuse_verification_tasks_post",
                "LangfuseTaskRequest",
                [],
            ),
        },
        "/api/langfuse/annotation-export-tasks": {
            "post": (
                "create_langfuse_annotation_export_task_api_langfuse_annotation_export_tasks_post",
                "LangfuseTaskRequest",
                [],
            ),
        },
        "/api/langfuse/link-manifest-tasks": {
            "post": (
                "create_langfuse_link_manifest_task_api_langfuse_link_manifest_tasks_post",
                "LangfuseTaskRequest",
                [],
            ),
        },
        "/api/tasks": {
            "get": (
                "list_tasks_api_tasks_get",
                None,
                [("status", "query", False), ("limit", "query", False)],
            ),
        },
        "/api/tasks/{task_id}": {
            "get": ("get_task_api_tasks__task_id__get", None, [("task_id", "path", True)]),
        },
        "/api/tasks/{task_id}/cancel": {
            "post": ("cancel_task_api_tasks__task_id__cancel_post", None, [("task_id", "path", True)]),
        },
        "/api/tasks/{task_id}/retry": {
            "post": ("retry_task_api_tasks__task_id__retry_post", None, [("task_id", "path", True)]),
        },
        "/api/tasks/{task_id}/events": {
            "get": (
                "list_task_events_api_tasks__task_id__events_get",
                None,
                [("task_id", "path", True), ("after_event_id", "query", False)],
            ),
        },
        "/api/tasks/{task_id}/artifacts": {
            "get": (
                "list_task_artifacts_api_tasks__task_id__artifacts_get",
                None,
                [("task_id", "path", True)],
            ),
        },
        "/api/tasks/{task_id}/artifacts/{artifact_id}": {
            "get": (
                "download_task_artifact_api_tasks__task_id__artifacts__artifact_id__get",
                None,
                [("task_id", "path", True), ("artifact_id", "path", True)],
            ),
        },
        "/api/health": {
            "get": ("health_api_health_get", None, []),
        },
        "/api/health/probes/llm": {
            "post": ("probe_llm_api_health_probes_llm_post", None, [("scope", "query", False)]),
        },
        "/api/settings/model-profiles": {
            "get": ("list_model_profiles_api_settings_model_profiles_get", None, []),
            "post": (
                "create_model_profile_api_settings_model_profiles_post",
                "ModelProfileCreateRequest",
                [("x-settings-admin-token", "header", False)],
            ),
        },
        "/api/settings/model-profiles/{profile_id}": {
            "patch": (
                "update_model_profile_api_settings_model_profiles__profile_id__patch",
                "ModelProfileUpdateRequest",
                [("profile_id", "path", True), ("x-settings-admin-token", "header", False)],
            ),
            "delete": (
                "delete_model_profile_api_settings_model_profiles__profile_id__delete",
                None,
                [("profile_id", "path", True), ("x-settings-admin-token", "header", False)],
            ),
        },
        "/api/settings/model-profiles/{profile_id}/test": {
            "post": (
                "test_model_profile_api_settings_model_profiles__profile_id__test_post",
                None,
                [("profile_id", "path", True), ("x-settings-admin-token", "header", False)],
            ),
        },
        "/api/settings/model-profiles/{profile_id}/disable": {
            "post": (
                "disable_model_profile_api_settings_model_profiles__profile_id__disable_post",
                None,
                [("profile_id", "path", True), ("x-settings-admin-token", "header", False)],
            ),
        },
        "/api/leaderboards": {
            "get": (
                "leaderboards_api_leaderboards_get",
                None,
                [
                    ("scope", "query", False),
                    ("evaluation_set_id", "query", False),
                    ("target_role", "query", False),
                    ("limit", "query", False),
                ],
            ),
        },
        "/api/leaderboards/compare": {
            "get": (
                "leaderboard_compare_api_leaderboards_compare_get",
                None,
                [
                    ("scope", "query", False),
                    ("evaluation_set_id", "query", False),
                    ("target_role", "query", False),
                    ("baseline_subject_id", "query", False),
                    ("limit", "query", False),
                ],
            ),
        },
        "/api/models/leaderboard": {
            "get": (
                "model_leaderboard_api_models_leaderboard_get",
                None,
                [("evaluation_set_id", "query", False), ("limit", "query", False)],
            ),
        },
        "/api/roles": {
            "get": ("list_roles_api_roles_get", None, []),
        },
        "/api/roles/overview": {
            "get": ("roles_overview_api_roles_overview_get", None, [("evaluation_set_id", "query", False)]),
        },
        "/api/roles/{role}/leaderboard": {
            "get": (
                "role_leaderboard_api_roles__role__leaderboard_get",
                None,
                [("role", "path", True), ("evaluation_set_id", "query", False)],
            ),
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
        "/api/tts/speech/stream": {
            "post": ("tts_speech_stream_api_tts_speech_stream_post", "TtsSpeechRequest", []),
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
        "BenchmarkLifecycleRequest",
        "BenchmarkSnapshotRequest",
        "BenchmarkViewRequest",
        "EvolutionActionRequest",
        "EvolutionProposalRejectRequest",
        "EvolutionStartRequest",
        "GameStartRequest",
        "HTTPValidationError",
        "HumanActionRequest",
        "LangfuseTaskRequest",
        "ModelProfileCreateRequest",
        "ModelProfileUpdateRequest",
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
    assert evolution_start["training_games"]["default"] == 5
    assert evolution_start["training_games"]["minimum"] == 0
    assert evolution_start["training_games"]["maximum"] == 200
    assert evolution_start["battle_games"]["default"] == 4
    assert evolution_start["battle_games"]["minimum"] == 0
    assert evolution_start["battle_games"]["maximum"] == 200
    assert evolution_start["max_days"]["default"] == 5
    assert evolution_start["auto_promote"]["default"] is True

    benchmark = _schema_properties(doc, "BenchmarkRequest")
    assert benchmark["benchmark_id"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert benchmark["target_type"]["default"] == "role_version"
    assert benchmark["roles"]["items"] == {"type": "string"}
    assert {"type": "null"} in benchmark["battle_games"]["anyOf"]
    battle_games_integer = next(item for item in benchmark["battle_games"]["anyOf"] if item.get("type") == "integer")
    assert battle_games_integer["minimum"] == 0
    assert battle_games_integer["maximum"] == 200
    assert {"type": "null"} in benchmark["max_days"]["anyOf"]
    max_days_integer = next(item for item in benchmark["max_days"]["anyOf"] if item.get("type") == "integer")
    assert max_days_integer["minimum"] == 1
    assert max_days_integer["maximum"] == 100
    assert benchmark["target_versions"]["additionalProperties"] == {"type": "string"}
    assert benchmark["model_id"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert benchmark["model_config_hash"]["anyOf"] == [{"type": "string"}, {"type": "null"}]
    assert {"type": "null"} in benchmark["budget_limit_units"]["anyOf"]
    budget_limit_integer = next(
        item for item in benchmark["budget_limit_units"]["anyOf"] if item.get("type") == "integer"
    )
    assert budget_limit_integer["minimum"] == 0
    assert budget_limit_integer["maximum"] == 1_000_000
    assert {"type": "null"} in benchmark["budget_limit_cost"]["anyOf"]
    budget_limit_number = next(
        item for item in benchmark["budget_limit_cost"]["anyOf"] if item.get("type") == "number"
    )
    assert budget_limit_number["minimum"] == 0.0
    assert budget_limit_number["maximum"] == 1_000_000.0
    assert {"type": "null"} in benchmark["stop_after_budget_units"]["anyOf"]
    stop_after_integer = next(
        item for item in benchmark["stop_after_budget_units"]["anyOf"] if item.get("type") == "integer"
    )
    assert stop_after_integer["minimum"] == 0
    assert stop_after_integer["maximum"] == 1_000_000
    for key in ("langfuse_dataset_name", "langfuse_experiment_name", "langfuse_run_name"):
        assert benchmark[key]["anyOf"] == [{"type": "string", "maxLength": 240}, {"type": "null"}]

    benchmark_lifecycle = _schema_properties(doc, "BenchmarkLifecycleRequest")
    assert benchmark_lifecycle["status"]["default"] == "enabled"
    assert benchmark_lifecycle["status"]["enum"] == ["enabled", "active", "draft", "deprecated", "disabled", "archived"]
    assert benchmark_lifecycle["reason"]["default"] == ""
    assert benchmark_lifecycle["reason"]["maxLength"] == 1000

    benchmark_snapshot = _schema_properties(doc, "BenchmarkSnapshotRequest")
    assert benchmark_snapshot["title"]["default"] == ""
    assert benchmark_snapshot["title"]["maxLength"] == 200
    assert benchmark_snapshot["release_notes"]["default"] == ""
    assert benchmark_snapshot["release_notes"]["maxLength"] == 4000
    assert benchmark_snapshot["scope"]["default"] == "role_version"
    assert benchmark_snapshot["scope"]["enum"] == ["role_version", "model"]
    assert benchmark_snapshot["evaluation_set_id"]["anyOf"] == [
        {"maxLength": 240, "type": "string"},
        {"type": "null"},
    ]
    assert benchmark_snapshot["source_filter"]["additionalProperties"] is True
    assert benchmark_snapshot["view_config"]["additionalProperties"] is True
    assert benchmark_snapshot["limit"]["minimum"] == 1
    assert benchmark_snapshot["limit"]["maximum"] == 500

    benchmark_view = _schema_properties(doc, "BenchmarkViewRequest")
    assert benchmark_view["view_key"]["minLength"] == 1
    assert benchmark_view["view_key"]["maxLength"] == 300
    assert benchmark_view["name"]["default"] == "Default view"
    assert benchmark_view["name"]["maxLength"] == 200
    assert benchmark_view["scope"]["default"] == "role_version"
    assert benchmark_view["scope"]["enum"] == ["role_version", "model"]
    assert benchmark_view["evaluation_set_id"]["anyOf"] == [
        {"maxLength": 240, "type": "string"},
        {"type": "null"},
    ]
    assert benchmark_view["view_config"]["additionalProperties"] is True

    evolution_action = _schema_properties(doc, "EvolutionActionRequest")
    assert evolution_action["action"]["default"] == ""

    proposal_reject = _schema_properties(doc, "EvolutionProposalRejectRequest")
    assert proposal_reject["reason"]["default"] == ""
    assert proposal_reject["reason"]["maxLength"] == 2000
    assert proposal_reject["tags"]["maxItems"] == 12
    assert proposal_reject["tags"]["items"] == {"type": "string"}

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
        missing_game_delete_response = client.delete("/api/games/missing_contract_game")
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
        missing_benchmark_detail_response = client.get("/api/benchmark/batch/missing_contract_batch")
        missing_benchmark_games_response = client.get("/api/benchmark/batch/missing_contract_batch/games")
        missing_benchmark_diagnostics_response = client.get(
            "/api/benchmark/batch/missing_contract_batch/diagnostics"
        )

        missing_role_version_response = client.get("/api/roles/seer/versions/missing_contract_version")
        missing_role_rollback_response = client.post("/api/roles/seer/rollback/missing_contract_version")

    _assert_error_detail(missing_game_response, 404, "game not found")
    _assert_error_detail(missing_game_events_response, 404, "game not found")
    _assert_error_detail(missing_game_delete_response, 404, "game not found")
    _assert_error_detail(missing_human_action_response, 404, "game not found")
    _assert_error_detail(stale_human_action_response, 409, "game is not waiting for human input")
    _assert_validation_error(invalid_game_start_response, ["body", "max_days"], "greater_than_equal")

    _assert_error_detail(missing_evolution_response, 404, "run not found")
    _assert_error_detail(missing_evolution_action_response, 404, "run not found")
    _assert_error_detail(missing_evolution_games_response, 404, "run not found")
    _assert_validation_error(invalid_evolution_start_response, ["body", "training_games"], "less_than_equal")

    _assert_error_detail(missing_benchmark_stop_response, 404, "batch not found")
    _assert_error_detail(missing_benchmark_detail_response, 404, "batch not found")
    _assert_error_detail(missing_benchmark_games_response, 404, "batch not found")
    _assert_error_detail(missing_benchmark_diagnostics_response, 404, "batch not found")
    _assert_validation_error(invalid_benchmark_response, ["body", "max_days"], "greater_than_equal")

    _assert_error_detail(missing_role_version_response, 404, "version not found")
    _assert_error_detail(missing_role_rollback_response, 404, "version not found")


def test_release_stage_domain_error_api_contract(tmp_path: Path) -> None:
    _write_benchmark_spec(tmp_path)
    proposal = {
        "proposal_id": "p1",
        "target_file": "seer.md",
        "section": "Strategy",
        "content": "Prefer checking players who drive split votes.",
        "rationale": "Observed in training games.",
        "status": "accepted",
    }

    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        baseline = store.registry.publish_skills(
            "seer",
            {"baseline.md": _valid_seer_skill()},
            version_id="seer_baseline_contract",
            source="contract-test",
            set_as_baseline=True,
            expected_current=None,
        )
        shadow = store.registry.publish_skills(
            "seer",
            {"shadow.md": _valid_seer_skill()},
            version_id="seer_shadow_contract",
            source="contract-test",
            release_stage="shadow",
        )
        canary = store.registry.publish_skills(
            "seer",
            {"canary.md": _valid_seer_skill()},
            version_id="seer_canary_contract",
            source="contract-test",
            release_stage="canary",
        )

        start_shadow_response = client.post(
            "/api/games",
            json={"max_days": 1, "player_count": 12, "role_versions": {"seer": shadow}},
        )
        start_canary_response = client.post(
            "/api/games",
            json={"max_days": 1, "player_count": 12, "role_versions": {"seer": canary}},
        )
        benchmark_plan_shadow_response = client.post(
            "/api/benchmark/plan",
            json={
                "benchmark_id": "role-baseline-v1",
                "roles": ["seer"],
                "target_versions": {"seer": shadow},
            },
        )
        benchmark_launch_shadow_response = client.post(
            "/api/benchmark",
            json={
                "benchmark_id": "role-baseline-v1",
                "roles": ["seer"],
                "target_versions": {"seer": shadow},
            },
        )
        rollback_shadow_response = client.post(f"/api/roles/seer/rollback/{shadow}")
        rollback_canary_response = client.post(f"/api/roles/seer/rollback/{canary}")
        baseline_after_rejects = store.registry.get_baseline("seer")

        store.evolution_runs["evolve_contract_shadow_parent"] = {
            "kind": "role_evolution_run",
            "schema_version": 1,
            "run_id": "evolve_contract_shadow_parent",
            "role": "seer",
            "status": "reviewing",
            "stop_requested": False,
            "cancelled": False,
            "interrupted": False,
            "failed": False,
            "parent_hash": shadow,
            "candidate_hash": "candidate_contract_shadow_parent",
            "proposals": [proposal],
            "diff": [],
            "battle_result": {"completed": 1, "candidate_win_rate": 1.0},
        }
        evolution_parent_response = client.post(
            "/api/evolution-runs/evolve_contract_shadow_parent/actions",
            json={"action": "promote"},
        )

    _assert_domain_error(
        start_shadow_response,
        409,
        "role_version_release_stage_not_allowed",
        detail_contains="release_stage=shadow",
        kind="role_version_release_stage_not_allowed",
    )
    _assert_domain_error(
        start_canary_response,
        409,
        "role_version_release_stage_not_allowed",
        detail_contains="release_stage=canary",
        kind="role_version_release_stage_not_allowed",
    )
    _assert_domain_error(
        benchmark_plan_shadow_response,
        409,
        "benchmark_target_version_not_allowed",
        detail_contains="release_stage=shadow",
        kind="benchmark_target_version_not_allowed",
    )
    _assert_domain_error(
        benchmark_launch_shadow_response,
        409,
        "benchmark_target_version_not_allowed",
        detail_contains="release_stage=shadow",
        kind="benchmark_target_version_not_allowed",
    )
    _assert_domain_error(
        rollback_shadow_response,
        409,
        "role_version_release_stage_not_allowed",
        detail_contains="release_stage=shadow",
        kind="role_rollback_version_not_allowed",
    )
    _assert_domain_error(
        rollback_canary_response,
        409,
        "role_version_release_stage_not_allowed",
        detail_contains="release_stage=canary",
        kind="role_rollback_version_not_allowed",
    )
    _assert_domain_error(
        evolution_parent_response,
        409,
        "evolution_parent_release_stage_not_allowed",
        detail_contains="release_stage=shadow",
        kind="evolution_parent_release_stage_not_allowed",
    )
    assert baseline_after_rejects == baseline


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
    _assert_player_view_contract(payload, visible_player_ids={1})
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
    _assert_no_forbidden_contract_fields(human_action)
    _assert_no_private_night_payload(human_action)
    assert human_action["player_id"] == 1
    assert human_action["observation"]["role_state"]["private_note"] == "human only"

    assert events_response.status_code == 200
    frames = _sse_frames(events_response.text)
    _assert_sse_replay_contract(frames, visible_player_ids={1})
    assert [frame["event"] for frame in frames] == ["log", "log", "log", "log", "decision", "decision", "done"]
    assert all(frame["data"] is not None for frame in frames)
    assert "2号私密视角" not in events_response.text
    assert "god-only role table" not in events_response.text
    assert "seer_check" not in events_response.text
    assert "private_reasoning" not in events_response.text
    assert frames[-1]["data"]["players"][2]["role"] == "unknown"

    assert archive_response.status_code == 200
    archive = archive_response.json()
    _assert_public_archive_contract(archive, visible_player_ids={1})
    assert archive["review"] is None
    assert archive["decision_count"] == 2
    assert all(event.get("visibility") != "god" for event in archive["events"])
    assert "roles" not in json.dumps(archive, ensure_ascii=False)
    assert "seer" not in json.dumps(archive["events"], ensure_ascii=False)

    assert review_response.status_code == 200
    review = review_response.json()
    _assert_no_forbidden_contract_fields(review)
    _assert_no_private_night_payload(review)
    assert review["review_status"] == "暂无复盘报告"


def test_abnormal_terminal_player_contract_redacts_archive_sse_and_review(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        game_id = _seed_abnormal_terminal_player_game(store, status="failed")

        read_response = client.get(f"/api/games/{game_id}")
        archive_response = client.get(f"/api/games/{game_id}/archive")
        events_response = client.get(f"/api/games/{game_id}/events")
        review_response = client.get(f"/api/games/{game_id}/review")

    assert read_response.status_code == 200
    payload = read_response.json()
    assert payload["status"] == "failed"
    assert payload["review"] is None
    _assert_player_view_contract(payload, visible_player_ids={1})

    assert archive_response.status_code == 200
    archive = archive_response.json()
    assert archive["review"] is None
    _assert_public_archive_contract(archive, visible_player_ids={1})

    assert events_response.status_code == 200
    frames = _sse_frames(events_response.text)
    assert frames[-1]["event"] == "done"
    assert frames[-1]["data"]["status"] == "failed"
    _assert_sse_replay_contract(frames, visible_player_ids={1})

    assert review_response.status_code == 200
    review = review_response.json()
    _assert_no_forbidden_contract_fields(review)
    _assert_no_private_night_payload(review)
    _assert_review_redacted(review)
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


def test_benchmark_batch_detail_games_diagnostics_api_contract(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        _, batch_id = _seed_evolution(store)
        batch = store.evolution_batches[batch_id]
        result_batch_id = f"{batch_id}_seer"
        batch["benchmark"] = {
            "id": "role-baseline-v1",
            "version": 1,
            "target_type": "role_version",
            "evaluation_set_id": "role-baseline-v1@v1",
            "seed_set_id": "role-baseline-quick-202606",
            "config_hash": "sha256:contract",
            "spec_snapshot": {"id": "role-baseline-v1", "version": 1},
        }
        batch["target_type"] = "role_version"
        batch["run_plan"] = {"kind": "benchmark_run_plan", "total_games": 2}
        batch["results"] = [
            {
                "batch_id": result_batch_id,
                "config": {
                    "batch_id": result_batch_id,
                    "comparison_group_id": batch_id,
                    "comparison_type": "role_version",
                    "target_role": "seer",
                    "target_version_id": "seer_v1",
                    "evaluation_set_id": "role-baseline-v1@v1",
                },
                "game_count": 1,
                "attempted_game_count": 2,
                "completed": 1,
                "errored": 1,
                "games": [
                    {
                        "game_id": "bench_contract_game_001",
                        "status": "completed",
                        "seed": 260600,
                        "winner": "good",
                        "events": [{"event_type": "game_init", "message": "start"}],
                        "decisions": [{"decision_id": "d1", "action_type": "seer_check"}],
                    },
                    {
                        "game_id": "bench_contract_game_002",
                        "status": "timeout",
                        "seed": 260607,
                        "timeout": True,
                        "error": "game timeout",
                        "events": [],
                        "decisions": [],
                        "diagnostics": [
                            {
                                "kind": "timeout",
                                "stage": "game.run",
                                "level": "warning",
                                "message": "game timeout",
                            }
                        ],
                    },
                ],
                "score_summary": {
                    "game_count": 1,
                    "decision_judge_aggregate": {
                        "status": "degraded",
                        "reason": "judge timeout",
                        "metrics": {"judged": 1},
                    },
                },
                "fairness": {"is_fair": False, "reason": "missing paired seed"},
                "rankable": False,
                "rankable_reason": "completed_games 1 < required 2",
                "leaderboard_gate": {
                    "accepted": False,
                    "reason": "quality_gate_failed",
                    "metrics": {"valid_game_rate": 0.5},
                },
                "warnings": ["judge skipped one decision"],
                "diagnostics": [
                    {
                        "kind": "fairness_failed",
                        "stage": "fairness.validate",
                        "level": "warning",
                        "message": "missing paired seed",
                    }
                ],
            }
        ]
        batch["result"] = batch["results"][0]

        detail_response = client.get(f"/api/benchmark/batch/{batch_id}")
        games_response = client.get(
            f"/api/benchmark/batch/{batch_id}/games?target_role=seer&status=timeout&seed=260607&limit=1&offset=0"
        )
        games_offset_response = client.get(
            f"/api/benchmark/batch/{batch_id}/games?target_role=seer&seed=260607&limit=1&offset=1"
        )
        diagnostics_response = client.get(f"/api/benchmark/batch/{batch_id}/diagnostics")
        filtered_diagnostics_response = client.get(
            f"/api/benchmark/batch/{batch_id}/diagnostics?"
            "target_role=seer&kind=game_failure&level=warning&status=timeout&stage=game.run&seed=260607"
        )

    assert detail_response.status_code == 200
    detail = detail_response.json()
    _assert_shape(
        detail,
        {
            "kind": str,
            "schema_version": int,
            "batch": dict,
            "batch_id": str,
            "status": str,
            "benchmark": dict,
            "target_type": str,
            "roles": list,
            "run_plan": dict,
            "result_count": int,
            "results": list,
            "game_summary": dict,
            "diagnostic_summary": dict,
        },
    )
    assert detail["kind"] == "benchmark_batch_detail"
    assert detail["batch_id"] == batch_id
    assert detail["benchmark"]["id"] == "role-baseline-v1"
    assert detail["result_count"] == 1
    assert detail["results"][0]["result_batch_id"] == result_batch_id
    assert detail["results"][0]["target_role"] == "seer"
    assert detail["game_summary"]["total"] == 2
    assert detail["game_summary"]["by_status"] == {"completed": 1, "timeout": 1}
    assert detail["diagnostic_summary"]["by_kind"]["rankable_failed"] == 1

    assert games_response.status_code == 200
    games = games_response.json()
    _assert_shape(
        games,
        {
            "kind": str,
            "schema_version": int,
            "batch_id": str,
            "target_role": str,
            "status": str,
            "seed": str,
            "games": list,
            "pagination": dict,
        },
    )
    _assert_pagination(games)
    assert games["kind"] == "benchmark_batch_games"
    assert games["seed"] == "260607"
    assert games["pagination"]["total"] == 1
    game = games["games"][0]
    _assert_shape(
        game,
        {
            "batch_id": str,
            "result_batch_id": str,
            "target_type": str,
            "target_role": str,
            "index": int,
            "game_id": str,
            "id": str,
            "replay_available": bool,
            "status": str,
            "seed": int,
            "event_count": int,
            "decision_count": int,
            "diagnostic_count": int,
        },
    )
    assert game["game_id"] == "bench_contract_game_002"
    assert game["status"] == "timeout"
    assert "events" not in game
    assert "decisions" not in game

    assert games_offset_response.status_code == 200
    games_offset = games_offset_response.json()
    assert games_offset["pagination"]["total"] == 1
    assert games_offset["pagination"]["limit"] == 1
    assert games_offset["pagination"]["offset"] == 1
    assert games_offset["pagination"]["returned"] == 0
    assert games_offset["games"] == []

    assert diagnostics_response.status_code == 200
    diagnostics = diagnostics_response.json()
    _assert_shape(
        diagnostics,
        {
            "kind": str,
            "schema_version": int,
            "batch_id": str,
            "status": str,
            "benchmark": dict,
            "target_type": str,
            "diagnostics": list,
            "summary": dict,
        },
    )
    assert diagnostics["kind"] == "benchmark_batch_diagnostics"
    assert diagnostics["summary"]["by_kind"]["decision_judge_degraded"] == 1
    assert diagnostics["summary"]["by_kind"]["game_failure"] == 1
    assert diagnostics["summary"]["by_kind"]["leaderboard_gate_failed"] == 1
    assert diagnostics["summary"]["by_origin"]["game"] >= 1

    assert filtered_diagnostics_response.status_code == 200
    filtered_diagnostics = filtered_diagnostics_response.json()
    assert filtered_diagnostics["summary"]["by_kind"] == {"game_failure": 1}
    assert filtered_diagnostics["summary"]["by_level"] == {"warning": 1}
    filtered_item = filtered_diagnostics["diagnostics"][0]
    _assert_shape(
        filtered_item,
        {"kind": str, "stage": str, "level": str, "game_id": str, "seed": int, "history_game_id": str},
    )
    assert filtered_item["game_id"] == "bench_contract_game_002"
    assert filtered_item["seed"] == 260607
    assert filtered_item["history_game_id"] == "bench_contract_game_002"


def test_benchmark_batch_report_api_contract(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        _, batch_id = _seed_evolution(store)
        batch = store.evolution_batches[batch_id]
        result_batch_id = f"{batch_id}_witch"
        batch["benchmark"] = {
            "id": "role-baseline-v1",
            "version": 1,
            "name": "Role Baseline Benchmark",
            "target_type": "role_version",
            "evaluation_set_id": "role-baseline-v1@v1",
            "seed_set_id": "role-baseline-quick-202606",
            "seed_set_version": 1,
            "seed_set_config_hash": "sha256:seed-contract",
            "config_hash": "sha256:report-contract",
        }
        batch["target_type"] = "role_version"
        batch["model_runtime"] = {
            "schema_version": 1,
            "source": "request",
            "model_id": "qwen-max",
            "model_config_hash": "sha256:model-runtime",
            "hash_source": "request",
            "hash_algorithm": "sha256",
            "hash_input_schema_version": 1,
            "hash_input": {},
            "hash_provided": True,
            "externally_provided": True,
        }
        batch["model_id"] = "qwen-max"
        batch["model_config_hash"] = "sha256:model-runtime"
        batch["config"] = {
            "benchmark_id": "role-baseline-v1",
            "evaluation_set_id": "role-baseline-v1@v1",
            "seed_set_id": "role-baseline-quick-202606",
            "seed_set_version": 1,
            "seed_set_config_hash": "sha256:seed-contract",
            "benchmark_config_hash": "sha256:report-contract",
            "model_id": "qwen-max",
            "model_config_hash": "sha256:model-runtime",
            "model_runtime": batch["model_runtime"],
            "roles": ["witch"],
        }
        batch["results"] = [
            {
                "batch_id": result_batch_id,
                "config": {
                    "batch_id": result_batch_id,
                    "target_role": "witch",
                    "target_version_id": "witch_candidate_v2",
                    "evaluation_set_id": "role-baseline-v1@v1",
                    "seed_set_id": "role-baseline-quick-202606",
                    "benchmark_config_hash": "sha256:report-contract",
                },
                "game_count": 2,
                "attempted_game_count": 2,
                "completed": 1,
                "errored": 1,
                "rankable": False,
                "rankable_reason": "valid_game_rate below threshold",
                "leaderboard_gate": {
                    "accepted": False,
                    "reason": "quality_gate_failed",
                },
                "score_summary": {
                    "decision_judge_aggregate": {
                        "status": "degraded",
                        "reason": "judge timeout",
                        "top_mistake_tags": [{"tag": "low_information_gain", "count": 2}],
                    },
                },
                "games": [
                    {
                        "game_id": "bench_report_game_ok",
                        "status": "completed",
                        "seed": 260600,
                        "events": [{"event_type": "game_init"}],
                        "decisions": [{"decision_id": "d1"}],
                    },
                    {
                        "game_id": "bench_report_game_timeout",
                        "history_game_id": "history_bench_report_game_timeout",
                        "status": "timeout",
                        "seed": 260607,
                        "timeout": True,
                        "error": "game timeout",
                        "events": [],
                        "decisions": [],
                    },
                ],
            }
        ]
        batch["result"] = batch["results"][0]

        json_response = client.get(f"/api/benchmark/batch/{batch_id}/report")
        second_json_response = client.get(f"/api/benchmark/batch/{batch_id}/report")
        markdown_response = client.get(f"/api/benchmark/batch/{batch_id}/report?format=markdown")
        csv_response = client.get(f"/api/benchmark/batch/{batch_id}/report?format=csv")
        unsupported_response = client.get(f"/api/benchmark/batch/{batch_id}/report?format=xml")

    assert json_response.status_code == 200
    payload = json_response.json()
    _assert_shape(
        payload,
        {
            "kind": str,
            "schema_version": int,
            "report_id": str,
            "generated_at": str,
            "run_id": str,
            "batch_id": str,
            "status": str,
            "evaluation_set_id": str,
            "seed_set_id": str,
            "benchmark_config_hash": str,
            "suite": dict,
            "subject": dict,
            "model_runtime": dict,
            "summary": dict,
            "results": list,
            "gates": list,
            "problem_games": list,
            "diagnostics": list,
            "tags": list,
            "reproducibility": dict,
            "reproducibility_manifest": dict,
            "reproducibility_manifest_hash": str,
            "leaderboard": dict,
            "content_hash": str,
            "artifacts": dict,
        },
    )
    assert payload["kind"] == "benchmark_run_report"
    assert payload["report_id"] == f"benchmark_report:{batch_id}"
    assert payload["content_hash"].startswith("sha256:")
    assert payload["artifacts"]["content_hash"] == payload["content_hash"]
    assert payload["artifacts"]["reproducibility_manifest_hash"] == payload["reproducibility_manifest_hash"]
    assert second_json_response.status_code == 200
    second_payload = second_json_response.json()
    assert second_payload["report_id"] == payload["report_id"]
    assert second_payload["content_hash"] == payload["content_hash"]
    assert second_payload["reproducibility_manifest_hash"] == payload["reproducibility_manifest_hash"]
    assert payload["run_id"] == batch_id
    assert payload["evaluation_set_id"] == "role-baseline-v1@v1"
    assert payload["seed_set_id"] == "role-baseline-quick-202606"
    assert payload["benchmark_config_hash"] == "sha256:report-contract"
    assert payload["suite"]["benchmark_id"] == "role-baseline-v1"
    assert payload["suite"]["evaluation_set_id"] == "role-baseline-v1@v1"
    assert payload["suite"]["benchmark_config_hash"] == "sha256:report-contract"
    assert payload["subject"]["target_role"] == "witch"
    assert payload["subject"]["target_version_id"] == "witch_candidate_v2"
    assert payload["summary"]["result_count"] == 1
    assert payload["summary"]["unrankable_count"] == 1
    assert payload["summary"]["problem_game_count"] == 1
    assert payload["summary"]["diagnostic_summary"]["by_kind"]["decision_judge_degraded"] == 1
    assert payload["summary"]["diagnostic_summary"]["by_kind"]["game_failure"] == 1
    assert payload["problem_games"][0]["game_id"] == "bench_report_game_timeout"
    assert payload["problem_games"][0]["history_game_id"] == "history_bench_report_game_timeout"
    assert payload["results"][0]["rankable_label"] == "未入榜"
    assert payload["gates"][0]["status"] == "未入榜"
    assert payload["reproducibility"]["评测集"] == "role-baseline-v1@v1"
    assert payload["reproducibility"]["Config Hash"] == "sha256:report-contract"
    manifest = payload["reproducibility_manifest"]
    assert manifest["benchmark_id"] == "role-baseline-v1"
    assert manifest["benchmark_version"] == "1"
    assert manifest["evaluation_set_id"] == "role-baseline-v1@v1"
    assert manifest["benchmark_config_hash"] == "sha256:report-contract"
    assert manifest["seed_set_id"] == "role-baseline-quick-202606"
    assert manifest["seed_set_version"] == "1"
    assert manifest["seed_set_config_hash"] == "sha256:seed-contract"
    assert manifest["model_id"] == "qwen-max"
    assert manifest["model_config_hash"] == "sha256:model-runtime"
    assert manifest["content_hash"] == payload["content_hash"]
    assert manifest["artifact_hashes"]["content_hash"] == payload["content_hash"]
    assert manifest["manifest_hash"] == payload["reproducibility_manifest_hash"]
    assert verify_benchmark_reproducibility_manifest(manifest)["ok"] is True
    assert payload["tags"][0] == {"label": "low_information_gain", "count": 2}

    assert markdown_response.status_code == 200
    markdown_payload = markdown_response.json()
    assert markdown_payload["kind"] == "benchmark_run_report_export"
    assert markdown_payload["format"] == "markdown"
    assert markdown_payload["report_id"] == payload["report_id"]
    assert markdown_payload["content_hash"] == payload["content_hash"]
    assert markdown_payload["export_content_hash"].startswith("sha256:")
    assert markdown_payload["artifact_hash"] == markdown_payload["export_content_hash"]
    assert markdown_payload["reproducibility_manifest_hash"] == markdown_payload["reproducibility_manifest"]["manifest_hash"]
    assert markdown_payload["reproducibility_manifest"]["content_hash"] == payload["content_hash"]
    assert markdown_payload["reproducibility_manifest"]["artifact_hashes"]["export_content_hash"] == markdown_payload["export_content_hash"]
    assert verify_benchmark_reproducibility_manifest(markdown_payload["reproducibility_manifest"])["ok"] is True
    assert "# 评测运行报告" in markdown_payload["content"]
    assert "## 门禁摘要" in markdown_payload["content"]
    assert "role-baseline-v1@v1" in markdown_payload["content"]
    assert "bench_report_game_timeout" in markdown_payload["content"]

    assert csv_response.status_code == 200
    csv_payload = csv_response.json()
    assert csv_payload["format"] == "csv"
    assert csv_payload["report_id"] == payload["report_id"]
    assert csv_payload["content_hash"] == payload["content_hash"]
    assert csv_payload["export_content_hash"].startswith("sha256:")
    assert csv_payload["artifact_hash"] == csv_payload["export_content_hash"]
    assert csv_payload["reproducibility_manifest_hash"] == csv_payload["reproducibility_manifest"]["manifest_hash"]
    assert csv_payload["reproducibility_manifest"]["artifact_hashes"]["export_content_hash"] == csv_payload["export_content_hash"]
    assert verify_benchmark_reproducibility_manifest(csv_payload["reproducibility_manifest"])["ok"] is True
    assert csv_payload["content"].splitlines()[0] == "区段,标签,值,详情"
    assert "摘要,可入榜" in csv_payload["content"]
    assert "bench_report_game_timeout" in csv_payload["content"]

    _assert_error_detail(unsupported_response, 422, "unsupported benchmark report format")


def test_benchmark_report_history_api_contract(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        store.evolution_batches["bench_report_history_a"] = {
            "kind": "benchmark_batch",
            "schema_version": 1,
            "batch_id": "bench_report_history_a",
            "roles": ["seer"],
            "status": "completed",
            "started_at": "2026-06-08T10:00:00+08:00",
            "finished_at": "2026-06-08T10:08:00+08:00",
            "target_type": "role_version",
            "benchmark": {
                "id": "role-baseline-v1",
                "version": 1,
                "name": "Role Baseline",
                "target_type": "role_version",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "config_hash": "sha256:history-role",
            },
            "config": {
                "benchmark_id": "role-baseline-v1",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "benchmark_config_hash": "sha256:history-role",
            },
            "result": {
                "batch_id": "bench_report_history_a_seer",
                "target_role": "seer",
                "target_version_id": "seer_candidate_v1",
                "game_count": 2,
                "completed": 1,
                "errored": 1,
                "rankable": False,
                "rankable_reason": "valid_game_rate below threshold",
                "games": [
                    {"game_id": "history_game_ok", "status": "completed", "seed": 260600},
                    {"game_id": "history_game_timeout", "status": "timeout", "seed": 260607, "error": "timeout"},
                ],
            },
        }
        store.evolution_batches["bench_report_history_model"] = {
            "kind": "benchmark_batch",
            "schema_version": 1,
            "batch_id": "bench_report_history_model",
            "roles": ["seer"],
            "status": "completed",
            "started_at": "2026-06-08T09:00:00+08:00",
            "finished_at": "2026-06-08T09:06:00+08:00",
            "target_type": "model",
            "benchmark": {
                "id": "model-baseline-v1",
                "version": 1,
                "name": "Model Baseline",
                "target_type": "model",
                "evaluation_set_id": "model-baseline-v1@v1",
                "seed_set_id": "model-baseline-standard-202606",
                "config_hash": "sha256:history-model",
            },
            "config": {
                "benchmark_id": "model-baseline-v1",
                "evaluation_set_id": "model-baseline-v1@v1",
                "seed_set_id": "model-baseline-standard-202606",
                "benchmark_config_hash": "sha256:history-model",
                "model_id": "qwen-max",
                "model_config_hash": "runtime-hash-v1",
            },
            "result": {
                "batch_id": "bench_report_history_model_all",
                "model_id": "qwen-max",
                "model_config_hash": "runtime-hash-v1",
                "game_count": 1,
                "completed": 1,
                "errored": 0,
                "rankable": True,
                "games": [{"game_id": "model_history_game", "status": "completed", "seed": 260600}],
            },
        }

        role_response = client.get(
            "/api/benchmark/reports?"
            "scope=role_version&evaluation_set_id=role-baseline-v1%40v1&"
            "benchmark_id=role-baseline-v1&target_role=seer&limit=10"
        )
        model_response = client.get(
            "/api/benchmark/reports?"
            "scope=model&evaluation_set_id=model-baseline-v1%40v1&"
            "model_id=qwen-max&model_config_hash=runtime-hash-v1"
        )
        paged_response = client.get("/api/benchmark/reports?limit=1&offset=1")

    assert role_response.status_code == 200
    payload = role_response.json()
    _assert_shape(
        payload,
        {
            "kind": str,
            "schema_version": int,
            "scope": str,
            "evaluation_set_id": str,
            "benchmark_id": str,
            "target_role": str,
            "filters": dict,
            "items": list,
            "summary": dict,
            "pagination": dict,
        },
    )
    assert payload["kind"] == "benchmark_run_reports"
    assert payload["pagination"]["total"] == 1
    item = payload["items"][0]
    _assert_shape(
        item,
        {
            "kind": str,
            "schema_version": int,
            "report_id": str,
            "run_id": str,
            "batch_id": str,
            "status": str,
            "suite": dict,
            "subject": dict,
            "summary": dict,
            "evaluation_set_id": str,
            "seed_set_id": str,
            "benchmark_config_hash": str,
            "rankable_count": int,
            "unrankable_count": int,
            "problem_game_count": int,
            "diagnostic_count": int,
            "content_hash": str,
            "links": dict,
        },
    )
    assert item["kind"] == "benchmark_run_report_summary"
    assert item["report_id"] == "benchmark_report:bench_report_history_a"
    assert item["batch_id"] == "bench_report_history_a"
    assert item["evaluation_set_id"] == "role-baseline-v1@v1"
    assert item["seed_set_id"] == "role-baseline-quick-202606"
    assert item["benchmark_config_hash"] == "sha256:history-role"
    assert item["subject"]["target_role"] == "seer"
    assert item["unrankable_count"] == 1
    assert item["problem_game_count"] == 1
    assert item["diagnostic_count"] >= 1
    assert item["content_hash"].startswith("sha256:")
    assert item["links"]["markdown"].endswith("?format=markdown")
    assert payload["summary"]["total"] == 1
    assert payload["summary"]["problem_game_count"] == 1

    assert model_response.status_code == 200
    model_payload = model_response.json()
    assert model_payload["items"][0]["batch_id"] == "bench_report_history_model"
    assert model_payload["items"][0]["subject"]["model_id"] == "qwen-max"
    assert model_payload["items"][0]["subject"]["model_config_hash"] == "runtime-hash-v1"

    assert paged_response.status_code == 200
    paged = paged_response.json()
    assert paged["pagination"]["limit"] == 1
    assert paged["pagination"]["offset"] == 1
    assert paged["pagination"]["returned"] == 1


def test_benchmark_diagnostics_api_aggregates_across_runs(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        store.evolution_batches["bench_diag_a"] = {
            "kind": "benchmark_batch",
            "schema_version": 1,
            "batch_id": "bench_diag_a",
            "roles": ["seer"],
            "status": "completed",
            "started_at": "2026-06-08T09:00:00+08:00",
            "finished_at": "2026-06-08T09:10:00+08:00",
            "benchmark": {
                "id": "role-baseline-v1",
                "version": 1,
                "target_type": "role_version",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
            },
            "config": {"evaluation_set_id": "role-baseline-v1@v1"},
            "result": {
                "batch_id": "bench_diag_a_seer",
                "target_role": "seer",
                "rankable": False,
                "rankable_reason": "completed_games 1 < required 2",
                "leaderboard_gate": {
                    "accepted": False,
                    "reason": "valid_game_rate below threshold",
                },
                "score_summary": {
                    "decision_judge_aggregate": {
                        "status": "degraded",
                        "reason": "judge timeout",
                    },
                },
                "games": [
                    {
                        "game_id": "bench_diag_a_game_001",
                        "status": "timeout",
                        "seed": 260600,
                        "timeout": True,
                        "error": "game timeout",
                    }
                ],
            },
        }
        store.evolution_batches["bench_diag_b"] = {
            "kind": "benchmark_batch",
            "schema_version": 1,
            "batch_id": "bench_diag_b",
            "roles": ["seer"],
            "status": "failed",
            "started_at": "2026-06-09T09:00:00+08:00",
            "finished_at": "2026-06-09T09:05:00+08:00",
            "benchmark": {
                "id": "role-baseline-v1",
                "version": 1,
                "target_type": "role_version",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
            },
            "config": {"evaluation_set_id": "role-baseline-v1@v1"},
            "result": {
                "batch_id": "bench_diag_b_seer",
                "target_role": "seer",
                "rankable": True,
                "games": [
                    {
                        "game_id": "bench_diag_b_game_001",
                        "status": "failed",
                        "seed": 260607,
                        "error": "persist failed",
                    }
                ],
            },
        }
        store.evolution_batches["bench_diag_model"] = {
            "kind": "benchmark_batch",
            "schema_version": 1,
            "batch_id": "bench_diag_model",
            "roles": ["seer"],
            "status": "completed",
            "benchmark": {
                "id": "model-baseline-v1",
                "version": 1,
                "target_type": "model",
                "evaluation_set_id": "model-baseline-v1@v1",
            },
            "config": {
                "target_type": "model",
                "evaluation_set_id": "model-baseline-v1@v1",
                "model_id": "qwen-max",
                "model_config_hash": "runtime_hash_v1",
            },
            "result": {
                "batch_id": "bench_diag_model",
                "rankable": False,
                "rankable_reason": "model gate failed",
            },
        }

        aggregate_response = client.get(
            "/api/benchmark/diagnostics?"
            "scope=role_version&benchmark_id=role-baseline-v1&"
            "evaluation_set_id=role-baseline-v1%40v1&target_role=seer&limit=10"
        )
        game_filter_response = client.get(
            "/api/benchmark/diagnostics?"
            "scope=role_version&benchmark_id=role-baseline-v1&"
            "evaluation_set_id=role-baseline-v1%40v1&target_role=seer&"
            "kind=game_failure&level=warning&status=timeout&stage=game.run&seed=260600"
        )
        error_response = client.get(
            "/api/benchmark/diagnostics?"
            "benchmark_id=role-baseline-v1&evaluation_set_id=role-baseline-v1%40v1&"
            "target_role=seer&level=error"
        )
        model_response = client.get(
            "/api/benchmark/diagnostics?"
            "scope=model&evaluation_set_id=model-baseline-v1%40v1&model_id=qwen-max"
        )

    assert aggregate_response.status_code == 200
    aggregate = aggregate_response.json()
    _assert_shape(
        aggregate,
        {
            "kind": str,
            "schema_version": int,
            "scope": str,
            "evaluation_set_id": str,
            "benchmark_id": str,
            "target_role": str,
            "filters": dict,
            "diagnostics": list,
            "affected_runs": list,
            "affected_games": list,
            "summary": dict,
            "pagination": dict,
        },
    )
    assert aggregate["kind"] == "benchmark_diagnostics"
    assert aggregate["summary"]["by_kind"]["decision_judge_degraded"] == 1
    assert aggregate["summary"]["by_kind"]["game_failure"] == 2
    assert aggregate["summary"]["by_kind"]["leaderboard_gate_failed"] == 1
    assert aggregate["summary"]["affected_run_count"] == 2
    assert aggregate["summary"]["affected_game_count"] == 2
    assert {run["batch_id"] for run in aggregate["affected_runs"]} == {"bench_diag_a", "bench_diag_b"}
    assert {game["game_id"] for game in aggregate["affected_games"]} == {
        "bench_diag_a_game_001",
        "bench_diag_b_game_001",
    }
    assert all(game["history_game_id"] for game in aggregate["affected_games"])
    assert aggregate["affected_runs"][0]["diagnostic_summary"]["total"] >= 1

    assert game_filter_response.status_code == 200
    game_filter_payload = game_filter_response.json()
    assert game_filter_payload["summary"]["by_kind"] == {"game_failure": 1}
    assert game_filter_payload["summary"]["by_level"] == {"warning": 1}
    assert [run["batch_id"] for run in game_filter_payload["affected_runs"]] == ["bench_diag_a"]
    assert [game["game_id"] for game in game_filter_payload["affected_games"]] == ["bench_diag_a_game_001"]
    assert game_filter_payload["affected_games"][0]["seed"] == 260600
    assert game_filter_payload["affected_games"][0]["history_game_id"] == "bench_diag_a_game_001"
    game_filter_item = game_filter_payload["diagnostics"][0]
    _assert_shape(
        game_filter_item,
        {"kind": str, "stage": str, "level": str, "game_id": str, "seed": int, "history_game_id": str},
    )
    assert game_filter_item["status"] == "timeout"
    assert game_filter_item["history_game_id"] == "bench_diag_a_game_001"

    assert error_response.status_code == 200
    error_payload = error_response.json()
    assert error_payload["summary"]["by_level"] == {"error": 1}
    assert error_payload["diagnostics"][0]["kind"] == "game_failure"

    assert model_response.status_code == 200
    model_payload = model_response.json()
    assert model_payload["summary"]["by_kind"] == {"rankable_failed": 1}
    assert model_payload["diagnostics"][0]["model_id"] == "qwen-max"


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

        list_response = client.get("/api/evolution-runs?limit=1000&offset=0")
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


def test_evolution_proposal_review_api_contract(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        run_id, batch_id = _seed_evolution(store)
        run = store.evolution_runs[run_id]
        store.registry.publish_skills(
            "seer",
            {"baseline.md": _valid_seer_skill()},
            version_id="baseline_seer",
            source="fixture",
            set_as_baseline=True,
            expected_current=None,
        )
        run["parent_hash"] = "baseline_seer"
        run["candidate_hash"] = "candidate_seer"
        run["proposals"] = [
            {
                "proposal_id": "p1",
                "target_file": "seer.md",
                "action_type": "append_rule",
                "title": "Prefer decisive checks",
                "hypothesis": "Checking vote-split drivers improves seer information gain.",
                "problem_observation": "The seer checked low-impact players in vote split states.",
                "trigger_condition": {"phase": ["day1"], "public_state": ["vote_split"]},
                "expected_effect": {"primary_metric": "seer_role_score", "expected_direction": "increase"},
                "evidence_game_ids": ["training_001"],
                "counter_evidence_game_ids": [],
                "metric_targets": {"role_score_delta": 0.2},
                "preflight": {"status": "passed", "passed": True, "checks": ["hypothesis_present"]},
                "content": "Prefer decisive checks.",
                "rationale": "Candidate improved paired seed score.",
            },
            {
                "proposal_id": "p2",
                "target_file": "seer.md",
                "action_type": "append_rule",
                "title": "Seed-specific check",
                "hypothesis": "Checking seat 3 improves this candidate on seed 101.",
                "problem_observation": "One seed favored seat 3.",
                "trigger_condition": {"seed": [101]},
                "expected_effect": {"primary_metric": "seer_role_score", "expected_direction": "increase"},
                "evidence_game_ids": ["training_002"],
                "counter_evidence_game_ids": ["training_003"],
                "metric_targets": {"role_score_delta": 0.1},
                "preflight": {"status": "passed", "passed": True, "checks": ["hypothesis_present"]},
                "content": "Always check seat 3 on seed 101.",
                "rationale": "Overfit to one sample.",
            },
            {
                "proposal_id": "p3",
                "target_file": "seer.md",
                "action_type": "append_rule",
                "title": "Missing evidence",
                "hypothesis": "A broad generic rule helps seer play.",
                "problem_observation": "Too generic to bind to a decision state.",
                "trigger_condition": {},
                "expected_effect": {},
                "evidence_game_ids": [],
                "counter_evidence_game_ids": [],
                "metric_targets": {},
                "preflight": {"status": "failed", "passed": False, "reasons": ["missing_evidence"]},
                "content": "Play better.",
                "rationale": "Generic proposal should not enter candidate package.",
            },
        ]
        run["generated_proposal_ids"] = ["p1", "p2", "p3"]
        run["preflight_passed_proposal_ids"] = ["p1", "p2"]
        run["diff"] = [
            {
                "proposal_ref": "p1",
                "target_file": "seer.md",
                "action": "append_rule",
                "before": "",
                "after": "Prefer decisive checks.",
            },
            {
                "proposal_ref": "p2",
                "target_file": "seer.md",
                "action": "append_rule",
                "before": "",
                "after": "Always check seat 3 on seed 101.",
            },
        ]
        run["gate_report"] = {
            "schema_version": "trust_loop_gate_v1",
            "gate_report_id": "gate_fixture",
            "decision": "review_required",
            "promote_allowed": False,
            "review_reasons": ["proposal_overfit_risk_high"],
            "metrics": {
                "paired_valid_count": 1,
                "role_score_delta": 0.5,
                "scenario_count": 1,
                "scenario_policy_violation_count": 0,
            },
            "policy_versions": {
                "gate_policy_version": "promotion_gate_v2",
                "score_policy_version": "role_score_v1",
                "judge_policy_version": "judge_policy_v1",
                "rubric_version": "seer_rubric_v1",
            },
            "thresholds": {"min_paired_valid_seeds": 1},
            "scenario_replay": {
                "execution_mode": "contract_only",
                "status": "contract_ready",
                "verdict": "contract_ready",
                "scenario_count": 1,
                "policy_violation_count": 0,
                "contract_missing_count": 0,
            },
            "release_gate": {
                "schema_version": "promotion_gate_v2",
                "decision": "review_required",
                "review_reasons": ["proposal_overfit_risk_high"],
                "metrics": {"paired_valid_count": 1, "scenario_count": 1},
            },
            "release_decision": "review_required",
            "trust_bundle_completeness": {
                "schema_version": "trust_bundle_completeness_v1",
                "complete": False,
                "score": 0.8,
                "missing": ["accepted_proposal_ids"],
            },
            "proposal_attribution": {
                "schema_version": "proposal_attribution_report_v1",
                "status": "attribution_inconclusive",
                "reason": "ablation_not_run",
                "review_required": True,
                "package_proposal_count": 2,
                "attribution_confidence": "none",
                "budget": {
                    "enabled": True,
                    "budget_scope": "not_run",
                    "scenario_budget": 0,
                    "full_game_budget": 0,
                    "max_proposals": 2,
                    "min_paired_valid_seeds_for_attribution": 4,
                },
                "rows": [
                    {
                        "proposal_id": "p1",
                        "status": "attribution_inconclusive",
                        "requires_ablation": False,
                        "estimated_contribution": None,
                    },
                    {
                        "proposal_id": "p2",
                        "status": "attribution_inconclusive",
                        "requires_ablation": True,
                        "estimated_contribution": None,
                    },
                ],
            },
        }
        run["release_gate"] = run["gate_report"]["release_gate"]
        run["release_decision"] = "review_required"
        run["proposal_attribution_report"] = run["gate_report"]["proposal_attribution"]
        run["scenario_replay_report"] = {
            "schema_version": "scenario_replay_report_v1",
            "execution_mode": "contract_only",
            "status": "contract_ready",
            "scenario_count": 1,
            "summary": {
                "verdict": "contract_ready",
                "scenario_count": 1,
                "policy_violation_count": 0,
                "contract_missing_count": 0,
            },
        }
        run["scenario_replay_summary"] = run["scenario_replay_report"]["summary"]
        run["trust_bundle"] = {
            "schema_version": "trust_bundle_v1",
            "trust_bundle_id": f"trust_bundle_{run_id}_fixture",
            "bundle_hash": "0" * 64,
            "run_id": run_id,
            "role": "seer",
            "baseline_version": "baseline_seer",
            "candidate_version": "candidate_seer",
            "gate_report_id": "gate_fixture",
            "attribution_report_id": "attribution_fixture",
            "training_game_ids": ["training_001", "training_002"],
            "scenario_ids": ["scenario_001"],
            "battle_pair_seeds": [101],
            "proposal_ids": ["p1", "p2", "p3"],
            "generated_proposal_ids": ["p1", "p2", "p3"],
            "preflight_passed_proposal_ids": ["p1", "p2"],
            "accepted_proposal_ids": [],
            "rejected_proposal_ids": [],
            "rollback_target": "baseline_seer",
            "repro_command": "not_available: dedicated evolution replay CLI is not implemented",
            "completeness": {"complete": False, "score": 0.8, "missing": ["accepted_proposal_ids"]},
        }
        run["paired_seed_pairs"] = [
            {
                "seed": 101,
                "baseline_game_id": "baseline_101",
                "candidate_game_id": "candidate_101",
                "baseline_score": 4.0,
                "candidate_score": 4.5,
                "score_delta": 0.5,
                "winner_side": "candidate",
            }
        ]

        no_bundle_run_id = f"{run_id}_no_bundle"
        store.evolution_runs[no_bundle_run_id] = {
            "kind": "role_evolution_run",
            "schema_version": 1,
            "run_id": no_bundle_run_id,
            "role": "seer",
            "status": "reviewing",
            "started_at": "2026-01-01T00:01:00+08:00",
            "finished_at": "2026-01-01T00:02:00+08:00",
        }

        read_response = client.get(f"/api/evolution-runs/{run_id}/proposals")
        trust_response = client.get(f"/api/evolution-runs/{run_id}/trust-bundle")
        accept_response = client.post(f"/api/evolution-runs/{run_id}/proposals/p1/accept")
        reject_response = client.post(
            f"/api/evolution-runs/{run_id}/proposals/p2/reject",
            json={"reason": " overfit ", "tags": ["Seed Specific", "seed-specific", " overfit risk "]},
        )
        apply_response = client.post(f"/api/evolution-runs/{run_id}/proposals/apply-accepted")
        promote_response = client.post(f"/api/evolution-runs/{run_id}/actions", json={"action": "promote"})
        versions_response = client.get("/api/roles/seer/versions")
        version_detail_response = client.get("/api/roles/seer/versions/candidate_seer")
        batch_response = client.get(f"/api/evolution-runs/{batch_id}/proposals")
        batch_trust_response = client.get(f"/api/evolution-runs/{batch_id}/trust-bundle")
        missing_response = client.get("/api/evolution-runs/missing_contract/proposals")
        missing_trust_response = client.get("/api/evolution-runs/missing_contract/trust-bundle")
        no_bundle_trust_response = client.get(f"/api/evolution-runs/{no_bundle_run_id}/trust-bundle")
        rejected = store.registry.load_rejected("seer")

    assert read_response.status_code == 200
    read_payload = read_response.json()
    _assert_shape(
        read_payload,
        {
            "kind": str,
            "schema_version": int,
            "run_id": str,
            "role": str,
            "proposals": list,
            "generated_proposal_ids": list,
            "preflight_passed_proposal_ids": list,
            "accepted_proposal_ids": list,
            "rejected_proposal_ids": list,
            "applied_proposal_ids": list,
            "proposal_review": dict,
            "gate_report": dict,
            "release_gate": dict,
            "release_decision": str,
            "trust_bundle": dict,
            "scenario_replay_report": dict,
            "scenario_replay_summary": dict,
            "proposal_attribution_report": dict,
            "paired_seed_pairs": list,
            "paired_seeds": list,
            "run": dict,
        },
    )
    assert read_payload["run_id"] == run_id
    assert [item["proposal_id"] for item in read_payload["proposals"]] == ["p1", "p2", "p3"]
    assert read_payload["generated_proposal_ids"] == ["p1", "p2", "p3"]
    assert read_payload["preflight_passed_proposal_ids"] == ["p1", "p2"]
    assert read_payload["accepted_proposal_ids"] == []
    assert read_payload["rejected_proposal_ids"] == []
    assert read_payload["applied_proposal_ids"] == []
    assert read_payload["proposal_review"]["generated_proposal_ids"] == ["p1", "p2", "p3"]
    assert read_payload["proposal_review"]["preflight_passed_proposal_ids"] == ["p1", "p2"]
    assert read_payload["proposal_review"]["pending_proposal_ids"] == ["p1", "p2"]
    assert read_payload["proposal_review"]["generated_count"] == 3
    assert read_payload["proposal_review"]["preflight_passed_count"] == 2
    assert read_payload["proposal_review"]["pending_count"] == 2
    assert read_payload["proposal_review"]["accepted_count"] == 0
    assert read_payload["proposal_review"]["rejected_count"] == 0
    assert read_payload["proposal_review"]["applied_count"] == 0
    assert read_payload["proposal_review"]["counts"]["generated"] == 3
    assert read_payload["proposal_review"]["counts"]["preflight"] == 2
    assert read_payload["proposals"][0]["hypothesis"] == "Checking vote-split drivers improves seer information gain."
    assert read_payload["proposals"][0]["preflight"]["status"] == "passed"
    assert read_payload["proposals"][2]["preflight"]["status"] == "failed"
    assert read_payload["gate_report"]["decision"] == "review_required"
    assert read_payload["gate_report"]["raw"]["gate_report_id"] == "gate_fixture"
    assert read_payload["gate_report"]["release_gate"]["schema_version"] == "promotion_gate_v2"
    assert read_payload["gate_report"]["scenario_replay"]["execution_mode"] == "contract_only"
    assert read_payload["gate_report"]["metrics"]["scenario_count"] == 1
    assert read_payload["release_gate"]["decision"] == "review_required"
    assert read_payload["release_decision"] == "review_required"
    assert read_payload["scenario_replay_report"]["execution_mode"] == "contract_only"
    assert read_payload["scenario_replay_summary"]["scenario_count"] == 1
    assert read_payload["proposal_attribution_report"]["schema_version"] == "proposal_attribution_report_v1"
    assert read_payload["proposal_attribution_report"]["rows"][1]["estimated_contribution"] is None
    assert read_payload["gate_report"]["proposal_attribution"]["status"] == "attribution_inconclusive"
    assert read_payload["trust_bundle"]["schema_version"] == "trust_bundle_v1"
    assert read_payload["trust_bundle"]["gate_report_id"] == "gate_fixture"
    assert read_payload["trust_bundle"]["rollback_target"] == "baseline_seer"
    assert read_payload["run"]["trust_bundle"]["schema_version"] == "trust_bundle_v1"
    assert read_payload["run"]["proposal_attribution_report"]["review_required"] is True
    assert read_payload["paired_seeds"][0]["winner_side"] == "candidate"

    assert trust_response.status_code == 200
    trust_payload = trust_response.json()
    _assert_shape(
        trust_payload,
        {
            "kind": str,
            "schema_version": int,
            "trust_bundle_id": str,
            "run_id": str,
            "role": str,
            "baseline_version": str,
            "candidate_version": str,
            "bundle_hash": str,
            "gate_report_id": str,
            "attribution_report_id": str,
            "trust_bundle": dict,
        },
    )
    assert trust_payload["kind"] == "evolution_trust_bundle"
    assert trust_payload["trust_bundle_id"] == f"trust_bundle_{run_id}_fixture"
    assert trust_payload["run_id"] == run_id
    assert trust_payload["role"] == "seer"
    assert trust_payload["baseline_version"] == "baseline_seer"
    assert trust_payload["candidate_version"] == "candidate_seer"
    assert trust_payload["bundle_hash"] == "0" * 64
    assert trust_payload["gate_report_id"] == "gate_fixture"
    assert trust_payload["attribution_report_id"] == "attribution_fixture"
    assert trust_payload["trust_bundle"]["schema_version"] == "trust_bundle_v1"
    assert trust_payload["trust_bundle"]["rollback_target"] == "baseline_seer"
    assert trust_payload["trust_bundle"]["proposal_ids"] == ["p1", "p2", "p3"]
    assert trust_payload["trust_bundle"]["generated_proposal_ids"] == ["p1", "p2", "p3"]
    assert trust_payload["trust_bundle"]["preflight_passed_proposal_ids"] == ["p1", "p2"]
    assert trust_payload["trust_bundle"]["training_game_ids"] == ["training_001", "training_002"]

    assert accept_response.status_code == 200
    accepted = accept_response.json()
    assert accepted["generated_proposal_ids"] == ["p1", "p2", "p3"]
    assert accepted["preflight_passed_proposal_ids"] == ["p1", "p2"]
    assert accepted["accepted_proposal_ids"] == ["p1"]
    assert accepted["proposal_review"]["accepted_proposal_ids"] == ["p1"]
    assert accepted["proposal_review"]["pending_proposal_ids"] == ["p2"]
    assert accepted["action"]["proposal"]["status"] == "accepted"
    assert accepted["action"]["proposal"]["hypothesis"] == "Checking vote-split drivers improves seer information gain."
    assert accepted["action"]["proposal"]["preflight"]["status"] == "passed"
    assert accepted["run"]["proposal_review"]["accepted_count"] == 1

    assert reject_response.status_code == 200
    rejected_payload = reject_response.json()
    assert rejected_payload["proposal_review"]["rejected_proposal_ids"] == ["p2"]
    assert rejected_payload["rejected_proposal_ids"] == ["p2"]
    assert rejected_payload["proposal_review"]["pending_proposal_ids"] == []
    assert rejected_payload["proposal_review"]["generated_count"] == 3
    assert rejected_payload["proposal_review"]["preflight_passed_count"] == 2
    assert rejected_payload["action"]["proposal"]["status"] == "rejected"
    assert rejected_payload["action"]["proposal"]["rejection_reason"] == "overfit"
    assert rejected_payload["action"]["proposal"]["rejection_tags"] == ["seed_specific", "overfit_risk"]
    assert rejected_payload["action"]["proposal"]["rejection_metadata"]["reason"] == "overfit"
    assert rejected_payload["action"]["proposal"]["rejection_metadata"]["tags"] == ["seed_specific", "overfit_risk"]
    assert rejected_payload["action"]["proposal"]["rejection_metadata"]["review_source"] == "ui_api"
    assert rejected_payload["action"]["proposal"]["reject_buffer"]["saved"] is True
    assert rejected_payload["action"]["proposal"]["reject_buffer"]["tags"] == ["seed_specific", "overfit_risk"]
    assert rejected_payload["action"]["proposal"]["reject_buffer"]["rejection_metadata"]["tags"] == [
        "seed_specific",
        "overfit_risk",
    ]
    assert rejected_payload["action"]["review_action"]["action"] == "reject"
    assert rejected_payload["action"]["review_action"]["tags"] == ["seed_specific", "overfit_risk"]
    assert rejected_payload["action"]["rejection_metadata"]["tags"] == ["seed_specific", "overfit_risk"]
    assert rejected_payload["action"]["proposal"]["hypothesis"] == "Checking seat 3 improves this candidate on seed 101."
    assert rejected_payload["action"]["proposal"]["preflight"]["status"] == "passed"
    assert rejected_payload["proposal_review"]["review_actions"][0]["proposal_id"] == "p2"
    assert rejected_payload["proposal_review"]["review_actions"][0]["tags"] == ["seed_specific", "overfit_risk"]
    assert rejected_payload["proposal_review"]["rejection_metadata"]["p2"]["tags"] == [
        "seed_specific",
        "overfit_risk",
    ]
    assert rejected_payload["proposal_review"]["rejection_metadata_by_proposal_id"]["p2"]["reason"] == "overfit"
    assert rejected[-1]["proposal_id"] == "p2"
    assert rejected[-1]["hypothesis"] == "Checking seat 3 improves this candidate on seed 101."
    assert rejected[-1]["preflight"]["status"] == "passed"
    assert rejected[-1]["dedupe_key"]
    assert rejected[-1]["rejection_tags"] == ["seed_specific", "overfit_risk"]
    assert rejected[-1]["rejection_metadata"]["tags"] == ["seed_specific", "overfit_risk"]
    assert rejected[-1]["reject_buffer"]["rejection_metadata"]["reason"] == "overfit"

    assert apply_response.status_code == 200
    applied = apply_response.json()
    assert applied["proposal_review"]["status"] == "applied"
    assert applied["proposal_review"]["applied_proposal_ids"] == ["p1"]
    assert applied["applied_proposal_ids"] == ["p1"]
    assert applied["proposal_review"]["accepted_proposal_ids"] == ["p1"]
    assert applied["proposal_review"]["rejected_proposal_ids"] == ["p2"]
    assert applied["action"]["accepted_proposal_ids"] == ["p1"]
    assert applied["run"]["proposal_review"]["applied_proposal_ids"] == ["p1"]

    assert promote_response.status_code == 200
    promoted = promote_response.json()
    assert promoted["status"] == "promoted"
    assert promoted["published_version_id"] == "candidate_seer"
    assert promoted["published_release_stage"] == "shadow"
    assert promoted["promoted_proposal_ids"] == ["p1"]
    assert promoted["trust_bundle"]["trust_bundle_id"] == trust_payload["trust_bundle_id"]
    assert promoted["trust_bundle"]["bundle_hash"] == trust_payload["bundle_hash"]
    assert promoted["trust_bundle"]["gate_report_id"] == trust_payload["gate_report_id"]

    assert versions_response.status_code == 200
    versions = {item["version_id"]: item for item in versions_response.json()["versions"]}
    published = versions["candidate_seer"]
    assert published["provenance"]["run_id"] == run_id
    assert published["provenance"]["proposal_ids"] == ["p1"]
    assert published["provenance"]["trust_bundle_id"] == trust_payload["trust_bundle_id"]
    assert published["provenance"]["bundle_hash"] == trust_payload["bundle_hash"]
    assert published["provenance"]["gate_report_id"] == trust_payload["gate_report_id"]
    assert published["provenance"]["attribution_report_id"] == trust_payload["attribution_report_id"]

    assert version_detail_response.status_code == 200
    version_detail = version_detail_response.json()
    assert version_detail["version_id"] == "candidate_seer"
    assert version_detail["source_run_id"] == run_id
    assert version_detail["trust_bundle_id"] == trust_payload["trust_bundle_id"]
    assert version_detail["bundle_hash"] == trust_payload["bundle_hash"]
    assert version_detail["gate_report_id"] == trust_payload["gate_report_id"]
    assert version_detail["attribution_report_id"] == trust_payload["attribution_report_id"]
    assert version_detail["provenance"]["proposal_ids"] == ["p1"]

    restored_target = {
        "run_id": read_payload["run_id"],
        "proposal_id": read_payload["proposals"][0]["proposal_id"],
        "gate_report_id": trust_payload["gate_report_id"],
        "role": version_detail["role"],
        "version_id": version_detail["version_id"],
    }
    assert restored_target == {
        "run_id": run_id,
        "proposal_id": "p1",
        "gate_report_id": trust_payload["gate_report_id"],
        "role": "seer",
        "version_id": "candidate_seer",
    }

    _assert_error_detail(batch_response, 400, "batch does not support proposals; select a child run")
    _assert_error_detail(batch_trust_response, 400, "batch does not support trust bundle; select a child run")
    _assert_error_detail(missing_response, 404, "run not found")
    _assert_error_detail(missing_trust_response, 404, "run not found")
    _assert_error_detail(no_bundle_trust_response, 404, "trust bundle not found")


def test_evolution_actions_promote_reject_stop_api_contract(tmp_path: Path) -> None:
    proposal = {
        "proposal_id": "p1",
        "target_file": "seer.md",
        "section": "Strategy",
        "content": "Prefer checking players who drive split votes.",
        "rationale": "Observed in training games.",
        "status": "accepted",
    }

    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        store.registry.publish_skills(
            "seer",
            {"baseline.md": _valid_seer_skill()},
            version_id="baseline_seer",
            source="fixture",
            set_as_baseline=True,
            expected_current=None,
        )
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
            "proposals": [{**proposal, "status": "proposed"}],
            "battle_result": {"completed": 1, "candidate_win_rate": 0.0},
        }
        reject_response = client.post(
            "/api/evolution-runs/evolve_contract_reject/actions",
            json={"action": "reject"},
        )
        rejected = store.registry.load_rejected("seer")

        store.evolution_runs["evolve_contract_unreviewed_promote"] = {
            "kind": "role_evolution_run",
            "schema_version": 1,
            "run_id": "evolve_contract_unreviewed_promote",
            "role": "seer",
            "status": "reviewing",
            "stop_requested": False,
            "cancelled": False,
            "interrupted": False,
            "failed": False,
            "candidate_hash": "candidate_seer_unreviewed_contract",
            "proposals": [{**proposal, "status": "proposed"}],
            "diff": [],
            "battle_result": {"completed": 1, "candidate_win_rate": 1.0},
        }
        unreviewed_promote_response = client.post(
            "/api/evolution-runs/evolve_contract_unreviewed_promote/actions",
            json={"action": "promote"},
        )

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
            "published_release_stage": str,
            "release_stage": str,
            "promoted_version_id": (str, type(None)),
            "finished_at": str,
            "last_heartbeat_at": str,
        },
    )
    assert promoted["status"] == "promoted"
    assert promoted["candidate_hash"] == "candidate_seer_contract"
    assert promoted["published_version_id"] == "candidate_seer_contract"
    assert promoted["published_release_stage"] == "shadow"
    assert promoted["release_stage"] == "shadow"
    assert promoted["promoted_version_id"] is None

    assert versions_response.status_code == 200
    published = next(
        item for item in versions_response.json()["versions"] if item["version_id"] == "candidate_seer_contract"
    )
    assert published["is_baseline"] is False
    assert published["status"] == "shadow"
    assert published["source"] == "evolution"
    assert published["release_stage"] == "shadow"
    assert published["provenance"]["manual_action"] == "promote"
    assert published["provenance"]["release_stage"] == "shadow"
    assert published["provenance"]["run_id"] == "evolve_contract_promote"
    assert published["provenance"]["proposal_ids"] == ["p1"]

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

    _assert_domain_error(
        unreviewed_promote_response,
        409,
        "evolution_proposal_review_required",
        detail_contains="accepted or applied proposal",
        kind="evolution_proposal_review_required",
    )

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


def test_evolution_actions_baseline_promote_gate_sets_registry_baseline_contract(tmp_path: Path) -> None:
    proposal = {
        "proposal_id": "p1",
        "target_file": "seer.md",
        "section": "Strategy",
        "content": "Prefer checking players who drive split votes.",
        "rationale": "Observed in training games.",
    }
    release_gate = {
        "schema_version": "promotion_gate_v2",
        "decision": "baseline_promote",
        "reasons": ["all gates passed"],
    }
    trust_completeness = {
        "schema_version": "trust_bundle_completeness_v1",
        "complete": True,
        "score": 1.0,
        "missing": [],
    }
    trust_bundle = {
        "schema_version": "trust_bundle_v1",
        "trust_bundle_id": "trust_bundle_evolve_contract_baseline_promote",
        "bundle_hash": "c" * 64,
        "run_id": "evolve_contract_baseline_promote",
        "role": "seer",
        "baseline_version": "baseline_seer",
        "candidate_version": "candidate_seer_baseline_promote",
        "gate_report_id": "gate_evolve_contract_baseline_promote",
        "training_game_ids": ["train_1"],
        "proposal_ids": ["p1"],
        "completeness": trust_completeness,
    }

    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        store.registry.publish_skills(
            "seer",
            {"baseline.md": _valid_seer_skill()},
            version_id="baseline_seer",
            source="fixture",
            set_as_baseline=True,
            expected_current=None,
        )
        store.evolution_runs["evolve_contract_baseline_promote"] = {
            "kind": "role_evolution_run",
            "schema_version": 1,
            "run_id": "evolve_contract_baseline_promote",
            "role": "seer",
            "status": "reviewing",
            "parent_hash": "baseline_seer",
            "candidate_hash": "candidate_seer_baseline_promote",
            "proposals": [proposal],
            "diff": [],
            "applied_proposal_ids": ["p1"],
            "proposal_review": {"applied_proposal_ids": ["p1"]},
            "release_decision": "baseline_promote",
            "release_gate": release_gate,
            "gate_report": {
                "gate_report_id": "gate_evolve_contract_baseline_promote",
                "release_gate": release_gate,
                "trust_bundle_completeness": trust_completeness,
            },
            "trust_bundle": trust_bundle,
            "battle_result": {
                "completed": 3,
                "candidate_win_rate": 1.0,
                "release_decision": "baseline_promote",
                "release_gate": release_gate,
            },
        }

        promote_response = client.post(
            "/api/evolution-runs/evolve_contract_baseline_promote/actions",
            json={"action": "promote"},
        )
        versions_response = client.get("/api/roles/seer/versions")
        baseline_version = store.registry.get_baseline("seer")

    assert promote_response.status_code == 200
    promoted = promote_response.json()
    assert promoted["status"] == "promoted"
    assert promoted["published_version_id"] == "candidate_seer_baseline_promote"
    assert promoted["published_release_stage"] == "baseline"
    assert promoted["promoted_version_id"] == "candidate_seer_baseline_promote"
    assert baseline_version == "candidate_seer_baseline_promote"

    assert versions_response.status_code == 200
    versions = {item["version_id"]: item for item in versions_response.json()["versions"]}
    assert versions["baseline_seer"]["is_baseline"] is False
    published = versions["candidate_seer_baseline_promote"]
    assert published["is_baseline"] is True
    assert published["release_stage"] == "baseline"
    assert published["provenance"]["release_stage"] == "baseline"
    assert published["provenance"]["release_decision"] == "baseline_promote"
    assert published["provenance"]["trust_bundle_id"] == "trust_bundle_evolve_contract_baseline_promote"
    assert published["provenance"]["gate_report_id"] == "gate_evolve_contract_baseline_promote"


def test_evolution_actions_baseline_promote_trust_gate_error_contract(tmp_path: Path) -> None:
    proposal = {
        "proposal_id": "p1",
        "target_file": "seer.md",
        "section": "Strategy",
        "content": "Prefer checking players who drive split votes.",
        "rationale": "Observed in training games.",
    }
    release_gate = {
        "schema_version": "promotion_gate_v2",
        "decision": "baseline_promote",
        "reasons": ["all gates passed"],
    }

    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        store.registry.publish_skills(
            "seer",
            {"baseline.md": _valid_seer_skill()},
            version_id="baseline_seer",
            source="fixture",
            set_as_baseline=True,
            expected_current=None,
        )
        store.evolution_runs["evolve_contract_missing_trust"] = {
            "kind": "role_evolution_run",
            "schema_version": 1,
            "run_id": "evolve_contract_missing_trust",
            "role": "seer",
            "status": "reviewing",
            "parent_hash": "baseline_seer",
            "candidate_hash": "candidate_missing_trust",
            "proposals": [proposal],
            "applied_proposal_ids": ["p1"],
            "proposal_review": {"applied_proposal_ids": ["p1"]},
            "release_decision": "baseline_promote",
            "release_gate": release_gate,
            "gate_report": {"release_gate": release_gate},
            "battle_result": {"release_decision": "baseline_promote", "release_gate": release_gate},
        }

        response = client.post(
            "/api/evolution-runs/evolve_contract_missing_trust/actions",
            json={"action": "promote"},
        )
        store.evolution_runs["evolve_contract_incomplete_trust"] = {
            "kind": "role_evolution_run",
            "schema_version": 1,
            "run_id": "evolve_contract_incomplete_trust",
            "role": "seer",
            "status": "reviewing",
            "parent_hash": "baseline_seer",
            "candidate_hash": "candidate_incomplete_trust",
            "proposals": [proposal],
            "applied_proposal_ids": ["p1"],
            "proposal_review": {"applied_proposal_ids": ["p1"]},
            "release_decision": "baseline_promote",
            "trust_bundle": {
                "schema_version": "trust_bundle_v1",
                "trust_bundle_id": "trust_bundle_contract_incomplete",
                "run_id": "evolve_contract_incomplete_trust",
                "role": "seer",
                "baseline_version": "baseline_seer",
                "candidate_version": "candidate_incomplete_trust",
                "completeness": {
                    "schema_version": "trust_bundle_completeness_v1",
                    "complete": False,
                    "score": 0.5,
                    "missing": ["training_game_ids", "proposal_ids", "gate_report_id", "bundle_hash"],
                },
            },
            "battle_result": {"release_decision": "baseline_promote"},
        }
        incomplete_response = client.post(
            "/api/evolution-runs/evolve_contract_incomplete_trust/actions",
            json={"action": "promote"},
        )
        baseline_version = store.registry.get_baseline("seer")

    payload = _assert_domain_error(
        response,
        409,
        "evolution_trust_bundle_required",
        detail_contains="complete trust bundle",
        kind="evolution_trust_bundle_required",
    )
    diagnostic = payload["error"]["diagnostics"][0]
    assert diagnostic["release_stage"] == "baseline"
    assert diagnostic["release_decision"] == "baseline_promote"
    incomplete_payload = _assert_domain_error(
        incomplete_response,
        409,
        "evolution_trust_bundle_incomplete",
        detail_contains="training_evidence",
        kind="evolution_trust_bundle_incomplete",
    )
    incomplete_diagnostic = incomplete_payload["error"]["diagnostics"][0]
    assert incomplete_diagnostic["release_stage"] == "baseline"
    assert incomplete_diagnostic["release_decision"] == "baseline_promote"
    assert set(incomplete_diagnostic["missing"]) == {
        "training_evidence",
        "proposals",
        "gate_report",
        "trust_bundle",
    }
    assert baseline_version == "baseline_seer"


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
            "run_plan": dict,
        },
    )
    assert payload["batch_id"].startswith("bench_")
    assert payload["roles"] == ["seer"]
    _assert_task_progress(payload["progress"])
    assert payload["diagnostics"] == []
    assert payload["run_plan"]["kind"] == "benchmark_run_plan"
    assert payload["run_plan"]["total_games"] == 0


def test_benchmark_plan_api_contract(tmp_path: Path) -> None:
    _write_benchmark_spec(tmp_path)

    with _client(tmp_path) as client:
        response = client.post(
            "/api/benchmark/plan",
            json={
                "benchmark_id": "role-baseline-v1",
                "roles": ["seer"],
                "budget_limit_units": 100,
                "budget_limit_cost": 0.1,
                "stop_after_budget_units": 120,
            },
        )
        blocked_response = client.post(
            "/api/benchmark",
            json={
                "benchmark_id": "role-baseline-v1",
                "roles": ["seer"],
                "budget_limit_units": 100,
                "budget_limit_cost": 0.1,
                "stop_after_budget_units": 120,
            },
        )
        missing_response = client.post("/api/benchmark/plan", json={"benchmark_id": "missing-suite"})

    assert response.status_code == 200
    payload = response.json()
    _assert_shape(
        payload,
        {
            "kind": str,
            "schema_version": int,
            "benchmark": dict,
            "target_type": str,
            "roles": list,
            "role_count": int,
            "eval_batch_count": int,
            "game_count_per_eval_batch": int,
            "max_days": int,
            "total_games": int,
            "seed_set_id": str,
            "seed_count": int,
            "cost_tier": str,
            "judge": dict,
            "estimates": dict,
            "dry_run": bool,
            "estimated_tokens": int,
            "estimated_cost": (int, float),
            "currency": str,
            "expected_duration_seconds": int,
            "concurrency_policy": dict,
            "assumptions": list,
            "budget": dict,
            "launchable": bool,
            "warnings": list,
        },
    )
    assert payload["kind"] == "benchmark_run_plan"
    assert payload["benchmark"]["id"] == "role-baseline-v1"
    assert payload["target_type"] == "role_version"
    assert payload["roles"] == ["seer"]
    assert payload["eval_batch_count"] == 1
    assert payload["game_count_per_eval_batch"] == 3
    assert payload["total_games"] == 3
    assert payload["judge"]["enabled"] is True
    assert payload["judge"]["estimated_decisions"] == 30
    assert payload["estimates"]["game_decision_units"] == 180
    assert payload["estimates"]["judge_decision_units"] == 30
    assert payload["estimates"]["estimated_llm_call_units"] == 210
    assert payload["dry_run"] is True
    assert payload["estimated_tokens"] == 225900
    assert payload["estimated_cost"] == 0.4518
    assert payload["currency"] == "USD"
    assert payload["expected_duration_seconds"] == 97
    assert payload["concurrency_policy"]["policy"] == "bounded_sequential_eval_batches"
    assert payload["concurrency_policy"]["game_concurrency"] == 3
    assert payload["concurrency_policy"]["judge_concurrency"] == 2
    assert payload["concurrency_policy"]["expected_duration_seconds"] == 97
    assert payload["assumptions"] == [
        "game_decision_units = total_games * max_days * 12 players",
        "judge_decision_units = total_games * judge_max_decisions when decision judge is enabled",
        "estimated_tokens = game units and judge units multiplied by planner token assumptions",
        "estimated_cost uses planner token cost assumptions and is reported before launch",
    ]
    assert payload["budget"] == {
        "limit_units": 100,
        "estimated_units": 210,
        "limit_cost": 0.1,
        "estimated_cost": 0.4518,
        "estimated_tokens": 225900,
        "currency": "USD",
        "stop_after_budget_units": 120,
        "stop_after_predicted": True,
        "exceeded": {
            "value": True,
            "reasons": ["estimated_units_exceed_limit_units", "estimated_cost_exceed_limit_cost"],
            "evidence": [
                {"metric": "estimated_units", "estimated": 210, "limit": 100, "delta": 110, "unit": "llm_call_unit"},
                {"metric": "estimated_cost", "estimated": 0.4518, "limit": 0.1, "delta": 0.3518, "unit": "USD"},
            ],
        },
    }
    assert payload["launchable"] is False
    assert payload["warnings"][0]["kind"] == "budget_exceeded"
    assert payload["warnings"][0]["reasons"] == [
        "estimated_units_exceed_limit_units",
        "estimated_cost_exceed_limit_cost",
    ]
    assert payload["warnings"][0]["evidence"] == payload["budget"]["exceeded"]["evidence"]

    assert blocked_response.status_code == 422
    blocked_payload = blocked_response.json()
    _assert_shape(blocked_payload, {"detail": dict, "error": dict})
    assert blocked_payload["detail"]["message"] == "benchmark budget exceeded"
    assert blocked_payload["detail"]["estimated"] == {
        "units": 210,
        "tokens": 225900,
        "cost": 0.4518,
        "currency": "USD",
    }
    assert blocked_payload["detail"]["limit"] == {"units": 100, "cost": 0.1, "currency": "USD"}
    assert blocked_payload["detail"]["budget"] == payload["budget"]
    assert blocked_payload["error"]["code"] == "benchmark_budget_exceeded"
    assert blocked_payload["error"]["diagnostics"][0]["kind"] == "budget_exceeded"
    assert blocked_payload["error"]["diagnostics"][0]["evidence"] == payload["budget"]["exceeded"]["evidence"]

    _assert_error_detail(missing_response, 404, "benchmark not found")


def test_benchmark_list_and_detail_api_contract(tmp_path: Path) -> None:
    _write_benchmark_spec(tmp_path)
    _write_benchmark_spec_v2(tmp_path)
    _write_model_benchmark_spec(tmp_path)

    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        store.evolution_batches["bench_role_contract_old"] = {
            "kind": "benchmark_batch",
            "schema_version": 1,
            "batch_id": "bench_role_contract_old",
            "roles": ["seer"],
            "status": "completed",
            "started_at": "2026-06-08T10:00:00+08:00",
            "finished_at": "2026-06-08T10:05:00+08:00",
            "last_heartbeat_at": "2026-06-08T10:05:00+08:00",
            "current_stage": "completed",
            "benchmark": {
                "id": "role-baseline-v1",
                "target_type": "role_version",
                "evaluation_set_id": "role-baseline-v1@v1",
            },
            "config": {"evaluation_set_id": "role-baseline-v1@v1"},
            "result": {"rankable": True},
            "diagnostics": [],
        }
        store.evolution_batches["bench_role_contract_new"] = {
            "kind": "benchmark_batch",
            "schema_version": 1,
            "batch_id": "bench_role_contract_new",
            "roles": ["seer", "witch"],
            "status": "running",
            "started_at": "2026-06-09T10:00:00+08:00",
            "last_heartbeat_at": "2026-06-09T10:10:00+08:00",
            "current_stage": "judge_decisions",
            "progress": {"stage": "judge_decisions"},
            "benchmark": {
                "id": "role-baseline-v1",
                "target_type": "role_version",
                "evaluation_set_id": "role-baseline-v1@v1",
            },
            "config": {"evaluation_set_id": "role-baseline-v1@v1"},
            "results": [{"target_role": "seer"}, {"target_role": "witch"}],
            "diagnostics": [{"kind": "rankable_failed", "level": "warning"}],
        }
        store.leaderboard_entries = lambda **_: [
            {
                "scope": "role_version",
                "subject_id": "seer_candidate_v2",
                "hash": "seer_candidate_v2",
                "target_role": "seer",
                "target_version_id": "seer_candidate_v2",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "benchmark_config_hash": "sha256:contract",
                "avg_role_score": 0.7,
                "target_side_win_rate": 0.6,
                "game_count": 3,
                "games_played": 3,
                "completed_games": 3,
                "sample_size": 3,
                "paired_sample_size": 0,
                "rankable": True,
                "source_run_id": "bench_role_contract_new",
                "batch_id": "bench_role_contract_new",
                "result_batch_id": "bench_role_contract_new:seer",
                "report_id": "benchmark_report:bench_role_contract_new",
            }
        ]
        snapshot_response = client.post(
            "/api/benchmark/snapshots",
            json={
                "title": "Role contract release",
                "scope": "role_version",
                "benchmark_id": "role-baseline-v1",
                "benchmark_version": 1,
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "benchmark_config_hash": "sha256:contract",
                "target_role": "seer",
                "limit": 10,
            },
        )
        list_response = client.get("/api/benchmarks")
        detail_response = client.get("/api/benchmarks/role-baseline-v1")
        model_detail_response = client.get("/api/benchmarks/model-baseline-v1")
        missing_response = client.get("/api/benchmarks/missing-suite")

    assert snapshot_response.status_code == 200
    assert list_response.status_code == 200
    list_payload = list_response.json()
    _assert_shape(list_payload, {"items": list})
    item = next(item for item in list_payload["items"] if item["id"] == "role-baseline-v1")
    _assert_shape(
        item,
        {
            "id": str,
            "version": int,
            "suite_family_id": str,
            "suite_version": str,
            "name": str,
            "target_type": str,
            "roles": list,
            "game_count": int,
            "max_days": int,
            "evaluation_set_id": str,
            "seed_set_id": str,
            "seed_count": int,
            "seed_preview": list,
            "seed_set": dict,
            "cost_tier": str,
            "status": str,
            "launchable": bool,
            "launch_disabled_reason": str,
            "version_lineage": list,
            "version_count": int,
            "latest_version": dict,
            "latest_launchable_version": dict,
            "is_latest_version": bool,
            "is_latest_launchable_version": bool,
            "last_run": dict,
            "latest_snapshot": dict,
        },
    )
    assert item["id"] == "role-baseline-v1"
    assert item["suite_family_id"] == "role-baseline"
    assert item["suite_version"] == "v1"
    assert item["evaluation_set_id"] == "role-baseline-v1@v1"
    assert item["seed_count"] == 3
    assert item["seed_preview"] == [260600, 260607, 260619]
    assert item["seed_set"]["purpose"] == "role_leaderboard_smoke"
    assert item["seed_set"]["config_hash"].startswith("sha256:")
    assert item["status"] == "enabled"
    assert item["launchable"] is True
    assert item["launch_disabled_reason"] == ""
    assert item["version_count"] == 2
    assert [entry["id"] for entry in item["version_lineage"]] == ["role-baseline-v2", "role-baseline-v1"]
    assert item["latest_version"]["id"] == "role-baseline-v2"
    assert item["latest_version"]["status"] == "draft"
    assert item["latest_version"]["launchable"] is False
    assert item["latest_launchable_version"]["id"] == "role-baseline-v1"
    assert item["latest_launchable_version"]["evaluation_set_id"] == "role-baseline-v1@v1"
    assert item["is_latest_version"] is False
    assert item["is_latest_launchable_version"] is True
    assert item["last_run"] == {
        "batch_id": "bench_role_contract_new",
        "status": "running",
        "current_stage": "judge_decisions",
        "target_type": "role_version",
        "started_at": "2026-06-09T10:00:00+08:00",
        "finished_at": None,
        "last_heartbeat_at": "2026-06-09T10:10:00+08:00",
        "role_count": 2,
        "result_count": 2,
        "diagnostic_count": 1,
    }
    assert item["latest_snapshot"]["title"] == "Role contract release"
    assert item["latest_snapshot"]["row_count"] == 1
    assert item["latest_snapshot"]["content_hash"].startswith("sha256:")
    draft_item = next(item for item in list_payload["items"] if item["id"] == "role-baseline-v2")
    assert draft_item["suite_family_id"] == "role-baseline"
    assert draft_item["suite_version"] == "v2"
    assert draft_item["status"] == "draft"
    assert draft_item["launchable"] is False
    assert draft_item["latest_version"]["id"] == "role-baseline-v2"
    assert draft_item["latest_launchable_version"]["id"] == "role-baseline-v1"
    assert draft_item["is_latest_version"] is True
    assert draft_item["is_latest_launchable_version"] is False
    model_item = next(item for item in list_payload["items"] if item["id"] == "model-baseline-v1")
    assert model_item["target_type"] == "model"
    assert model_item["suite_family_id"] == "model-baseline"
    assert model_item["version_count"] == 1
    assert model_item["evaluation_set_id"] == "model-baseline-v1@v1"
    assert model_item["seed_set_id"] == "model-baseline-quick-202606"
    assert model_item["seed_preview"] == [270600, 270611, 270623]
    assert model_item["seed_set"]["purpose"] == "model_leaderboard_smoke"
    assert model_item["last_run"] is None
    assert model_item["latest_snapshot"] is None

    assert detail_response.status_code == 200
    detail = detail_response.json()
    _assert_shape(
        detail,
        {
            "id": str,
            "version": int,
            "suite_family_id": str,
            "suite_version": str,
            "name": str,
            "description": str,
            "target_type": str,
            "roles": list,
            "game_count": int,
            "max_days": int,
            "paired_seed": bool,
            "seed_set_id": str,
            "seed_start": int,
            "seed_count": int,
            "seed_preview": list,
            "evaluation_set_id": str,
            "config_hash": str,
            "seed_set": dict,
            "metrics": dict,
            "gates": dict,
            "judge": dict,
            "status": str,
            "launchable": bool,
            "launch_disabled_reason": str,
            "version_lineage": list,
            "version_count": int,
            "latest_version": dict,
            "latest_launchable_version": dict,
            "is_latest_version": bool,
            "is_latest_launchable_version": bool,
        },
    )
    assert detail["id"] == "role-baseline-v1"
    assert detail["suite_family_id"] == "role-baseline"
    assert detail["suite_version"] == "v1"
    assert detail["roles"] == ["seer", "witch"]
    assert detail["seed_count"] == 3
    assert detail["seed_preview"] == [260600, 260607, 260619]
    assert detail["seed_set"]["seed_count"] == 3
    assert detail["gates"]["min_completed_games"] == 1
    assert detail["config_hash"].startswith("sha256:")
    assert detail["status"] == "enabled"
    assert detail["launchable"] is True
    assert detail["launch_disabled_reason"] == ""
    assert detail["version_count"] == 2
    assert [entry["evaluation_set_id"] for entry in detail["version_lineage"]] == [
        "role-baseline-v2@v2",
        "role-baseline-v1@v1",
    ]
    assert detail["latest_version"]["id"] == "role-baseline-v2"
    assert detail["latest_launchable_version"]["id"] == "role-baseline-v1"
    assert detail["is_latest_version"] is False
    assert detail["is_latest_launchable_version"] is True

    assert model_detail_response.status_code == 200
    model_detail = model_detail_response.json()
    _assert_shape(
        model_detail,
        {
            "id": str,
            "version": int,
            "target_type": str,
            "roles": list,
            "seed_set_id": str,
            "seed_count": int,
            "seed_preview": list,
            "evaluation_set_id": str,
            "config_hash": str,
            "seed_set": dict,
            "metrics": dict,
            "gates": dict,
            "judge": dict,
            "status": str,
            "launchable": bool,
            "launch_disabled_reason": str,
        },
    )
    assert model_detail["id"] == "model-baseline-v1"
    assert model_detail["target_type"] == "model"
    assert model_detail["evaluation_set_id"] == "model-baseline-v1@v1"
    assert model_detail["seed_set"]["target_type"] == "model"
    assert model_detail["seed_preview"] == [270600, 270611, 270623]
    assert model_detail["metrics"]["primary"] == "strength_score"

    _assert_error_detail(missing_response, 404, "benchmark not found")


def test_benchmark_seed_set_registry_api_contract(tmp_path: Path) -> None:
    _write_benchmark_seed_set(
        tmp_path,
        "role-registry-a.yaml",
        """
id: role-registry-a
purpose: registry_contract
version: 1
description: Primary registry contract seed set
target_type: role_version
created_at: "2026-06-09T00:00:00+08:00"
tier: Standard
usage_boundary: release boundary only
non_overlap_group: registry-contract
immutable: false
seeds: [900001, 900002, 900003]
enabled: true
""",
    )
    _write_benchmark_seed_set(
        tmp_path,
        "role-registry-b.yaml",
        """
id: role-registry-b
purpose: registry_contract_disabled
version: 1
target_type: role_version
created_at: "2026-06-09T00:00:00+08:00"
tier: standard
usage_boundary: disabled audit boundary
non_overlap_group: registry-contract
immutable: true
seeds: [900002, 900010, 900011]
enabled: false
""",
    )
    _write_benchmark_seed_set(
        tmp_path,
        "role-registry-c.yaml",
        """
id: role-registry-c
purpose: registry_contract_other_boundary
version: 1
target_type: role_version
created_at: "2026-06-09T00:00:00+08:00"
tier: quick
usage_boundary: separate smoke boundary
non_overlap_group: registry-contract-smoke
immutable: true
seeds: [900002, 900020, 900021]
enabled: true
""",
    )

    with _client(tmp_path) as client:
        list_response = client.get("/api/benchmark/seed-sets")
        detail_response = client.get("/api/benchmark/seed-sets/role-registry-a")
        disabled_detail_response = client.get("/api/benchmark/seed-sets/role-registry-b")
        missing_response = client.get("/api/benchmark/seed-sets/missing-registry")

    assert list_response.status_code == 200
    payload = list_response.json()
    _assert_shape(
        payload,
        {
            "kind": str,
            "schema_version": int,
            "items": list,
            "summary": dict,
        },
    )
    assert payload["kind"] == "benchmark_seed_set_registry"
    assert payload["schema_version"] == 1
    items = {item["id"]: item for item in payload["items"]}
    assert {"role-registry-a", "role-registry-b", "role-registry-c"} <= set(items)
    _assert_shape(
        items["role-registry-a"],
        {
            "id": str,
            "purpose": str,
            "version": int,
            "description": str,
            "target_type": str,
            "created_at": str,
            "tier": str,
            "usage_boundary": str,
            "non_overlap_group": str,
            "immutable": bool,
            "boundary": dict,
            "seed_count": int,
            "seed_preview": list,
            "config_hash": str,
            "enabled": bool,
            "overlap_warnings": list,
        },
    )
    assert items["role-registry-a"]["tier"] == "standard"
    assert items["role-registry-a"]["immutable"] is False
    assert items["role-registry-a"]["seed_count"] == 3
    assert items["role-registry-a"]["seed_preview"] == [900001, 900002, 900003]
    assert items["role-registry-a"]["config_hash"].startswith("sha256:")
    assert items["role-registry-a"]["boundary"]["usage_boundary"] == "release boundary only"
    assert items["role-registry-a"]["boundary"]["non_overlap_group"] == "registry-contract"
    assert items["role-registry-b"]["enabled"] is False
    assert payload["summary"]["disabled"] >= 1
    assert payload["summary"]["by_non_overlap_group"]["registry-contract"] == 2

    warnings = [
        warning
        for warning in payload["summary"]["overlap_warnings"]
        if {warning["left_seed_set_id"], warning["right_seed_set_id"]} == {"role-registry-a", "role-registry-b"}
    ]
    assert len(warnings) == 1
    assert warnings[0]["kind"] == "seed_overlap"
    assert warnings[0]["non_overlap_group"] == "registry-contract"
    assert warnings[0]["overlap_count"] == 1
    assert warnings[0]["overlap_seed_preview"] == [900002]
    assert items["role-registry-a"]["overlap_warnings"] == warnings
    assert items["role-registry-b"]["overlap_warnings"] == warnings
    assert items["role-registry-c"]["overlap_warnings"] == []

    assert detail_response.status_code == 200
    detail_payload = detail_response.json()
    _assert_shape(detail_payload, {"kind": str, "schema_version": int, "item": dict})
    detail_item = detail_payload["item"]
    assert detail_item["id"] == "role-registry-a"
    assert detail_item["seeds"] == [900001, 900002, 900003]
    assert detail_item["overlap_warnings"] == warnings

    assert disabled_detail_response.status_code == 200
    disabled_item = disabled_detail_response.json()["item"]
    assert disabled_item["id"] == "role-registry-b"
    assert disabled_item["enabled"] is False
    assert disabled_item["seeds"] == [900002, 900010, 900011]

    _assert_error_detail(missing_response, 404, "benchmark seed set not found")


def test_benchmark_lifecycle_api_lists_inactive_suite_and_blocks_launch(tmp_path: Path) -> None:
    _write_benchmark_spec(tmp_path)
    _write_deprecated_benchmark_spec(tmp_path)

    with _client(tmp_path) as client:
        list_response = client.get("/api/benchmarks")
        detail_response = client.get("/api/benchmarks/role-deprecated-v1")
        plan_response = client.post(
            "/api/benchmark/plan",
            json={"benchmark_id": "role-deprecated-v1", "roles": ["seer"]},
        )
        start_response = client.post(
            "/api/benchmark",
            json={"benchmark_id": "role-deprecated-v1", "roles": ["seer"]},
        )

    assert list_response.status_code == 200
    deprecated_item = next(item for item in list_response.json()["items"] if item["id"] == "role-deprecated-v1")
    assert deprecated_item["status"] == "deprecated"
    assert deprecated_item["launchable"] is False
    assert "deprecated" in deprecated_item["launch_disabled_reason"]
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["status"] == "deprecated"
    assert detail["launchable"] is False
    assert "deprecated" in detail["launch_disabled_reason"]

    for response in (plan_response, start_response):
        payload = _assert_domain_error(
            response,
            409,
            "benchmark_suite_not_launchable",
            detail_contains="deprecated",
            kind="benchmark_suite_not_launchable",
        )
        diagnostic = payload["error"]["diagnostics"][0]
        assert diagnostic["benchmark_id"] == "role-deprecated-v1"
        assert diagnostic["status"] == "deprecated"


def test_benchmark_lifecycle_api_persists_runtime_enable_and_deprecate(tmp_path: Path) -> None:
    _write_benchmark_spec(tmp_path)

    with _client(tmp_path) as client:
        deprecate_response = client.patch(
            "/api/benchmarks/role-baseline-v1/lifecycle",
            json={"status": "deprecated", "reason": "release suite retired"},
        )
        detail_response = client.get("/api/benchmarks/role-baseline-v1")
        plan_response = client.post(
            "/api/benchmark/plan",
            json={"benchmark_id": "role-baseline-v1", "roles": ["seer"]},
        )
        missing_response = client.patch(
            "/api/benchmarks/missing-suite/lifecycle",
            json={"status": "deprecated"},
        )

    assert deprecate_response.status_code == 200
    deprecated = deprecate_response.json()
    assert deprecated["kind"] == "benchmark_suite_lifecycle"
    assert deprecated["benchmark_id"] == "role-baseline-v1"
    assert deprecated["status"] == "deprecated"
    assert deprecated["launchable"] is False
    assert deprecated["item"]["lifecycle_override"]["reason"] == "release suite retired"
    assert deprecated["item"]["lifecycle_override"]["status"] == "deprecated"
    assert deprecated["item"]["lifecycle_override"]["enabled"] is False

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["status"] == "deprecated"
    assert detail["launchable"] is False
    assert detail["lifecycle_override"]["reason"] == "release suite retired"
    _assert_domain_error(
        plan_response,
        409,
        "benchmark_suite_not_launchable",
        detail_contains="deprecated",
        kind="benchmark_suite_not_launchable",
    )
    _assert_error_detail(missing_response, 404, "benchmark not found")

    with _client(tmp_path) as restarted_client:
        restarted_detail_response = restarted_client.get("/api/benchmarks/role-baseline-v1")
        enable_response = restarted_client.patch(
            "/api/benchmarks/role-baseline-v1/lifecycle",
            json={"status": "enabled", "reason": "release suite restored"},
        )
        enabled_plan_response = restarted_client.post(
            "/api/benchmark/plan",
            json={"benchmark_id": "role-baseline-v1", "roles": ["seer"]},
        )

    assert restarted_detail_response.status_code == 200
    restarted_detail = restarted_detail_response.json()
    assert restarted_detail["status"] == "deprecated"
    assert restarted_detail["lifecycle_override"]["reason"] == "release suite retired"

    assert enable_response.status_code == 200
    enabled = enable_response.json()
    assert enabled["status"] == "enabled"
    assert enabled["launchable"] is True
    assert enabled["item"]["lifecycle_override"]["reason"] == "release suite restored"
    assert enabled_plan_response.status_code == 200
    assert enabled_plan_response.json()["launchable"] is True


def test_leaderboards_api_contract_preserves_scope_isolation_params(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        captured: dict[str, Any] = {}

        def fake_leaderboard_entries(
            *,
            scope: str | None = None,
            evaluation_set_id: str | None = None,
            target_role: str | None = None,
            limit: int = 100,
        ) -> list[dict[str, Any]]:
            captured.update(
                {
                    "scope": scope,
                    "evaluation_set_id": evaluation_set_id,
                    "target_role": target_role,
                    "limit": limit,
                }
            )
            return [
                {
                    "scope": scope,
                    "subject_id": "seer_candidate_v2",
                    "model_id": "qwen-max",
                    "model_config_hash": "runtime_hash_v1",
                    "target_role": target_role,
                    "target_version_id": "seer_candidate_v2",
                    "comparison_group_id": "bench_role",
                    "evaluation_set_id": evaluation_set_id,
                    "seed_set_id": "role-baseline-quick-202606",
                    "game_count": 3,
                    "games_played": 3,
                    "valid_game_rate": 1.0,
                    "strength_score": 0.7,
                    "avg_role_score": 0.7,
                    "rankable": True,
                    "data_sufficient": True,
                    "sample_size": 3,
                    "paired_sample_size": 0,
                    "win_rate_ci": {"low": 0.0, "high": 1.0, "level": 0.95},
                    "ci_low": 0.0,
                    "ci_high": 1.0,
                    "standard_error": 0.0,
                    "paired_delta": None,
                    "significant": False,
                    "significance_label": "差异不显著",
                    "warnings": ["low_sample", "unpaired_seeds"],
                    "summary": {},
                    "updated_at": "2026-06-09T10:00:00+08:00",
                }
            ]

        store.leaderboard_entries = fake_leaderboard_entries
        response = client.get(
            "/api/leaderboards?"
            "scope=role_version&evaluation_set_id=role-baseline-v1%40v1&target_role=seer&limit=25"
        )

    assert response.status_code == 200
    payload = response.json()
    _assert_shape(
        payload,
        {
            "kind": str,
            "schema_version": int,
            "scope": str,
            "evaluation_set_id": str,
            "target_role": str,
            "entries": list,
            "source": str,
            "source_type": str,
        },
    )
    assert captured == {
        "scope": "role_version",
        "evaluation_set_id": "role-baseline-v1@v1",
        "target_role": "seer",
        "limit": 25,
    }
    assert payload["scope"] == "role_version"
    assert payload["evaluation_set_id"] == "role-baseline-v1@v1"
    assert payload["target_role"] == "seer"
    assert payload["entries"][0]["scope"] == "role_version"
    assert payload["entries"][0]["target_role"] == "seer"
    assert payload["entries"][0]["evaluation_set_id"] == "role-baseline-v1@v1"
    _assert_leaderboard_statistics_contract(payload["entries"][0])
    assert payload["entries"][0]["significance_label"] == "差异不显著"
    assert payload["entries"][0]["warnings"] == ["low_sample", "unpaired_seeds"]


def test_leaderboard_compare_api_pins_baseline_and_reports_boundary(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        rows = [
            {
                "scope": "role_version",
                "hash": "seer_baseline",
                "subject_id": "seer_baseline",
                "target_role": "seer",
                "target_version_id": "seer_baseline",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "game_count": 40,
                "games_played": 40,
                "avg_role_score": 0.6,
                "target_role_role_weighted_score": 0.6,
                "target_side_win_rate": 0.55,
                "fallback_rate": 0.02,
                "llm_error_rate": 0.01,
                "policy_adjusted_rate": 0.03,
                "rankable": True,
                "is_baseline": True,
                "summary": {
                    "is_baseline": True,
                    "seed_metrics": [
                        {"seed": 101, "target_side_win": True},
                        {"seed": 102, "target_side_win": False},
                        {"seed": 103, "target_side_win": True},
                    ],
                },
            },
            {
                "scope": "role_version",
                "hash": "seer_candidate",
                "subject_id": "seer_candidate",
                "target_role": "seer",
                "target_version_id": "seer_candidate",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "game_count": 40,
                "games_played": 40,
                "avg_role_score": 0.66,
                "target_role_role_weighted_score": 0.66,
                "target_side_win_rate": 0.58,
                "fallback_rate": 0.03,
                "llm_error_rate": 0.01,
                "policy_adjusted_rate": 0.02,
                "rankable": True,
                "summary": {
                    "seed_metrics": [
                        {"seed": 101, "target_side_win": True},
                        {"seed": 102, "target_side_win": True},
                        {"seed": 103, "target_side_win": True},
                    ],
                },
            },
            {
                "scope": "role_version",
                "hash": "seer_mismatch",
                "subject_id": "seer_mismatch",
                "target_role": "seer",
                "target_version_id": "seer_mismatch",
                "evaluation_set_id": "role-baseline-v2@v1",
                "seed_set_id": "role-baseline-other-202606",
                "game_count": 40,
                "games_played": 40,
                "avg_role_score": 0.7,
                "target_role_role_weighted_score": 0.7,
                "target_side_win_rate": 0.62,
                "fallback_rate": 0.02,
                "llm_error_rate": 0.01,
                "policy_adjusted_rate": 0.03,
                "rankable": True,
                "summary": {},
            },
        ]
        captured: dict[str, Any] = {}

        def fake_leaderboard_entries(
            *,
            scope: str | None = None,
            evaluation_set_id: str | None = None,
            target_role: str | None = None,
            limit: int = 100,
        ) -> list[dict[str, Any]]:
            captured.update(
                {
                    "scope": scope,
                    "evaluation_set_id": evaluation_set_id,
                    "target_role": target_role,
                    "limit": limit,
                }
            )
            return [dict(row) for row in rows]

        store.leaderboard_entries = fake_leaderboard_entries
        response = client.get(
            "/api/leaderboards/compare?"
            "scope=role_version&evaluation_set_id=role-baseline-v1%40v1&"
            "target_role=seer&baseline_subject_id=seer_baseline&limit=25"
        )

    assert response.status_code == 200
    payload = response.json()
    _assert_shape(
        payload,
        {
            "kind": str,
            "schema_version": int,
            "scope": str,
            "evaluation_set_id": str,
            "target_role": str,
            "baseline_subject_id": str,
            "baseline": dict,
            "rows": list,
            "summary": dict,
        },
    )
    assert captured == {
        "scope": "role_version",
        "evaluation_set_id": "role-baseline-v1@v1",
        "target_role": "seer",
        "limit": 25,
    }
    assert payload["kind"] == "benchmark_leaderboard_compare"
    assert payload["baseline_subject_id"] == "seer_baseline"
    rows_by_subject = {row["subject_id"]: row for row in payload["rows"]}
    assert rows_by_subject["seer_baseline"]["change"] == "reference"
    assert rows_by_subject["seer_candidate"]["change"] == "improvement"
    assert abs(rows_by_subject["seer_candidate"]["delta_vs_baseline"]["score"] - 0.06) < 0.000001
    assert abs(rows_by_subject["seer_candidate"]["delta_vs_baseline"]["target_side_win_rate"] - 0.03) < 0.000001
    _assert_leaderboard_statistics_contract(rows_by_subject["seer_candidate"])
    assert rows_by_subject["seer_candidate"]["paired_sample_size"] == 3
    assert abs(rows_by_subject["seer_candidate"]["paired_delta"] - (1 / 3)) < 0.000001
    assert rows_by_subject["seer_candidate"]["significant"] is False
    assert rows_by_subject["seer_candidate"]["significance_label"] == "差异不显著"
    assert rows_by_subject["seer_candidate"]["warnings"] == ["insufficient_overlap"]
    assert rows_by_subject["seer_mismatch"]["change"] == "incomparable"
    assert rows_by_subject["seer_mismatch"]["boundary_warnings"] == [
        "evaluation_set_mismatch",
        "seed_set_mismatch",
    ]
    assert payload["summary"]["improvement_count"] == 1
    assert payload["summary"]["boundary_mismatch_count"] == 1
    assert payload["summary"]["not_significant_count"] == 1
    assert payload["summary"]["unpaired_seed_count"] >= 1
    assert payload["summary"]["insufficient_overlap_count"] >= 1


def test_leaderboard_compare_api_requires_paired_overlap_for_significance(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        rows = [
            {
                "scope": "role_version",
                "subject_id": "seer_baseline",
                "target_role": "seer",
                "target_version_id": "seer_baseline",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "game_count": 40,
                "games_played": 40,
                "avg_role_score": 0.2,
                "target_side_win_rate": 0.05,
                "rankable": True,
                "is_baseline": True,
                "summary": {
                    "is_baseline": True,
                    "seed_metrics": [{"seed": seed, "target_side_win": False} for seed in range(100, 130)],
                },
            },
            {
                "scope": "role_version",
                "subject_id": "seer_candidate",
                "target_role": "seer",
                "target_version_id": "seer_candidate",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "game_count": 40,
                "games_played": 40,
                "avg_role_score": 0.95,
                "target_side_win_rate": 0.95,
                "rankable": True,
                "summary": {
                    "seed_metrics": [{"seed": seed, "target_side_win": True} for seed in range(200, 230)],
                },
            },
        ]
        store.leaderboard_entries = lambda **_: [dict(row) for row in rows]
        response = client.get(
            "/api/leaderboards/compare?"
            "scope=role_version&evaluation_set_id=role-baseline-v1%40v1&"
            "target_role=seer&baseline_subject_id=seer_baseline"
        )

    assert response.status_code == 200
    candidate = next(row for row in response.json()["rows"] if row["subject_id"] == "seer_candidate")
    _assert_leaderboard_statistics_contract(candidate)
    assert candidate["paired_sample_size"] == 0
    assert candidate["paired_delta"] is None
    assert candidate["significant"] is False
    assert candidate["significance_label"] == "差异不显著"
    assert candidate["warnings"] == ["insufficient_overlap"]


def test_leaderboard_compare_api_pairs_duplicate_seeds_by_game_index(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        rows = [
            {
                "scope": "role_version",
                "subject_id": "seer_baseline",
                "target_role": "seer",
                "target_version_id": "seer_baseline",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "game_count": 40,
                "games_played": 40,
                "avg_role_score": 0.5,
                "target_side_win_rate": 0.5,
                "rankable": True,
                "is_baseline": True,
                "summary": {
                    "is_baseline": True,
                    "seed_metrics": [
                        {"seed": 777, "game_index": 1, "target_side_win": True},
                        {"seed": 777, "game_index": 2, "target_side_win": False},
                    ],
                },
            },
            {
                "scope": "role_version",
                "subject_id": "seer_candidate",
                "target_role": "seer",
                "target_version_id": "seer_candidate",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "game_count": 40,
                "games_played": 40,
                "avg_role_score": 0.7,
                "target_side_win_rate": 0.75,
                "rankable": True,
                "summary": {
                    "seed_metrics": [
                        {"seed": 777, "game_index": 1, "target_side_win": True},
                        {"seed": 777, "game_index": 2, "target_side_win": True},
                    ],
                },
            },
        ]
        store.leaderboard_entries = lambda **_: [dict(row) for row in rows]
        response = client.get(
            "/api/leaderboards/compare?"
            "scope=role_version&evaluation_set_id=role-baseline-v1%40v1&"
            "target_role=seer&baseline_subject_id=seer_baseline"
        )

    assert response.status_code == 200
    candidate = next(row for row in response.json()["rows"] if row["subject_id"] == "seer_candidate")
    _assert_leaderboard_statistics_contract(candidate)
    assert candidate["paired_sample_size"] == 2
    assert candidate["paired_delta"] == 0.5
    assert candidate["significant"] is False
    assert candidate["warnings"] == ["insufficient_overlap"]


def test_leaderboard_compare_api_reports_unrankable_evidence_outside_rows(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        rows = [
            {
                "scope": "model",
                "hash": "runtime_hash_v1",
                "subject_id": "runtime_hash_v1",
                "model_id": "qwen-max",
                "model_config_hash": "runtime_hash_v1",
                "evaluation_set_id": "model-baseline-v1@v1",
                "seed_set_id": "model-baseline-202606",
                "comparison_group_id": "bench-model-release-20260609",
                "batch_id": "bench-model-release-20260609",
                "result_batch_id": "result-qwen-max",
                "game_count": 40,
                "games_played": 40,
                "valid_game_rate": 1.0,
                "strength_score": 0.72,
                "avg_role_score": 0.72,
                "target_side_win_rate": 0.61,
                "fallback_rate": 0.02,
                "llm_error_rate": 0.01,
                "policy_adjusted_rate": 0.03,
                "rankable": True,
                "is_baseline": True,
                "summary": {
                    "is_baseline": True,
                    "seed_metrics": [
                        {"seed": 101, "target_side_win": True},
                        {"seed": 102, "target_side_win": False},
                        {"seed": 103, "target_side_win": True},
                    ],
                },
            },
            {
                "scope": "model",
                "hash": "runtime_hash_v2",
                "subject_id": "runtime_hash_v2",
                "model_id": "qwen-plus",
                "model_config_hash": "runtime_hash_v2",
                "evaluation_set_id": "model-baseline-v1@v1",
                "seed_set_id": "model-baseline-202606",
                "comparison_group_id": "bench-model-release-20260609",
                "batch_id": "bench-model-release-20260609",
                "result_batch_id": "result-qwen-plus",
                "game_count": 40,
                "games_played": 12,
                "valid_game_rate": 0.3,
                "strength_score": 0.4,
                "avg_role_score": 0.4,
                "target_side_win_rate": 0.42,
                "fallback_rate": 0.2,
                "llm_error_rate": 0.08,
                "policy_adjusted_rate": 0.12,
                "rankable": False,
                "rankable_reason": "completed_games 12 < required 30",
                "summary": {"rankable_reason": "completed_games 12 < required 30"},
            },
        ]

        store.leaderboard_entries = lambda **_: [dict(row) for row in rows]
        response = client.get(
            "/api/leaderboards/compare?"
            "scope=model&evaluation_set_id=model-baseline-v1%40v1&baseline_subject_id=runtime_hash_v1"
        )

    assert response.status_code == 200
    payload = response.json()
    _assert_shape(
        payload,
        {
            "kind": str,
            "schema_version": int,
            "scope": str,
            "evaluation_set_id": str,
            "baseline_subject_id": str,
            "baseline": dict,
            "rows": list,
            "unrankable_evidence": list,
            "summary": dict,
        },
    )
    assert [row["subject_id"] for row in payload["rows"]] == ["runtime_hash_v1"]
    assert payload["unrankable_evidence"][0]["subject_id"] == "runtime_hash_v2"
    assert payload["unrankable_evidence"][0]["reason"] == "completed_games 12 < required 30"
    assert payload["unrankable_evidence"][0]["completed_games"] == 12
    assert payload["unrankable_evidence"][0]["total_games"] == 40
    assert payload["unrankable_evidence"][0]["valid_game_rate"] == 0.3
    assert payload["unrankable_evidence"][0]["batch_id"] == "bench-model-release-20260609"
    assert payload["summary"]["row_count"] == 1
    assert payload["summary"]["rankable_count"] == 1
    assert payload["summary"]["unrankable_count"] == 1
    assert payload["summary"]["unrankable_evidence_count"] == 1


def test_leaderboard_compare_api_recovers_batch_gate_failures_as_unrankable_evidence(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        rankable_rows = [
            {
                "scope": "model",
                "hash": "runtime_hash_v1",
                "subject_id": "runtime_hash_v1",
                "model_id": "qwen-max",
                "model_config_hash": "runtime_hash_v1",
                "evaluation_set_id": "model-baseline-v1@v1",
                "seed_set_id": "model-baseline-202606",
                "comparison_group_id": "bench-model-release-20260609",
                "batch_id": "bench-model-release-20260609",
                "result_batch_id": "result-qwen-max",
                "game_count": 40,
                "games_played": 40,
                "valid_game_rate": 1.0,
                "strength_score": 0.72,
                "avg_role_score": 0.72,
                "target_side_win_rate": 0.61,
                "rankable": True,
                "is_baseline": True,
                "summary": {
                    "is_baseline": True,
                    "seed_metrics": [
                        {"seed": 101, "target_side_win": True},
                        {"seed": 102, "target_side_win": False},
                        {"seed": 103, "target_side_win": True},
                    ],
                },
            }
        ]
        store.leaderboard_entries = lambda **_: [dict(row) for row in rankable_rows]
        store.evolution_batches["bench_model_gate_failed"] = {
            "kind": "benchmark_batch",
            "schema_version": 1,
            "batch_id": "bench_model_gate_failed",
            "status": "completed",
            "target_type": "model",
            "finished_at": "2026-06-09T11:00:00+08:00",
            "benchmark": {
                "id": "model-baseline-v1",
                "version": 1,
                "target_type": "model",
                "evaluation_set_id": "model-baseline-v1@v1",
                "seed_set_id": "model-baseline-202606",
                "config_hash": "sha256:model-release",
            },
            "config": {
                "target_type": "model",
                "model_id": "qwen-plus",
                "model_config_hash": "runtime_hash_v2",
                "evaluation_set_id": "model-baseline-v1@v1",
                "seed_set_id": "model-baseline-202606",
            },
            "results": [
                {
                    "batch_id": "bench_model_gate_failed_result",
                    "model_id": "qwen-plus",
                    "model_config_hash": "runtime_hash_v2",
                    "game_count": 40,
                    "completed": 12,
                    "valid_game_rate": 0.3,
                    "rankable": False,
                    "rankable_reason": "completed_games 12 < required 30",
                    "leaderboard_gate": {
                        "accepted": False,
                        "reason": "completed_games 12 < required 30",
                        "metrics": {"completed_games": 12, "valid_game_rate": 0.3},
                    },
                    "score_summary": {
                        "avg_role_score": 0.4,
                        "strength_score": 0.4,
                        "valid_game_rate": 0.3,
                    },
                }
            ],
        }
        response = client.get(
            "/api/leaderboards/compare?"
            "scope=model&evaluation_set_id=model-baseline-v1%40v1&baseline_subject_id=runtime_hash_v1"
        )

    assert response.status_code == 200
    payload = response.json()
    assert [row["subject_id"] for row in payload["rows"]] == ["runtime_hash_v1"]
    assert payload["summary"]["row_count"] == 1
    assert payload["summary"]["unrankable_evidence_count"] == 1
    evidence = payload["unrankable_evidence"][0]
    assert evidence["source"] == "benchmark_batch"
    assert evidence["subject_id"] == "runtime_hash_v2"
    assert evidence["model_id"] == "qwen-plus"
    assert evidence["reason"] == "completed_games 12 < required 30"
    assert evidence["completed_games"] == 12
    assert evidence["total_games"] == 40
    assert evidence["valid_game_rate"] == 0.3
    assert evidence["batch_id"] == "bench_model_gate_failed"
    assert evidence["result_batch_id"] == "bench_model_gate_failed_result"


def _benchmark_snapshot_release_row(*, drop: tuple[str, ...] = (), **overrides: Any) -> dict[str, Any]:
    row = {
        "scope": "role_version",
        "hash": "seer_candidate_v2",
        "subject_id": "seer_candidate_v2",
        "target_role": "seer",
        "target_version_id": "seer_candidate_v2",
        "comparison_group_id": "bench_role",
        "evaluation_set_id": "role-baseline-v1@v1",
        "seed_set_id": "role-baseline-quick-202606",
        "benchmark_config_hash": "sha256:contract",
        "game_count": 3,
        "games_played": 3,
        "valid_game_rate": 1.0,
        "strength_score": 0.7,
        "avg_role_score": 0.7,
        "target_role_role_weighted_score": 0.7,
        "rankable": True,
        "data_sufficient": True,
        "batch_id": "bench_snapshot_run_a",
        "source_run_id": "bench_snapshot_run_a",
        "result_batch_id": "bench_snapshot_run_a_seer",
        "report_id": "benchmark_report:bench_snapshot_run_a",
        "summary": {"source": "release-gate-contract"},
        "updated_at": "2026-06-09T10:00:00+08:00",
    }
    for key in drop:
        row.pop(key, None)
    row.update(overrides)
    return row


def _benchmark_snapshot_release_request(*, drop: tuple[str, ...] = (), **overrides: Any) -> dict[str, Any]:
    request = {
        "title": "Role release gate contract",
        "release_notes": "formal release gate contract",
        "scope": "role_version",
        "benchmark_id": "role-baseline-v1",
        "benchmark_version": 1,
        "evaluation_set_id": "role-baseline-v1@v1",
        "seed_set_id": "role-baseline-quick-202606",
        "benchmark_config_hash": "sha256:contract",
        "target_role": "seer",
        "source_filter": {"rankable": "rankable"},
        "view_config": {"columns": ["score", "win_rate"]},
        "limit": 25,
    }
    for key in drop:
        request.pop(key, None)
    request.update(overrides)
    return request


def _post_benchmark_snapshot_with_rows(
    client: TestClient,
    rows: list[dict[str, Any]],
    request: dict[str, Any],
) -> Any:
    store = client.app.state.backend_store
    store.leaderboard_entries = lambda **_: [dict(row) for row in rows]
    return client.post("/api/benchmark/snapshots", json=request)


def test_benchmark_snapshot_api_rejects_formal_release_without_seed_set(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = _post_benchmark_snapshot_with_rows(
            client,
            [_benchmark_snapshot_release_row()],
            _benchmark_snapshot_release_request(drop=("seed_set_id",)),
        )

    _assert_snapshot_release_gate_error(response, "seed_set_id")


def test_benchmark_snapshot_api_rejects_formal_release_without_config_hash(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = _post_benchmark_snapshot_with_rows(
            client,
            [_benchmark_snapshot_release_row()],
            _benchmark_snapshot_release_request(drop=("benchmark_config_hash",)),
        )

    _assert_snapshot_release_gate_error(response, "benchmark_config_hash")


def test_benchmark_snapshot_api_rejects_formal_release_without_row_config_hash(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = _post_benchmark_snapshot_with_rows(
            client,
            [
                _benchmark_snapshot_release_row(
                    drop=("benchmark_config_hash",),
                    summary={"source": "missing-row-hash"},
                )
            ],
            _benchmark_snapshot_release_request(),
        )

    _assert_snapshot_release_gate_error(response, "snapshot rows must include benchmark_config_hash")


def test_benchmark_snapshot_api_rejects_model_release_without_runtime_identity(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = _post_benchmark_snapshot_with_rows(
            client,
            [
                _benchmark_snapshot_release_row(
                    scope="model",
                    hash="runtime_hash_v1",
                    subject_id="runtime_hash_v1",
                    target_role=None,
                    target_version_id=None,
                    model_id="qwen-max",
                    model_config_hash="",
                    evaluation_set_id="model-baseline-v1@v1",
                    seed_set_id="model-baseline-quick-202606",
                    benchmark_config_hash="sha256:model-contract",
                    result_batch_id="bench_snapshot_model_runtime",
                    summary={
                        "source": "model-release",
                        "scope": "model",
                        "benchmark_config_hash": "sha256:model-contract",
                    },
                )
            ],
            _benchmark_snapshot_release_request(
                scope="model",
                benchmark_id="model-baseline-v1",
                evaluation_set_id="model-baseline-v1@v1",
                seed_set_id="model-baseline-quick-202606",
                benchmark_config_hash="sha256:model-contract",
                target_role=None,
            ),
        )

    _assert_snapshot_release_gate_error(response, "model_config_hash")


def test_benchmark_snapshot_api_rejects_formal_release_without_source_run(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = _post_benchmark_snapshot_with_rows(
            client,
            [_benchmark_snapshot_release_row(drop=("batch_id", "run_id", "source_run_id"))],
            _benchmark_snapshot_release_request(),
        )

    _assert_snapshot_release_gate_error(response, "source_run_id")


def test_benchmark_snapshot_api_rejects_formal_release_without_source_report(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = _post_benchmark_snapshot_with_rows(
            client,
            [_benchmark_snapshot_release_row(drop=("report_id", "source_report_id"))],
            _benchmark_snapshot_release_request(),
        )

    _assert_snapshot_release_gate_error(response, "report_id")


def test_benchmark_snapshot_api_rejects_formal_release_without_result_batch(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = _post_benchmark_snapshot_with_rows(
            client,
            [_benchmark_snapshot_release_row(drop=("result_batch_id",))],
            _benchmark_snapshot_release_request(),
        )

    _assert_snapshot_release_gate_error(response, "result_batch_id")


def test_benchmark_snapshot_api_rejects_formal_release_with_mixed_boundary_rows(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = _post_benchmark_snapshot_with_rows(
            client,
            [
                _benchmark_snapshot_release_row(),
                _benchmark_snapshot_release_row(
                    hash="seer_candidate_v3",
                    subject_id="seer_candidate_v3",
                    target_version_id="seer_candidate_v3",
                    seed_set_id="role-baseline-other-seeds",
                    benchmark_config_hash="sha256:different-config",
                    source_run_id="bench_snapshot_run_b",
                    batch_id="bench_snapshot_run_b",
                    result_batch_id="bench_snapshot_run_b_seer",
                    report_id="benchmark_report:bench_snapshot_run_b",
                ),
            ],
            _benchmark_snapshot_release_request(),
        )

    _assert_snapshot_release_gate_error(response, "seed_set_id")


def test_benchmark_snapshot_api_applies_rankable_source_filter_before_freezing(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        response = _post_benchmark_snapshot_with_rows(
            client,
            [
                _benchmark_snapshot_release_row(),
                _benchmark_snapshot_release_row(
                    hash="seer_unrankable_v1",
                    subject_id="seer_unrankable_v1",
                    target_version_id="seer_unrankable_v1",
                    rankable=False,
                    data_sufficient=False,
                    source_run_id="bench_snapshot_run_b",
                    batch_id="bench_snapshot_run_b",
                    result_batch_id="bench_snapshot_run_b_seer",
                    report_id="benchmark_report:bench_snapshot_run_b",
                    summary={"source": "unrankable", "benchmark_config_hash": "sha256:contract"},
                ),
            ],
            _benchmark_snapshot_release_request(source_filter={"rankable": "rankable"}),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source_filter"] == {"rankable": "rankable"}
    assert payload["summary"]["source_filter_applied"] == {"rankable": "rankable"}
    assert payload["row_count"] == 1
    assert payload["rankable_count"] == 1
    assert payload["unrankable_count"] == 0
    assert [row["subject_id"] for row in payload["rows"]] == ["seer_candidate_v2"]
    assert payload["linked_run_ids"] == ["bench_snapshot_run_a"]
    assert payload["release_manifest"]["source"]["source_filter_applied"] == {"rankable": "rankable"}


def test_benchmark_snapshot_api_freezes_current_leaderboard_rows(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        current_rows = [
            {
                "scope": "role_version",
                "hash": "seer_candidate_v2",
                "subject_id": "seer_candidate_v2",
                "target_role": "seer",
                "target_version_id": "seer_candidate_v2",
                "comparison_group_id": "bench_role",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "benchmark_config_hash": "sha256:contract",
                "game_count": 3,
                "games_played": 3,
                "valid_game_rate": 1.0,
                "strength_score": 0.7,
                "avg_role_score": 0.7,
                "target_role_role_weighted_score": 0.7,
                "rankable": True,
                "data_sufficient": True,
                "batch_id": "bench_snapshot_run_a",
                "source_run_id": "bench_snapshot_run_a",
                "result_batch_id": "bench_snapshot_run_a_seer",
                "report_id": "benchmark_report:bench_snapshot_run_a",
                "summary": {"source": "first", "benchmark_config_hash": "sha256:contract"},
                "updated_at": "2026-06-09T10:00:00+08:00",
            },
            {
                "scope": "role_version",
                "hash": "seer_unrankable_v1",
                "subject_id": "seer_unrankable_v1",
                "target_role": "seer",
                "target_version_id": "seer_unrankable_v1",
                "comparison_group_id": "bench_role",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "benchmark_config_hash": "sha256:contract",
                "game_count": 3,
                "games_played": 1,
                "valid_game_rate": 0.33,
                "strength_score": 0.2,
                "avg_role_score": 0.2,
                "target_role_role_weighted_score": 0.2,
                "rankable": False,
                "rankable_reason": "valid_game_rate below threshold",
                "data_sufficient": False,
                "batch_id": "bench_snapshot_run_b",
                "source_run_id": "bench_snapshot_run_b",
                "result_batch_id": "bench_snapshot_run_b_seer",
                "report_id": "benchmark_report:bench_snapshot_run_b",
                "summary": {"source": "unrankable", "benchmark_config_hash": "sha256:contract"},
                "updated_at": "2026-06-09T10:05:00+08:00",
            }
        ]
        captured: dict[str, Any] = {}

        def fake_leaderboard_entries(
            *,
            scope: str | None = None,
            evaluation_set_id: str | None = None,
            target_role: str | None = None,
            limit: int = 100,
        ) -> list[dict[str, Any]]:
            captured.update(
                {
                    "scope": scope,
                    "evaluation_set_id": evaluation_set_id,
                    "target_role": target_role,
                    "limit": limit,
                }
            )
            return [dict(row) for row in current_rows]

        store.leaderboard_entries = fake_leaderboard_entries
        create_response = client.post(
            "/api/benchmark/snapshots",
            json={
                "title": "Role release 2026-06-09",
                "release_notes": "first release",
                "scope": "role_version",
                "benchmark_id": "role-baseline-v1",
                "benchmark_version": 1,
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "benchmark_config_hash": "sha256:contract",
                "target_role": "seer",
                "source_filter": {"rankable": "all"},
                "view_config": {"columns": ["score", "win_rate"]},
                "limit": 25,
            },
        )
        current_rows[0] = {
            **current_rows[0],
            "subject_id": "seer_candidate_v3",
            "hash": "seer_candidate_v3",
            "target_version_id": "seer_candidate_v3",
            "avg_role_score": 0.9,
            "target_role_role_weighted_score": 0.9,
            "summary": {"source": "changed"},
        }
        snapshot_id = create_response.json()["snapshot_id"]
        detail_response = client.get(f"/api/benchmark/snapshots/{snapshot_id}")
        json_export_response = client.get(f"/api/benchmark/snapshots/{snapshot_id}/export")
        markdown_export_response = client.get(f"/api/benchmark/snapshots/{snapshot_id}/export?format=markdown")
        csv_export_response = client.get(f"/api/benchmark/snapshots/{snapshot_id}/export?format=csv")
        unsupported_export_response = client.get(f"/api/benchmark/snapshots/{snapshot_id}/export?format=xml")
        list_response = client.get(
            "/api/benchmark/snapshots?scope=role_version&evaluation_set_id=role-baseline-v1%40v1&benchmark_id=role-baseline-v1"
        )
        missing_response = client.get("/api/benchmark/snapshots/missing-snapshot")

    assert create_response.status_code == 200
    assert captured == {
        "scope": "role_version",
        "evaluation_set_id": "role-baseline-v1@v1",
        "target_role": "seer",
        "limit": 25,
    }
    created = create_response.json()
    _assert_shape(
        created,
        {
            "kind": str,
            "schema_version": int,
            "snapshot_id": str,
            "title": str,
            "release_notes": str,
            "scope": str,
            "benchmark_id": str,
            "benchmark_version": (str, int),
            "evaluation_set_id": str,
            "seed_set_id": str,
            "benchmark_config_hash": str,
            "target_role": str,
            "source_filter": dict,
            "view_config": dict,
            "summary": dict,
            "row_count": int,
            "rankable_count": int,
            "unrankable_count": int,
            "linked_run_ids": list,
            "linked_report_ids": list,
            "linked_result_batch_ids": list,
            "source_run_count": int,
            "source_report_count": int,
            "source_result_batch_count": int,
            "release_gate": dict,
            "release_manifest": dict,
            "content_hash": str,
            "created_at": str,
            "rows": list,
        },
    )
    expected_audit_metadata = {
        "row_count": 2,
        "rankable_count": 1,
        "unrankable_count": 1,
        "linked_run_ids": ["bench_snapshot_run_a", "bench_snapshot_run_b"],
        "linked_report_ids": [
            "benchmark_report:bench_snapshot_run_a",
            "benchmark_report:bench_snapshot_run_b",
        ],
        "linked_result_batch_ids": [
            "bench_snapshot_run_a_seer",
            "bench_snapshot_run_b_seer",
        ],
        "source_run_count": 2,
        "source_report_count": 2,
        "source_result_batch_count": 2,
    }
    for key, expected in expected_audit_metadata.items():
        assert created[key] == expected
        assert created["summary"][key] == expected
    assert created["rows"][0]["subject_id"] == "seer_candidate_v2"
    assert created["rows"][0]["avg_role_score"] == 0.7
    assert created["rows"][0]["batch_id"] == "bench_snapshot_run_a"
    assert created["rows"][0]["source_run_id"] == "bench_snapshot_run_a"
    assert created["rows"][0]["result_batch_id"] == "bench_snapshot_run_a_seer"
    assert created["rows"][0]["report_id"] == "benchmark_report:bench_snapshot_run_a"
    assert created["rows"][1]["subject_id"] == "seer_unrankable_v1"
    assert created["rows"][1]["rankable"] is False
    assert created["content_hash"].startswith("sha256:")
    assert created["release_gate"]["ok"] is True
    assert created["release_gate"]["summary"]["blocker_count"] == 0
    assert created["summary"]["release_gate_ok"] is True
    assert created["summary"]["release_gate_blocker_count"] == 0
    assert created["release_manifest"]["boundaries"]["benchmark_config_hash"] == "sha256:contract"
    assert created["release_manifest"]["release_gate"]["ok"] is True
    assert created["release_manifest"]["release_gate"]["blocker_count"] == 0
    assert created["release_manifest"]["source"]["linked_run_ids"] == ["bench_snapshot_run_a", "bench_snapshot_run_b"]

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["snapshot_id"] == snapshot_id
    for key, expected in expected_audit_metadata.items():
        assert detail[key] == expected
        assert detail["summary"][key] == expected
    assert detail["content_hash"] == created["content_hash"]
    assert detail["rows"][0]["subject_id"] == "seer_candidate_v2"
    assert detail["rows"][0]["avg_role_score"] == 0.7
    assert detail["rows"][0]["summary"] == {"source": "first", "benchmark_config_hash": "sha256:contract"}
    assert detail["rows"][1]["subject_id"] == "seer_unrankable_v1"
    assert detail["rows"][1]["summary"] == {"source": "unrankable", "benchmark_config_hash": "sha256:contract"}
    assert detail["release_gate"]["ok"] is True
    assert detail["release_manifest"]["release_gate"]["ok"] is True

    assert json_export_response.status_code == 200
    json_export = json_export_response.json()
    assert json_export["kind"] == "benchmark_leaderboard_snapshot_export"
    assert json_export["format"] == "json"
    assert json_export["snapshot_id"] == snapshot_id
    assert json_export["content_hash"] == created["content_hash"]
    assert json_export["export_content_hash"].startswith("sha256:")
    assert json_export["artifact_hash"] == json_export["export_content_hash"]
    assert json_export["export_content_hash"] != json_export["content_hash"]
    assert '"snapshot_id": "' + snapshot_id + '"' in json_export["content"]
    assert json_export["release_gate"]["ok"] is True
    assert json_export["release_manifest"]["release_gate"]["ok"] is True
    assert json_export["snapshot"]["rows"][0]["subject_id"] == "seer_candidate_v2"

    assert markdown_export_response.status_code == 200
    markdown_export = markdown_export_response.json()
    assert markdown_export["format"] == "markdown"
    assert markdown_export["export_content_hash"].startswith("sha256:")
    assert markdown_export["export_content_hash"] != json_export["export_content_hash"]
    assert "# 榜单快照：Role release 2026-06-09" in markdown_export["content"]
    assert "发布门禁: 通过 / 阻断 0 / 警告 0" in markdown_export["content"]
    assert "seer_candidate_v2" in markdown_export["content"]
    assert "benchmark_report:bench_snapshot_run_a" in markdown_export["content"]

    assert csv_export_response.status_code == 200
    csv_export = csv_export_response.json()
    assert csv_export["format"] == "csv"
    assert csv_export["export_content_hash"].startswith("sha256:")
    assert csv_export["export_content_hash"] != json_export["export_content_hash"]
    assert csv_export["content"].splitlines()[0] == "区段,标签,值,详情"
    assert "快照头,快照 ID," + snapshot_id in csv_export["content"]
    assert "发布门禁,状态,通过,阻断 0 / 警告 0" in csv_export["content"]
    assert "冻结行,seer_candidate_v2" in csv_export["content"]

    _assert_error_detail(unsupported_export_response, 422, "unsupported benchmark snapshot export format")

    assert list_response.status_code == 200
    listed = list_response.json()
    assert listed["kind"] == "benchmark_leaderboard_snapshots"
    listed_item = listed["items"][0]
    assert listed_item["snapshot_id"] == snapshot_id
    for key, expected in expected_audit_metadata.items():
        assert listed_item[key] == expected
        assert listed_item["summary"][key] == expected
    assert listed_item["content_hash"] == created["content_hash"]
    assert listed_item["release_gate"]["ok"] is True
    assert listed_item["release_manifest"]["release_gate"]["ok"] is True
    assert "rows" not in listed_item

    _assert_error_detail(missing_response, 404, "benchmark snapshot not found")


def test_benchmark_snapshot_and_saved_view_repository_persist_across_store_instances(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    _install_sqlite_eval_storage(monkeypatch, tmp_path)
    view_key = "benchmark-release-view:role_version:role-baseline-v1:role-baseline-v1@v1:seer"

    with _client(tmp_path) as client:
        snapshot_response = _post_benchmark_snapshot_with_rows(
            client,
            [_benchmark_snapshot_release_row(summary={"source": "repository-contract"})],
            _benchmark_snapshot_release_request(
                title="Repository persisted release",
                view_config={"columns": ["score", "rankable"], "density": "compact"},
            ),
        )
        view_response = client.post(
            "/api/benchmark/views",
            json={
                "view_key": view_key,
                "name": "Repository release reviewer",
                "scope": "role_version",
                "benchmark_id": "role-baseline-v1",
                "evaluation_set_id": "role-baseline-v1@v1",
                "target_role": "seer",
                "view_config": {
                    "rank_filter": "rankable",
                    "columns": ["score", "rankable"],
                },
            },
        )

    assert snapshot_response.status_code == 200
    assert view_response.status_code == 200
    snapshot_id = snapshot_response.json()["snapshot_id"]

    with _client(tmp_path) as restarted_client:
        detail_response = restarted_client.get(f"/api/benchmark/snapshots/{snapshot_id}")
        list_response = restarted_client.get(
            "/api/benchmark/snapshots?scope=role_version&"
            "evaluation_set_id=role-baseline-v1%40v1&benchmark_id=role-baseline-v1&target_role=seer"
        )
        export_response = restarted_client.get(f"/api/benchmark/snapshots/{snapshot_id}/export?format=json")
        view_detail_response = restarted_client.get(f"/api/benchmark/views/{view_key}")
        view_list_response = restarted_client.get(
            "/api/benchmark/views?scope=role_version&"
            "evaluation_set_id=role-baseline-v1%40v1&benchmark_id=role-baseline-v1&target_role=seer"
        )
        delete_view_response = restarted_client.delete(f"/api/benchmark/views/{view_key}")
        missing_view_response = restarted_client.get(f"/api/benchmark/views/{view_key}")

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["snapshot_id"] == snapshot_id
    assert detail["title"] == "Repository persisted release"
    assert detail["view_config"] == {"columns": ["score", "rankable"], "density": "compact"}
    assert detail["rows"][0]["summary"] == {"source": "repository-contract"}
    assert detail["release_gate"]["ok"] is True
    assert detail["release_manifest"]["release_gate"]["ok"] is True

    assert list_response.status_code == 200
    listed = list_response.json()
    assert [item["snapshot_id"] for item in listed["items"]] == [snapshot_id]
    assert "rows" not in listed["items"][0]
    assert listed["items"][0]["release_gate"]["ok"] is True

    assert export_response.status_code == 200
    exported = export_response.json()
    assert exported["snapshot_id"] == snapshot_id
    assert exported["snapshot"]["rows"][0]["subject_id"] == "seer_candidate_v2"

    assert view_detail_response.status_code == 200
    view_detail = view_detail_response.json()
    assert view_detail["view_key"] == view_key
    assert view_detail["name"] == "Repository release reviewer"
    assert view_detail["view_config"]["columns"] == ["score", "rankable"]

    assert view_list_response.status_code == 200
    assert [item["view_key"] for item in view_list_response.json()["items"]] == [view_key]

    assert delete_view_response.status_code == 200
    assert delete_view_response.json()["deleted"] is True
    _assert_error_detail(missing_view_response, 404, "benchmark view not found")


def test_benchmark_snapshot_compare_api_reports_current_vs_frozen_delta(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        current_rows = [
            {
                "scope": "role_version",
                "hash": "seer_candidate_v2",
                "subject_id": "seer_candidate_v2",
                "target_role": "seer",
                "target_version_id": "seer_candidate_v2",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "benchmark_config_hash": "sha256:contract",
                "games_played": 3,
                "avg_role_score": 0.7,
                "target_side_win_rate": 0.55,
                "rankable": True,
                "batch_id": "bench_compare_run_a",
                "source_run_id": "bench_compare_run_a",
                "result_batch_id": "bench_compare_run_a_seer",
                "report_id": "benchmark_report:bench_compare_run_a",
            },
            {
                "scope": "role_version",
                "hash": "seer_removed_v1",
                "subject_id": "seer_removed_v1",
                "target_role": "seer",
                "target_version_id": "seer_removed_v1",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "benchmark_config_hash": "sha256:contract",
                "games_played": 3,
                "avg_role_score": 0.62,
                "target_side_win_rate": 0.5,
                "rankable": True,
                "batch_id": "bench_compare_run_b",
                "source_run_id": "bench_compare_run_b",
                "result_batch_id": "bench_compare_run_b_seer",
                "report_id": "benchmark_report:bench_compare_run_b",
            },
        ]
        captured: list[dict[str, Any]] = []

        def fake_leaderboard_entries(
            *,
            scope: str | None = None,
            evaluation_set_id: str | None = None,
            target_role: str | None = None,
            limit: int = 100,
        ) -> list[dict[str, Any]]:
            captured.append(
                {
                    "scope": scope,
                    "evaluation_set_id": evaluation_set_id,
                    "target_role": target_role,
                    "limit": limit,
                }
            )
            return [dict(row) for row in current_rows]

        store.leaderboard_entries = fake_leaderboard_entries
        create_response = client.post(
            "/api/benchmark/snapshots",
            json={
                "title": "Role release",
                "scope": "role_version",
                "benchmark_id": "role-baseline-v1",
                "benchmark_version": 1,
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "benchmark_config_hash": "sha256:contract",
                "target_role": "seer",
                "limit": 25,
            },
        )
        snapshot_id = create_response.json()["snapshot_id"]
        current_rows[:] = [
            {
                **current_rows[0],
                "seed_set_id": "role-baseline-different-seeds",
                "games_played": 4,
                "avg_role_score": 0.76,
                "target_side_win_rate": 0.61,
            },
            {
                "scope": "role_version",
                "hash": "seer_candidate_v3",
                "subject_id": "seer_candidate_v3",
                "target_role": "seer",
                "target_version_id": "seer_candidate_v3",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "benchmark_config_hash": "sha256:contract",
                "games_played": 3,
                "avg_role_score": 0.8,
                "target_side_win_rate": 0.66,
                "rankable": True,
                "batch_id": "bench_compare_run_c",
                "source_run_id": "bench_compare_run_c",
                "result_batch_id": "bench_compare_run_c_seer",
                "report_id": "benchmark_report:bench_compare_run_c",
            },
        ]
        compare_response = client.get(f"/api/benchmark/snapshots/{snapshot_id}/compare?limit=50")
        missing_response = client.get("/api/benchmark/snapshots/missing-snapshot/compare")

    assert create_response.status_code == 200
    assert compare_response.status_code == 200
    payload = compare_response.json()
    _assert_shape(
        payload,
        {
            "kind": str,
            "schema_version": int,
            "snapshot": dict,
            "current": dict,
            "frozen": dict,
            "summary": dict,
            "changed": list,
            "added": list,
            "removed": list,
            "boundary_warnings": list,
        },
    )
    assert captured[-1] == {
        "scope": "role_version",
        "evaluation_set_id": "role-baseline-v1@v1",
        "target_role": "seer",
        "limit": 50,
    }
    assert payload["kind"] == "benchmark_snapshot_compare"
    assert payload["snapshot"]["snapshot_id"] == snapshot_id
    _assert_shape(
        payload["snapshot"],
        {
            "row_count": int,
            "rankable_count": int,
            "unrankable_count": int,
            "linked_run_ids": list,
            "linked_report_ids": list,
            "linked_result_batch_ids": list,
            "source_run_count": int,
            "source_report_count": int,
            "source_result_batch_count": int,
            "content_hash": str,
            "summary": dict,
        },
    )
    expected_snapshot_audit = {
        "row_count": 2,
        "rankable_count": 2,
        "unrankable_count": 0,
        "linked_run_ids": ["bench_compare_run_a", "bench_compare_run_b"],
        "linked_report_ids": [
            "benchmark_report:bench_compare_run_a",
            "benchmark_report:bench_compare_run_b",
        ],
        "linked_result_batch_ids": [
            "bench_compare_run_a_seer",
            "bench_compare_run_b_seer",
        ],
        "source_run_count": 2,
        "source_report_count": 2,
        "source_result_batch_count": 2,
    }
    for key, expected in expected_snapshot_audit.items():
        assert payload["snapshot"][key] == expected
        assert payload["snapshot"]["summary"][key] == expected
    assert payload["snapshot"]["content_hash"].startswith("sha256:")
    assert payload["summary"]["current_row_count"] == 2
    assert payload["summary"]["snapshot_row_count"] == 2
    assert payload["current"]["row_count"] == 2
    assert payload["frozen"]["row_count"] == 2
    assert payload["summary"]["rankable_current_count"] == 2
    assert payload["summary"]["rankable_snapshot_count"] == 2
    assert payload["summary"]["changed_count"] == 1
    assert payload["summary"]["added_count"] == 1
    assert payload["summary"]["removed_count"] == 1
    assert payload["changed"][0]["key"] == "seer_candidate_v2"
    assert payload["changed"][0]["snapshot"]["source_run_id"] == "bench_compare_run_a"
    assert payload["changed"][0]["current"]["source_run_id"] == "bench_compare_run_a"
    assert abs(payload["changed"][0]["score_delta"] - 0.06) < 0.000001
    assert abs(payload["changed"][0]["win_rate_delta"] - 0.06) < 0.000001
    assert payload["changed"][0]["games_delta"] == 1
    assert payload["changed"][0]["boundary_warnings"] == ["seed_set_mismatch"]
    assert payload["added"][0]["key"] == "seer_candidate_v3"
    assert payload["added"][0]["source_run_id"] == "bench_compare_run_c"
    assert payload["removed"][0]["key"] == "seer_removed_v1"
    assert payload["removed"][0]["source_run_id"] == "bench_compare_run_b"
    assert payload["boundary_warnings"] == ["seed_set_mismatch"]

    _assert_error_detail(missing_response, 404, "benchmark snapshot not found")


def test_benchmark_snapshot_compare_api_reuses_snapshot_source_filter_for_current_rows(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        current_rows = [
            _benchmark_snapshot_release_row(),
            _benchmark_snapshot_release_row(
                hash="seer_unrankable_v1",
                subject_id="seer_unrankable_v1",
                target_version_id="seer_unrankable_v1",
                rankable=False,
                data_sufficient=False,
                source_run_id="bench_snapshot_run_b",
                batch_id="bench_snapshot_run_b",
                result_batch_id="bench_snapshot_run_b_seer",
                report_id="benchmark_report:bench_snapshot_run_b",
                summary={"source": "unrankable", "benchmark_config_hash": "sha256:contract"},
            ),
        ]

        def fake_leaderboard_entries(
            *,
            scope: str | None = None,
            evaluation_set_id: str | None = None,
            target_role: str | None = None,
            limit: int = 100,
        ) -> list[dict[str, Any]]:
            assert scope == "role_version"
            assert evaluation_set_id == "role-baseline-v1@v1"
            assert target_role == "seer"
            assert limit in {25, 50}
            return [dict(row) for row in current_rows]

        store.leaderboard_entries = fake_leaderboard_entries
        create_response = client.post(
            "/api/benchmark/snapshots",
            json=_benchmark_snapshot_release_request(source_filter={"rankable": "rankable"}),
        )
        snapshot_id = create_response.json()["snapshot_id"]
        current_rows[:] = [
            {
                **_benchmark_snapshot_release_row(),
                "avg_role_score": 0.72,
                "target_role_role_weighted_score": 0.72,
                "target_side_win_rate": 0.57,
            },
            _benchmark_snapshot_release_row(
                hash="seer_added_unrankable_v3",
                subject_id="seer_added_unrankable_v3",
                target_version_id="seer_added_unrankable_v3",
                rankable=False,
                data_sufficient=False,
                source_run_id="bench_snapshot_run_c",
                batch_id="bench_snapshot_run_c",
                result_batch_id="bench_snapshot_run_c_seer",
                report_id="benchmark_report:bench_snapshot_run_c",
                summary={"source": "current-unrankable", "benchmark_config_hash": "sha256:contract"},
            ),
        ]
        compare_response = client.get(f"/api/benchmark/snapshots/{snapshot_id}/compare?limit=50")

    assert create_response.status_code == 200
    assert compare_response.status_code == 200
    payload = compare_response.json()
    assert payload["snapshot"]["source_filter"] == {"rankable": "rankable"}
    assert payload["summary"]["current_row_count"] == 1
    assert payload["current"]["row_count"] == 1
    assert [row["subject_id"] for row in payload["current"]["rows"]] == ["seer_candidate_v2"]
    assert payload["summary"]["added_count"] == 0
    assert payload["added"] == []


def test_benchmark_snapshot_compare_api_supports_frozen_snapshot_pair(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        leaderboard_calls: list[dict[str, Any]] = []
        current_rows = [
            {
                "scope": "role_version",
                "hash": "seer_candidate_v2",
                "subject_id": "seer_candidate_v2",
                "target_role": "seer",
                "target_version_id": "seer_candidate_v2",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "benchmark_config_hash": "sha256:base",
                "games_played": 6,
                "avg_role_score": 0.66,
                "target_side_win_rate": 0.52,
                "rankable": True,
                "source_run_id": "release_a_run",
                "result_batch_id": "release_a_run_seer_candidate_v2",
                "report_id": "benchmark_report:release_a_run",
            },
            {
                "scope": "role_version",
                "hash": "seer_removed_v1",
                "subject_id": "seer_removed_v1",
                "target_role": "seer",
                "target_version_id": "seer_removed_v1",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "benchmark_config_hash": "sha256:base",
                "games_played": 6,
                "avg_role_score": 0.61,
                "target_side_win_rate": 0.48,
                "rankable": True,
                "source_run_id": "release_a_run",
                "result_batch_id": "release_a_run_seer_removed_v1",
                "report_id": "benchmark_report:release_a_run",
            },
        ]

        def fake_leaderboard_entries(
            *,
            scope: str | None = None,
            evaluation_set_id: str | None = None,
            target_role: str | None = None,
            limit: int = 100,
        ) -> list[dict[str, Any]]:
            leaderboard_calls.append(
                {
                    "scope": scope,
                    "evaluation_set_id": evaluation_set_id,
                    "target_role": target_role,
                    "limit": limit,
                }
            )
            return [dict(row) for row in current_rows]

        store.leaderboard_entries = fake_leaderboard_entries
        base_response = client.post(
            "/api/benchmark/snapshots",
            json={
                "title": "Release A",
                "scope": "role_version",
                "benchmark_id": "role-baseline-v1",
                "benchmark_version": 1,
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "benchmark_config_hash": "sha256:base",
                "target_role": "seer",
                "limit": 25,
            },
        )
        base_snapshot_id = base_response.json()["snapshot_id"]
        current_rows[:] = [
            {
                **current_rows[0],
                "benchmark_config_hash": "sha256:next",
                "games_played": 8,
                "avg_role_score": 0.72,
                "target_side_win_rate": 0.58,
                "source_run_id": "release_b_run",
                "result_batch_id": "release_b_run_seer_candidate_v2",
                "report_id": "benchmark_report:release_b_run",
            },
            {
                "scope": "role_version",
                "hash": "seer_added_v3",
                "subject_id": "seer_added_v3",
                "target_role": "seer",
                "target_version_id": "seer_added_v3",
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "benchmark_config_hash": "sha256:next",
                "games_played": 8,
                "avg_role_score": 0.77,
                "target_side_win_rate": 0.63,
                "rankable": True,
                "source_run_id": "release_b_run",
                "result_batch_id": "release_b_run_seer_added_v3",
                "report_id": "benchmark_report:release_b_run",
            },
        ]
        against_response = client.post(
            "/api/benchmark/snapshots",
            json={
                "title": "Release B",
                "scope": "role_version",
                "benchmark_id": "role-baseline-v1",
                "benchmark_version": 1,
                "evaluation_set_id": "role-baseline-v1@v1",
                "seed_set_id": "role-baseline-quick-202606",
                "benchmark_config_hash": "sha256:next",
                "target_role": "seer",
                "limit": 25,
            },
        )
        against_snapshot_id = against_response.json()["snapshot_id"]
        calls_after_create = len(leaderboard_calls)
        compare_response = client.get(
            f"/api/benchmark/snapshots/{base_snapshot_id}/compare?"
            f"against_snapshot_id={against_snapshot_id}&limit=5"
        )

    assert base_response.status_code == 200
    assert against_response.status_code == 200
    assert compare_response.status_code == 200
    assert len(leaderboard_calls) == calls_after_create
    payload = compare_response.json()
    assert payload["kind"] == "benchmark_snapshot_compare"
    assert payload["compare_mode"] == "snapshot_to_snapshot"
    assert payload["snapshot"]["snapshot_id"] == base_snapshot_id
    assert payload["against_snapshot"]["snapshot_id"] == against_snapshot_id
    assert payload["current"]["snapshot_id"] == against_snapshot_id
    assert payload["summary"]["snapshot_id"] == base_snapshot_id
    assert payload["summary"]["against_snapshot_id"] == against_snapshot_id
    assert payload["summary"]["changed_count"] == 1
    assert payload["summary"]["added_count"] == 1
    assert payload["summary"]["removed_count"] == 1
    assert payload["changed"][0]["key"] == "seer_candidate_v2"
    assert payload["changed"][0]["current"]["source_run_id"] == "release_b_run"
    assert payload["changed"][0]["snapshot"]["source_run_id"] == "release_a_run"
    assert abs(payload["changed"][0]["score_delta"] - 0.06) < 0.000001
    assert payload["changed"][0]["games_delta"] == 2
    assert payload["added"][0]["key"] == "seer_added_v3"
    assert payload["removed"][0]["key"] == "seer_removed_v1"
    assert "benchmark_config_hash_mismatch" in payload["boundary_warnings"]


def test_benchmark_saved_view_api_persists_filter_config(tmp_path: Path) -> None:
    view_key = "benchmark-comparison-view:role_version:role-baseline-v1:role-baseline-v1@v1:seer"
    with _client(tmp_path) as client:
        create_response = client.post(
            "/api/benchmark/views",
            json={
                "view_key": view_key,
                "name": "Release reviewer",
                "scope": "role_version",
                "benchmark_id": "role-baseline-v1",
                "evaluation_set_id": "role-baseline-v1@v1",
                "target_role": "seer",
                "view_config": {
                    "rank_filter": "rankable",
                    "columns": ["score", "winRate", "rankable"],
                },
            },
        )
        detail_response = client.get(f"/api/benchmark/views/{view_key}")
        listed_response = client.get(
            "/api/benchmark/views?"
            "scope=role_version&evaluation_set_id=role-baseline-v1%40v1&"
            "benchmark_id=role-baseline-v1&target_role=seer"
        )
        delete_response = client.delete(f"/api/benchmark/views/{view_key}")
        missing_response = client.get(f"/api/benchmark/views/{view_key}")

    assert create_response.status_code == 200
    created = create_response.json()
    _assert_shape(
        created,
        {
            "kind": str,
            "schema_version": int,
            "view_key": str,
            "name": str,
            "scope": str,
            "benchmark_id": str,
            "evaluation_set_id": str,
            "target_role": str,
            "view_config": dict,
            "created_at": str,
            "updated_at": str,
        },
    )
    assert created["kind"] == "benchmark_saved_view"
    assert created["view_key"] == view_key
    assert created["view_config"]["rank_filter"] == "rankable"

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["name"] == "Release reviewer"
    assert detail["view_config"]["columns"] == ["score", "winRate", "rankable"]

    assert listed_response.status_code == 200
    listed = listed_response.json()
    assert listed["kind"] == "benchmark_saved_views"
    assert [item["view_key"] for item in listed["items"]] == [view_key]

    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True
    _assert_error_detail(missing_response, 404, "benchmark view not found")


def test_model_leaderboard_api_contract(tmp_path: Path) -> None:
    with _client(tmp_path) as client:
        store = client.app.state.backend_store
        captured: dict[str, Any] = {}

        def fake_model_leaderboard_entries(
            *,
            evaluation_set_id: str | None = None,
            limit: int = 100,
        ) -> list[dict[str, Any]]:
            captured["evaluation_set_id"] = evaluation_set_id
            captured["limit"] = limit
            return [
                {
                    "scope": "model",
                    "hash": "runtime_hash_v1",
                    "subject_id": "runtime_hash_v1",
                    "model_id": "qwen-max",
                    "model_config_hash": "runtime_hash_v1",
                    "target_role": None,
                    "target_version_id": None,
                    "comparison_group_id": "bench_model",
                    "evaluation_set_id": evaluation_set_id,
                    "seed_set_id": "model-baseline-standard-202606",
                    "game_count": 30,
                    "games_played": 30,
                    "valid_game_rate": 1.0,
                    "strength_score": 0.72,
                    "avg_role_score": 0.69,
                    "target_role_role_weighted_score": 0.69,
                    "by_role_category_scores": {"seer": 0.7, "witch": 0.68},
                    "avg_speech_score": 0.61,
                    "avg_vote_score": 0.62,
                    "avg_skill_score": 0.63,
                    "avg_logic_score": 0.64,
                    "avg_team_score": 0.65,
                    "risk_penalty": 0.01,
                    "fallback_rate": 0.02,
                    "target_role_fallback_rate": 0.02,
                    "llm_error_rate": 0.0,
                    "policy_adjusted_rate": 0.01,
                    "target_side_win_rate": 0.57,
                    "rankable": True,
                    "data_sufficient": True,
                    "summary": {"is_baseline": False},
                    "is_baseline": False,
                    "delta_vs_baseline": {},
                    "updated_at": "2026-06-09T10:00:00+08:00",
                }
            ]

        store.model_leaderboard_entries = fake_model_leaderboard_entries
        response = client.get(
            "/api/models/leaderboard?evaluation_set_id=model-baseline-standard-v1%40v1&limit=10"
        )

    assert response.status_code == 200
    payload = response.json()
    _assert_shape(
        payload,
        {
            "kind": str,
            "schema_version": int,
            "scope": str,
            "evaluation_set_id": str,
            "entries": list,
            "source": str,
            "source_type": str,
        },
    )
    assert captured == {"evaluation_set_id": "model-baseline-standard-v1@v1", "limit": 10}
    assert payload["scope"] == "model"
    assert payload["evaluation_set_id"] == "model-baseline-standard-v1@v1"
    assert len(payload["entries"]) == 1
    entry = payload["entries"][0]
    _assert_shape(
        entry,
        {
            "scope": str,
            "hash": str,
            "subject_id": str,
            "model_id": str,
            "model_config_hash": str,
            "comparison_group_id": str,
            "evaluation_set_id": str,
            "seed_set_id": str,
            "game_count": int,
            "games_played": int,
            "valid_game_rate": float,
            "strength_score": float,
            "avg_role_score": float,
            "target_role_role_weighted_score": float,
            "by_role_category_scores": dict,
            "fallback_rate": float,
            "llm_error_rate": float,
            "policy_adjusted_rate": float,
            "target_side_win_rate": float,
            "rankable": bool,
            "data_sufficient": bool,
            "summary": dict,
            "delta_vs_baseline": dict,
            "updated_at": str,
        },
    )
    assert entry["model_id"] == "qwen-max"
    assert entry["model_config_hash"] == "runtime_hash_v1"
    assert entry["target_role"] is None
    assert entry["target_version_id"] is None


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
