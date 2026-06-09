import asyncio
import importlib
import sys
import types
from typing import Any


class _NoopObservation:
    def __enter__(self) -> "_NoopObservation":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


def _install_observability(monkeypatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    def _capture(name: str, return_value: Any = None):
        def _call(*args: Any, **kwargs: Any):
            captured.append({"name": name, "args": args, "kwargs": kwargs})
            return return_value

        return _call

    fake_observability = types.ModuleType("app.services.observability")
    fake_observability.observe_llm_call = _capture("observe_llm_call", _NoopObservation())
    fake_observability.update_observation = _capture("update_observation")
    monkeypatch.setitem(sys.modules, "app.services.observability", fake_observability)
    return captured


class _FakeModel:
    model_name = "prompt-registry-test-model"

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def ainvoke(self, messages: Any) -> Any:
        self.calls.append(messages)
        return type("Result", (), {"content": '{"schema_version":"1.0","ok":true}'})()


def _metadata_from_last_observe(captured: list[dict[str, Any]]) -> dict[str, Any]:
    observe_calls = [call for call in captured if call["name"] == "observe_llm_call"]
    assert observe_calls
    metadata = observe_calls[-1]["kwargs"]["metadata"]
    assert isinstance(metadata, dict)
    return metadata


def _reload_chain_without_registry(monkeypatch):
    monkeypatch.setitem(sys.modules, "app.services.prompt_registry", None)
    monkeypatch.delitem(sys.modules, "app.services.chain", raising=False)
    return importlib.import_module("app.services.chain")


def test_low_risk_registry_disabled_preserves_messages_and_metadata(monkeypatch):
    captured = _install_observability(monkeypatch)
    chain = _reload_chain_without_registry(monkeypatch)
    model = _FakeModel()
    messages = [{"role": "user", "content": "judge this evidence"}]

    result = asyncio.run(
        chain.run_evidence_chain(
            model,
            messages=messages,
            metadata={"run_id": "run-disabled"},
        )
    )

    assert result == '{"schema_version":"1.0","ok":true}'
    assert model.calls
    assert model.calls[-1][0] == messages[0]
    assert any("schema_version" in getattr(message, "content", "") for message in model.calls[-1])

    metadata = _metadata_from_last_observe(captured)
    assert metadata["stage"] == "evidence"
    assert metadata["run_id"] == "run-disabled"
    assert "prompt_name" not in metadata
    assert "prompt_version" not in metadata
    assert "prompt_label" not in metadata


def test_low_risk_registry_metadata_is_merged_into_llm_observation(monkeypatch):
    captured = _install_observability(monkeypatch)
    fake_registry = types.ModuleType("app.services.prompt_registry")

    def get_prompt(name: str, *, label: str = "production", fallback: Any = None):
        assert name == "decision_judge"
        assert label == "production"
        assert fallback is not None
        return {
            "metadata": {
                "prompt_name": "decision_judge",
                "prompt_version": 17,
                "prompt_label": label,
            }
        }

    fake_registry.get_prompt = get_prompt
    monkeypatch.setitem(sys.modules, "app.services.prompt_registry", fake_registry)
    monkeypatch.delitem(sys.modules, "app.services.chain", raising=False)
    chain = importlib.import_module("app.services.chain")

    result = asyncio.run(
        chain.run_decision_judge_chain(
            _FakeModel(),
            messages=[{"role": "user", "content": "judge this decision"}],
        )
    )

    assert result == '{"schema_version":"1.0","ok":true}'
    metadata = _metadata_from_last_observe(captured)
    assert metadata["stage"] == "decision_judge"
    assert metadata["prompt_name"] == "decision_judge"
    assert metadata["prompt_version"] == 17
    assert metadata["prompt_label"] == "production"


def test_prompt_registry_errors_fail_open(monkeypatch):
    captured = _install_observability(monkeypatch)
    fake_registry = types.ModuleType("app.services.prompt_registry")

    def get_prompt(*args: Any, **kwargs: Any):
        raise RuntimeError("registry unavailable")

    fake_registry.get_prompt = get_prompt
    monkeypatch.setitem(sys.modules, "app.services.prompt_registry", fake_registry)
    monkeypatch.delitem(sys.modules, "app.services.chain", raising=False)
    chain = importlib.import_module("app.services.chain")

    result = asyncio.run(
        chain.run_evidence_chain(
            _FakeModel(),
            messages=[{"role": "user", "content": "judge this evidence"}],
        )
    )

    assert result == '{"schema_version":"1.0","ok":true}'
    metadata = _metadata_from_last_observe(captured)
    assert metadata["stage"] == "evidence"
    assert "prompt_name" not in metadata


def test_prompt_registry_is_not_called_for_core_decision_stage(monkeypatch):
    _install_observability(monkeypatch)
    fake_registry = types.ModuleType("app.services.prompt_registry")
    calls: list[Any] = []

    def get_prompt(*args: Any, **kwargs: Any):
        calls.append((args, kwargs))
        return {"metadata": {"prompt_name": "decision"}}

    fake_registry.get_prompt = get_prompt
    monkeypatch.setitem(sys.modules, "app.services.prompt_registry", fake_registry)
    monkeypatch.delitem(sys.modules, "app.services.chain", raising=False)
    chain = importlib.import_module("app.services.chain")

    asyncio.run(
        chain.run_decision_chain(
            _FakeModel(),
            messages=[{"role": "user", "content": "make a decision"}],
        )
    )

    assert calls == []
