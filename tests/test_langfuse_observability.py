"""Unit contracts for the optional Langfuse observability integration.

The production integration is intentionally optional and must never require a
real Langfuse server during tests. These tests stub the SDK and skip until
``app.services.observability`` lands in the app code.
"""

from __future__ import annotations

import asyncio
import importlib
import importlib.util
import sys
import types
from collections.abc import Iterable
from contextlib import nullcontext
from typing import Any

import pytest


_LANGFUSE_ENV_KEYS = (
    "LANGFUSE_TRACING_ENABLED",
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_BASE_URL",
    "LANGFUSE_ENVIRONMENT",
    "LANGFUSE_RELEASE",
    "LANGFUSE_SAMPLE_RATE",
    "LANGFUSE_CAPTURE_INPUT_OUTPUT",
)


def _clear_langfuse_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _LANGFUSE_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _observability_available() -> bool:
    return importlib.util.find_spec("app.services.observability") is not None


def _load_observability(monkeypatch: pytest.MonkeyPatch):
    if not _observability_available():
        pytest.skip("app.services.observability has not been implemented yet")

    monkeypatch.delitem(sys.modules, "app.services.observability", raising=False)
    return importlib.import_module("app.services.observability")


def _install_langfuse_network_guard(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple, dict]]:
    sdk_calls: list[tuple[str, tuple, dict]] = []

    def _raise_sdk_call(name: str):
        def _call(*args: Any, **kwargs: Any):
            sdk_calls.append((name, args, kwargs))
            raise AssertionError(f"Langfuse SDK should not be used for no-op tracing: {name}")

        return _call

    class _Langfuse:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            sdk_calls.append(("Langfuse", args, kwargs))
            raise AssertionError("Langfuse client should not be constructed for no-op tracing")

    class _CallbackHandler:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            sdk_calls.append(("CallbackHandler", args, kwargs))
            raise AssertionError("Langfuse callback should not be constructed for no-op tracing")

    langfuse_mod = types.ModuleType("langfuse")
    langfuse_mod.Langfuse = _Langfuse
    langfuse_mod.observe = _raise_sdk_call("observe")
    langfuse_mod.propagate_attributes = _raise_sdk_call("propagate_attributes")

    langfuse_langchain_mod = types.ModuleType("langfuse.langchain")
    langfuse_langchain_mod.CallbackHandler = _CallbackHandler

    monkeypatch.setitem(sys.modules, "langfuse", langfuse_mod)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", langfuse_langchain_mod)
    return sdk_calls


def _assert_observability_api(obs: Any) -> None:
    missing = [
        name
        for name in (
            "langfuse_enabled",
            "get_langfuse_client",
            "langfuse_callbacks",
            "langfuse_run_context",
            "build_langfuse_dataset_item_id",
            "get_langfuse_dataset_item",
            "get_experiment_url",
            "link_langfuse_dataset_run_item",
            "score_dataset_run",
            "flush_langfuse",
        )
        if not callable(getattr(obs, name, None))
    ]
    assert missing == []


def _assert_empty_callbacks(value: Any) -> None:
    if value is None:
        return
    if isinstance(value, dict):
        assert value.get("callbacks") in (None, [])
        return
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        assert list(value) == []
        return
    assert value in (None, [])


def test_tracing_disabled_is_noop_without_langfuse_keys(monkeypatch: pytest.MonkeyPatch):
    _clear_langfuse_env(monkeypatch)
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://127.0.0.1:3000")
    sdk_calls = _install_langfuse_network_guard(monkeypatch)

    obs = _load_observability(monkeypatch)
    _assert_observability_api(obs)

    assert obs.langfuse_enabled() is False
    assert obs.get_langfuse_client() is None
    _assert_empty_callbacks(
        obs.langfuse_callbacks(
            trace_id="trace-disabled",
            session_id="game-disabled",
            metadata={"game_id": "game-disabled"},
        )
    )
    with obs.langfuse_run_context(
        trace_name="eval.disabled",
        trace_id_seed="trace-disabled",
        session_id="game-disabled",
        metadata={"game_id": "game-disabled"},
    ) as observation:
        assert observation is None
    obs.flush_langfuse()
    assert sdk_calls == []


def test_tracing_enabled_without_keys_is_still_noop(monkeypatch: pytest.MonkeyPatch):
    _clear_langfuse_env(monkeypatch)
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://127.0.0.1:3000")
    sdk_calls = _install_langfuse_network_guard(monkeypatch)

    obs = _load_observability(monkeypatch)
    _assert_observability_api(obs)

    assert obs.langfuse_enabled() is False
    assert obs.get_langfuse_client() is None
    _assert_empty_callbacks(
        obs.langfuse_callbacks(
            trace_id="trace-missing-keys",
            session_id="game-missing-keys",
            metadata={"game_id": "game-missing-keys"},
        )
    )
    with obs.langfuse_run_context(
        trace_name="eval.missing_keys",
        trace_id_seed="trace-missing-keys",
        session_id="game-missing-keys",
        metadata={"game_id": "game-missing-keys"},
    ) as observation:
        assert observation is None
    obs.flush_langfuse()
    assert sdk_calls == []


def test_langfuse_client_uses_mask_and_explicit_trace_helpers(monkeypatch: pytest.MonkeyPatch):
    _clear_langfuse_env(monkeypatch)
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://127.0.0.1:3000/")
    monkeypatch.setenv("LANGFUSE_ENVIRONMENT", "test")
    monkeypatch.setenv("LANGFUSE_RELEASE", "release-test")
    monkeypatch.setenv("LANGFUSE_SAMPLE_RATE", "0.5")

    captured: list[dict[str, Any]] = []

    class _Langfuse:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured.append({"name": "Langfuse", "args": args, "kwargs": kwargs})

        def create_score(self, **kwargs: Any) -> None:
            captured.append({"name": "create_score", "kwargs": kwargs})

        def score_current_trace(self, **kwargs: Any) -> None:
            captured.append({"name": "score_current_trace", "kwargs": kwargs})

        def get_current_trace_id(self) -> str:
            captured.append({"name": "get_current_trace_id"})
            return "trace-current"

        def get_trace_url(self, *, trace_id: str | None = None) -> str:
            captured.append({"name": "get_trace_url", "trace_id": trace_id})
            return f"http://127.0.0.1:3000/project/traces/{trace_id or 'trace-current'}"

    langfuse_mod = types.ModuleType("langfuse")
    langfuse_mod.Langfuse = _Langfuse
    monkeypatch.setitem(sys.modules, "langfuse", langfuse_mod)

    obs = _load_observability(monkeypatch)

    client = obs.get_langfuse_client()
    assert client is not None
    init = captured[0]
    assert init["name"] == "Langfuse"
    assert init["kwargs"]["base_url"] == "http://127.0.0.1:3000"
    assert init["kwargs"]["environment"] == "test"
    assert init["kwargs"]["release"] == "release-test"
    assert init["kwargs"]["sample_rate"] == 0.5
    mask = init["kwargs"]["mask"]
    assert callable(mask)
    assert mask({"api_key": "sk-secret", "prompt": "full prompt"})["api_key"] == "[REDACTED]"
    assert obs.capture_input_output() is False

    obs.score_trace(
        "trace-explicit",
        "eval.rankable",
        True,
        data_type="BOOLEAN",
        metadata={"batch_id": "batch-a"},
    )
    obs.score_trace(
        None,
        "eval.current",
        1.0,
        data_type="NUMERIC",
        metadata={"batch_id": "batch-b"},
    )

    assert obs.get_current_trace_id() == "trace-current"
    assert obs.get_trace_url("trace-explicit").endswith("/trace-explicit")

    by_name = {call["name"]: call for call in captured if call["name"] != "Langfuse"}
    assert by_name["create_score"]["kwargs"]["trace_id"] == "trace-explicit"
    assert by_name["create_score"]["kwargs"]["value"] is True
    assert by_name["score_current_trace"]["kwargs"]["name"] == "eval.current"


def test_dataset_experiment_facade_is_noop_when_tracing_disabled(monkeypatch: pytest.MonkeyPatch):
    _clear_langfuse_env(monkeypatch)
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://127.0.0.1:3000")
    sdk_calls = _install_langfuse_network_guard(monkeypatch)

    obs = _load_observability(monkeypatch)

    item_id = obs.build_langfuse_dataset_item_id(
        evaluation_set_id="eval-contract-v1@v1",
        seed_set_id="seed-set-a",
        seed=910001,
    )
    assert item_id == "eval-contract-v1@v1:seed-set-a:910001"
    assert obs.get_langfuse_dataset_item("eval-contract-v1@v1", item_id) is None
    assert obs.get_experiment_url(dataset_name="eval-contract-v1@v1", run_name="run-disabled") is None

    link = obs.link_langfuse_dataset_run_item(
        dataset_name="eval-contract-v1@v1",
        dataset_item_id=item_id,
        experiment_name="experiment-disabled",
        run_name="run-disabled",
        trace_id="trace-disabled",
        metadata={"batch_id": "batch-disabled"},
    )
    assert link.linked is False
    assert link.trace_id == "trace-disabled"
    assert link.trace_url is None
    assert link.experiment_url is None
    assert link.metadata["batch_id"] == "batch-disabled"

    obs.score_dataset_run("dataset-run-disabled", "eval.rankable", True, data_type="BOOLEAN")
    assert sdk_calls == []


def test_dataset_experiment_facade_links_trace_and_scores_run(monkeypatch: pytest.MonkeyPatch):
    _clear_langfuse_env(monkeypatch)
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://127.0.0.1:3000/")

    captured: list[dict[str, Any]] = []

    class _Dataset:
        id = "dataset-123"

        def __init__(self, item_id: str) -> None:
            self.items = [
                types.SimpleNamespace(
                    id=item_id,
                    dataset_id=self.id,
                    dataset_name="eval-contract-v1@v1",
                    metadata={"item_name": item_id},
                )
            ]

    class _Langfuse:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._base_url = kwargs["base_url"]
            self._project_id = "project-123"
            captured.append({"name": "Langfuse", "args": args, "kwargs": kwargs})

        def get_dataset(self, name: str, **kwargs: Any) -> _Dataset:
            captured.append({"name": "get_dataset", "name": name, "kwargs": kwargs})
            return _Dataset("eval-contract-v1@v1:seed-set-a:910001")

        def create_dataset_run_item(self, **kwargs: Any) -> Any:
            captured.append({"name": "create_dataset_run_item", "kwargs": kwargs})
            return types.SimpleNamespace(
                id="dataset-run-item-123",
                dataset_id="dataset-123",
                dataset_run_id="dataset-run-123",
            )

        def get_dataset_run(self, *, dataset_name: str, run_name: str) -> Any:
            captured.append({"name": "get_dataset_run", "dataset_name": dataset_name, "run_name": run_name})
            return types.SimpleNamespace(
                id="dataset-run-123",
                dataset_id="dataset-123",
                dataset_name=dataset_name,
                name=run_name,
            )

        def create_score(self, **kwargs: Any) -> None:
            captured.append({"name": "create_score", "kwargs": kwargs})

    langfuse_mod = types.ModuleType("langfuse")
    langfuse_mod.Langfuse = _Langfuse
    monkeypatch.setitem(sys.modules, "langfuse", langfuse_mod)

    obs = _load_observability(monkeypatch)
    item_id = obs.build_langfuse_dataset_item_id(
        evaluation_set_id="eval-contract-v1@v1",
        seed_set_id="seed-set-a",
        seed=910001,
    )

    item = obs.get_langfuse_dataset_item("eval-contract-v1@v1", item_id)
    assert item is not None
    assert item.id == item_id

    link = obs.link_langfuse_dataset_run_item(
        dataset_name="eval-contract-v1@v1",
        dataset_item_id=item_id,
        experiment_name="experiment-a",
        run_name="run-model-a",
        trace_id="trace-abc",
        observation_id="obs-abc",
        metadata={"batch_id": "batch-a"},
    )

    assert link.linked is True
    assert link.dataset_run_id == "dataset-run-123"
    assert link.dataset_run_item_id == "dataset-run-item-123"
    assert link.trace_url == "http://127.0.0.1:3000/project/project-123/traces/trace-abc"
    assert link.experiment_url == (
        "http://127.0.0.1:3000/project/project-123/datasets/dataset-123/runs/dataset-run-123"
    )
    assert link.to_dict()["experiment_url"] == link.experiment_url

    create_call = next(call for call in captured if call["name"] == "create_dataset_run_item")
    assert create_call["kwargs"]["run_name"] == "run-model-a"
    assert create_call["kwargs"]["dataset_item_id"] == item_id
    assert create_call["kwargs"]["trace_id"] == "trace-abc"
    assert create_call["kwargs"]["observation_id"] == "obs-abc"
    assert create_call["kwargs"]["metadata"]["batch_id"] == "batch-a"
    assert create_call["kwargs"]["metadata"]["langfuse_dataset_name"] == "eval-contract-v1@v1"
    assert create_call["kwargs"]["metadata"]["langfuse_dataset_item_id"] == item_id
    assert create_call["kwargs"]["metadata"]["langfuse_experiment_name"] == "experiment-a"
    assert create_call["kwargs"]["metadata"]["langfuse_run_name"] == "run-model-a"

    obs.score_dataset_run(
        link.dataset_run_id,
        "eval.win_rate",
        0.75,
        data_type="NUMERIC",
        metadata={"batch_id": "batch-a"},
    )
    score_call = [call for call in captured if call["name"] == "create_score"][-1]
    assert score_call["kwargs"] == {
        "dataset_run_id": "dataset-run-123",
        "name": "eval.win_rate",
        "value": 0.75,
        "data_type": "NUMERIC",
        "comment": None,
        "metadata": {"batch_id": "batch-a"},
    }


def test_dataset_run_item_link_uses_langfuse_v4_internal_api(monkeypatch: pytest.MonkeyPatch):
    _clear_langfuse_env(monkeypatch)
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://127.0.0.1:3000/")

    captured: list[dict[str, Any]] = []

    class _DatasetRunItems:
        def create(self, **kwargs: Any) -> Any:
            captured.append({"name": "api.dataset_run_items.create", "kwargs": kwargs})
            return {
                "id": "dataset-run-item-api",
                "datasetRunId": "dataset-run-api",
                "datasetItemId": kwargs["dataset_item_id"],
            }

    class _Datasets:
        def get_run(self, *, dataset_name: str, run_name: str) -> Any:
            captured.append({
                "name": "api.datasets.get_run",
                "dataset_name": dataset_name,
                "run_name": run_name,
            })
            return {"id": "dataset-run-api", "datasetId": "dataset-api"}

    class _Langfuse:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._base_url = kwargs["base_url"]
            self._project_id = "project-api"
            self.api = types.SimpleNamespace(
                dataset_run_items=_DatasetRunItems(),
                datasets=_Datasets(),
            )

    langfuse_mod = types.ModuleType("langfuse")
    langfuse_mod.Langfuse = _Langfuse
    monkeypatch.setitem(sys.modules, "langfuse", langfuse_mod)

    obs = _load_observability(monkeypatch)
    link = obs.link_langfuse_dataset_run_item(
        dataset_name="eval-contract-v1@v1",
        dataset_item_id="eval-contract-v1@v1:seed-set-a:910001",
        experiment_name="experiment-api",
        run_name="run-api",
        trace_id="trace-api",
        observation_id="obs-api",
        metadata={"batch_id": "batch-api"},
    )

    assert link.linked is True
    assert link.dataset_id == "dataset-api"
    assert link.dataset_run_id == "dataset-run-api"
    assert link.dataset_run_item_id == "dataset-run-item-api"
    assert link.experiment_url == (
        "http://127.0.0.1:3000/project/project-api/datasets/dataset-api/runs/dataset-run-api"
    )

    create_call = next(call for call in captured if call["name"] == "api.dataset_run_items.create")
    assert create_call["kwargs"]["run_name"] == "run-api"
    assert create_call["kwargs"]["dataset_item_id"] == "eval-contract-v1@v1:seed-set-a:910001"
    assert create_call["kwargs"]["trace_id"] == "trace-api"
    assert create_call["kwargs"]["observation_id"] == "obs-api"
    assert create_call["kwargs"]["metadata"]["langfuse_experiment_name"] == "experiment-api"
    get_run_call = next(call for call in captured if call["name"] == "api.datasets.get_run")
    assert get_run_call["dataset_name"] == "eval-contract-v1@v1"
    assert get_run_call["run_name"] == "run-api"


def test_dataset_experiment_facade_fails_open_on_sdk_errors(monkeypatch: pytest.MonkeyPatch):
    _clear_langfuse_env(monkeypatch)
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "public-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "secret-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "http://127.0.0.1:3000/")

    class _Langfuse:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._base_url = kwargs["base_url"]
            self._project_id = "project-error"

        def get_dataset(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("dataset down")

        def create_dataset_run_item(self, **kwargs: Any) -> Any:
            raise RuntimeError("run item down")

        def get_dataset_run(self, **kwargs: Any) -> Any:
            raise RuntimeError("run lookup down")

        def create_score(self, **kwargs: Any) -> None:
            raise RuntimeError("score down")

    langfuse_mod = types.ModuleType("langfuse")
    langfuse_mod.Langfuse = _Langfuse
    monkeypatch.setitem(sys.modules, "langfuse", langfuse_mod)

    obs = _load_observability(monkeypatch)

    assert obs.get_langfuse_dataset_item("dataset-error", "item-error") is None
    link = obs.link_langfuse_dataset_run_item(
        dataset_name="dataset-error",
        dataset_item_id="item-error",
        run_name="run-error",
        trace_id="trace-error",
        metadata={"batch_id": "batch-error"},
    )
    assert link.linked is False
    assert link.trace_id == "trace-error"
    assert link.dataset_run_id is None
    assert link.experiment_url is None

    obs.score_dataset_run("dataset-run-error", "eval.failed_open", 1.0)


class _NoopObservation:
    def __enter__(self):
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def __iter__(self):
        return iter(())

    def update(self, *args: Any, **kwargs: Any) -> None:
        return None

    def end(self, *args: Any, **kwargs: Any) -> None:
        return None


def test_chain_forwards_stage_model_metadata_to_observability(monkeypatch: pytest.MonkeyPatch):
    if not _observability_available():
        pytest.skip("app.services.observability has not been implemented yet")

    captured: list[dict[str, Any]] = []

    def _capture(name: str, return_value: Any = None):
        def _call(*args: Any, **kwargs: Any):
            captured.append({"name": name, "args": args, "kwargs": kwargs})
            if name == "langfuse_enabled":
                return True
            return return_value

        return _call

    fake_observability = types.ModuleType("app.services.observability")
    fake_observability.langfuse_enabled = _capture("langfuse_enabled", True)
    fake_observability.get_langfuse_client = _capture("get_langfuse_client", object())
    fake_observability.langfuse_callbacks = _capture("langfuse_callbacks", [])
    fake_observability.flush_langfuse = _capture("flush_langfuse", None)
    fake_observability.observe_llm_call = _capture("observe_llm_call", _NoopObservation())
    fake_observability.update_observation = _capture("update_observation", None)
    fake_observability.record_llm_call = _capture("record_llm_call", None)
    fake_observability.record_llm_generation = _capture("record_llm_generation", None)
    fake_observability.langfuse_context = _capture("langfuse_context", nullcontext())

    monkeypatch.setitem(sys.modules, "app.services.observability", fake_observability)
    monkeypatch.delitem(sys.modules, "app.services.chain", raising=False)

    chain = importlib.import_module("app.services.chain")

    class FakeModel:
        model_name = "metadata-test-model"

        async def ainvoke(self, *args: Any, **kwargs: Any):
            return type("Result", (), {"content": '{"schema_version":"1.0","ok":true}'})()

    async def _run() -> None:
        result = await chain.run_apply_chain(
            FakeModel(),
            messages=[{"role": "user", "content": "apply this"}],
        )
        assert result == '{"schema_version":"1.0","ok":true}'

    asyncio.run(_run())

    if not captured:
        pytest.xfail("chain has not wired app.services.observability yet; this is the metadata contract draft")

    observed_text = repr(captured)
    assert "apply" in observed_text
    assert "metadata-test-model" in observed_text
    assert "metadata" in observed_text


def _install_capturing_observability(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    def _capture(name: str, return_value: Any = None):
        def _call(*args: Any, **kwargs: Any):
            captured.append({"name": name, "args": args, "kwargs": kwargs})
            if name == "langfuse_enabled":
                return True
            return return_value

        return _call

    fake_observability = types.ModuleType("app.services.observability")
    fake_observability.langfuse_enabled = _capture("langfuse_enabled", True)
    fake_observability.get_langfuse_client = _capture("get_langfuse_client", object())
    fake_observability.langfuse_callbacks = _capture("langfuse_callbacks", [])
    fake_observability.flush_langfuse = _capture("flush_langfuse", None)
    fake_observability.observe_llm_call = _capture("observe_llm_call", _NoopObservation())
    fake_observability.update_observation = _capture("update_observation", None)
    fake_observability.langfuse_context = _capture("langfuse_context", nullcontext())

    monkeypatch.setitem(sys.modules, "app.services.observability", fake_observability)
    return captured


def _metadata_from_call(call: dict[str, Any]) -> dict[str, Any]:
    metadata = call.get("kwargs", {}).get("metadata")
    assert isinstance(metadata, dict)
    return metadata


def test_chain_merges_business_metadata_into_llm_observation(monkeypatch: pytest.MonkeyPatch):
    if not _observability_available():
        pytest.skip("app.services.observability has not been implemented yet")

    captured = _install_capturing_observability(monkeypatch)
    monkeypatch.delitem(sys.modules, "app.services.chain", raising=False)
    chain = importlib.import_module("app.services.chain")

    class FakeModel:
        model_name = "metadata-business-model"

        async def ainvoke(self, *args: Any, **kwargs: Any):
            return type("Result", (), {"content": '{"schema_version":"1.0","ok":true}'})()

    business_metadata = {
        "game_id": "g-chain-meta",
        "player_id": 7,
        "role": "seer",
        "action_type": "seer_check",
        "phase": "night",
        "day": 2,
        "source": "llm",
    }

    async def _run() -> None:
        try:
            result = await chain.run_decision_chain(
                FakeModel(),
                messages=[{"role": "user", "content": "decide"}],
                metadata=business_metadata,
            )
        except TypeError as exc:
            pytest.xfail(f"run_decision_chain does not yet accept business metadata: {exc}")
        assert result == '{"schema_version":"1.0","ok":true}'

    asyncio.run(_run())

    observe_calls = [call for call in captured if call["name"] == "observe_llm_call"]
    if not observe_calls:
        pytest.xfail("chain has not wired observe_llm_call yet")

    observe_metadata = _metadata_from_call(observe_calls[0])
    assert observe_metadata["stage"] == "decision"
    assert observe_metadata["model"] == "metadata-business-model"
    for key, value in business_metadata.items():
        assert observe_metadata[key] == value

    update_calls = [call for call in captured if call["name"] == "update_observation"]
    assert update_calls
    update_metadata = _metadata_from_call(update_calls[-1])
    for key, value in business_metadata.items():
        assert update_metadata[key] == value


def test_chain_writes_llm_usage_metadata_to_observation(monkeypatch: pytest.MonkeyPatch):
    if not _observability_available():
        pytest.skip("app.services.observability has not been implemented yet")

    captured = _install_capturing_observability(monkeypatch)
    monkeypatch.delitem(sys.modules, "app.services.chain", raising=False)
    chain = importlib.import_module("app.services.chain")

    class FakeModel:
        model_name = "usage-metadata-model"

        async def ainvoke(self, *args: Any, **kwargs: Any):
            return type(
                "Result",
                (),
                {
                    "content": '{"schema_version":"1.0","ok":true}',
                    "usage_metadata": {
                        "input_tokens": 11,
                        "output_tokens": 7,
                        "total_tokens": 18,
                    },
                },
            )()

    asyncio.run(
        chain.run_apply_chain(
            FakeModel(),
            messages=[{"role": "user", "content": "apply this"}],
            metadata={"langfuse_trace_id": "trace-usage"},
        )
    )

    observe_calls = [call for call in captured if call["name"] == "observe_llm_call"]
    assert observe_calls
    assert observe_calls[0]["kwargs"]["trace_id"] == "trace-usage"

    update_calls = [call for call in captured if call["name"] == "update_observation"]
    assert update_calls
    update_metadata = _metadata_from_call(update_calls[-1])
    assert update_metadata["usage"]["input_tokens"] == 11
    assert update_metadata["usage"]["output_tokens"] == 7
    assert update_metadata["usage"]["total_tokens"] == 18
    assert update_calls[-1]["kwargs"]["usage_details"] == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }


def test_chain_writes_response_metadata_token_usage(monkeypatch: pytest.MonkeyPatch):
    if not _observability_available():
        pytest.skip("app.services.observability has not been implemented yet")

    captured = _install_capturing_observability(monkeypatch)
    monkeypatch.delitem(sys.modules, "app.services.chain", raising=False)
    chain = importlib.import_module("app.services.chain")

    class FakeModel:
        model_name = "response-token-usage-model"

        async def ainvoke(self, *args: Any, **kwargs: Any):
            return type(
                "Result",
                (),
                {
                    "content": '{"schema_version":"1.0","ok":true}',
                    "response_metadata": {
                        "token_usage": {
                            "prompt_tokens": 13,
                            "completion_tokens": 5,
                            "total_tokens": 18,
                        },
                    },
                },
            )()

    asyncio.run(
        chain.run_apply_chain(
            FakeModel(),
            messages=[{"role": "user", "content": "apply this"}],
        )
    )

    update_calls = [call for call in captured if call["name"] == "update_observation"]
    assert update_calls
    usage = _metadata_from_call(update_calls[-1])["usage"]
    assert usage["input_tokens"] == 13
    assert usage["output_tokens"] == 5
    assert usage["total_tokens"] == 18


def test_agent_decision_call_passes_business_metadata_to_chain(monkeypatch: pytest.MonkeyPatch):
    from app.graphs.subgraphs.agent import nodes as agent_nodes

    captured: list[dict[str, Any]] = []

    async def _fake_run_decision_chain(
        model: Any,
        *,
        messages: list[dict[str, str]],
        prompt_budget: Any | None = None,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        captured.append({
            "model": model,
            "messages": messages,
            "prompt_budget": prompt_budget,
            "metadata": metadata,
            "kwargs": kwargs,
        })
        return '{"schema_version":"1.0","target":2,"public_text":"查验 2 号","confidence":0.8}'

    monkeypatch.setattr(agent_nodes, "run_decision_chain", _fake_run_decision_chain)

    state = {
        "game_id": "g-agent-meta",
        "source_run_id": "batch-agent-meta",
        "langfuse_trace_id": "trace-agent-meta",
        "player_id": 7,
        "role": "seer",
        "source": "llm",
        "request": {
            "player_id": 7,
            "action_type": "seer_check",
            "phase": "night",
            "observation": types.SimpleNamespace(day=2),
            "candidates": [2, 3],
            "retry_count": 1,
            "metadata": {"engine_request_id": "req-7"},
        },
        "memory_context": {
            "current_visible_state": {
                "day": 2,
                "phase": "night",
            }
        },
        "messages": [{"role": "user", "content": "decide"}],
        "errors": [],
        "diagnostics": [],
    }

    result = asyncio.run(agent_nodes._call_model_node(state, model=object()))

    assert result["source"] == "llm"
    assert result["raw_output"]
    assert captured
    metadata = captured[0].get("metadata")
    if metadata is None:
        pytest.xfail("_call_model_node does not yet pass business metadata to run_decision_chain")

    assert metadata["game_id"] == "g-agent-meta"
    assert metadata["player_id"] == 7
    assert metadata["role"] == "seer"
    assert metadata["action_type"] == "seer_check"
    assert metadata["phase"] == "night"
    assert metadata["day"] == 2
    assert metadata["source"] == "llm"
    assert metadata["langfuse_trace_id"] == "trace-agent-meta"
    assert metadata["candidate_count"] == 2
    assert metadata["retry_count"] == 1


def test_game_trace_scores_decision_quality_metrics(monkeypatch: pytest.MonkeyPatch):
    from app.graphs.subgraphs.game import nodes as game_nodes

    captured: list[dict[str, Any]] = []

    def _score_current_trace(
        name: str,
        value: Any,
        *,
        data_type: str | None = None,
        comment: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        captured.append({
            "name": name,
            "value": value,
            "data_type": data_type,
            "comment": comment,
            "metadata": metadata,
        })

    fake_observability = types.ModuleType("app.services.observability")
    fake_observability.score_current_trace = _score_current_trace
    monkeypatch.setitem(sys.modules, "app.services.observability", fake_observability)

    events = [
        {"event_type": "invalid_response"},
        {"event_type": "default_action"},
        {"type": "default_action"},
    ]
    state = {
        "game_id": "g-dq",
        "batch_id": "bench_dq",
        "seed": 270600,
        "storage_run_type": "evaluation_batch",
        "evaluation_set_id": "role-baseline-v1@v1",
        "seed_set_id": "role-baseline-quick-202606",
        "model_config_hash": "sha256:model-a",
        "target_role": "seer",
        "target_version_id": "seer_v2",
        "langfuse_dataset_name": "role-baseline-v1@v1",
        "langfuse_dataset_item_id": "role-baseline-v1@v1:role-baseline-quick-202606:270600",
        "langfuse_experiment_name": "seer-canary",
        "langfuse_run_name": "bench_dq:seer",
        "winner": "villagers",
        "finished": True,
        "decisions": [
            {"source": "fallback"},
            {"source": "llm_error"},
            {"source": "policy_adjusted"},
            {"source": "llm", "policy_adjustments": ["target repaired"]},
        ],
        "events": events,
        "game_events": events,
    }

    game_nodes._score_langfuse_game_trace(state)

    by_name = {call["name"]: call for call in captured}
    quality_names = {name for name in by_name if name.startswith("decision_quality.")}
    if not quality_names:
        pytest.xfail("_score_langfuse_game_trace does not yet write decision_quality scores")

    expected = {
        "decision_quality.decision_count": 4,
        "decision_quality.fallback_rate": 0.25,
        "decision_quality.llm_error_rate": 0.25,
        "decision_quality.policy_adjusted_rate": 0.5,
        "decision_quality.invalid_response_rate": 0.333333,
        "decision_quality.default_action_rate": 0.666667,
    }
    for name, value in expected.items():
        assert by_name[name]["value"] == value
        assert by_name[name]["metadata"]["metric_family"] == "decision_quality"
        assert by_name[name]["metadata"]["game_id"] == "g-dq"
        assert by_name[name]["metadata"]["batch_id"] == "bench_dq"
        assert by_name[name]["metadata"]["evaluation_set_id"] == "role-baseline-v1@v1"
        assert by_name[name]["metadata"]["seed_set_id"] == "role-baseline-quick-202606"
        assert by_name[name]["metadata"]["langfuse_dataset_name"] == "role-baseline-v1@v1"
        assert by_name[name]["metadata"]["langfuse_dataset_item_id"] == (
            "role-baseline-v1@v1:role-baseline-quick-202606:270600"
        )
        assert by_name[name]["metadata"]["langfuse_experiment_name"] == "seer-canary"
        assert by_name[name]["metadata"]["experiment_name"] == "seer-canary"
        assert by_name[name]["metadata"]["langfuse_run_name"] == "bench_dq:seer"
        assert by_name[name]["metadata"]["run_name"] == "bench_dq:seer"
    assert by_name["winner"]["metadata"]["metric_family"] == "game"
    assert by_name["winner"]["metadata"]["langfuse_dataset_item_id"] == (
        "role-baseline-v1@v1:role-baseline-quick-202606:270600"
    )


def test_game_loop_flushes_langfuse_after_trace_context(monkeypatch: pytest.MonkeyPatch):
    from app.graphs.subgraphs.game import nodes as game_nodes

    captured: list[str] = []

    class _RecordingContext:
        def __enter__(self) -> object:
            captured.append("context_enter")
            return object()

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            captured.append("context_exit")
            return False

    class _Winner:
        value = "villagers"

    class _Engine:
        async def run_until_finished(self) -> _Winner:
            captured.append("engine_run")
            return _Winner()

    def _score_current_trace(*args: Any, **kwargs: Any) -> None:
        captured.append("score")

    fake_observability = types.ModuleType("app.services.observability")
    fake_observability.create_trace_id = lambda *, seed=None: "trace-game-loop"
    fake_observability.langfuse_context = lambda **kwargs: _RecordingContext()
    fake_observability.score_current_trace = _score_current_trace
    fake_observability.flush_langfuse = lambda: captured.append("flush")
    monkeypatch.setitem(sys.modules, "app.services.observability", fake_observability)

    state = {
        "engine": _Engine(),
        "game_id": "g-langfuse-flush",
        "seed": 7,
        "decisions": [],
        "events": [],
        "game_events": [],
    }

    out = asyncio.run(game_nodes.game_loop_node(state))

    assert out["winner"] == "villagers"
    assert captured[0:2] == ["context_enter", "engine_run"]
    assert "score" in captured
    assert captured[-2:] == ["context_exit", "flush"]


def test_game_loop_links_langfuse_dataset_metadata(monkeypatch: pytest.MonkeyPatch):
    from app.graphs.subgraphs.game import nodes as game_nodes

    captured: list[dict[str, Any]] = []

    class _RecordingContext:
        def __init__(self, kwargs: dict[str, Any]) -> None:
            self.kwargs = kwargs

        def __enter__(self) -> object:
            captured.append({"name": "context_enter", "kwargs": self.kwargs})
            return object()

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            captured.append({"name": "context_exit", "kwargs": self.kwargs})
            return False

    class _Winner:
        value = "villagers"

    class _Engine:
        async def run_until_finished(self) -> _Winner:
            return _Winner()

    def _score_current_trace(
        name: str,
        value: Any,
        *,
        data_type: str | None = None,
        comment: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        captured.append({
            "name": "score",
            "score_name": name,
            "value": value,
            "data_type": data_type,
            "comment": comment,
            "metadata": metadata,
        })

    fake_observability = types.ModuleType("app.services.observability")
    fake_observability.create_trace_id = lambda *, seed=None: f"trace-{seed}"
    fake_observability.langfuse_context = lambda **kwargs: _RecordingContext(kwargs)
    fake_observability.score_current_trace = _score_current_trace
    fake_observability.flush_langfuse = lambda: captured.append({"name": "flush"})
    monkeypatch.setitem(sys.modules, "app.services.observability", fake_observability)

    state = {
        "engine": _Engine(),
        "game_id": "bench_game_001",
        "batch_id": "bench_langfuse",
        "source_run_id": "bench_langfuse",
        "seed": 270600,
        "storage_run_type": "evaluation_batch",
        "evaluation_set_id": "role-baseline-v1@v1",
        "seed_set_id": "role-baseline-quick-202606",
        "model_config_hash": "sha256:model-a",
        "target_role": "seer",
        "target_version_id": "seer_v2",
        "langfuse_dataset_name": "role-baseline-v1@v1",
        "langfuse_experiment_name": "seer-canary",
        "langfuse_run_name": "bench_langfuse:seer",
        "decisions": [],
        "events": [],
        "game_events": [],
    }

    out = asyncio.run(game_nodes.game_loop_node(state))

    assert out["winner"] == "villagers"
    assert out["langfuse_trace_id"] == "trace-bench_game_001"
    context = next(call["kwargs"] for call in captured if call["name"] == "context_enter")
    assert context["trace_name"] == "game.evaluation_batch"
    assert context["trace_id"] == "trace-bench_game_001"
    assert context["session_id"] == "bench_langfuse"
    assert context["metadata"]["game_id"] == "bench_game_001"
    assert context["metadata"]["batch_id"] == "bench_langfuse"
    assert context["metadata"]["evaluation_set_id"] == "role-baseline-v1@v1"
    assert context["metadata"]["seed_set_id"] == "role-baseline-quick-202606"
    assert context["metadata"]["langfuse_dataset_name"] == "role-baseline-v1@v1"
    assert context["metadata"]["langfuse_dataset_item_id"] == (
        "role-baseline-v1@v1:role-baseline-quick-202606:270600"
    )
    assert context["metadata"]["langfuse_experiment_name"] == "seer-canary"
    assert context["metadata"]["experiment_name"] == "seer-canary"
    assert context["metadata"]["langfuse_run_name"] == "bench_langfuse:seer"
    assert context["metadata"]["run_name"] == "bench_langfuse:seer"

    by_name = {
        call["score_name"]: call
        for call in captured
        if call["name"] == "score"
    }
    assert by_name["winner"]["metadata"]["batch_id"] == "bench_langfuse"
    assert by_name["winner"]["metadata"]["langfuse_dataset_item_id"] == (
        "role-baseline-v1@v1:role-baseline-quick-202606:270600"
    )


def test_game_loop_langfuse_failures_are_best_effort(monkeypatch: pytest.MonkeyPatch):
    from app.graphs.subgraphs.game import nodes as game_nodes

    class _FailingContext:
        def __enter__(self) -> object:
            raise RuntimeError("context down")

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            raise RuntimeError("context exit down")

    class _Winner:
        value = "villagers"

    class _Engine:
        async def run_until_finished(self) -> _Winner:
            return _Winner()

    fake_observability = types.ModuleType("app.services.observability")
    fake_observability.create_trace_id = lambda *, seed=None: (_ for _ in ()).throw(RuntimeError("trace down"))
    fake_observability.langfuse_context = lambda **kwargs: _FailingContext()
    fake_observability.score_current_trace = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("score down"))
    fake_observability.flush_langfuse = lambda: (_ for _ in ()).throw(RuntimeError("flush down"))
    monkeypatch.setitem(sys.modules, "app.services.observability", fake_observability)

    state = {
        "engine": _Engine(),
        "game_id": "g-langfuse-down",
        "seed": 7,
        "decisions": [],
        "events": [],
        "game_events": [],
    }

    out = asyncio.run(game_nodes.game_loop_node(state))

    assert out["winner"] == "villagers"
    assert out["finished"] is True
