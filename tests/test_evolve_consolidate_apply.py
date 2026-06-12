"""Tests for evolve consolidate_node / apply_node wired to LLM chains.

Uses a fake model (no network) and an on-disk skill dir to exercise the full
consolidate -> apply path: prompt building, JSON parsing, applier validation,
smoke test, candidate skill-file writing, and graceful degradation.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

import pytest

from app.graphs.subgraphs.evolve.nodes import (
    _attach_training_evidence,
    apply_node,
    battle_node,
    consolidate_node,
    decide_node,
    init_evolve_node,
    scenario_replay_node,
    training_node,
)


SEER_SKILL = """---
name: seer_vote
role: seer
status: active
applicable_actions:
  - vote
evolution:
  enabled: true
  allowed_actions:
    - append_rule
---

# Seer voting

## Strategy

Vote the most suspicious player.
"""


class FakeModel:
    """Async LLM stand-in: returns canned text per call in order."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls: list[list[dict]] = []

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return self._responses.pop(0) if self._responses else ""


class FakeRuntimeRegistry:
    """In-memory stand-in for the PostgreSQL-backed runtime registry."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._versions: dict[tuple[str, str], dict[str, str]] = {}
        self._metadata: dict[tuple[str, str], dict[str, Any]] = {}
        self._baselines: dict[str, str] = {}
        self._rejected: dict[str, list[dict[str, Any]]] = {}
        self.closed = False

    @property
    def registry_dir(self) -> Path:
        return self._root

    def close(self) -> None:
        self.closed = True

    def seed_version(
        self,
        role: str,
        version_id: str,
        skills: dict[str, str],
        *,
        baseline: bool = False,
    ) -> str:
        self._versions[(role, version_id)] = dict(skills)
        self._metadata[(role, version_id)] = {
            "release_stage": "baseline" if baseline else "draft",
            "status": "baseline" if baseline else "active",
        }
        if baseline:
            self._baselines[role] = version_id
        return version_id

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
        version_id = version_id or f"{role}_v{len(self._versions) + 1}"
        current = self.get_baseline(role)
        if set_as_baseline and expected_current is not None and current != expected_current:
            raise RuntimeError(f"baseline mismatch: expected {expected_current}, got {current}")
        self.seed_version(role, version_id, skill_contents, baseline=set_as_baseline)
        stage = "baseline" if set_as_baseline else str(release_stage or "draft")
        provenance_payload = dict(provenance or {})
        provenance_payload.setdefault("source", source)
        if run_id:
            provenance_payload.setdefault("run_id", run_id)
        provenance_payload.setdefault("proposal_ids", list(proposal_ids or []))
        provenance_payload.setdefault("release_stage", stage)
        self._metadata[(role, version_id)] = {
            "release_stage": stage,
            "status": "baseline" if set_as_baseline else stage if stage in {"shadow", "canary"} else "active",
            "provenance": provenance_payload,
        }
        return version_id

    def get_baseline(self, role: str) -> str | None:
        return self._baselines.get(role)

    def set_baseline(
        self,
        role: str,
        version_id: str,
        expected_current: str | None = None,
    ) -> bool:
        current = self.get_baseline(role)
        if expected_current is not None and current != expected_current:
            return False
        if (role, version_id) not in self._versions:
            return False
        self._baselines[role] = version_id
        self._metadata.setdefault((role, version_id), {})["release_stage"] = "baseline"
        self._metadata[(role, version_id)]["status"] = "baseline"
        return True

    def release_stage(self, role: str, version_id: str) -> str:
        return str(self._metadata.get((role, version_id), {}).get("release_stage") or "")

    def provenance(self, role: str, version_id: str) -> dict[str, Any]:
        return dict(self._metadata.get((role, version_id), {}).get("provenance") or {})

    def reject(self, role: str, version_id: str, reason: str = "") -> None:
        del role, version_id, reason

    def read_skill_contents(self, role: str, version_id: str) -> dict[str, str]:
        try:
            return dict(self._versions[(role, version_id)])
        except KeyError as exc:
            raise FileNotFoundError(f"Version {role}/{version_id} not found") from exc

    def get_skill_dir(self, role: str, version_id: str) -> Path:
        root = Path(tempfile.mkdtemp(prefix=f"fake_skill_{role}_{version_id}_", dir=self._root))
        for rel_path, content in self.read_skill_contents(role, version_id).items():
            output = root / rel_path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(content, encoding="utf-8")
        return root

    def build_skill_dir(self, role_versions: dict[str, str]) -> Path:
        root = Path(tempfile.mkdtemp(prefix="fake_skills_", dir=self._root))
        for role, version_id in role_versions.items():
            for rel_path, content in self.read_skill_contents(role, version_id).items():
                path = Path(rel_path)
                parts = path.parts
                if parts and parts[0] == role:
                    path = Path(*parts[1:]) if len(parts) > 1 else Path(path.name)
                output = root / role / path
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(content, encoding="utf-8")
        return root

    def list_versions(self, role: str) -> list[Any]:
        return []

    def list_roles(self) -> list[str]:
        return sorted({role for role, _ in self._versions})

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
            rows.append(row)

    def load_rejected(self, role: str) -> list[dict[str, Any]]:
        return [dict(item) for item in self._rejected.get(role, [])]


class _Cursor:
    rowcount = 0

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = list(rows or [])
        self.rowcount = len(self._rows)

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


class FakeEvolutionConnection:
    def __init__(
        self,
        rows: dict[str, dict[str, Any]],
        trust_bundles: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._rows = rows
        self._trust_bundles = trust_bundles if trust_bundles is not None else {}
        self.closed = False
        self.commits = 0
        self.rollbacks = 0
        self.columns = {
            "id",
            "role",
            "parent_hash",
            "status",
            "training_games",
            "battle_games",
            "config",
            "candidate_hash",
            "battle_result",
            "runtime_state",
            "errors",
            "started_at",
            "finished_at",
        }

    def execute(self, sql: str, parameters: Any = ()) -> _Cursor:
        if self.closed:
            raise RuntimeError("connection closed")
        text = " ".join(sql.split())
        params = tuple(parameters)

        if text.startswith("INSERT INTO trust_bundles"):
            (
                bundle_id,
                run_id,
                role,
                baseline_version,
                candidate_version,
                bundle_hash,
                gate_report_id,
                attribution_report_id,
                bundle_json,
                created_at,
                updated_at,
            ) = params
            run_key = str(run_id)
            existing = self._trust_bundles.get(run_key)
            self._trust_bundles[run_key] = {
                "id": bundle_id,
                "run_id": run_id,
                "role": role,
                "baseline_version": baseline_version,
                "candidate_version": candidate_version,
                "bundle_hash": bundle_hash,
                "gate_report_id": gate_report_id,
                "attribution_report_id": attribution_report_id,
                "bundle_json": bundle_json,
                "created_at": existing.get("created_at") if existing is not None else created_at,
                "updated_at": updated_at,
            }
            return _Cursor()

        if text == "SELECT * FROM trust_bundles WHERE run_id = ? OR id = ? LIMIT 1":
            lookup = str(params[0])
            row = self._trust_bundles.get(lookup)
            if row is None:
                row = next(
                    (item for item in self._trust_bundles.values() if str(item.get("id")) == str(params[1])),
                    None,
                )
            return _Cursor([row] if row is not None else [])

        if text.startswith("SELECT * FROM trust_bundles"):
            limit = int(params[-1])
            role = str(params[0]) if "role = ?" in text else None
            rows = [
                row
                for row in self._trust_bundles.values()
                if role is None or row.get("role") == role
            ]
            rows.sort(key=lambda row: str(row.get("updated_at") or ""), reverse=True)
            return _Cursor(rows[:limit])

        if text.startswith("INSERT INTO evolution_runs"):
            (
                run_id,
                role,
                parent_hash,
                status,
                training_games,
                battle_games,
                config,
                candidate_hash,
                battle_result,
                runtime_state,
                errors,
                started_at,
                finished_at,
            ) = params
            existing = self._rows.get(str(run_id))
            persisted_started_at = started_at
            persisted_finished_at = finished_at
            if existing is not None:
                if "started_at = COALESCE(evolution_runs.started_at, excluded.started_at)" in text:
                    persisted_started_at = existing.get("started_at") or started_at
                elif "started_at = excluded.started_at" not in text:
                    persisted_started_at = existing.get("started_at")
                if "finished_at = COALESCE(excluded.finished_at, evolution_runs.finished_at)" in text:
                    persisted_finished_at = finished_at or existing.get("finished_at")
            self._rows[str(run_id)] = {
                "id": run_id,
                "role": role,
                "parent_hash": parent_hash,
                "status": status,
                "training_games": training_games,
                "battle_games": battle_games,
                "config": config,
                "candidate_hash": candidate_hash,
                "battle_result": battle_result,
                "runtime_state": runtime_state,
                "errors": errors,
                "started_at": persisted_started_at,
                "finished_at": persisted_finished_at,
            }
            return _Cursor()

        if text.startswith("UPDATE evolution_runs SET"):
            run_id = str(params[-1])
            row = self._rows.get(run_id)
            if row is not None:
                assignments = text.removeprefix("UPDATE evolution_runs SET ").split(" WHERE id = ?")[0]
                for assignment, value in zip(assignments.split(", "), params[:-1], strict=False):
                    row[assignment.split(" = ")[0]] = value
            return _Cursor()

        if text == "SELECT * FROM evolution_runs WHERE id = ?":
            row = self._rows.get(str(params[0]))
            return _Cursor([row] if row is not None else [])

        if text.startswith("SELECT runtime_state FROM evolution_runs"):
            rows = [
                {"runtime_state": row.get("runtime_state")}
                for row in self._rows.values()
                if row.get("runtime_state") is not None
            ]
            return _Cursor(rows[: int(params[-1])])

        if text.startswith("SELECT battle_result FROM evolution_runs"):
            limit = int(params[-1])
            role = str(params[0]) if "role = ?" in text else None
            rows = [
                {"battle_result": row.get("battle_result")}
                for row in self._rows.values()
                if row.get("battle_result") is not None
                and (role is None or row.get("role") == role)
            ]
            return _Cursor(rows[:limit])

        raise AssertionError(f"unexpected SQL: {text}")

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "FakeEvolutionConnection":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    def table_exists(self, table_name: str) -> bool:
        return table_name in {"evolution_runs", "trust_bundles"}

    def table_columns(self, table_name: str) -> set[str]:
        if table_name == "trust_bundles":
            return {
                "id",
                "run_id",
                "role",
                "baseline_version",
                "candidate_version",
                "bundle_hash",
                "gate_report_id",
                "attribution_report_id",
                "bundle_json",
                "created_at",
                "updated_at",
            }
        assert table_name == "evolution_runs"
        return set(self.columns)

    def add_column(self, table_name: str, column_name: str, declaration: str) -> None:
        del declaration
        assert table_name == "evolution_runs"
        self.columns.add(column_name)


class FakeEvolutionStorageProvider:
    def __init__(self, *, fail_message: str | None = None) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.trust_bundles: dict[str, dict[str, Any]] = {}
        self.connections: list[FakeEvolutionConnection] = []
        self.fail_message = fail_message

    def open_wolf_connection(self) -> FakeEvolutionConnection:
        raise AssertionError("wolf connection should not be used")

    def open_registry_connection(self) -> FakeEvolutionConnection:
        raise AssertionError("registry connection should not be used")

    def open_evolution_connection(self) -> FakeEvolutionConnection:
        if self.fail_message is not None:
            raise RuntimeError(self.fail_message)
        conn = FakeEvolutionConnection(self.rows, self.trust_bundles)
        self.connections.append(conn)
        return conn

    def row(self, run_id: str) -> dict[str, Any]:
        return self.rows[run_id]

    def runtime_state(self, run_id: str) -> dict[str, Any]:
        value = self.row(run_id)["runtime_state"]
        if isinstance(value, str):
            return json.loads(value)
        assert isinstance(value, dict)
        return value

    def trust_bundle(self, run_id: str) -> dict[str, Any]:
        value = self.trust_bundles[run_id]["bundle_json"]
        if isinstance(value, str):
            return json.loads(value)
        assert isinstance(value, dict)
        return value


def test_evolution_store_save_runtime_state_preserves_existing_started_at():
    from storage.evolution.run_repo import EvolutionStore

    rows: dict[str, dict[str, Any]] = {}
    store = EvolutionStore(FakeEvolutionConnection(rows))

    store.save_runtime_state(
        "r_started",
        role="seer",
        parent_hash="baseline_seer",
        status="training",
        runtime_state={"stage": "training"},
    )
    rows["r_started"]["started_at"] = "2026-06-08T10:00:00+08:00"

    store.save_runtime_state(
        "r_started",
        role="seer",
        parent_hash="baseline_seer",
        status="reviewing",
        training_games=1,
        runtime_state={"stage": "done"},
        finished_at="2026-06-08T10:30:00+08:00",
    )

    assert rows["r_started"]["started_at"] == "2026-06-08T10:00:00+08:00"
    assert rows["r_started"]["finished_at"] == "2026-06-08T10:30:00+08:00"
    assert rows["r_started"]["status"] == "reviewing"


def test_evolution_store_save_runtime_state_uses_supplied_started_at_on_first_insert():
    from storage.evolution.run_repo import EvolutionStore

    rows: dict[str, dict[str, Any]] = {}
    store = EvolutionStore(FakeEvolutionConnection(rows))

    store.save_runtime_state(
        "r_first_insert",
        role="seer",
        parent_hash="baseline_seer",
        status="reviewing",
        training_games=1,
        runtime_state={"stage": "done"},
        started_at="2026-06-08T10:00:00+08:00",
        finished_at="2026-06-08T10:30:00+08:00",
    )

    assert rows["r_first_insert"]["started_at"] == "2026-06-08T10:00:00+08:00"
    assert rows["r_first_insert"]["finished_at"] == "2026-06-08T10:30:00+08:00"


def test_evolution_store_save_and_get_trust_bundle_audit_row():
    from storage.evolution.run_repo import EvolutionStore

    rows: dict[str, dict[str, Any]] = {}
    trust_bundles: dict[str, dict[str, Any]] = {}
    store = EvolutionStore(FakeEvolutionConnection(rows, trust_bundles))
    bundle = {
        "schema_version": "trust_bundle_v1",
        "trust_bundle_id": "trust_bundle_r_audit_fixture",
        "bundle_hash": "a" * 64,
        "run_id": "r_audit",
        "role": "seer",
        "baseline_version": "baseline_seer",
        "candidate_version": "candidate_seer",
        "gate_report_id": "gate_r_audit",
        "attribution_report_id": "attribution_r_audit",
        "rollback_target": "baseline_seer",
    }

    row = store.save_trust_bundle(bundle)
    by_run = store.get_trust_bundle("r_audit")
    by_id = store.get_trust_bundle("trust_bundle_r_audit_fixture")
    listed = store.list_trust_bundles(role="seer")

    assert row["id"] == "trust_bundle_r_audit_fixture"
    assert trust_bundles["r_audit"]["bundle_hash"] == "a" * 64
    assert by_run is not None
    assert by_run == by_id
    assert by_run["kind"] == "evolution_trust_bundle"
    assert by_run["trust_bundle_id"] == "trust_bundle_r_audit_fixture"
    assert by_run["run_id"] == "r_audit"
    assert by_run["role"] == "seer"
    assert by_run["bundle_hash"] == "a" * 64
    assert by_run["trust_bundle"]["schema_version"] == "trust_bundle_v1"
    assert by_run["trust_bundle"]["rollback_target"] == "baseline_seer"
    assert listed[0]["trust_bundle_id"] == "trust_bundle_r_audit_fixture"

    updated = dict(bundle)
    updated["bundle_hash"] = "b" * 64
    updated["candidate_version"] = "candidate_seer_v2"
    store.save_trust_bundle(updated)

    refreshed = store.get_trust_bundle("r_audit")
    assert refreshed is not None
    assert refreshed["bundle_hash"] == "b" * 64
    assert refreshed["candidate_version"] == "candidate_seer_v2"
    assert trust_bundles["r_audit"]["created_at"] <= trust_bundles["r_audit"]["updated_at"]


@pytest.fixture(autouse=True)
def _fake_pg_provider(monkeypatch: pytest.MonkeyPatch) -> FakeEvolutionStorageProvider:
    import storage.provider as provider_mod

    provider = FakeEvolutionStorageProvider()
    monkeypatch.setattr(provider_mod, "storage_provider_from_env", lambda *, paths=None: provider)
    return provider


def _patch_runtime_registry(monkeypatch: pytest.MonkeyPatch, registry: FakeRuntimeRegistry) -> None:
    import app.graphs.subgraphs.evolve.nodes as nodes

    monkeypatch.setattr(nodes, "_registry", lambda state: registry)


def _write_seer_skills(tmp_path):
    skill_dir = tmp_path / "skills"
    (skill_dir / "seer").mkdir(parents=True)
    (skill_dir / "seer" / "vote.md").write_text(SEER_SKILL, encoding="utf-8")
    return skill_dir


def _training_games():
    return [
        {
            "game_id": "g1",
            "winner": "villagers",
            "days": 4,
            "player_roles": {"1": "seer"},
            "decisions": [
                {"player_id": 1, "action_type": "vote", "action": "vote:3", "reasoning": "P3 lied"},
            ],
        },
        {
            "game_id": "g2",
            "winner": "werewolves",
            "days": 3,
            "player_roles": {"2": "seer"},
            "decisions": [
                {"player_id": 2, "action_type": "vote", "action": "vote:5", "reasoning": "guess"},
            ],
        },
    ]


def test_evolution_store_list_battle_summaries_accepts_jsonb_dict():
    from storage.evolution.run_repo import EvolutionStore

    rows = {
        "r_jsonb": {
            "id": "r_jsonb",
            "role": "seer",
            "battle_result": {"significant": True, "candidate_win_rate": 0.75},
        }
    }
    summaries = EvolutionStore(FakeEvolutionConnection(rows)).list_battle_summaries(role="seer")

    assert summaries == [{"significant": True, "candidate_win_rate": 0.75}]


class TrainingEvidenceGameSubgraph:
    """One-game subgraph fixture with a seer key decision for training_node."""

    def __init__(self):
        self.invocations: list[dict] = []

    async def ainvoke(self, game_state: dict):
        self.invocations.append(dict(game_state))
        return {
            "winner": "villagers",
            "roles": {"1": "seer", "2": "werewolf"},
            "game_events": [
                {"event_type": "game_init", "payload": {"roles": {"1": "seer", "2": "werewolf"}}},
                {"event_type": "night_end", "day": 1, "phase": "night", "target": 2},
            ],
            "decisions": [
                {
                    "decision_id": "d_check",
                    "player_id": 1,
                    "role": "seer",
                    "day": 1,
                    "phase": "night",
                    "action_type": "seer_check",
                    "selected_target": 2,
                    "private_reasoning": "2号发言前后矛盾，查验收益高。",
                    "confidence": 0.82,
                }
            ],
        }


def test_init_evolve_node_rejects_unsafe_run_id():
    with pytest.raises(ValueError, match="Unsafe run_id"):
        asyncio.run(init_evolve_node({"role": "seer", "run_id": "../escape"}))


def test_init_evolve_node_freezes_registry_baseline(tmp_path, monkeypatch):
    paths = _PathsStub(tmp_path)
    registry = FakeRuntimeRegistry(paths.registry_dir)
    baseline = registry.seed_version(
        "seer",
        "seer_v1",
        {"seer/vote.md": SEER_SKILL},
        baseline=True,
    )
    _patch_runtime_registry(monkeypatch, registry)

    out = asyncio.run(init_evolve_node({"role": "seer", "run_id": "r_baseline", "paths": paths}))

    assert out["parent_hash"] == baseline
    assert out["baseline_config"]["role_versions"] == {"seer": baseline}


def test_init_evolve_node_materializes_registry_baseline_skill_dir(tmp_path, monkeypatch):
    paths = _PathsStub(tmp_path)
    registry = FakeRuntimeRegistry(paths.registry_dir)
    baseline = registry.seed_version(
        "seer",
        "seer_v1",
        {"seer/vote.md": SEER_SKILL},
        baseline=True,
    )
    _patch_runtime_registry(monkeypatch, registry)
    legacy_dir = tmp_path / "legacy_skills"

    out = asyncio.run(
        init_evolve_node(
            {
                "role": "seer",
                "run_id": "r_baseline_skill_dir",
                "paths": paths,
                "config": {"skill_dir": str(legacy_dir)},
            }
        )
    )

    baseline_dir = Path(out["baseline_skill_dir"])
    assert out["parent_hash"] == baseline
    assert baseline_dir != legacy_dir
    assert (baseline_dir / "seer" / "vote.md").read_text(encoding="utf-8") == SEER_SKILL
    assert not (baseline_dir / "seer" / "seer" / "vote.md").exists()


@pytest.mark.parametrize("release_stage", ["shadow", "canary"])
def test_init_evolve_node_rejects_experimental_explicit_parent(tmp_path, monkeypatch, release_stage):
    paths = _PathsStub(tmp_path)
    registry = FakeRuntimeRegistry(paths.registry_dir)
    registry.seed_version("seer", "seer_v1", {"seer/vote.md": SEER_SKILL}, baseline=True)
    registry.publish_skills(
        "seer",
        {"seer/vote.md": SEER_SKILL + f"\n# {release_stage}\n"},
        version_id=f"seer_{release_stage}_v1",
        release_stage=release_stage,
    )
    _patch_runtime_registry(monkeypatch, registry)

    with pytest.raises(ValueError, match=f"release_stage={release_stage}"):
        asyncio.run(
            init_evolve_node(
                {
                    "role": "seer",
                    "run_id": f"r_parent_{release_stage}",
                    "paths": paths,
                    "parent_hash": f"seer_{release_stage}_v1",
                }
            )
        )


def test_init_evolve_node_rejects_explicit_parent_when_registry_check_fails(tmp_path, monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    def _boom(state):
        raise RuntimeError("registry down")

    monkeypatch.setattr(nodes, "_registry", _boom)

    with pytest.raises(RuntimeError, match="explicit parent release-stage check failed"):
        asyncio.run(
            init_evolve_node(
                {
                    "role": "seer",
                    "run_id": "r_parent_registry_down",
                    "paths": _PathsStub(tmp_path),
                    "parent_hash": "seer_v_explicit",
                }
            )
        )


def test_init_evolve_node_rejects_missing_explicit_parent(tmp_path, monkeypatch):
    paths = _PathsStub(tmp_path)
    registry = FakeRuntimeRegistry(paths.registry_dir)
    registry.seed_version("seer", "seer_v1", {"seer/vote.md": SEER_SKILL}, baseline=True)
    _patch_runtime_registry(monkeypatch, registry)

    with pytest.raises(ValueError, match="explicit parent_hash must resolve"):
        asyncio.run(
            init_evolve_node(
                {
                    "role": "seer",
                    "run_id": "r_parent_missing",
                    "paths": paths,
                    "parent_hash": "missing_parent",
                }
            )
        )


def test_init_evolve_node_warns_when_registry_baseline_unavailable(tmp_path, monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    def _boom(state):
        raise RuntimeError("registry down")

    monkeypatch.setattr(nodes, "_registry", _boom)
    out = asyncio.run(init_evolve_node({"role": "seer", "run_id": "r_no_registry", "paths": _PathsStub(tmp_path)}))

    assert out["parent_hash"] == "baseline_seer"
    assert out["baseline_config"]["role_versions"] == {"seer": "baseline_seer"}
    assert any("baseline freeze failed" in warning and "registry down" in warning for warning in out["warnings"])


def test_training_node_attaches_compact_evidence(tmp_path):
    game = TrainingEvidenceGameSubgraph()
    baseline_dir = str(tmp_path / "frozen_baseline")
    legacy_dir = str(tmp_path / "legacy_skills")
    state = {
        "role": "seer",
        "run_id": "evolve_evidence",
        "config": {"training_games": 1, "seed_start": 7, "max_days": 2, "game_concurrency": 1},
        "baseline_skill_dir": baseline_dir,
        "skill_dir": legacy_dir,
        "paths": _PathsStub(tmp_path),
        "game_subgraph": game,
    }

    out = asyncio.run(training_node(state))

    assert len(game.invocations) == 1
    assert game.invocations[0]["skill_dir"] == baseline_dir
    training_game = out["training_games"][0]
    evidence = training_game["evidence"]
    assert evidence["counts"]["decisions"] == 1
    assert evidence["counts"]["role_key_decisions"] == 1
    key = evidence["role_key_decisions"][0]
    assert key["decision_id"] == "d_check"
    assert key["action_type"] == "seer_check"
    assert key["role"] == "seer"
    assert key["target"] == 2
    assert "查验收益高" in key["reason"]


def test_training_node_resumes_only_missing_seeds(tmp_path):
    game = TrainingEvidenceGameSubgraph()
    state = {
        "role": "seer",
        "run_id": "evolve_resume_training",
        "config": {"training_games": 3, "seed_start": 7, "max_days": 2, "game_concurrency": 1},
        "paths": _PathsStub(tmp_path),
        "game_subgraph": game,
        "training_games": [
            {"game_id": "existing", "seed": 7, "winner": "villagers", "evidence": {"existing": True}},
        ],
    }

    out = asyncio.run(training_node(state))

    assert [invocation["seed"] for invocation in game.invocations] == [8, 9]
    assert [item["seed"] for item in out["training_games"]] == [7, 8, 9]
    assert out["training_games"][0]["evidence"] == {"existing": True}


def test_consolidate_node_reuses_persisted_proposals(tmp_path, monkeypatch):
    async def fail_chain(*_args, **_kwargs):
        raise AssertionError("consolidation chain should not run")

    monkeypatch.setattr("app.services.chain.run_consolidate_chain", fail_chain)
    proposal = {
        "proposal_id": "existing",
        "target_file": "seer/vote.md",
        "action_type": "append_rule",
    }
    state = {
        "role": "seer",
        "run_id": "evolve_resume_proposal",
        "config": {"max_proposals": 3},
        "training_games": [{"game_id": "g1", "winner": "villagers"}],
        "proposals": [proposal],
        "resume_stage": "applying",
    }

    out = asyncio.run(consolidate_node(state))

    assert out["proposals"] == [proposal]
    assert out["progress"]["resumed"] is True


def test_training_node_attaches_decision_judge_when_enabled(tmp_path):
    game = TrainingEvidenceGameSubgraph()
    judge_calls = []

    async def fake_judge(messages):
        judge_calls.append(messages)
        return (
            '{"schema_version":"1.0","decision_id":"d_check","score":8.0,'
            '"quality":"good","reason":"查验命中狼人且理由明确",'
            '"evidence_refs":["rule_natural_key_action"],"mistake_tags":[],'
            '"suggestion":"继续优先查验发言矛盾位","confidence":0.9}'
        )

    state = {
        "role": "seer",
        "run_id": "evolve_judge_evidence",
        "config": {
            "training_games": 1,
            "seed_start": 7,
            "max_days": 2,
            "game_concurrency": 1,
            "enable_llm_judge": True,
            "training_judge_max_decisions": 1,
        },
        "paths": _PathsStub(tmp_path),
        "game_subgraph": game,
        "decision_judge_fn": fake_judge,
    }

    out = asyncio.run(training_node(state))

    assert len(judge_calls) == 1
    evidence = out["training_games"][0]["evidence"]
    assert evidence["decision_judge"]["status"] == "ok"
    assert evidence["decision_judge"]["summary"]["average_score"] == 8.0
    assert evidence["decision_judge"]["metrics"]["judged"] == 1
    key = evidence["role_key_decisions"][0]
    assert key["decision_id"] == "d_check"
    assert key["judge"]["score"] == 8.0
    assert key["judge"]["quality"] == "good"


def test_training_evidence_judges_games_concurrently_with_shared_limit(monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    active = 0
    max_active = 0
    semaphore_ids: set[int] = set()

    monkeypatch.setattr(
        nodes,
        "_build_training_evidence_summary",
        lambda _game, *, role: {
            "role": role,
            "key_decisions": [],
            "role_key_decisions": [],
            "counts": {},
        },
    )

    async def fake_judge_key_decisions(_model, **kwargs):
        nonlocal active, max_active
        semaphore = kwargs["shared_semaphore"]
        semaphore_ids.add(id(semaphore))
        async with semaphore:
            active += 1
            max_active = max(max_active, active)
            try:
                await asyncio.sleep(0.01)
            finally:
                active -= 1
        return {
            "status": "ok",
            "summary": {"average_score": None},
            "metrics": {"judged": 0},
            "judgments": [],
            "warnings": [],
        }

    monkeypatch.setattr("app.lib.decision_judge.judge_key_decisions", fake_judge_key_decisions)
    games = [
        {"game_id": f"training_judge_{index}", "winner": "villagers", "error": None}
        for index in range(5)
    ]

    enriched = asyncio.run(_attach_training_evidence(
        games,
        role="seer",
        model=object(),
        enable_judge=True,
        judge_concurrency=2,
    ))

    assert len(enriched) == 5
    assert max_active == 2
    assert len(semaphore_ids) == 1
    assert all(game["evidence"]["decision_judge"]["status"] == "ok" for game in enriched)


def test_scenario_replay_node_freezes_contract_snapshots(tmp_path):
    game = TrainingEvidenceGameSubgraph()
    state = {
        "role": "seer",
        "run_id": "evolve_scenario",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_scenario",
        "baseline_skill_dir": str(tmp_path / "baseline"),
        "candidate_skill_dir": str(tmp_path / "candidate"),
        "config": {
            "training_games": 1,
            "seed_start": 7,
            "max_days": 2,
            "game_concurrency": 1,
            "scenario_replay_max_snapshots": 1,
        },
        "paths": _PathsStub(tmp_path),
        "game_subgraph": game,
        "proposals": [{
            "proposal_id": "p1",
            "target_file": "seer/vote.md",
            "action_type": "append_rule",
            "hypothesis": "Checking contradiction drivers improves seer information gain.",
        }],
        "diff": [{
            "filename": "seer/vote.md",
            "action": "modified",
            "proposal_ref": "p1",
        }],
    }

    trained = asyncio.run(training_node(state))
    out = asyncio.run(scenario_replay_node(trained))

    assert out["current_stage"] == "scenario_replay"
    assert out["status"] == "scenario_replay"
    assert len(out["scenario_snapshots"]) == 1
    snapshot = out["scenario_snapshots"][0]
    assert snapshot["schema_version"] == "scenario_snapshot_v1"
    assert snapshot["source_game_id"] == "evolve_scenario_train_001"
    assert snapshot["source_decision_id"] == "d_check"
    assert snapshot["role"] == "seer"
    assert snapshot["actor_id"] == 1
    assert snapshot["legal_actions"] == ["seer_check"]
    assert snapshot["proposal_ids"] == ["p1"]
    assert snapshot["baseline_version"] == "baseline_seer"
    assert snapshot["candidate_version"] == "candidate_scenario"
    assert snapshot["selected_skill_context"][0]["proposal_ref"] == "p1"
    assert snapshot["players_public_state"]
    assert all("known_role" not in row for row in snapshot["players_public_state"])
    assert all("public_role" not in row for row in snapshot["players_public_state"])
    report = out["scenario_replay_report"]
    assert report["schema_version"] == "scenario_replay_report_v1"
    assert report["execution_mode"] == "contract_only"
    assert report["summary"]["verdict"] == "contract_ready"
    assert report["summary"]["scenario_count"] == 1
    assert report["results"][0]["verdict"] == "contract_ready"


def test_training_node_records_evidence_extraction_warning(tmp_path, monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    def _boom(game, *, role):
        raise RuntimeError("evidence boom")

    monkeypatch.setattr(nodes, "_build_training_evidence_summary", _boom)
    game = TrainingEvidenceGameSubgraph()
    state = {
        "role": "seer",
        "run_id": "evolve_evidence_warning",
        "config": {"training_games": 1, "seed_start": 7, "max_days": 2, "game_concurrency": 1},
        "paths": _PathsStub(tmp_path),
        "game_subgraph": game,
    }

    out = asyncio.run(training_node(state))

    assert "warnings" in out
    assert "evidence extraction failed" in out["warnings"][0]
    assert "evidence boom" in out["warnings"][0]
    training_game = out["training_games"][0]
    assert training_game["evidence"]["error"] == "evidence boom"
    assert training_game["warnings"] == out["warnings"]


def test_training_node_records_unexpected_failure(tmp_path, monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    async def _boom(*args, **kwargs):
        raise RuntimeError("scheduler down")

    monkeypatch.setattr(nodes, "_run_games", _boom)
    state = {
        "role": "seer",
        "run_id": "r_training_fail",
        "config": {"training_games": 1, "seed_start": 7, "max_days": 2, "game_concurrency": 1},
        "paths": _PathsStub(tmp_path),
        "game_subgraph": TrainingEvidenceGameSubgraph(),
    }

    out = asyncio.run(training_node(state))

    assert out["training_games"] == []
    assert out["status"] == "failed"
    assert out["errors"] == ["training: scheduler down"]
    assert out["current_stage"] == "training"
    assert out["progress"]["stage"] == "training"
    assert out["progress"]["completed_games"] == 0
    assert out["last_heartbeat_at"]
    assert out["diagnostics"][0]["kind"] == "training_error"
    assert out["diagnostics"][0]["stage"] == "training.run_games"
    assert out["diagnostics"][0]["exception_type"] == "RuntimeError"


def test_consolidate_node_parses_llm_proposals(tmp_path):
    skill_dir = _write_seer_skills(tmp_path)
    raw = (
        '{"trends": ["seer votes too early"], "proposals": [{'
        '"proposal_id": "p1", "target_file": "seer/vote.md", "action_type": "append_rule", '
        '"content": "Wait one round before voting.", "rationale": "two losses from early votes", '
        '"hypothesis": "When day one vote evidence is thin, waiting one round improves seer voting quality.", '
        '"trigger_condition": {"phase": ["day1"], "public_state": ["thin_vote_evidence"]}, '
        '"expected_effect": {"primary_metric": "role_score", "expected_direction": "increase"}, '
        '"metric_targets": {"min_role_score_delta": 0.2}, '
        '"evidence_game_ids": ["g1", "g2"], '
        '"confidence": 0.8, "risk": "low", "expected_metric": "role_score", '
        '"expected_direction": "improve", "evidence": [{"game_id": "g1"}, {"game_id": "g2"}]}]}'
    )
    model = FakeModel([raw])
    state = {
        "role": "seer",
        "run_id": "evolve_test",
        "parent_hash": "baseline_seer",
        "config": {"max_proposals": 3, "skill_dir": str(skill_dir)},
        "model": model,
        "training_games": _training_games(),
    }
    out = asyncio.run(consolidate_node(state))

    assert len(model.calls) == 1
    assert out["status"] == "consolidating"
    assert len(out["proposals"]) == 1
    prop = out["proposals"][0]
    assert prop["target_file"] == "seer/vote.md"
    assert prop["status"] == "proposed"
    assert prop["hypothesis"].startswith("When day one vote evidence")
    assert prop["preflight_status"] == "passed"
    assert out["generated_proposal_ids"] == ["p1"]
    assert out["preflight_passed_proposal_ids"] == ["p1"]
    assert out["preflight_rejected_proposal_ids"] == []
    assert out["consolidation"]["trends"] == ["seer votes too early"]


def test_consolidate_node_records_skill_load_warnings(tmp_path):
    skill_dir = _write_seer_skills(tmp_path)
    (skill_dir / "seer" / "broken.md").write_text("# missing front matter\n", encoding="utf-8")
    raw = '{"trends": [], "proposals": []}'
    model = FakeModel([raw])
    state = {
        "role": "seer",
        "run_id": "evolve_test",
        "parent_hash": "baseline_seer",
        "config": {"max_proposals": 3, "skill_dir": str(skill_dir)},
        "model": model,
        "training_games": _training_games(),
    }

    out = asyncio.run(consolidate_node(state))

    assert len(model.calls) == 1
    assert out["proposals"] == []
    assert any(
        "consolidate: skill load error: seer/broken.md: missing YAML front matter" in warning
        for warning in out["warnings"]
    )


def test_consolidate_node_surfaces_parse_errors_and_filters_bad_proposals(tmp_path, monkeypatch):
    skill_dir = _write_seer_skills(tmp_path)
    _patch_runtime_registry(monkeypatch, FakeRuntimeRegistry(tmp_path / "registry"))
    raw = (
        '{"trends": ["x"], "proposals": [{'
        '"proposal_id": "p_bad", "target_file": "seer/vote.md", "action_type": "append_rule", '
        '"content": "Wait for two checks.", "rationale": "only one supporting game", '
        '"confidence": 0.8, "risk": "low", "evidence": [{"game_id": "g1"}]'
        '}]}'
    )
    model = FakeModel([raw])
    state = {
        "role": "seer",
        "run_id": "evolve_test",
        "parent_hash": "baseline_seer",
        "config": {"max_proposals": 3, "skill_dir": str(skill_dir)},
        "model": model,
        "training_games": _training_games(),
    }

    out = asyncio.run(consolidate_node(state))

    assert len(model.calls) == 1
    assert out["proposals"] == []
    assert out["consolidation"]["proposals"] == []
    assert out["consolidation"]["warnings"] == out["warnings"]
    assert any("at least 2 distinct game_id" in warning for warning in out["warnings"])


def test_consolidate_prompt_includes_training_key_decisions(tmp_path):
    skill_dir = _write_seer_skills(tmp_path)
    raw = '{"trends": [], "proposals": []}'
    model = FakeModel([raw])
    game = _training_games()[0]
    game["evidence"] = {
        "role_key_decisions": [
            {
                "decision_id": "d_check",
                "day": 1,
                "phase": "night",
                "action_type": "seer_check",
                "player_id": 1,
                "role": "seer",
                "target": 3,
                "impact_level": "high",
                "key_reason": "rule_natural_key_action",
                "reason": "查验 3 号能验证白天冲突。",
                "notes": ["规则上直接改变信息。"],
            }
        ],
        "counts": {"decisions": 1, "key_decisions": 1, "role_key_decisions": 1},
    }
    state = {
        "role": "seer",
        "run_id": "r",
        "parent_hash": "baseline_seer",
        "config": {"max_proposals": 3, "skill_dir": str(skill_dir)},
        "model": model,
        "training_games": [game],
    }

    asyncio.run(consolidate_node(state))

    user_content = model.calls[0][1]["content"]
    assert "key_decisions" in user_content
    assert "decision_id" in user_content
    assert "d_check" in user_content
    assert "seer_check" in user_content


def test_consolidate_prompt_includes_decision_judge_signal(tmp_path):
    skill_dir = _write_seer_skills(tmp_path)
    raw = '{"trends": [], "proposals": []}'
    model = FakeModel([raw])
    game = _training_games()[0]
    game["evidence"] = {
        "role_key_decisions": [
            {
                "decision_id": "d_check",
                "day": 1,
                "phase": "night",
                "action_type": "seer_check",
                "player_id": 1,
                "role": "seer",
                "target": 3,
                "impact_level": "high",
                "key_reason": "rule_natural_key_action",
                "reason": "查验 3 号能验证白天冲突。",
                "judge": {
                    "score": 4.0,
                    "quality": "bad",
                    "reason": "过度依赖单点冲突，信息收益不足。",
                    "mistake_tags": ["low_information_gain"],
                    "rubric_misses": ["missed_multi_player_information_gain"],
                    "related_skills": ["seer/night_check.md"],
                    "suggestion": "优先查验能打开多人关系链的位置。",
                    "confidence": 0.75,
                },
            }
        ],
        "decision_judge": {
            "status": "ok",
            "summary": {
                "judged": 1,
                "average_score": 4.0,
                "quality_counts": {"bad": 1},
                "top_mistake_tags": [{"tag": "low_information_gain", "count": 1}],
                "top_rubric_misses": [{"miss": "missed_multi_player_information_gain", "count": 1}],
                "related_skills": [{"skill": "seer/night_check.md", "count": 1}],
            },
            "metrics": {"judged": 1, "failed": 0},
        },
        "counts": {"decisions": 1, "key_decisions": 1, "role_key_decisions": 1},
    }
    state = {
        "role": "seer",
        "run_id": "r",
        "parent_hash": "baseline_seer",
        "config": {"max_proposals": 3, "skill_dir": str(skill_dir)},
        "model": model,
        "training_games": [game],
    }

    asyncio.run(consolidate_node(state))

    user_content = model.calls[0][1]["content"]
    assert "decision_judge" in user_content
    assert "average_score" in user_content
    assert "low_information_gain" in user_content
    assert "missed_multi_player_information_gain" in user_content
    assert "seer/night_check.md" in user_content
    assert "优先查验能打开多人关系链的位置" in user_content


def test_consolidate_node_no_games_yields_no_proposals(tmp_path):
    skill_dir = _write_seer_skills(tmp_path)
    model = FakeModel(["{}"])
    state = {
        "role": "seer",
        "run_id": "r",
        "config": {"max_proposals": 3, "skill_dir": str(skill_dir)},
        "model": model,
        "training_games": [],
    }
    out = asyncio.run(consolidate_node(state))
    assert out["proposals"] == []
    assert out["consolidation"] is None
    assert model.calls == []  # no LLM call when there is nothing to consolidate


def test_consolidate_node_dedups_rejected_proposals(tmp_path, monkeypatch):
    """A proposal repeating a rejected direction is dropped after parsing."""
    paths = _PathsStub(tmp_path)
    registry = FakeRuntimeRegistry(paths.registry_dir)
    registry.save_rejected("seer", [{"target_file": "seer/vote.md", "rationale": "wait one round"}])
    _patch_runtime_registry(monkeypatch, registry)
    skill_dir = _write_seer_skills(tmp_path)

    # LLM returns a proposal on the same file with the same rationale → dup.
    raw = (
        '{"trends": ["x"], "proposals": [{'
        '"proposal_id": "p1", "target_file": "seer/vote.md", "action_type": "append_rule", '
        '"content": "c", "rationale": "wait one round", "confidence": 0.8, "risk": "low", '
        '"hypothesis": "When early vote evidence is weak, waiting one round improves seer voting quality.", '
        '"trigger_condition": {"phase": ["day1"], "public_state": ["weak_vote_evidence"]}, '
        '"expected_effect": {"primary_metric": "role_score", "expected_direction": "increase"}, '
        '"metric_targets": {"min_role_score_delta": 0.2}, '
        '"evidence_game_ids": ["g1", "g2"], '
        '"evidence": [{"game_id": "g1"}, {"game_id": "g2"}]}]}'
    )
    model = FakeModel([raw])
    state = {
        "role": "seer",
        "run_id": "r",
        "parent_hash": "baseline_seer",
        "config": {"max_proposals": 3, "skill_dir": str(skill_dir)},
        "paths": paths,
        "model": model,
        "training_games": _training_games(),
    }
    out = asyncio.run(consolidate_node(state))
    assert len(model.calls) == 1  # LLM was consulted
    assert out["proposals"] == []  # but the duplicate proposal was dropped
    assert out["generated_proposal_ids"] == ["p1"]
    assert out["preflight_passed_proposal_ids"] == []
    assert out["preflight_rejected_proposal_ids"] == ["p1"]


def test_consolidate_node_records_rejected_buffer_warning(tmp_path, monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    skill_dir = _write_seer_skills(tmp_path)
    raw = '{"trends": [], "proposals": []}'
    model = FakeModel([raw])

    def _boom(state):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(nodes, "_registry", _boom)
    state = {
        "role": "seer",
        "run_id": "r",
        "parent_hash": "baseline_seer",
        "config": {"max_proposals": 3, "skill_dir": str(skill_dir)},
        "model": model,
        "training_games": _training_games(),
    }

    out = asyncio.run(consolidate_node(state))

    assert len(model.calls) == 1
    assert out["proposals"] == []
    assert "warnings" in out
    assert "failed to load rejected buffer" in out["warnings"][0]
    assert "registry unavailable" in out["warnings"][0]


def test_apply_node_writes_candidate_skills(tmp_path):
    skill_dir = _write_seer_skills(tmp_path)
    # Consolidation with one eligible proposal.
    consolidation = {
        "role": "seer",
        "run_id": "evolve_test",
        "proposals": [{
            "proposal_id": "p1",
            "target_file": "seer/vote.md",
            "action_type": "append_rule",
            "content": "Wait one round before voting.",
            "rationale": "two losses",
            "confidence": 0.8,
            "risk": "low",
            "status": "proposed",
        }],
    }
    # Applier LLM returns the full (modified) file set.
    new_file = SEER_SKILL + "\n- Wait one round before voting.\n"
    apply_raw = '{"files": {"seer/vote.md": %s}, "changes": [{"filename": "seer/vote.md", "action": "modified"}]}' % _json_str(new_file)
    model = FakeModel([apply_raw])
    state = {
        "role": "seer",
        "run_id": "evolve_test",
        "parent_hash": "baseline_seer",
        "config": {"skill_dir": str(skill_dir)},
        "paths": _PathsStub(tmp_path),
        "model": model,
        "consolidation": consolidation,
        "proposals": consolidation["proposals"],
    }
    out = asyncio.run(apply_node(state))

    assert len(model.calls) == 1
    assert out["status"] == "applying"
    assert out["candidate_hash"] == "candidate_evolve_test"
    assert len(out["diff"]) == 1
    assert out["diff"][0]["filename"] == "seer/vote.md"
    # Candidate file written to disk with the new content.
    candidate = out["candidate_skill_dir"]
    assert candidate is not None
    from pathlib import Path
    written = (Path(candidate) / "seer" / "vote.md").read_text(encoding="utf-8")
    assert "Wait one round before voting." in written


def test_apply_node_rejects_unauthorized_apply_output_before_writing_candidate(tmp_path):
    skill_dir = tmp_path / "skills"
    (skill_dir / "seer").mkdir(parents=True)
    (skill_dir / "hunter").mkdir(parents=True)
    vote_skill = SEER_SKILL
    check_skill = SEER_SKILL.replace("name: seer_vote", "name: seer_check").replace(
        "# Seer voting",
        "# Seer checks",
    )
    hunter_skill = SEER_SKILL.replace("name: seer_vote", "name: hunter_vote").replace(
        "role: seer",
        "role: hunter",
    )
    (skill_dir / "seer" / "vote.md").write_text(vote_skill, encoding="utf-8")
    (skill_dir / "seer" / "check.md").write_text(check_skill, encoding="utf-8")
    (skill_dir / "hunter" / "shot_timing.md").write_text(hunter_skill, encoding="utf-8")

    consolidation = {
        "role": "seer",
        "run_id": "evolve_sanitized",
        "proposals": [{
            "proposal_id": "p1",
            "target_file": "seer/vote.md",
            "action_type": "append_rule",
            "content": "Wait one round before voting.",
            "confidence": 0.8,
            "risk": "low",
            "status": "proposed",
        }],
    }
    modified_vote = vote_skill + "\n- Wait one round before voting.\n"
    modified_hunter = hunter_skill + "\n- Unauthorized hunter change.\n"
    unauthorized_new = hunter_skill.replace("name: hunter_vote", "name: white_wolf_extra").replace(
        "role: hunter",
        "role: white_wolf_king",
    )
    raw = json.dumps({
        "files": {
            "seer/vote.md": modified_vote,
            "hunter/shot_timing.md": modified_hunter,
            "white_wolf_king/self_destruct_timing.md": unauthorized_new,
        },
        "changes": [],
    })
    state = {
        "role": "seer",
        "run_id": "evolve_sanitized",
        "parent_hash": "baseline_seer",
        "config": {"skill_dir": str(skill_dir)},
        "paths": _PathsStub(tmp_path),
        "model": FakeModel([raw]),
        "consolidation": consolidation,
        "proposals": consolidation["proposals"],
    }

    out = asyncio.run(apply_node(state))

    assert out["candidate_hash"] == "baseline_seer"
    assert out["candidate_skill_dir"] is None
    assert out["diff"] == []
    assert any("preflight failed" in item for item in out["warnings"])
    assert any("hunter/shot_timing.md" in item for item in out["warnings"])
    assert any("white_wolf_king/self_destruct_timing.md" in item for item in out["warnings"])
    report = out["preflight_reports"][-1]
    assert report["kind"] == "apply_output_preflight"
    assert report["status"] == "failed"
    assert report["blocking"] is True


def test_apply_node_reuses_persisted_diff_and_candidate_directory(tmp_path, monkeypatch):
    candidate_dir = tmp_path / "candidate"
    candidate_dir.mkdir()

    async def fail_chain(*_args, **_kwargs):
        raise AssertionError("apply chain should not run")

    monkeypatch.setattr("app.services.chain.run_apply_chain", fail_chain)
    persisted_diff = [{
        "target_file": "seer/vote.md",
        "before_hash": "before",
        "after_hash": "after",
        "proposal_ref": "p1",
    }]
    state = {
        "role": "seer",
        "run_id": "resume_apply",
        "parent_hash": "baseline",
        "candidate_hash": "candidate",
        "candidate_skill_dir": str(candidate_dir),
        "diff": persisted_diff,
        "proposals": [{
            "proposal_id": "p1",
            "target_file": "seer/vote.md",
            "action_type": "append_rule",
        }],
        "resume_stage": "applying",
    }

    out = asyncio.run(apply_node(state))

    assert out["diff"] == persisted_diff
    assert out["progress"]["resumed"] is True


def test_apply_prompt_only_includes_eligible_target_files():
    from app.lib.evolve import SkillProposal, _build_apply_messages

    messages = _build_apply_messages(
        {
            "seer/vote.md": SEER_SKILL,
            "hunter/shot_timing.md": "HUNTER SECRET",
        },
        [
            SkillProposal(
                proposal_id="p1",
                target_file="seer/vote.md",
                action_type="append_rule",
                content="Wait one round.",
                confidence=0.8,
                risk="low",
            )
        ],
        "seer",
    )

    prompt = messages[0]["content"]
    assert "### seer/vote.md" in prompt
    assert "hunter/shot_timing.md" not in prompt
    assert "HUNTER SECRET" not in prompt
    assert "Return ONLY files targeted by the eligible proposals" in prompt


@pytest.mark.parametrize(
    "raw_template",
    [
        "```json\n{payload}\n```",
        "Here is the patch:\n\n{payload}\n\nDone.",
    ],
)
def test_parse_apply_output_extracts_json_object(raw_template):
    from app.lib.evolve import _parse_apply_output

    new_file = SEER_SKILL + "\n- Wait one round before voting.\n"
    payload = (
        '{"files": {"seer/vote.md": %s}, '
        '"changes": [{"filename": "seer/vote.md", "action": "modified"}]}'
    ) % _json_str(new_file)

    parsed = _parse_apply_output(raw_template.format(payload=payload))

    assert parsed["files"]["seer/vote.md"] == new_file
    assert parsed["changes"][0]["filename"] == "seer/vote.md"


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ('["not", "an", "object"]', "LLM output is not a JSON object"),
        ('{"changes": []}', "LLM output missing 'files' object"),
        ('{"files": []}', "LLM output missing 'files' object"),
    ],
)
def test_parse_apply_output_requires_files_object(raw, message):
    from app.lib.evolve import _parse_apply_output

    with pytest.raises(ValueError, match=message):
        _parse_apply_output(raw)


def test_apply_node_records_candidate_write_failure(tmp_path, monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    skill_dir = _write_seer_skills(tmp_path)
    consolidation = {
        "role": "seer",
        "run_id": "evolve_write_fail",
        "proposals": [{
            "proposal_id": "p1",
            "target_file": "seer/vote.md",
            "action_type": "append_rule",
            "content": "Wait one round before voting.",
            "rationale": "two losses",
            "confidence": 0.8,
            "risk": "low",
            "status": "proposed",
        }],
    }
    new_file = SEER_SKILL + "\n- Wait one round before voting.\n"
    apply_raw = '{"files": {"seer/vote.md": %s}, "changes": [{"filename": "seer/vote.md", "action": "modified"}]}' % _json_str(new_file)
    model = FakeModel([apply_raw])

    def _boom(state, skills):
        raise RuntimeError("candidate disk unavailable")

    monkeypatch.setattr(nodes, "_write_candidate_skills", _boom)
    state = {
        "role": "seer",
        "run_id": "evolve_write_fail",
        "parent_hash": "baseline_seer",
        "config": {"skill_dir": str(skill_dir)},
        "paths": _PathsStub(tmp_path),
        "model": model,
        "consolidation": consolidation,
        "proposals": consolidation["proposals"],
    }

    out = asyncio.run(apply_node(state))

    assert out["candidate_hash"] == "baseline_seer"
    assert out["candidate_skill_dir"] is None
    assert out["diff"] == []
    assert "apply: failed to write candidate skills: candidate disk unavailable" in out["errors"]
    assert out["warnings"] == out["errors"]


def test_apply_node_records_current_skill_read_failure(tmp_path, monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    skill_dir = _write_seer_skills(tmp_path)
    consolidation = {
        "role": "seer",
        "run_id": "evolve_read_fail",
        "proposals": [{
            "proposal_id": "p1",
            "target_file": "seer/vote.md",
            "action_type": "append_rule",
            "content": "Wait one round before voting.",
            "rationale": "two losses",
            "confidence": 0.8,
            "risk": "low",
            "status": "proposed",
        }],
    }
    model = FakeModel([])

    def _boom(skill_dir):
        raise RuntimeError("baseline skills unreadable")

    monkeypatch.setattr(nodes, "_read_skill_contents", _boom)
    state = {
        "role": "seer",
        "run_id": "evolve_read_fail",
        "parent_hash": "baseline_seer",
        "config": {"skill_dir": str(skill_dir)},
        "paths": _PathsStub(tmp_path),
        "model": model,
        "consolidation": consolidation,
        "proposals": consolidation["proposals"],
    }

    out = asyncio.run(apply_node(state))

    assert out["candidate_hash"] == "baseline_seer"
    assert out["candidate_skill_dir"] is None
    assert out["diff"] == []
    assert model.calls == []
    assert "apply: failed to read current skills: baseline skills unreadable" in out["errors"]
    assert out["warnings"] == out["errors"]


def test_apply_node_no_proposals_falls_back_to_baseline(tmp_path):
    skill_dir = _write_seer_skills(tmp_path)
    model = FakeModel([])  # must not be called
    state = {
        "role": "seer",
        "run_id": "r",
        "parent_hash": "baseline_seer",
        "config": {"skill_dir": str(skill_dir)},
        "paths": _PathsStub(tmp_path),
        "model": model,
        "consolidation": {"role": "seer", "proposals": []},
        "proposals": [],
    }
    out = asyncio.run(apply_node(state))
    assert out["candidate_hash"] == "baseline_seer"
    assert out["candidate_skill_dir"] is None
    assert out["diff"] == []
    assert model.calls == []


def test_apply_node_rejects_unsafe_edit(tmp_path):
    """Applier validation rejects edits to files without an eligible proposal."""
    skill_dir = _write_seer_skills(tmp_path)
    consolidation = {
        "role": "seer",
        "run_id": "r",
        "proposals": [{
            "proposal_id": "p1",
            "target_file": "seer/vote.md",
            "action_type": "append_rule",
            "content": "x",
            "confidence": 0.8,
            "risk": "low",
            "status": "proposed",
        }],
    }
    # LLM tries to change the role front-matter (illegal) -> validation fails -> fallback.
    bad = SEER_SKILL.replace("role: seer", "role: witch")
    raw = '{"files": {"seer/vote.md": %s}, "changes": []}' % _json_str(bad)
    model = FakeModel([raw])
    state = {
        "role": "seer",
        "run_id": "r",
        "parent_hash": "baseline_seer",
        "config": {"skill_dir": str(skill_dir)},
        "paths": _PathsStub(tmp_path),
        "model": model,
        "consolidation": consolidation,
        "proposals": consolidation["proposals"],
    }
    out = asyncio.run(apply_node(state))
    assert out["candidate_hash"] == "baseline_seer"
    assert out["diff"] == []
    assert "warnings" in out
    assert any("validation failed" in item for item in out["warnings"])
    assert out["consolidation"]["errors"] == out["warnings"]


def test_apply_smoke_test_reports_skill_loader_diagnostics():
    from app.lib.evolve import _smoke_test

    ok, message = _smoke_test({"broken.md": "# missing front matter\n"})

    assert ok is False
    assert "load_markdown_skills returned empty list" in message
    assert "broken.md: missing YAML front matter" in message


def _json_str(value: str) -> str:
    import json

    return json.dumps(value)


class _PathsStub:
    def __init__(self, root):
        from pathlib import Path

        self.evolution_dir = Path(root) / "evolution"
        self.registry_dir = Path(root) / "registry"


# ---------------------------------------------------------------------------
# battle_node — fixed-seed baseline vs candidate A/B
# ---------------------------------------------------------------------------

class FakeGameSubgraph:
    """Returns a winner per effective skill source for one role.

    The 'effective' skill dir for the evolving role is role_skill_dirs[role]
    if present, else skill_dir — mirroring create_agents_node. Keying off that
    lets a test distinguish baseline vs candidate sides.
    """

    def __init__(self, win_by_dir: dict, role: str = "seer"):
        self._win_by_dir = win_by_dir
        self._role = role
        self.invocations: list[dict] = []

    async def ainvoke(self, game_state: dict):
        self.invocations.append(dict(game_state))
        role_dirs = game_state.get("role_skill_dirs") or {}
        effective = role_dirs.get(self._role, game_state.get("skill_dir"))
        winner = self._win_by_dir.get(str(effective), "werewolves")
        return {
            "winner": winner,
            "roles": {"1": self._role},
            "game_events": [{"day": 2}],
            "decisions": [],
        }


def test_battle_node_runs_ab_and_flags_significant(tmp_path):
    baseline_dir = str(tmp_path / "baseline_skills")
    legacy_dir = str(tmp_path / "legacy_skills")
    candidate_dir = str(tmp_path / "candidate_skills")
    # Candidate (seer = villagers team) wins every game; baseline loses every game.
    game = FakeGameSubgraph({baseline_dir: "werewolves", candidate_dir: "villagers"})
    state = {
        "role": "seer",
        "run_id": "r",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_r",
        "candidate_skill_dir": candidate_dir,
        "baseline_skill_dir": baseline_dir,
        "skill_dir": legacy_dir,
        "config": {"battle_games": 4, "skill_dir": legacy_dir},
        "proposals": [{
            "proposal_id": "p1",
            "target_file": "seer/vote.md",
            "risk": "low",
            "confidence": 0.9,
            "quality_score": {"score": 0.9, "risk": "low"},
        }],
        "game_subgraph": game,
    }
    out = asyncio.run(battle_node(state))
    res = out["battle_result"]

    assert res["target_team"] == "villagers"
    assert res["candidate_win_rate"] == 1.0
    assert res["baseline_win_rate"] == 0.0
    assert res["win_rate_delta"] == 1.0
    assert res["significant"] is True
    assert res["promotion_gate"]["promote_allowed"] is False
    assert res["promotion_gate"]["recommendation"] == "review"
    assert "baseline_completed_below_promotion_minimum" in res["promotion_gate"]["reasons"]
    assert "candidate_completed_below_promotion_minimum" in res["promotion_gate"]["reasons"]
    assert len(res["paired_seed_battle_table"]) == 4
    assert res["paired_seed_battle_table"][0]["baseline_game_id"] == "r_battle_baseline_001"
    assert res["paired_seed_battle_table"][0]["candidate_game_id"] == "r_battle_candidate_001"
    assert res["paired_seed_summary"]["seed_count"] == 4
    assert res["paired_seed_summary"]["valid_count"] == 4
    assert res["paired_seed_summary"]["candidate_wins"] == 4
    assert out["paired_seed_pairs"] == res["paired_seed_battle_table"]
    assert out["paired_seed_summary"] == res["paired_seed_summary"]
    assert res["gate_report"]["schema_version"] == "trust_loop_gate_v1"
    assert res["gate_report"]["metrics"]["paired_valid_count"] == 4
    assert res["gate_report"]["decision"] == "review_required"
    assert res["promotion_gate"]["recommendation"] == "review"
    # Same seed range used for both sides.
    seeds = [inv["seed"] for inv in game.invocations]
    assert sorted(seeds[:4]) == sorted(seeds[4:])
    # Candidate side overrides only the evolving role; baseline side does not.
    baseline_invs = game.invocations[:4]
    candidate_invs = game.invocations[4:]
    assert all(not inv.get("role_skill_dirs") for inv in baseline_invs)
    assert all(inv["role_skill_dirs"] == {"seer": candidate_dir} for inv in candidate_invs)
    assert all(inv["skill_dir"] == baseline_dir for inv in candidate_invs)
    # battle_games carries both sides, each tagged for the UI split.
    sides = {g["side"] for g in out["battle_games"]}
    assert sides == {"baseline", "candidate"}
    assert len(out["battle_games"]) == 8


def test_battle_node_resumes_only_missing_side_seeds(tmp_path):
    baseline_dir = str(tmp_path / "baseline_skills")
    candidate_dir = str(tmp_path / "candidate_skills")
    game = FakeGameSubgraph({baseline_dir: "werewolves", candidate_dir: "villagers"})
    state = {
        "role": "seer",
        "run_id": "resume_battle",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_resume",
        "candidate_skill_dir": candidate_dir,
        "baseline_skill_dir": baseline_dir,
        "config": {"battle_games": 2, "battle_seed_start": 100},
        "proposals": [],
        "battle_games": [
            {
                "game_id": "baseline-existing",
                "seed": 100,
                "winner": "werewolves",
                "side": "baseline",
            },
            {
                "game_id": "candidate-existing",
                "seed": 100,
                "winner": "villagers",
                "side": "candidate",
            },
        ],
        "game_subgraph": game,
    }

    out = asyncio.run(battle_node(state))

    assert [invocation["seed"] for invocation in game.invocations] == [101, 101]
    assert len(out["battle_games"]) == 4
    assert sorted((item["side"], item["seed"]) for item in out["battle_games"]) == [
        ("baseline", 100),
        ("baseline", 101),
        ("candidate", 100),
        ("candidate", 101),
    ]


def test_battle_node_reuses_complete_persisted_result(tmp_path):
    baseline_dir = str(tmp_path / "baseline_skills")
    candidate_dir = str(tmp_path / "candidate_skills")
    game = FakeGameSubgraph({})
    battle_games = [
        {"game_id": f"b-{seed}", "seed": seed, "winner": "werewolves", "side": "baseline"}
        for seed in (100, 101)
    ] + [
        {"game_id": f"c-{seed}", "seed": seed, "winner": "villagers", "side": "candidate"}
        for seed in (100, 101)
    ]
    persisted_result = {"candidate_win_rate": 1.0, "baseline_win_rate": 0.0}
    state = {
        "role": "seer",
        "run_id": "resume_complete_battle",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_resume",
        "candidate_skill_dir": candidate_dir,
        "baseline_skill_dir": baseline_dir,
        "config": {"battle_games": 2, "battle_seed_start": 100},
        "battle_games": battle_games,
        "battle_result": persisted_result,
        "game_subgraph": game,
    }

    out = asyncio.run(battle_node(state))

    assert game.invocations == []
    assert out["battle_result"] == persisted_result
    assert out["progress"]["resumed"] is True


def test_promotion_gate_blocks_small_sample_auto_promote_even_with_win_rate_edge():
    from app.graphs.subgraphs.evolve.nodes import _promotion_gate

    baseline_games = [{"winner": "werewolves", "error": None} for _ in range(4)]
    candidate_games = [{"winner": "villagers", "error": None} for _ in range(4)]
    battle = {
        "significant": True,
        "win_rate_delta": 1.0,
        "significance": {"reasons": [], "win_rate_delta": 1.0},
        "baseline": {"games": 4, "completed": 4, "target_win_rate": 0.0},
        "candidate": {"games": 4, "completed": 4, "target_win_rate": 1.0},
    }

    gate = _promotion_gate(
        battle,
        proposals=[{
            "proposal_id": "p1",
            "target_file": "seer/vote.md",
            "risk": "low",
            "quality_score": {"score": 0.9, "risk": "low"},
        }],
        baseline_games=baseline_games,
        candidate_games=candidate_games,
        cfg={},
    )

    assert gate["promote_allowed"] is False
    assert gate["recommendation"] == "review"
    assert gate["samples"]["baseline"]["completed"] == 4
    assert gate["samples"]["candidate"]["completed"] == 4
    assert "baseline_completed_below_promotion_minimum" in gate["reasons"]
    assert "candidate_completed_below_promotion_minimum" in gate["reasons"]


def test_promotion_gate_blocks_candidate_decision_quality_issue_rate():
    from app.graphs.subgraphs.evolve.nodes import _promotion_gate

    baseline_games = [
        {
            "winner": "werewolves",
            "error": None,
            "decisions": [{"source": "llm"}],
            "events": [{"event_type": "action_response"}],
        }
        for _ in range(8)
    ]
    candidate_games = [
        {
            "winner": "villagers",
            "error": None,
            "decisions": [{"source": "fallback"}],
            "events": [{"event_type": "default_action"}],
        }
        for _ in range(8)
    ]
    battle = {
        "significant": True,
        "win_rate_delta": 1.0,
        "significance": {"reasons": [], "win_rate_delta": 1.0},
        "baseline": {"games": 8, "completed": 8, "target_win_rate": 0.0},
        "candidate": {"games": 8, "completed": 8, "target_win_rate": 1.0},
    }

    gate = _promotion_gate(
        battle,
        proposals=[{
            "proposal_id": "p1",
            "target_file": "seer/vote.md",
            "risk": "low",
            "quality_score": {"score": 0.9, "risk": "low"},
        }],
        baseline_games=baseline_games,
        candidate_games=candidate_games,
        cfg={},
    )

    assert gate["promote_allowed"] is False
    assert gate["recommendation"] == "review"
    assert gate["samples"]["candidate"]["completed"] == 8
    assert "candidate_decision_issue_rate_above_ceiling" in gate["reasons"]
    assert "candidate_completed_below_promotion_minimum" not in gate["reasons"]
    assert gate["decision_quality"]["candidate"]["fallback_rate"] == 1.0
    assert gate["decision_quality"]["candidate"]["default_action_rate"] == 1.0
    assert gate["decision_quality"]["candidate"]["issue_rate"] == 1.0


def test_battle_node_treats_no_winner_games_as_invalid_not_significant(tmp_path):
    baseline_dir = str(tmp_path / "baseline_skills")
    candidate_dir = str(tmp_path / "candidate_skills")
    game = FakeGameSubgraph({baseline_dir: "werewolves", candidate_dir: None})
    state = {
        "role": "seer",
        "run_id": "r_no_winner_battle",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_no_winner",
        "candidate_skill_dir": candidate_dir,
        "baseline_skill_dir": baseline_dir,
        "config": {"battle_games": 4},
        "game_subgraph": game,
    }

    out = asyncio.run(battle_node(state))
    res = out["battle_result"]

    assert res["candidate"]["completed"] == 0
    assert res["candidate"]["invalid"] == 4
    assert res["candidate"]["errors"] == 4
    assert res["candidate"]["winner_counts"] == {"unknown": 4}
    assert res["candidate_win_rate"] == 0.0
    assert res["significant"] is False
    assert "candidate_completed_below_minimum" in res["significance"]["reasons"]


def test_battle_node_skips_when_no_candidate(tmp_path):
    game = FakeGameSubgraph({})
    state = {
        "role": "seer",
        "run_id": "r",
        "parent_hash": "baseline_seer",
        "candidate_hash": "baseline_seer",  # equals parent → nothing changed
        "candidate_skill_dir": None,
        "skill_dir": str(tmp_path / "skills"),
        "config": {"battle_games": 4},
        "game_subgraph": game,
    }
    out = asyncio.run(battle_node(state))
    assert out["battle_result"]["skipped"] is True
    assert game.invocations == []  # no games run


def test_battle_node_records_unexpected_failure(tmp_path, monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    async def _boom(*args, **kwargs):
        raise RuntimeError("batch runner down")

    monkeypatch.setattr(nodes, "_run_games", _boom)
    state = {
        "role": "seer",
        "run_id": "r_battle_fail",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_r",
        "candidate_skill_dir": str(tmp_path / "candidate"),
        "skill_dir": str(tmp_path / "baseline"),
        "config": {"battle_games": 2},
        "game_subgraph": FakeGameSubgraph({}),
    }

    out = asyncio.run(battle_node(state))

    assert out["battle_games"] == []
    assert out["status"] == "failed"
    assert out["battle_result"]["skipped"] is True
    assert out["battle_result"]["reason"] == "battle_failed"
    assert out["battle_result"]["error"] == "batch runner down"
    assert out["errors"] == ["battle: batch runner down"]


def test_create_agents_node_applies_per_role_skill_dir(tmp_path):
    """create_agents_node routes the evolving role to its override dir only."""
    from app.graphs.subgraphs.agent.builder import build_agent_subgraph
    from app.graphs.subgraphs.game.nodes import create_agents_node

    baseline = tmp_path / "baseline"
    candidate = tmp_path / "candidate"
    baseline.mkdir()
    candidate.mkdir()

    class _Model:
        async def ainvoke(self, messages):
            return type("R", (), {"content": "{}"})()

    state = {
        "roles": {1: "seer", 2: "villager", 3: "werewolf"},
        "model": _Model(),
        "game_id": "g",
        "skill_dir": str(baseline),
        "role_skill_dirs": {"seer": str(candidate)},
        "agent_subgraph": build_agent_subgraph(),
    }
    out = asyncio.run(create_agents_node(state))
    agents = out["agents"]
    # Seer (evolving role) uses the candidate dir; everyone else uses baseline.
    assert str(agents[1].skill_dir) == str(candidate)
    assert str(agents[2].skill_dir) == str(baseline)
    assert str(agents[3].skill_dir) == str(baseline)


# ---------------------------------------------------------------------------
# decide_node — recommendation + registry side effects
# ---------------------------------------------------------------------------

def _seer_candidate_dir(tmp_path):
    d = tmp_path / "cand" / "seer"
    d.mkdir(parents=True)
    (d.parent / "seer" / "vote.md").write_text(SEER_SKILL, encoding="utf-8")
    return str(tmp_path / "cand")


def test_decide_promotes_to_registry_on_auto_promote(tmp_path, monkeypatch, _fake_pg_provider):
    candidate_dir = _seer_candidate_dir(tmp_path)
    paths = _PathsStub(tmp_path)
    registry = FakeRuntimeRegistry(paths.registry_dir)
    registry.seed_version("seer", "baseline_seer", {"seer/vote.md": SEER_SKILL}, baseline=True)
    _patch_runtime_registry(monkeypatch, registry)
    state = {
        "role": "seer",
        "run_id": "r1",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_r1",
        "candidate_skill_dir": candidate_dir,
        "paths": paths,
        "config": {"auto_promote": True},
        "proposals": [{"proposal_id": "p1", "target_file": "seer/vote.md"}],
        "battle_result": {"significant": True, "candidate_win_rate": 0.7},
    }
    out = asyncio.run(decide_node(state))
    assert out["result"]["recommendation"] == "promote"
    assert out["status"] == "promoted"
    published = out["result"]["published_version_id"]

    assert published == "candidate_r1"
    assert out["result"]["published_release_stage"] == "shadow"
    assert out["result"]["promoted_version_id"] is None
    assert registry.get_baseline("seer") == "baseline_seer"
    assert registry.release_stage("seer", published) == "shadow"
    provenance = registry.provenance("seer", published)
    assert provenance["automatic_action"] == "auto_promote"
    assert provenance["release_stage"] == "shadow"
    payload = _fake_pg_provider.runtime_state("r1")
    assert payload["kind"] == "role_evolution_run"
    assert payload["run_id"] == "r1"
    assert payload["status"] == "promoted"
    assert payload["result"]["published_version_id"] == published
    assert payload["result"]["published_release_stage"] == "shadow"
    assert payload["result"]["promoted_version_id"] is None
    assert payload["finished_at"] == out["result"]["finished_at"]
    assert _fake_pg_provider.row("r1")["finished_at"] == out["result"]["finished_at"]
    assert not (paths.evolution_dir / "r1" / "state.json").exists()
    assert not (paths.evolution_dir / "r1" / "manifest.json").exists()


def test_decide_baseline_promote_updates_registry_baseline(tmp_path, monkeypatch):
    candidate_dir = _seer_candidate_dir(tmp_path)
    paths = _PathsStub(tmp_path)
    registry = FakeRuntimeRegistry(paths.registry_dir)
    registry.seed_version("seer", "baseline_seer", {"seer/vote.md": SEER_SKILL}, baseline=True)
    _patch_runtime_registry(monkeypatch, registry)
    state = {
        "role": "seer",
        "run_id": "r_baseline",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_baseline",
        "candidate_skill_dir": candidate_dir,
        "paths": paths,
        "config": {"auto_promote": True},
        "proposals": [{"proposal_id": "p1", "target_file": "seer/vote.md"}],
        "release_gate": {"schema_version": "promotion_gate_v2", "decision": "baseline_promote"},
        "release_decision": "baseline_promote",
        "trust_bundle": {
            "schema_version": "trust_bundle_v1",
            "trust_bundle_id": "trust_bundle_r_baseline",
            "bundle_hash": "1" * 64,
            "gate_report_id": "gate_r_baseline",
            "attribution_report_id": "attr_r_baseline",
        },
        "battle_result": {"significant": True, "candidate_win_rate": 0.9},
    }

    out = asyncio.run(decide_node(state))

    assert out["result"]["recommendation"] == "promote"
    assert out["status"] == "promoted"
    assert out["result"]["published_version_id"] == "candidate_baseline"
    assert out["result"]["published_release_stage"] == "baseline"
    assert out["result"]["promoted_version_id"] == "candidate_baseline"
    assert registry.get_baseline("seer") == "candidate_baseline"
    assert registry.release_stage("seer", "candidate_baseline") == "baseline"
    provenance = registry.provenance("seer", "candidate_baseline")
    assert provenance["automatic_action"] == "auto_promote"
    assert provenance["release_decision"] == "baseline_promote"
    assert provenance["trust_bundle_id"] == "trust_bundle_r_baseline"
    assert provenance["gate_report_id"] == "gate_r_baseline"


def test_decide_rejects_and_saves_rejected(tmp_path, monkeypatch):
    paths = _PathsStub(tmp_path)
    registry = FakeRuntimeRegistry(paths.registry_dir)
    _patch_runtime_registry(monkeypatch, registry)
    state = {
        "role": "seer",
        "run_id": "r2",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_r2",
        "candidate_skill_dir": str(tmp_path / "cand"),
        "paths": paths,
        "config": {"auto_promote": True},
        "proposals": [{"proposal_id": "p1", "target_file": "seer/vote.md", "rationale": "x"}],
        "battle_result": {"significant": False, "candidate_win_rate": 0.3},
    }
    out = asyncio.run(decide_node(state))
    assert out["result"]["recommendation"] == "reject"
    assert out["status"] == "rejected"

    assert len(registry.load_rejected("seer")) == 1


def test_decide_review_only_without_auto_promote(tmp_path):
    candidate_dir = _seer_candidate_dir(tmp_path)
    paths = _PathsStub(tmp_path)
    state = {
        "role": "seer",
        "run_id": "r3",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_r3",
        "candidate_skill_dir": candidate_dir,
        "baseline_skill_dir": str(tmp_path / "baseline"),
        "paths": paths,
        "config": {"auto_promote": False},
        "proposals": [{"proposal_id": "p1", "target_file": "seer/vote.md"}],
        "battle_result": {"significant": True, "candidate_win_rate": 0.7},
    }
    out = asyncio.run(decide_node(state))
    assert out["result"]["recommendation"] == "promote"
    assert out["status"] == "reviewing"  # gate passed but no auto-promote → human review

    assert not paths.registry_dir.exists()  # registry untouched


def test_decide_review_when_promotion_gate_blocks_auto_promote(tmp_path, monkeypatch):
    candidate_dir = _seer_candidate_dir(tmp_path)
    paths = _PathsStub(tmp_path)
    registry = FakeRuntimeRegistry(paths.registry_dir)
    registry.seed_version("seer", "baseline_seer", {"seer/vote.md": SEER_SKILL}, baseline=True)
    _patch_runtime_registry(monkeypatch, registry)
    state = {
        "role": "seer",
        "run_id": "r_gate_review",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_gate_review",
        "candidate_skill_dir": candidate_dir,
        "paths": paths,
        "config": {"auto_promote": True},
        "proposals": [{"proposal_id": "p1", "target_file": "seer/vote.md"}],
        "battle_result": {
            "significant": True,
            "candidate_win_rate": 1.0,
            "baseline_win_rate": 0.0,
            "promotion_gate": {
                "promote_allowed": False,
                "recommendation": "review",
                "reasons": ["candidate_completed_below_promotion_minimum"],
            },
        },
    }

    out = asyncio.run(decide_node(state))

    assert out["result"]["recommendation"] == "review"
    assert out["status"] == "reviewing"
    assert out["result"]["published_version_id"] is None
    assert registry.get_baseline("seer") == "baseline_seer"
    assert registry.load_rejected("seer") == []


def test_decide_records_promote_error_when_candidate_dir_missing(tmp_path):
    paths = _PathsStub(tmp_path)
    state = {
        "role": "seer",
        "run_id": "r_missing_candidate",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_missing",
        "candidate_skill_dir": None,
        "paths": paths,
        "config": {"auto_promote": True},
        "proposals": [{"proposal_id": "p1", "target_file": "seer/vote.md"}],
        "battle_result": {"significant": True, "candidate_win_rate": 0.7},
    }

    out = asyncio.run(decide_node(state))

    assert out["result"]["recommendation"] == "promote"
    assert out["status"] == "reviewing"
    assert out["errors"] == ["promote: missing candidate_skill_dir"]
    assert out["result"]["errors"] == out["errors"]
    assert out["diagnostics"][0]["kind"] == "registry_error"
    assert out["diagnostics"][0]["stage"] == "registry.promote"


def test_decide_records_promote_error_when_candidate_dir_empty(tmp_path):
    paths = _PathsStub(tmp_path)
    candidate_dir = tmp_path / "empty_candidate"
    candidate_dir.mkdir()
    state = {
        "role": "seer",
        "run_id": "r_empty_candidate",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_empty",
        "candidate_skill_dir": str(candidate_dir),
        "paths": paths,
        "config": {"auto_promote": True},
        "proposals": [{"proposal_id": "p1", "target_file": "seer/vote.md"}],
        "battle_result": {"significant": True, "candidate_win_rate": 0.7},
    }

    out = asyncio.run(decide_node(state))

    assert out["result"]["recommendation"] == "promote"
    assert out["status"] == "reviewing"
    assert "promote: no skill files found" in out["errors"][0]
    assert out["result"]["errors"] == out["errors"]


def test_decide_records_promote_error_when_candidate_read_fails(tmp_path, monkeypatch):
    import app.graphs.subgraphs.evolve.nodes as nodes

    paths = _PathsStub(tmp_path)
    candidate_dir = _seer_candidate_dir(tmp_path)

    def _boom(skill_dir):
        raise RuntimeError("candidate skills unreadable")

    monkeypatch.setattr(nodes, "_read_skill_contents", _boom)
    state = {
        "role": "seer",
        "run_id": "r_unreadable_candidate",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_unreadable",
        "candidate_skill_dir": candidate_dir,
        "paths": paths,
        "config": {"auto_promote": True},
        "proposals": [{"proposal_id": "p1", "target_file": "seer/vote.md"}],
        "battle_result": {"significant": True, "candidate_win_rate": 0.7},
    }

    out = asyncio.run(decide_node(state))

    assert out["result"]["recommendation"] == "promote"
    assert out["status"] == "reviewing"
    assert out["errors"] == ["promote: failed to read candidate skills: candidate skills unreadable"]
    assert out["result"]["errors"] == out["errors"]


def test_decide_records_persist_warning_in_result(tmp_path):
    paths = _PathsStub(tmp_path)
    storage_provider = FakeEvolutionStorageProvider(fail_message="pg unavailable")
    state = {
        "role": "seer",
        "run_id": "r4",
        "parent_hash": "baseline_seer",
        "candidate_hash": "baseline_seer",
        "candidate_skill_dir": None,
        "paths": paths,
        "storage_provider": storage_provider,
        "config": {"auto_promote": False},
        "proposals": [],
        "battle_result": {"skipped": True, "reason": "no_candidate_changes"},
    }

    out = asyncio.run(decide_node(state))

    assert out["result"]["recommendation"] == "reject"
    assert "warnings" in out
    assert "failed to persist run state" in out["warnings"][0]
    assert "pg unavailable" in out["result"]["warnings"][0]
    assert "r4" not in storage_provider.rows


def test_decide_persists_run_diagnostics(tmp_path, _fake_pg_provider):
    paths = _PathsStub(tmp_path)
    candidate_dir = _seer_candidate_dir(tmp_path)
    state = {
        "role": "seer",
        "run_id": "r_diag",
        "parent_hash": "baseline_seer",
        "started_at": "2026-06-08T10:00:00+08:00",
        "candidate_hash": "candidate_r_diag",
        "candidate_skill_dir": candidate_dir,
        "baseline_skill_dir": str(tmp_path / "baseline"),
        "paths": paths,
        "config": {"auto_promote": False},
        "warnings": ["consolidate: dropped proposal p_bad: missing content"],
        "errors": ["apply: validation failed: invalid target"],
        "consolidation": {
            "role": "seer",
            "run_id": "r_diag",
            "parent_hash": "baseline_seer",
            "warnings": ["consolidate: dropped proposal p_bad: missing content"],
            "errors": [],
            "proposals": [{
                "proposal_id": "p1",
                "target_file": "seer/vote.md",
                "action_type": "append_rule",
                "content": "Wait one round.",
                "rationale": "two supporting games",
                "confidence": 0.8,
                "risk": "low",
                "evidence": [{"game_id": "g1"}, {"game_id": "g2"}],
                "status": "proposed",
            }],
        },
        "proposals": [{"proposal_id": "p1", "target_file": "seer/vote.md"}],
        "diff": [{
            "filename": "seer/vote.md",
            "action": "modified",
            "proposal_ref": "p1",
            "before": "old",
            "after": "new",
        }],
        "battle_result": {"significant": True, "candidate_win_rate": 0.7},
    }

    asyncio.run(decide_node(state))

    payload = _fake_pg_provider.runtime_state("r_diag")
    assert payload["candidate_skill_dir"] == candidate_dir
    assert payload["baseline_skill_dir"] == str(tmp_path / "baseline")
    assert payload["warnings"] == ["consolidate: dropped proposal p_bad: missing content"]
    assert payload["errors"] == ["apply: validation failed: invalid target"]
    assert payload["proposals"]["proposals"][0]["proposal_id"] == "p1"
    assert payload["diff"][0]["filename"] == "seer/vote.md"
    assert payload["current_stage"] == "done"
    assert payload["progress"]["stage"] == "done"
    assert payload["progress"]["percent"] == 1.0
    assert payload["progress"]["recommendation"] == "promote"
    assert payload["last_heartbeat_at"]
    assert payload["started_at"] == "2026-06-08T10:00:00+08:00"
    assert payload["result"]["started_at"] == "2026-06-08T10:00:00+08:00"
    assert payload["finished_at"] == payload["result"]["finished_at"]
    assert payload["diagnostics"] == []
    assert payload["result"]["status"] == "reviewing"
    assert payload["result"]["recommendation"] == "promote"
    row = _fake_pg_provider.row("r_diag")
    assert row["status"] == "reviewing"
    assert row["started_at"] == "2026-06-08T10:00:00+08:00"
    assert row["started_at"] <= row["finished_at"]
    assert row["finished_at"] == payload["finished_at"]
    assert json.loads(row["battle_result"]) == {"significant": True, "candidate_win_rate": 0.7}
    assert json.loads(row["errors"]) == ["apply: validation failed: invalid target"]
    assert not (paths.evolution_dir / "r_diag" / "state.json").exists()
    assert not (paths.evolution_dir / "r_diag" / "manifest.json").exists()


def test_decide_persists_trust_loop_artifacts_without_replacing_promotion_gate(tmp_path, _fake_pg_provider):
    paths = _PathsStub(tmp_path)
    baseline_games = [
        {
            "game_id": "r_trust_battle_baseline_001",
            "seed": 10000,
            "winner": "werewolves",
            "role_score": 4.0,
            "decisions": [{"source": "llm"}],
        }
    ]
    candidate_games = [
        {
            "game_id": "r_trust_battle_candidate_001",
            "seed": 10000,
            "winner": "villagers",
            "role_score": 5.0,
            "decisions": [{"source": "llm"}],
        }
    ]
    state = {
        "role": "seer",
        "run_id": "r_trust_decide",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_trust",
        "candidate_skill_dir": str(tmp_path / "candidate"),
        "baseline_skill_dir": str(tmp_path / "baseline"),
        "paths": paths,
        "config": {"auto_promote": False},
        "proposals": [{
            "proposal_id": "p1",
            "target_file": "seer/vote.md",
            "risk": "low",
            "confidence": 0.9,
            "hypothesis": "Checking vote split drivers improves seer information gain.",
            "trigger_condition": {"phase": ["day1"], "public_state": ["vote_split"]},
            "metric_targets": {"min_role_score_delta": 0.2},
            "evidence_game_ids": ["train_a", "train_b"],
        }],
        "generated_proposal_ids": ["p1"],
        "preflight_passed_proposal_ids": ["p1"],
        "training_games": [{"game_id": "train_a"}, {"game_id": "train_b"}],
        "diff": [{"filename": "seer/vote.md", "action": "append_rule", "proposal_ref": "p1", "before": "", "after": "Check vote split drivers."}],
        "scenario_snapshots": [{
            "schema_version": "scenario_snapshot_v1",
            "scenario_id": "scenario_1",
            "source_game_id": "train_a",
            "role": "seer",
            "actor_id": 1,
            "phase": "day",
            "legal_actions": ["vote"],
            "prompt_policy_version": "agent_prompt_v1",
            "judge_policy_version": "judge_policy_v1",
            "rubric_version": "seer_rubric_v1",
            "baseline_version": "baseline_seer",
            "candidate_version": "candidate_trust",
        }],
        "scenario_replay_report": {
            "schema_version": "scenario_replay_report_v1",
            "execution_mode": "contract_only",
            "status": "contract_ready",
            "scenario_count": 1,
            "results": [{"scenario_id": "scenario_1", "verdict": "contract_ready", "policy_violations": []}],
            "summary": {
                "verdict": "contract_ready",
                "scenario_count": 1,
                "policy_violation_count": 0,
                "contract_missing_count": 0,
            },
        },
        "scenario_replay_summary": {
            "verdict": "contract_ready",
            "scenario_count": 1,
            "policy_violation_count": 0,
            "contract_missing_count": 0,
        },
        "battle_result": {
            "target_team": "villagers",
            "seeds": [10000],
            "baseline_games": baseline_games,
            "candidate_games": candidate_games,
            "significant": True,
            "win_rate_delta": 1.0,
            "significance": {"reasons": [], "win_rate_delta": 1.0},
            "promotion_gate": {
                "schema_version": "1.0",
                "promote_allowed": False,
                "recommendation": "review",
                "reasons": ["candidate_completed_below_promotion_minimum"],
            },
        },
    }

    out = asyncio.run(decide_node(state))

    assert out["result"]["recommendation"] == "review"
    assert out["result"]["promotion_gate"]["recommendation"] == "review"
    assert out["result"]["gate_report"]["schema_version"] == "trust_loop_gate_v1"
    assert out["result"]["gate_report"]["release_gate"]["schema_version"] == "promotion_gate_v2"
    assert out["result"]["gate_report"]["scenario_replay"]["execution_mode"] == "contract_only"
    assert out["result"]["gate_report"]["metrics"]["scenario_count"] == 1
    assert out["result"]["gate_report"]["proposal_attribution"]["schema_version"] == "proposal_attribution_report_v1"
    assert out["result"]["gate_report"]["proposal_attribution"]["status"] == "attribution_inconclusive"
    assert out["result"]["release_gate"]["schema_version"] == "promotion_gate_v2"
    assert out["result"]["proposal_attribution_report"]["schema_version"] == "proposal_attribution_report_v1"
    assert out["result"]["proposal_attribution_report"]["rows"][0]["estimated_contribution"] is None
    assert out["result"]["trust_bundle"]["schema_version"] == "trust_bundle_v1"
    assert out["result"]["trust_bundle"]["trust_bundle_id"].startswith("trust_bundle_r_trust_decide_")
    assert len(out["result"]["trust_bundle"]["bundle_hash"]) == 64
    assert out["result"]["trust_bundle"]["scenario_ids"] == ["scenario_1"]
    assert out["result"]["trust_bundle"]["training_game_ids"] == ["train_a", "train_b"]
    assert out["result"]["paired_seed_summary"]["seed_count"] == 1
    assert out["result"]["paired_seed_pairs"][0]["winner_side"] == "candidate"
    payload = _fake_pg_provider.runtime_state("r_trust_decide")
    assert payload["promotion_gate"]["recommendation"] == "review"
    assert payload["gate_report"]["metrics"]["paired_valid_count"] == 1
    assert payload["gate_report"]["release_gate"]["schema_version"] == "promotion_gate_v2"
    assert payload["release_gate"]["schema_version"] == "promotion_gate_v2"
    assert payload["trust_bundle"]["schema_version"] == "trust_bundle_v1"
    assert payload["trust_bundle"]["rollback_target"] == "baseline_seer"
    assert payload["trust_bundle"]["trust_bundle_id"] == out["result"]["trust_bundle"]["trust_bundle_id"]
    assert payload["scenario_replay_report"]["execution_mode"] == "contract_only"
    assert payload["proposal_attribution_report"]["schema_version"] == "proposal_attribution_report_v1"
    assert payload["paired_seed_battle_table"][0]["score_delta"] == 1.0
    assert payload["result"]["paired_seed_pairs"] == payload["paired_seed_pairs"]
    trust_bundle = _fake_pg_provider.trust_bundle("r_trust_decide")
    assert trust_bundle["schema_version"] == "trust_bundle_v1"
    assert trust_bundle["trust_bundle_id"] == out["result"]["trust_bundle"]["trust_bundle_id"]
    assert trust_bundle["bundle_hash"] == out["result"]["trust_bundle"]["bundle_hash"]
    stored_bundle = _fake_pg_provider.trust_bundles["r_trust_decide"]
    assert stored_bundle["id"] == out["result"]["trust_bundle"]["trust_bundle_id"]
    assert stored_bundle["bundle_hash"] == out["result"]["trust_bundle"]["bundle_hash"]

    from storage.evolution.run_repo import EvolutionStore

    audit_payload = EvolutionStore(
        FakeEvolutionConnection({}, _fake_pg_provider.trust_bundles)
    ).get_trust_bundle("r_trust_decide")
    assert audit_payload is not None
    assert audit_payload["kind"] == "evolution_trust_bundle"
    assert audit_payload["trust_bundle"]["rollback_target"] == "baseline_seer"


def test_build_evolve_graph_signature_exposes_only_wired_parameters():
    import inspect

    from app.graphs.subgraphs.evolve.builder import build_evolve_graph

    assert list(inspect.signature(build_evolve_graph).parameters) == ["game_subgraph"]


# ---------------------------------------------------------------------------
# Pure trust-loop helpers
# ---------------------------------------------------------------------------

def test_normalize_proposal_reviews_canonicalizes_status_and_apply_adapter():
    from app.lib.evolve import (
        accepted_proposals_for_apply,
        normalize_proposal_review_status,
        normalize_proposal_reviews,
    )

    proposals = [
        {"proposal_id": "p1", "target_file": "seer/vote.md", "status": "pending"},
        {"proposal_id": "p2", "target_file": "seer/check.md", "status": "approved"},
        {"proposal_id": "p3", "target_file": "seer/timing.md", "status": "declined"},
    ]

    reviewed = normalize_proposal_reviews(
        proposals,
        {
            "p1": "accept",
            "p3": {"decision": "reject", "review_reason": "too narrow"},
        },
    )

    assert normalize_proposal_review_status("APPROVED") == "accepted"
    assert normalize_proposal_review_status("drop") == "rejected"
    assert normalize_proposal_review_status("unknown") == "proposed"
    assert [row["review_status"] for row in reviewed] == ["accepted", "accepted", "rejected"]
    assert reviewed[2]["review_reason"] == "too narrow"
    assert proposals[0]["status"] == "pending"

    apply_rows = accepted_proposals_for_apply(proposals, {"p1": "accepted", "p2": "rejected"})
    assert [row["proposal_id"] for row in apply_rows] == ["p1"]
    assert apply_rows[0]["status"] == "proposed"
    assert apply_rows[0]["review_status"] == "accepted"


def test_build_paired_seed_battle_table_from_run_battle_games_and_missing_seed():
    from app.lib.evolve import build_paired_seed_battle_table

    run = {
        "role": "seer",
        "battle_result": {"target_team": "villagers", "seeds": [100, 101, 102]},
        "battle_games": [
            {
                "game_id": "r_battle_baseline_001",
                "seed": 100,
                "side": "baseline",
                "winner": "werewolves",
                "score_summary": {"by_role_category": {"seer": 5.0}},
            },
            {
                "game_id": "r_battle_candidate_001",
                "seed": 100,
                "side": "candidate",
                "winner": "villagers",
                "score_summary": {"by_role_category": {"seer": 7.0}},
            },
            {
                "game_id": "r_battle_baseline_002",
                "seed": 101,
                "side": "baseline",
                "winner": "villagers",
                "score_summary": {"by_role_category": {"seer": 8.0}},
            },
            {
                "game_id": "r_battle_candidate_002",
                "seed": 101,
                "side": "candidate",
                "winner": "villagers",
                "score_summary": {"by_role_category": {"seer": 6.5}},
            },
        ],
    }

    table = build_paired_seed_battle_table(run)

    assert [row["seed"] for row in table] == [100, 101, 102]
    assert table[0]["baseline_game_id"] == "r_battle_baseline_001"
    assert table[0]["candidate_game_id"] == "r_battle_candidate_001"
    assert table[0]["score_delta"] == 2.0
    assert table[0]["winner_side"] == "candidate"
    assert table[1]["score_delta"] == -1.5
    assert table[1]["winner_side"] == "baseline"
    assert table[2]["winner_side"] == "invalid"
    assert table[2]["failure_reason"] == "missing_baseline_game"


def test_build_paired_seed_battle_table_from_battle_result_side_lists():
    from app.lib.evolve import build_paired_seed_battle_table

    battle_result = {
        "target_team": "villagers",
        "baseline_games": [
            {"game_id": "r_battle_baseline_001", "seed": 1, "winner": "werewolves", "role_score": 4.0},
        ],
        "candidate_games": [
            {"game_id": "r_battle_candidate_001", "seed": 1, "winner": "villagers", "role_score": 4.75},
        ],
    }

    table = build_paired_seed_battle_table(battle_result=battle_result, role="seer")

    assert table == [
        {
            "seed": 1,
            "baseline_game_id": "r_battle_baseline_001",
            "candidate_game_id": "r_battle_candidate_001",
            "baseline_winner": "werewolves",
            "candidate_winner": "villagers",
            "baseline_score": 4.0,
            "candidate_score": 4.75,
            "score_delta": 0.75,
            "baseline_rankable": True,
            "candidate_rankable": True,
            "winner_side": "candidate",
            "failure_reason": "",
        }
    ]


def test_evolution_gate_report_adds_role_score_paired_decision_and_risk_tags():
    from app.lib.evolve import build_evolution_gate_report

    battle_games = []
    for seed in range(4):
        battle_games.append({
            "game_id": f"r_battle_baseline_{seed + 1:03d}",
            "seed": seed,
            "side": "baseline",
            "winner": "werewolves",
            "role_score": 5.0,
            "decisions": [{"source": "llm"}],
            "events": [{"event_type": "action_response"}],
        })
        battle_games.append({
            "game_id": f"r_battle_candidate_{seed + 1:03d}",
            "seed": seed,
            "side": "candidate",
            "winner": "villagers",
            "role_score": 5.6,
            "decisions": [{"source": "fallback"}],
            "events": [{"event_type": "default_action"}],
        })
    proposal = {
        "proposal_id": "p_seed",
        "target_file": "seer/vote.md",
        "action_type": "append_rule",
        "content": "When seed 10000 appears, always vote player 3.",
        "rationale": "Matched seed 10000 evidence.",
        "risk": "low",
    }
    run = {
        "role": "seer",
        "battle_games": battle_games,
        "battle_result": {
            "target_team": "villagers",
            "significant": True,
            "win_rate_delta": 1.0,
            "seeds": [0, 1, 2, 3],
            "significance": {"reasons": []},
        },
        "proposals": [proposal],
    }

    report = build_evolution_gate_report(
        run,
        rejected=[{**proposal, "proposal_id": "old_p_seed", "source_run_id": "older"}],
        thresholds={
            "min_paired_valid_seeds": 4,
            "min_role_score_delta": 0.1,
            "max_decision_issue_rate": 0.1,
            "max_decision_issue_delta": 0.05,
        },
    )

    assert report["schema_version"] == "trust_loop_gate_v1"
    assert report["decision"] == "review_required"
    assert report["promote_allowed"] is False
    assert report["metrics"]["paired_valid_count"] == 4
    assert report["metrics"]["paired_candidate_wins"] == 4
    assert report["metrics"]["role_score_delta"] == pytest.approx(0.6)
    assert report["decision_quality"]["candidate"]["issue_rate"] == 1.0
    assert "candidate_decision_issue_rate_above_ceiling" in report["review_reasons"]
    assert "proposal_duplicates_rejected_buffer" in report["review_reasons"]
    assert "proposal_overfit_risk_high" in report["review_reasons"]
    assert "proposal_attribution_inconclusive" in report["review_reasons"]
    assert {"duplicate_rejected", "seed_specific", "player_specific", "overfit_high"} <= set(report["risk_tags"])
    assert report["proposal_risks"][0]["similarity"]["matched_rejection"]["source_run_id"] == "older"
    assert report["gate_policy_version"] == "promotion_gate_v2"
    assert report["release_gate"]["schema_version"] == "promotion_gate_v2"
    assert report["release_gate"]["decision"] == "block"
    assert report["trust_bundle_completeness"]["complete"] is False
    attribution = report["proposal_attribution"]
    assert attribution["schema_version"] == "proposal_attribution_report_v1"
    assert attribution["status"] == "attribution_inconclusive"
    assert attribution["review_required"] is True
    assert attribution["rows"][0]["estimated_contribution"] is None
    assert attribution["rows"][0]["requires_ablation"] is True


def test_build_trust_bundle_collects_evidence_gate_and_repro_metadata():
    from app.lib.evolve import build_evolution_gate_report, build_trust_bundle

    proposal = {
        "proposal_id": "p1",
        "target_file": "seer/vote.md",
        "action_type": "append_rule",
        "status": "accepted",
        "hypothesis": "Vote split drivers are better check targets.",
        "trigger_condition": {"phase": ["day1"], "public_state": ["vote_split"]},
        "metric_targets": {"min_role_score_delta": 0.2},
        "evidence_game_ids": ["train_1", "train_2"],
        "risk": "low",
    }
    run = {
        "run_id": "r_bundle",
        "role": "seer",
        "parent_hash": "baseline_seer",
        "candidate_hash": "candidate_seer",
        "training_games": [{"game_id": "train_1"}, {"game_id": "train_2"}],
        "scenario_snapshots": [{"scenario_id": "scenario_1", "source_game_id": "train_1"}],
        "battle_games": [
            {"game_id": "b_base", "seed": 42, "side": "baseline", "winner": "werewolves", "role_score": 4.0},
            {"game_id": "b_cand", "seed": 42, "side": "candidate", "winner": "villagers", "role_score": 4.4},
        ],
        "battle_result": {"target_team": "villagers", "significant": True, "seeds": [42], "significance": {"reasons": []}},
        "proposals": [proposal],
        "generated_proposal_ids": ["p1"],
        "preflight_passed_proposal_ids": ["p1"],
        "accepted_proposal_ids": ["p1"],
        "diff": [{"filename": "seer/vote.md", "action": "append_rule", "proposal_ref": "p1", "before": "", "after": "Check drivers."}],
        "scenario_replay_report": {
            "schema_version": "scenario_replay_report_v1",
            "execution_mode": "contract_only",
            "status": "contract_ready",
            "scenario_count": 1,
            "summary": {"verdict": "contract_ready", "scenario_count": 1, "policy_violation_count": 0, "contract_missing_count": 0},
        },
    }
    gate_report = build_evolution_gate_report(run, thresholds={"min_paired_valid_seeds": 1})
    bundle = build_trust_bundle(run, gate_report=gate_report)

    assert gate_report["release_gate"]["schema_version"] == "promotion_gate_v2"
    assert gate_report["policy_versions"]["judge_policy_version"] == "judge_policy_v1"
    assert bundle["schema_version"] == "trust_bundle_v1"
    assert bundle["training_game_ids"] == ["train_1", "train_2"]
    assert bundle["scenario_ids"] == ["scenario_1"]
    assert bundle["battle_pair_seeds"] == [42]
    assert bundle["accepted_proposal_ids"] == ["p1"]
    assert bundle["rollback_target"] == "baseline_seer"
    assert bundle["gate_policy_version"] == "promotion_gate_v2"
    assert bundle["trust_bundle_id"].startswith("trust_bundle_r_bundle_")
    assert len(bundle["bundle_hash"]) == 64
    assert bundle["attribution_report_id"].startswith("attribution_r_bundle_")
    assert bundle["repro_command"].startswith("not_available:")


def test_reject_buffer_similarity_and_overfit_risk_detect_duplicate_specific_rules():
    from app.lib.evolve import detect_overfit_risk, reject_buffer_similarity

    proposal = {
        "proposal_id": "p_new",
        "target_file": "seer/vote.md",
        "action_type": "append_rule",
        "content": "For seed 10000, vote player 3 before day 2.",
        "rationale": "This won game_id evolve_seed_10000.",
    }
    rejected = [{
        "proposal_id": "p_old",
        "target_file": "seer/vote.md",
        "action_type": "append_rule",
        "content": "For seed 10001, vote player 5 before day 2.",
        "rejection_reason": "seed-specific overfit",
    }]

    similarity = reject_buffer_similarity(proposal, rejected, threshold=0.7)
    risk = detect_overfit_risk(proposal, rejected=rejected, duplicate_threshold=0.7)

    assert similarity["duplicate_rejected"] is True
    assert similarity["similarity"] >= 0.7
    assert similarity["matched_rejection"]["proposal_id"] == "p_old"
    assert risk["gate_effect"] == "block"
    assert {"seed_specific", "game_id_specific", "player_specific", "duplicate_rejected", "overfit_high"} <= set(
        risk["risk_tags"]
    )
