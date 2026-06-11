from __future__ import annotations

from typing import Any

from storage.interfaces import EvolutionRunData


def _run(run_id: str = "run-1", *, status: str = "training") -> EvolutionRunData:
    return EvolutionRunData(
        run_id=run_id,
        role="seer",
        parent_hash="baseline",
        status=status,
        training_games=3,
        runtime_state={"run_id": run_id, "status": status},
    )


def test_evolution_state_gateway_preserves_provider_and_store_monkeypatches(monkeypatch: Any) -> None:
    import storage.evolution.run_repo as run_repo
    import storage.provider as provider_mod
    from storage.evolution.state_gateway import EvolutionStateGateway

    saved: dict[str, EvolutionRunData] = {}
    opened: list["_FakeConn"] = []
    calls: list[tuple[Any, ...]] = []

    class _FakeConn:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class _FakeProvider:
        def open_evolution_connection(self) -> _FakeConn:
            conn = _FakeConn()
            opened.append(conn)
            return conn

    class _FakeEvolutionStore:
        def __init__(self, conn: _FakeConn) -> None:
            self._conn = conn

        def save_run(self, run: EvolutionRunData) -> None:
            assert self._conn.closed is False
            calls.append(("save_run", run.run_id))
            saved[run.run_id] = run

        def get_run(self, run_id: str) -> EvolutionRunData | None:
            assert self._conn.closed is False
            calls.append(("get_run", run_id))
            return saved.get(run_id)

        def list_runs(
            self,
            role: str | None = None,
            status: str | None = None,
            limit: int = 50,
        ) -> list[EvolutionRunData]:
            assert self._conn.closed is False
            calls.append(("list_runs", role, status, limit))
            return [
                run
                for run in saved.values()
                if (role is None or run.role == role)
                and (status is None or run.status == status)
            ][:limit]

    monkeypatch.setattr(provider_mod, "storage_provider_from_env", lambda: _FakeProvider())
    monkeypatch.setattr(run_repo, "EvolutionStore", _FakeEvolutionStore)

    gateway = EvolutionStateGateway()
    gateway.save_run(_run())
    loaded = gateway.get_run("run-1")
    listed = gateway.list_runs(role="seer", status="training", limit=20)

    assert loaded is saved["run-1"]
    assert listed == [saved["run-1"]]
    assert calls == [
        ("save_run", "run-1"),
        ("get_run", "run-1"),
        ("list_runs", "seer", "training", 20),
    ]
    assert len(opened) == 3
    assert all(conn.closed for conn in opened)


def test_evolution_state_gateway_passes_paths_when_provided(monkeypatch: Any) -> None:
    import storage.provider as provider_mod
    from storage.evolution.state_gateway import EvolutionStateGateway

    calls: list[Any] = []

    class _FakeProvider:
        def open_evolution_connection(self) -> Any:
            raise RuntimeError("stop after provider resolution")

    def provider_from_env(*, paths: Any = None) -> _FakeProvider:
        calls.append(paths)
        return _FakeProvider()

    paths = object()
    monkeypatch.setattr(provider_mod, "storage_provider_from_env", provider_from_env)

    try:
        EvolutionStateGateway(paths=paths).get_run("run-1")
    except RuntimeError as exc:
        assert str(exc) == "stop after provider resolution"
    else:  # pragma: no cover - explicit failure path
        raise AssertionError("provider exception did not propagate")

    assert calls == [paths]


def test_evolution_state_gateway_runtime_state_uses_provider_and_saves_trust_bundle(
    monkeypatch: Any,
) -> None:
    import storage.evolution.run_repo as run_repo
    import storage.provider as provider_mod
    from storage.evolution.state_gateway import EvolutionStateGateway

    opened: list["_FakeConn"] = []
    calls: list[tuple[str, str]] = []

    class _FakeConn:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class _FakeProvider:
        def open_evolution_connection(self) -> _FakeConn:
            conn = _FakeConn()
            opened.append(conn)
            return conn

    class _FakeEvolutionStore:
        def __init__(self, conn: _FakeConn) -> None:
            self._conn = conn

        def save_run(self, run: EvolutionRunData) -> None:
            assert self._conn.closed is False
            calls.append(("save_run", run.run_id))

        def save_trust_bundle(self, bundle: dict[str, Any]) -> dict[str, Any]:
            assert self._conn.closed is False
            bundle_id = str(bundle["trust_bundle_id"])
            calls.append(("save_trust_bundle", bundle_id))
            return {"id": bundle_id}

    def fail_provider_from_env(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("env provider should not be used")

    monkeypatch.setattr(provider_mod, "storage_provider_from_env", fail_provider_from_env)
    monkeypatch.setattr(run_repo, "EvolutionStore", _FakeEvolutionStore)

    trust_bundle = {
        "schema_version": "trust_bundle_v1",
        "trust_bundle_id": "tb-run-1",
    }
    EvolutionStateGateway(provider=_FakeProvider()).save_runtime_state(
        _run("run-rt"),
        trust_bundle=trust_bundle,
    )

    assert calls == [
        ("save_run", "run-rt"),
        ("save_trust_bundle", "tb-run-1"),
    ]
    assert len(opened) == 1
    assert opened[0].closed is True


def test_evolution_state_gateway_runtime_state_unwraps_trust_bundle_payload(
    monkeypatch: Any,
) -> None:
    import storage.evolution.run_repo as run_repo
    from storage.evolution.state_gateway import EvolutionStateGateway

    calls: list[tuple[str, str]] = []

    class _FakeConn:
        def close(self) -> None:
            return None

    class _FakeProvider:
        def open_evolution_connection(self) -> _FakeConn:
            return _FakeConn()

    class _FakeEvolutionStore:
        def __init__(self, conn: _FakeConn) -> None:
            self._conn = conn

        def save_run(self, run: EvolutionRunData) -> None:
            calls.append(("save_run", run.run_id))

        def save_trust_bundle(self, bundle: dict[str, Any]) -> dict[str, Any]:
            bundle_id = str(bundle["trust_bundle_id"])
            calls.append(("save_trust_bundle", bundle_id))
            return {"id": bundle_id}

    monkeypatch.setattr(run_repo, "EvolutionStore", _FakeEvolutionStore)

    EvolutionStateGateway(provider=_FakeProvider()).save_runtime_state(
        _run("run-wrapper"),
        trust_bundle={
            "kind": "evolution_trust_bundle",
            "schema_version": 1,
            "trust_bundle": {
                "schema_version": "trust_bundle_v1",
                "trust_bundle_id": "tb-run-wrapper",
            },
        },
    )

    assert calls == [
        ("save_run", "run-wrapper"),
        ("save_trust_bundle", "tb-run-wrapper"),
    ]


def test_evolution_state_gateway_runtime_state_close_error_is_best_effort(
    monkeypatch: Any,
) -> None:
    import storage.evolution.run_repo as run_repo
    from storage.evolution.state_gateway import EvolutionStateGateway

    calls: list[tuple[str, str]] = []

    class _CloseFailConn:
        def close(self) -> None:
            raise RuntimeError("close failed")

    class _FakeProvider:
        def open_evolution_connection(self) -> _CloseFailConn:
            return _CloseFailConn()

    class _FakeEvolutionStore:
        def __init__(self, conn: _CloseFailConn) -> None:
            self._conn = conn

        def save_run(self, run: EvolutionRunData) -> None:
            calls.append(("save_run", run.run_id))

    monkeypatch.setattr(run_repo, "EvolutionStore", _FakeEvolutionStore)

    EvolutionStateGateway(provider=_FakeProvider()).save_runtime_state(_run("run-close"))

    assert calls == [("save_run", "run-close")]


def test_evolution_state_gateway_get_trust_bundle_uses_store_and_closes(
    monkeypatch: Any,
) -> None:
    import storage.evolution.run_repo as run_repo
    from storage.evolution.state_gateway import EvolutionStateGateway

    opened: list["_FakeConn"] = []
    calls: list[tuple[str, str]] = []

    class _FakeConn:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class _FakeProvider:
        def open_evolution_connection(self) -> _FakeConn:
            conn = _FakeConn()
            opened.append(conn)
            return conn

    class _FakeEvolutionStore:
        def __init__(self, conn: _FakeConn) -> None:
            self._conn = conn

        def get_trust_bundle(self, run_id: str) -> dict[str, Any] | None:
            assert self._conn.closed is False
            calls.append(("get_trust_bundle", run_id))
            return {"kind": "evolution_trust_bundle", "run_id": run_id}

    monkeypatch.setattr(run_repo, "EvolutionStore", _FakeEvolutionStore)

    payload = EvolutionStateGateway(provider=_FakeProvider()).get_trust_bundle("run-1")

    assert payload == {"kind": "evolution_trust_bundle", "run_id": "run-1"}
    assert calls == [("get_trust_bundle", "run-1")]
    assert len(opened) == 1
    assert opened[0].closed is True
