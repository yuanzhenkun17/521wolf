from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from storage.provider import (
    PostgresStorageProvider,
    open_evolution_connection,
    open_registry_connection,
    open_wolf_connection,
    storage_provider_from_env,
)


class _FakeConn:
    def __init__(self) -> None:
        self.closed = False
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


def test_postgres_storage_provider_delegates_to_domain_factories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def factory(name: str):
        def _open(conninfo: str | None = None, **kwargs: Any) -> object:
            calls.append((name, conninfo or "", kwargs))
            return object()

        return _open

    import storage.postgres

    monkeypatch.setattr(storage.postgres, "get_wolf_postgres_connection", factory("wolf"))
    monkeypatch.setattr(
        storage.postgres,
        "get_registry_postgres_connection",
        factory("registry"),
    )
    monkeypatch.setattr(
        storage.postgres,
        "get_evolution_postgres_connection",
        factory("evolution"),
    )

    provider = PostgresStorageProvider(
        "postgresql://app@example/db",
        connect_kwargs={"connect_timeout": 3},
    )

    assert provider.open_wolf_connection() is not None
    assert provider.open_registry_connection() is not None
    assert provider.open_evolution_connection() is not None
    assert calls == [
        ("wolf", "postgresql://app@example/db", {"connect_timeout": 3}),
        ("registry", "postgresql://app@example/db", {"connect_timeout": 3}),
        ("evolution", "postgresql://app@example/db", {"connect_timeout": 3}),
    ]


def test_storage_provider_from_env_is_postgres_only() -> None:
    provider = storage_provider_from_env(paths=SimpleNamespace(root="ignored"))

    assert isinstance(provider, PostgresStorageProvider)


def test_open_wolf_connection_uses_injected_provider_without_env_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeProvider:
        def __init__(self) -> None:
            self.conn = _FakeConn()
            self.opened = 0

        def open_wolf_connection(self) -> _FakeConn:
            self.opened += 1
            return self.conn

    def fail_provider_from_env(**_: Any) -> _FakeProvider:
        raise AssertionError("provider should not be resolved when injected")

    import storage.provider

    monkeypatch.setattr(storage.provider, "storage_provider_from_env", fail_provider_from_env)
    provider = _FakeProvider()

    conn = open_wolf_connection(provider)

    assert conn is provider.conn
    assert provider.opened == 1


def test_open_wolf_connection_preserves_no_arg_provider_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeProvider:
        def __init__(self) -> None:
            self.conn = _FakeConn()

        def open_wolf_connection(self) -> _FakeConn:
            return self.conn

    provider = _FakeProvider()

    import storage.provider

    monkeypatch.setattr(storage.provider, "storage_provider_from_env", lambda: provider)

    assert open_wolf_connection() is provider.conn


@pytest.mark.parametrize(
    ("helper_name", "domain"),
    [
        ("open_registry_connection", "registry"),
        ("open_evolution_connection", "evolution"),
    ],
)
def test_domain_connection_helpers_use_injected_provider_without_env_lookup(
    monkeypatch: pytest.MonkeyPatch,
    helper_name: str,
    domain: str,
) -> None:
    class _FakeProvider:
        def __init__(self) -> None:
            self.registry_conn = _FakeConn()
            self.evolution_conn = _FakeConn()
            self.opened: list[str] = []

        def open_registry_connection(self) -> _FakeConn:
            self.opened.append("registry")
            return self.registry_conn

        def open_evolution_connection(self) -> _FakeConn:
            self.opened.append("evolution")
            return self.evolution_conn

    def fail_provider_from_env(**_: Any) -> _FakeProvider:
        raise AssertionError("provider should not be resolved when injected")

    import storage.provider

    monkeypatch.setattr(storage.provider, "storage_provider_from_env", fail_provider_from_env)
    provider = _FakeProvider()
    helper = getattr(storage.provider, helper_name)

    conn = helper(provider)

    assert conn is getattr(provider, f"{domain}_conn")
    assert provider.opened == [domain]


@pytest.mark.parametrize(
    ("helper_name", "domain"),
    [
        ("open_registry_connection", "registry"),
        ("open_evolution_connection", "evolution"),
    ],
)
def test_domain_connection_helpers_preserve_no_arg_provider_lookup(
    monkeypatch: pytest.MonkeyPatch,
    helper_name: str,
    domain: str,
) -> None:
    class _FakeProvider:
        def __init__(self) -> None:
            self.registry_conn = _FakeConn()
            self.evolution_conn = _FakeConn()

        def open_registry_connection(self) -> _FakeConn:
            return self.registry_conn

        def open_evolution_connection(self) -> _FakeConn:
            return self.evolution_conn

    provider = _FakeProvider()

    import storage.provider

    monkeypatch.setattr(storage.provider, "storage_provider_from_env", lambda: provider)
    helper = getattr(storage.provider, helper_name)

    assert helper() is getattr(provider, f"{domain}_conn")


@pytest.mark.parametrize(
    ("helper_name", "domain"),
    [
        ("open_registry_connection", "registry"),
        ("open_evolution_connection", "evolution"),
    ],
)
def test_domain_connection_helpers_forward_paths(
    monkeypatch: pytest.MonkeyPatch,
    helper_name: str,
    domain: str,
) -> None:
    class _FakeProvider:
        def __init__(self) -> None:
            self.registry_conn = _FakeConn()
            self.evolution_conn = _FakeConn()

        def open_registry_connection(self) -> _FakeConn:
            return self.registry_conn

        def open_evolution_connection(self) -> _FakeConn:
            return self.evolution_conn

    provider = _FakeProvider()
    seen_paths: list[Any] = []

    def provider_from_env(*, paths: Any | None = None) -> _FakeProvider:
        seen_paths.append(paths)
        return provider

    import storage.provider

    monkeypatch.setattr(storage.provider, "storage_provider_from_env", provider_from_env)
    helper = getattr(storage.provider, helper_name)
    paths = SimpleNamespace(root="ignored")

    assert helper(paths=paths) is getattr(provider, f"{domain}_conn")
    assert seen_paths == [paths]


def test_game_run_service_uses_postgres_provider_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.lib.store import GameRunConfig, GameRunService

    class _FakeProvider:
        def __init__(self) -> None:
            self.wolf_conn = _FakeConn()
            self.opened = 0

        def open_wolf_connection(self) -> _FakeConn:
            self.opened += 1
            return self.wolf_conn

        def open_registry_connection(self) -> _FakeConn:
            return _FakeConn()

        def open_evolution_connection(self) -> _FakeConn:
            return _FakeConn()

    provider = _FakeProvider()
    seen_paths: list[Any] = []

    def provider_from_env(*, paths: Any | None = None) -> _FakeProvider:
        seen_paths.append(paths)
        return provider

    import storage.provider

    monkeypatch.setattr(storage.provider, "storage_provider_from_env", provider_from_env)
    paths = SimpleNamespace()

    service = GameRunService(paths=paths)
    handle = service.create_run(
        GameRunConfig(run_id="pg_env_run", run_type="ordinary_game")
    )
    try:
        assert handle.persistence.has_db is True
        assert provider.opened == 1
        assert seen_paths == [paths]
    finally:
        handle.close()

    assert provider.wolf_conn.closed is True
    assert provider.wolf_conn.commits == 1


def test_open_eval_connection_uses_postgres_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.lib.score import open_eval_connection

    class _FakeProvider:
        def __init__(self) -> None:
            self.wolf_conn = _FakeConn()

        def open_wolf_connection(self) -> _FakeConn:
            return self.wolf_conn

        def open_registry_connection(self) -> _FakeConn:
            return _FakeConn()

        def open_evolution_connection(self) -> _FakeConn:
            return _FakeConn()

    provider = _FakeProvider()
    seen_paths: list[Any] = []

    def provider_from_env(*, paths: Any | None = None) -> _FakeProvider:
        seen_paths.append(paths)
        return provider

    import storage.provider

    monkeypatch.setattr(storage.provider, "storage_provider_from_env", provider_from_env)
    paths = SimpleNamespace(root="ignored")

    conn = open_eval_connection(paths)

    assert conn is provider.wolf_conn
    assert seen_paths == [paths]


def test_open_benchmark_connection_uses_wolf_provider_with_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from storage.benchmark.evaluation_repo import open_benchmark_connection

    class _FakeProvider:
        def __init__(self) -> None:
            self.wolf_conn = _FakeConn()
            self.opened = 0

        def open_wolf_connection(self) -> _FakeConn:
            self.opened += 1
            return self.wolf_conn

        def open_registry_connection(self) -> _FakeConn:
            return _FakeConn()

        def open_evolution_connection(self) -> _FakeConn:
            return _FakeConn()

    provider = _FakeProvider()
    seen_paths: list[Any] = []

    def provider_from_env(*, paths: Any | None = None) -> _FakeProvider:
        seen_paths.append(paths)
        return provider

    import storage.provider

    monkeypatch.setattr(storage.provider, "storage_provider_from_env", provider_from_env)
    paths = SimpleNamespace(root="ignored")

    conn = open_benchmark_connection(paths=paths)

    assert conn is provider.wolf_conn
    assert provider.opened == 1
    assert seen_paths == [paths]


def _registry_skill(body: str = "check carefully", *, role: str = "seer") -> str:
    return f"""---
name: {role}_main
role: {role}
status: active
applicable_actions:
  - vote
evolution:
  enabled: true
  allowed_actions:
    - append_rule
---

# {role}

{body}
"""


def test_postgres_version_registry_facade_materializes_skills() -> None:
    from app.lib.version import (
        PostgresVersionRegistry,
        build_baseline_config,
        build_composite_skill_dir,
    )

    class _Row(dict):
        def keys(self):
            return super().keys()

    class _Conn(_FakeConn):
        def __init__(self) -> None:
            super().__init__()
            self.versions: dict[tuple[str, str], dict[str, Any]] = {}
            self.baselines: dict[str, str] = {}
            self.rejected: dict[str, str] = {}

        def execute(self, sql: str, params: Any = ()):
            text = " ".join(sql.split())
            if text.startswith("SELECT * FROM role_versions"):
                role, version_id = params
                row = self.versions.get((role, version_id))
                return SimpleNamespace(fetchone=lambda: _Row(row) if row else None)
            if text.startswith("SELECT version_id FROM role_current_baseline"):
                role = params[0]
                value = self.baselines.get(role)
                return SimpleNamespace(
                    fetchone=lambda: _Row({"version_id": value}) if value else None
                )
            if text.startswith("SELECT DISTINCT role FROM role_versions"):
                roles = sorted({role for role, _ in self.versions})
                return SimpleNamespace(fetchall=lambda: [_Row({"role": role}) for role in roles])
            if text.startswith("SELECT id, status FROM role_versions"):
                role = params[0]
                rows = [
                    _Row({"id": version_id, "status": item["status"]})
                    for (item_role, version_id), item in self.versions.items()
                    if item_role == role
                ]
                return SimpleNamespace(fetchall=lambda: rows)
            if text.startswith("SELECT id, role, source, created_at, status"):
                role = params[0]
                rows = [
                    _Row(
                        {
                            "id": version_id,
                            "role": item["role"],
                            "source": item["source"],
                            "created_at": item["created_at"],
                            "status": item["status"],
                            "provenance_json": item["provenance_json"],
                        }
                    )
                    for (item_role, version_id), item in self.versions.items()
                    if item_role == role
                ]
                return SimpleNamespace(fetchall=lambda: rows)
            if text.startswith("INSERT INTO role_versions"):
                (
                    version_id,
                    role,
                    parent_id,
                    source,
                    run_id,
                    skills,
                    notes,
                    status,
                    created_at,
                    provenance_json,
                ) = params
                self.versions[(role, version_id)] = {
                    "id": version_id,
                    "role": role,
                    "parent_id": parent_id,
                    "source": source,
                    "run_id": run_id,
                    "skills": skills,
                    "notes": notes,
                    "status": status,
                    "created_at": created_at,
                    "provenance_json": provenance_json,
                }
                return SimpleNamespace(fetchone=lambda: None, fetchall=lambda: [])
            if text.startswith("UPDATE role_versions SET status = ?, provenance_json = ?"):
                status, provenance_json, role, version_id = params
                self.versions[(role, version_id)]["status"] = status
                self.versions[(role, version_id)]["provenance_json"] = provenance_json
                return SimpleNamespace(fetchone=lambda: None, fetchall=lambda: [])
            if text.startswith("UPDATE role_versions SET status = 'archived'"):
                role, version_id = params
                for (item_role, item_version), item in self.versions.items():
                    if item_role == role and item_version != version_id and item["status"] == "baseline":
                        item["status"] = "archived"
                return SimpleNamespace(fetchone=lambda: None, fetchall=lambda: [])
            if text.startswith("UPDATE role_versions SET status = 'baseline'"):
                role, version_id = params
                self.versions[(role, version_id)]["status"] = "baseline"
                return SimpleNamespace(fetchone=lambda: None, fetchall=lambda: [])
            if text.startswith("INSERT INTO role_current_baseline"):
                role, version_id, _updated_at = params
                self.baselines[role] = version_id
                return SimpleNamespace(fetchone=lambda: None, fetchall=lambda: [])
            if text.startswith("INSERT INTO role_baseline_history"):
                return SimpleNamespace(fetchone=lambda: None, fetchall=lambda: [])
            if text.startswith("BEGIN"):
                return SimpleNamespace(fetchone=lambda: None, fetchall=lambda: [])
            if text.startswith("INSERT INTO rejected_proposals"):
                role, proposals_json = params
                self.rejected.setdefault(role, proposals_json)
                return SimpleNamespace(fetchone=lambda: None, fetchall=lambda: [])
            if text.startswith("SELECT proposals_json FROM rejected_proposals"):
                role = params[0]
                return SimpleNamespace(
                    fetchone=lambda: _Row({"proposals_json": self.rejected[role]})
                    if role in self.rejected
                    else None
                )
            if text.startswith("UPDATE rejected_proposals SET proposals_json"):
                proposals_json, role = params
                self.rejected[role] = proposals_json
                return SimpleNamespace(fetchone=lambda: None, fetchall=lambda: [])
            raise AssertionError(f"unexpected SQL: {text}")

        def begin_write(self) -> None:
            pass

        def execute_for_update(self, sql: str, params: Any = ()):
            return self.execute(sql, params)

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        conn = _Conn()
        registry = PostgresVersionRegistry(
            conn,
            registry_dir=Path(tmp) / "registry",
            owns_conn=True,
        )
        try:
            version_id = registry.publish_skills(
                "seer",
                {"main.md": _registry_skill("check carefully\r\n  ")},
                version_id="seer_baseline",
                set_as_baseline=True,
                expected_current=None,
            )
            shadow_id = registry.publish_skills(
                "seer",
                {"main.md": _registry_skill("shadow candidate")},
                parent_id=version_id,
                source="evolve",
                run_id="run_shadow",
                proposal_ids=["p_shadow"],
                version_id="seer_shadow",
                release_stage="shadow",
                provenance={
                    "trust_bundle_id": "tb_shadow",
                    "release_decision": "shadow_candidate",
                },
            )
            canary_id = registry.publish_skills(
                "seer",
                {"main.md": _registry_skill("canary candidate")},
                parent_id=shadow_id,
                source="evolve",
                run_id="run_canary",
                proposal_ids=["p_canary"],
                version_id="seer_canary",
                release_stage="canary",
                provenance={
                    "trust_bundle_id": "tb_canary",
                    "release_decision": "canary_candidate",
                },
            )

            assert version_id == "seer_baseline"
            assert registry.get_baseline("seer") == version_id
            assert conn.baselines["seer"] == version_id
            assert registry.read_skill_contents("seer", version_id)["main.md"].endswith("\n")
            assert registry.list_roles() == ["seer"]
            summaries = {summary.version_id: summary for summary in registry.list_versions("seer")}
            assert summaries[version_id].is_baseline is True
            assert summaries[version_id].release_stage == "baseline"
            assert summaries[version_id].to_dict()["provenance"]["release_stage"] == "baseline"
            assert summaries[shadow_id].is_baseline is False
            assert summaries[shadow_id].status == "shadow"
            assert summaries[shadow_id].release_stage == "shadow"
            assert summaries[shadow_id].provenance["run_id"] == "run_shadow"
            assert summaries[shadow_id].provenance["proposal_ids"] == ["p_shadow"]
            assert summaries[shadow_id].to_dict()["provenance"]["trust_bundle_id"] == "tb_shadow"
            assert summaries[canary_id].is_baseline is False
            assert summaries[canary_id].status == "canary"
            assert summaries[canary_id].release_stage == "canary"
            assert summaries[canary_id].provenance["release_decision"] == "canary_candidate"
            assert json.loads(conn.versions[("seer", shadow_id)]["provenance_json"])["release_stage"] == "shadow"
            assert json.loads(conn.versions[("seer", canary_id)]["provenance_json"])["release_stage"] == "canary"
            assert (registry.get_skill_dir("seer", version_id) / "main.md").exists()

            config = build_baseline_config(registry)
            assert config.role_versions == {"seer": version_id}
            canary_baseline_id = registry.publish_skills(
                "seer",
                {"main.md": _registry_skill("canary candidate")},
                parent_id=shadow_id,
                source="evolve",
                run_id="run_canary_baseline",
                proposal_ids=["p_canary"],
                version_id=canary_id,
                set_as_baseline=True,
                expected_current=version_id,
                release_stage="baseline",
                provenance={
                    "trust_bundle_id": "tb_canary_baseline",
                    "release_decision": "baseline_promote",
                },
            )
            assert canary_baseline_id == canary_id
            assert registry.get_baseline("seer") == canary_id
            canary_summary = {
                summary.version_id: summary
                for summary in registry.list_versions("seer")
            }[canary_id]
            assert canary_summary.is_baseline is True
            assert canary_summary.release_stage == "baseline"
            assert canary_summary.provenance["release_decision"] == "baseline_promote"
            assert canary_summary.provenance["trust_bundle_id"] == "tb_canary_baseline"
            assert json.loads(conn.versions[("seer", canary_id)]["provenance_json"])["release_stage"] == "baseline"

            config = build_baseline_config(registry)
            assert config.role_versions == {"seer": canary_id}
            promoted_id = registry.publish_skills(
                "seer",
                {"main.md": _registry_skill("baseline promoted")},
                parent_id=canary_id,
                source="evolve",
                run_id="run_baseline",
                proposal_ids=["p_baseline"],
                version_id="seer_promoted",
                set_as_baseline=True,
                expected_current=canary_id,
                release_stage="baseline",
                provenance={
                    "trust_bundle_id": "tb_baseline",
                    "release_decision": "baseline_promote",
                },
            )
            assert registry.get_baseline("seer") == promoted_id
            promoted_summary = {
                summary.version_id: summary
                for summary in registry.list_versions("seer")
            }[promoted_id]
            assert promoted_summary.status == "baseline"
            assert promoted_summary.release_stage == "baseline"
            assert promoted_summary.provenance["trust_bundle_id"] == "tb_baseline"

            config = build_baseline_config(registry)
            assert config.role_versions == {"seer": promoted_id}
            composite = build_composite_skill_dir(registry, config)
            assert composite is not None
            assert (composite / "seer" / "main.md").exists()

            proposal = {
                "proposal_id": "p1",
                "target_file": "seer/main.md",
                "action_type": "append_rule",
                "content": "wait",
                "rationale": "duplicate",
            }
            registry.save_rejected("seer", [proposal], {"significant": False})
            registry.save_rejected("seer", [{**proposal, "proposal_id": "p2"}])
            assert len(registry.load_rejected("seer")) == 1
        finally:
            registry.close()


def test_filesystem_version_registry_refreshes_existing_candidate_provenance_on_baseline() -> None:
    from app.lib.version import VersionRegistry

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        registry = VersionRegistry(Path(tmp) / "registry")
        baseline_id = registry.publish_skills(
            "seer",
            {"main.md": _registry_skill("baseline candidate")},
            version_id="seer_baseline",
            set_as_baseline=True,
            expected_current=None,
        )
        canary_id = registry.publish_skills(
            "seer",
            {"main.md": _registry_skill("canary candidate")},
            parent_id=baseline_id,
            source="evolve",
            run_id="run_canary",
            proposal_ids=["p_canary"],
            version_id="seer_canary",
            release_stage="canary",
            provenance={
                "trust_bundle_id": "tb_canary",
                "release_decision": "canary_candidate",
            },
        )
        assert registry.get_baseline("seer") == baseline_id
        assert {
            summary.version_id: summary
            for summary in registry.list_versions("seer")
        }[canary_id].release_stage == "canary"

        republished = registry.publish_skills(
            "seer",
            {"main.md": _registry_skill("canary candidate")},
            parent_id=baseline_id,
            source="evolve",
            run_id="run_canary_baseline",
            proposal_ids=["p_canary"],
            version_id=canary_id,
            set_as_baseline=True,
            expected_current=baseline_id,
            release_stage="baseline",
            provenance={
                "trust_bundle_id": "tb_canary_baseline",
                "release_decision": "baseline_promote",
            },
        )

        assert republished == canary_id
        assert registry.get_baseline("seer") == canary_id
        summary = {
            item.version_id: item
            for item in registry.list_versions("seer")
        }[canary_id]
        assert summary.is_baseline is True
        assert summary.release_stage == "baseline"
        assert summary.provenance["release_stage"] == "baseline"
        assert summary.provenance["release_decision"] == "baseline_promote"
        assert summary.provenance["trust_bundle_id"] == "tb_canary_baseline"


def test_version_registry_from_env_selects_postgres_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.lib.version import PostgresVersionRegistry, version_registry_from_env

    class _FakeProvider:
        def __init__(self) -> None:
            self.conn = _FakeConn()
            self.opened = 0

        def open_wolf_connection(self) -> _FakeConn:
            return _FakeConn()

        def open_registry_connection(self) -> _FakeConn:
            self.opened += 1
            return self.conn

        def open_evolution_connection(self) -> _FakeConn:
            return _FakeConn()

    provider = _FakeProvider()
    seen_paths: list[Any] = []

    def provider_from_env(*, paths: Any | None = None) -> _FakeProvider:
        seen_paths.append(paths)
        return provider

    import storage.provider

    monkeypatch.setattr(storage.provider, "storage_provider_from_env", provider_from_env)
    paths = SimpleNamespace(registry_dir=tmp_path / "registry")

    registry = version_registry_from_env(paths=paths)

    assert isinstance(registry, PostgresVersionRegistry)
    assert registry.registry_dir == tmp_path / "registry"
    assert provider.opened == 1
    assert seen_paths == [paths]
    registry.close()
    assert provider.conn.closed is True


def test_storage_registry_runtime_factory_selects_postgres_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.lib.version import PostgresVersionRegistry
    from storage.registry.runtime import resolve_registry_dir, version_registry_from_env

    class _FakeProvider:
        def __init__(self) -> None:
            self.conn = _FakeConn()
            self.opened = 0

        def open_wolf_connection(self) -> _FakeConn:
            return _FakeConn()

        def open_registry_connection(self) -> _FakeConn:
            self.opened += 1
            return self.conn

        def open_evolution_connection(self) -> _FakeConn:
            return _FakeConn()

    provider = _FakeProvider()
    seen_paths: list[Any] = []

    def provider_from_env(*, paths: Any | None = None) -> _FakeProvider:
        seen_paths.append(paths)
        return provider

    import storage.provider
    from app.config import DEFAULT_PATHS

    monkeypatch.setattr(storage.provider, "storage_provider_from_env", provider_from_env)
    paths = SimpleNamespace(registry_dir=tmp_path / "registry")

    registry = version_registry_from_env(paths=paths)

    assert isinstance(registry, PostgresVersionRegistry)
    assert registry.registry_dir == tmp_path / "registry"
    assert resolve_registry_dir(tmp_path / "explicit", paths) == tmp_path / "explicit"
    assert resolve_registry_dir(paths=paths) == tmp_path / "registry"
    assert resolve_registry_dir() == DEFAULT_PATHS.registry_dir
    assert provider.opened == 1
    assert seen_paths == [paths]
    registry.close()
    assert provider.conn.closed is True


def test_backend_store_caches_and_closes_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.config import PathConfig
    import ui.backend.store as store_mod

    class _FakeRegistry:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    created: list[_FakeRegistry] = []

    def registry_from_env(*, paths: Any | None = None) -> _FakeRegistry:
        registry = _FakeRegistry()
        created.append(registry)
        return registry

    monkeypatch.setattr(store_mod, "version_registry_from_env", registry_from_env)
    store = store_mod.BackendStore(paths=PathConfig(root=tmp_path))

    first = store.registry
    second = store.registry
    assert first is second
    assert len(created) == 1

    store.close()
    assert created[0].closed is True
    assert store.registry is not first
    assert len(created) == 2


def test_postgres_backend_skips_local_checkpointer() -> None:
    from app.graphs.main import builder

    builder._cache.clear()

    graph = builder.build_root_graph(use_checkpointer=True)

    assert graph is not None
