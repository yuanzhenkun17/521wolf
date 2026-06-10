from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from storage.provider import (
    PostgresStorageProvider,
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


@pytest.mark.parametrize(
    ("helper_name", "factory_name"),
    [
        ("open_wolf_connection", "get_wolf_postgres_connection"),
        ("open_registry_connection", "get_registry_postgres_connection"),
        ("open_evolution_connection", "get_evolution_postgres_connection"),
    ],
)
def test_domain_connection_helpers_apply_connect_kwargs_to_env_postgres_provider(
    monkeypatch: pytest.MonkeyPatch,
    helper_name: str,
    factory_name: str,
) -> None:
    import storage.postgres
    import storage.provider

    calls: list[tuple[str, dict[str, Any]]] = []

    def factory(conninfo: str | None = None, **kwargs: Any) -> _FakeConn:
        calls.append((conninfo or "", kwargs))
        return _FakeConn()

    monkeypatch.setattr(storage.postgres, factory_name, factory)
    monkeypatch.setattr(
        storage.provider,
        "storage_provider_from_env",
        lambda: PostgresStorageProvider("postgresql://app@example/db"),
    )
    helper = getattr(storage.provider, helper_name)

    conn = helper(connect_kwargs={"connect_timeout": 3})

    assert isinstance(conn, _FakeConn)
    assert calls == [
        ("postgresql://app@example/db", {"connect_timeout": 3}),
    ]


def test_domain_connection_helpers_do_not_override_existing_connect_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import storage.postgres
    import storage.provider

    calls: list[dict[str, Any]] = []

    def factory(conninfo: str | None = None, **kwargs: Any) -> _FakeConn:
        calls.append(kwargs)
        return _FakeConn()

    monkeypatch.setattr(storage.postgres, "get_wolf_postgres_connection", factory)
    monkeypatch.setattr(
        storage.provider,
        "storage_provider_from_env",
        lambda: PostgresStorageProvider(
            "postgresql://app@example/db",
            connect_kwargs={"application_name": "existing"},
        ),
    )

    conn = storage.provider.open_wolf_connection(connect_kwargs={"connect_timeout": 3})

    assert isinstance(conn, _FakeConn)
    assert calls == [{"application_name": "existing"}]


@pytest.mark.parametrize(
    ("helper_name", "domain"),
    [
        ("open_wolf_connection", "wolf"),
        ("open_registry_connection", "registry"),
        ("open_evolution_connection", "evolution"),
    ],
)
def test_domain_connection_helpers_keep_fake_provider_with_connect_kwargs(
    monkeypatch: pytest.MonkeyPatch,
    helper_name: str,
    domain: str,
) -> None:
    class _FakeProvider:
        def __init__(self) -> None:
            self.wolf_conn = _FakeConn()
            self.registry_conn = _FakeConn()
            self.evolution_conn = _FakeConn()

        def open_wolf_connection(self) -> _FakeConn:
            return self.wolf_conn

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

    conn = helper(paths=paths, connect_kwargs={"connect_timeout": 3})

    assert conn is getattr(provider, f"{domain}_conn")
    assert seen_paths == [paths]


def test_startup_postgresql_check_uses_short_connect_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ui.backend.startup_checks import _check_postgresql

    class _Cursor:
        def fetchone(self) -> dict[str, int]:
            return {"ok": 1}

    class _Conn(_FakeConn):
        def execute(self, sql: str, parameters: Any = ()) -> _Cursor:
            return _Cursor()

    import storage.postgres
    import storage.provider

    calls: list[tuple[str, dict[str, Any]]] = []
    seen_paths: list[Any] = []
    conn = _Conn()

    def factory(conninfo: str | None = None, **kwargs: Any) -> _Conn:
        calls.append((conninfo or "", kwargs))
        return conn

    def provider_from_env(*, paths: Any | None = None) -> PostgresStorageProvider:
        seen_paths.append(paths)
        return PostgresStorageProvider("postgresql://app@example/db")

    monkeypatch.setattr(storage.postgres, "get_wolf_postgres_connection", factory)
    monkeypatch.setattr(storage.provider, "storage_provider_from_env", provider_from_env)
    paths = SimpleNamespace(root="ignored")

    result = _check_postgresql(SimpleNamespace(paths=paths))

    assert result["status"] == "ok"
    assert calls == [
        ("postgresql://app@example/db", {"connect_timeout": 3}),
    ]
    assert seen_paths == [paths]
    assert conn.commits == 1
    assert conn.closed is True


def test_startup_alembic_check_uses_short_connect_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ui.backend.startup_checks as startup_checks

    class _Cursor:
        def fetchall(self) -> list[dict[str, str]]:
            return [{"version_num": "head_1"}]

    class _Conn(_FakeConn):
        def execute(self, sql: str, parameters: Any = ()) -> _Cursor:
            return _Cursor()

    import storage.postgres
    import storage.provider

    calls: list[tuple[str, dict[str, Any]]] = []
    seen_paths: list[Any] = []
    conn = _Conn()

    def factory(conninfo: str | None = None, **kwargs: Any) -> _Conn:
        calls.append((conninfo or "", kwargs))
        return conn

    def provider_from_env(*, paths: Any | None = None) -> PostgresStorageProvider:
        seen_paths.append(paths)
        return PostgresStorageProvider("postgresql://app@example/db")

    monkeypatch.setattr(startup_checks, "_migration_heads", lambda: ["head_1"])
    monkeypatch.setattr(storage.postgres, "get_wolf_postgres_connection", factory)
    monkeypatch.setattr(storage.provider, "storage_provider_from_env", provider_from_env)
    paths = SimpleNamespace(root="ignored")

    result = startup_checks._check_alembic(SimpleNamespace(paths=paths))

    assert result["status"] == "ok"
    assert calls == [
        ("postgresql://app@example/db", {"connect_timeout": 3}),
    ]
    assert seen_paths == [paths]
    assert conn.commits == 1
    assert conn.closed is True


def test_startup_registry_check_uses_short_connect_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from ui.backend.startup_checks import _registry_for_check

    class _Registry:
        def __init__(
            self,
            conn: _FakeConn,
            *,
            registry_dir: Any,
            owns_conn: bool,
        ) -> None:
            self.conn = conn
            self.registry_dir = registry_dir
            self.owns_conn = owns_conn

    import app.lib.version
    import storage.postgres
    import storage.provider

    calls: list[tuple[str, dict[str, Any]]] = []
    seen_paths: list[Any] = []
    conn = _FakeConn()

    def factory(conninfo: str | None = None, **kwargs: Any) -> _FakeConn:
        calls.append((conninfo or "", kwargs))
        return conn

    def provider_from_env(*, paths: Any | None = None) -> PostgresStorageProvider:
        seen_paths.append(paths)
        return PostgresStorageProvider("postgresql://app@example/db")

    monkeypatch.setattr(app.lib.version, "PostgresVersionRegistry", _Registry)
    monkeypatch.setattr(storage.postgres, "get_registry_postgres_connection", factory)
    monkeypatch.setattr(storage.provider, "storage_provider_from_env", provider_from_env)
    paths = SimpleNamespace(registry_dir=tmp_path / "registry")

    registry, owns_registry = _registry_for_check(SimpleNamespace(paths=paths))

    assert isinstance(registry, _Registry)
    assert owns_registry is True
    assert registry.conn is conn
    assert registry.registry_dir == tmp_path / "registry"
    assert registry.owns_conn is True
    assert calls == [
        ("postgresql://app@example/db", {"connect_timeout": 3}),
    ]
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
            canary_before = dict(conn.versions[("seer", canary_id)])
            with pytest.raises(RuntimeError, match="Failed to set baseline for seer"):
                registry.publish_skills(
                    "seer",
                    {"main.md": _registry_skill("canary candidate")},
                    parent_id=shadow_id,
                    source="evolve",
                    run_id="run_canary_wrong_expected",
                    proposal_ids=["p_canary"],
                    version_id=canary_id,
                    set_as_baseline=True,
                    expected_current="wrong_baseline",
                    release_stage="baseline",
                    provenance={
                        "trust_bundle_id": "tb_should_not_persist",
                        "release_decision": "baseline_promote",
                    },
                )
            assert registry.get_baseline("seer") == version_id
            assert conn.versions[("seer", canary_id)]["status"] == canary_before["status"]
            assert conn.versions[("seer", canary_id)]["provenance_json"] == canary_before["provenance_json"]

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


def test_backend_store_ui_task_connection_uses_wolf_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.config import PathConfig
    import storage.provider
    import ui.backend.store as store_mod

    conn = _FakeConn()
    seen_paths: list[Any] = []

    def open_conn(provider: Any | None = None, *, paths: Any | None = None) -> _FakeConn:
        assert provider is None
        seen_paths.append(paths)
        return conn

    monkeypatch.setattr(storage.provider, "open_wolf_connection", open_conn)
    paths = PathConfig(root=tmp_path)
    store = store_mod.BackendStore(paths=paths)

    assert store.task_service.open_connection() is conn
    assert store._open_ui_task_connection() is conn
    assert seen_paths == [paths, paths]


def test_backend_game_read_connection_uses_wolf_helper(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.config import PathConfig
    import storage.provider
    import ui.backend.store as store_mod

    conn = _FakeConn()
    seen_paths: list[Any] = []

    def open_conn(provider: Any | None = None, *, paths: Any | None = None) -> _FakeConn:
        assert provider is None
        seen_paths.append(paths)
        return conn

    monkeypatch.setattr(storage.provider, "open_wolf_connection", open_conn)
    paths = PathConfig(root=tmp_path)
    store = store_mod.BackendStore(paths=paths)

    assert store._open_wolf_connection() is conn
    assert seen_paths == [paths]


def test_backend_game_read_gateway_reuses_and_closes_wolf_connection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.config import PathConfig
    import storage.provider
    import ui.backend.store as store_mod

    class _ReadConn:
        def __init__(self) -> None:
            self.closed = False
            self.commits = 0
            self.rollbacks = 0

        def commit(self) -> None:
            self.commits += 1

        def rollback(self) -> None:
            self.rollbacks += 1

        def close(self) -> None:
            self.closed = True

    opened: list[_ReadConn] = []
    seen_paths: list[Any] = []

    def open_conn(provider: Any | None = None, *, paths: Any | None = None) -> _ReadConn:
        assert provider is None
        seen_paths.append(paths)
        conn = _ReadConn()
        opened.append(conn)
        return conn

    monkeypatch.setattr(storage.provider, "open_wolf_connection", open_conn)
    paths = PathConfig(root=tmp_path)
    store = store_mod.BackendStore(paths=paths)

    assert store._read_wolf_repository(lambda _repo: "ok") == "ok"
    assert store._read_wolf_repository(lambda _repo: "again") == "again"
    assert len(opened) == 1
    assert opened[0].commits == 2
    assert opened[0].closed is False

    with pytest.raises(RuntimeError, match="boom"):
        store._read_wolf_repository(lambda _repo: (_ for _ in ()).throw(RuntimeError("boom")))
    assert opened[0].rollbacks == 1
    assert opened[0].closed is True

    assert store._read_wolf_repository(lambda _repo: "after") == "after"
    assert len(opened) == 2
    assert opened[1].commits == 1
    assert seen_paths == [paths, paths]

    store._close_wolf_read_connection()
    assert opened[1].closed is True


def test_backend_game_read_gateway_closes_when_rollback_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.config import PathConfig
    import storage.provider
    import ui.backend.store as store_mod

    class _ReadConn:
        def __init__(self, *, rollback_fails: bool = False) -> None:
            self.closed = False
            self.rollback_fails = rollback_fails

        def commit(self) -> None:
            pass

        def rollback(self) -> None:
            if self.rollback_fails:
                raise RuntimeError("rollback failed")

        def close(self) -> None:
            self.closed = True

    opened: list[_ReadConn] = []

    def open_conn(provider: Any | None = None, *, paths: Any | None = None) -> _ReadConn:
        assert provider is None
        assert paths is not None
        conn = _ReadConn(rollback_fails=not opened)
        opened.append(conn)
        return conn

    monkeypatch.setattr(storage.provider, "open_wolf_connection", open_conn)
    store = store_mod.BackendStore(paths=PathConfig(root=tmp_path))

    with pytest.raises(RuntimeError, match="read failed"):
        store._read_wolf_repository(lambda _repo: (_ for _ in ()).throw(RuntimeError("read failed")))
    assert opened[0].closed is True

    assert store._read_wolf_repository(lambda _repo: "fresh") == "fresh"
    assert len(opened) == 2
    assert opened[1].closed is False


def test_backend_game_delete_coordinator_uses_store_delete_hook(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.config import PathConfig
    import ui.backend.store as store_mod

    store = store_mod.BackendStore(paths=PathConfig(root=tmp_path))
    store.games["delete_me"] = {"game_id": "delete_me", "log_source": "normal"}
    deleted: list[str] = []
    invalidated = 0

    def delete_from_pg(game_id: str) -> None:
        deleted.append(game_id)

    def invalidate() -> None:
        nonlocal invalidated
        invalidated += 1

    monkeypatch.setattr(store, "_delete_game_from_pg", delete_from_pg)
    monkeypatch.setattr(store, "invalidate_game_history_index", invalidate)

    payload = store.delete_game("delete_me")

    assert payload == {
        "game_id": "delete_me",
        "deleted": True,
        "log_source": "normal",
        "force": False,
    }
    assert deleted == ["delete_me"]
    assert "delete_me" not in store.games
    assert store._is_game_deleted("delete_me") is True
    assert invalidated == 1


def test_backend_game_delete_coordinator_preserves_state_when_storage_delete_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.config import PathConfig
    import ui.backend.store as store_mod

    store = store_mod.BackendStore(paths=PathConfig(root=tmp_path))
    store.games["fail_delete"] = {"game_id": "fail_delete", "log_source": "normal"}
    invalidated = 0

    def fail_delete(_game_id: str) -> None:
        raise RuntimeError("delete failed")

    def invalidate() -> None:
        nonlocal invalidated
        invalidated += 1

    monkeypatch.setattr(store, "_delete_game_from_pg", fail_delete)
    monkeypatch.setattr(store, "invalidate_game_history_index", invalidate)

    with pytest.raises(RuntimeError, match="delete failed"):
        store.delete_game("fail_delete")

    assert "fail_delete" in store.games
    assert store._is_game_deleted("fail_delete") is False
    assert invalidated == 0


def test_backend_game_delete_coordinator_deletes_persisted_only_game(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.config import PathConfig
    import ui.backend.store as store_mod

    store = store_mod.BackendStore(paths=PathConfig(root=tmp_path))
    loaded: list[str] = []
    deleted: list[str] = []
    invalidated = 0

    def load_from_pg(game_id: str) -> dict[str, Any] | None:
        loaded.append(game_id)
        return {"game_id": game_id, "config": {"log_source": "normal"}}

    def delete_from_pg(game_id: str) -> None:
        deleted.append(game_id)

    def invalidate() -> None:
        nonlocal invalidated
        invalidated += 1

    monkeypatch.setattr(store, "_load_game_from_pg", load_from_pg)
    monkeypatch.setattr(store, "_delete_game_from_pg", delete_from_pg)
    monkeypatch.setattr(store, "invalidate_game_history_index", invalidate)

    payload = store.delete_game("persisted_only")

    assert payload == {
        "game_id": "persisted_only",
        "deleted": True,
        "log_source": "normal",
        "force": False,
    }
    assert loaded == ["persisted_only"]
    assert deleted == ["persisted_only"]
    assert store._is_game_deleted("persisted_only") is True
    assert invalidated == 1


def test_backend_game_delete_coordinator_cancels_live_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    from app.config import PathConfig
    import ui.backend.store as store_mod

    class _Persistence:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class _LiveSession:
        def __init__(self) -> None:
            self.cancelled = False
            self.persistence = _Persistence()

        def snapshot(self) -> dict[str, Any]:
            return {"game_id": "live_delete", "log_source": "normal"}

        def cancel(self) -> None:
            self.cancelled = True

    store = store_mod.BackendStore(paths=PathConfig(root=tmp_path))
    live = _LiveSession()
    store.live_sessions["live_delete"] = live
    store.games["live_delete"] = {"game_id": "live_delete", "log_source": "normal"}
    deleted: list[str] = []
    invalidated = 0

    def delete_from_pg(game_id: str) -> None:
        deleted.append(game_id)

    def invalidate() -> None:
        nonlocal invalidated
        invalidated += 1

    monkeypatch.setattr(store, "_delete_game_from_pg", delete_from_pg)
    monkeypatch.setattr(store, "invalidate_game_history_index", invalidate)

    payload = store.delete_game("live_delete")

    assert payload == {
        "game_id": "live_delete",
        "deleted": True,
        "log_source": "normal",
        "force": False,
    }
    assert deleted == ["live_delete"]
    assert live.cancelled is True
    assert live.persistence.closed is True
    assert "live_delete" not in store.live_sessions
    assert "live_delete" not in store.games
    assert store._is_game_deleted("live_delete") is True
    assert invalidated == 1


def test_postgres_backend_skips_local_checkpointer() -> None:
    from app.graphs.main import builder

    builder._cache.clear()

    graph = builder.build_root_graph(use_checkpointer=True)

    assert graph is not None
