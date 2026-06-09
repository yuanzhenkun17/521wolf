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
    prompt_calls: list[dict[str, Any]] = []

    from app.services.prompt_registry import prompt_label_for, prompt_management_enabled

    def get_prompt(
        name: str,
        *,
        label: str = "production",
        fallback: Any = None,
        enable_compile: bool = False,
    ):
        assert name == "decision_judge"
        assert fallback is not None
        prompt_calls.append(
            {
                "name": name,
                "label": label,
                "enable_compile": enable_compile,
                "fallback": fallback,
            }
        )
        return {
            "metadata": {
                "prompt_name": "decision_judge",
                "prompt_version": 17,
                "prompt_label": label,
                "prompt_source": "langfuse",
                "prompt_fallback_used": False,
                "prompt_compile_enabled": enable_compile,
            }
        }

    fake_registry.get_prompt = get_prompt
    fake_registry.prompt_label_for = prompt_label_for
    fake_registry.prompt_management_enabled = prompt_management_enabled
    monkeypatch.setitem(sys.modules, "app.services.prompt_registry", fake_registry)
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL", "canary")
    monkeypatch.delenv("LANGFUSE_PROMPT_MANAGEMENT_ENABLED", raising=False)
    monkeypatch.delitem(sys.modules, "app.services.chain", raising=False)
    chain = importlib.import_module("app.services.chain")
    model = _FakeModel()
    messages = [{"role": "user", "content": "judge this decision"}]

    result = asyncio.run(
        chain.run_decision_judge_chain(
            model,
            messages=messages,
        )
    )

    assert result == '{"schema_version":"1.0","ok":true}'
    assert prompt_calls
    assert prompt_calls[-1]["label"] == "canary"
    assert prompt_calls[-1]["enable_compile"] is False
    assert model.calls[-1][0] == messages[0]
    metadata = _metadata_from_last_observe(captured)
    assert metadata["stage"] == "decision_judge"
    assert metadata["prompt_name"] == "decision_judge"
    assert metadata["prompt_version"] == 17
    assert metadata["prompt_label"] == "canary"
    assert metadata["prompt_compile_enabled"] is False


def test_prompt_management_enabled_compiles_remote_prompt_for_low_risk_stage(monkeypatch):
    captured = _install_observability(monkeypatch)
    fake_registry = types.ModuleType("app.services.prompt_registry")
    prompt_calls: list[dict[str, Any]] = []

    from app.services.prompt_registry import prompt_label_for, prompt_management_enabled

    class RemotePrompt:
        metadata = {
            "prompt_name": "evidence",
            "prompt_version": 23,
            "prompt_label": "canary",
            "prompt_source": "langfuse",
            "prompt_fallback_used": False,
            "prompt_compile_enabled": True,
        }

        def compile(self, **kwargs: Any) -> str:
            assert kwargs == {}
            return "remote evidence prompt"

    def get_prompt(
        name: str,
        *,
        label: str = "production",
        fallback: Any = None,
        enable_compile: bool = False,
    ) -> RemotePrompt:
        prompt_calls.append(
            {
                "name": name,
                "label": label,
                "enable_compile": enable_compile,
                "fallback": fallback,
            }
        )
        return RemotePrompt()

    fake_registry.get_prompt = get_prompt
    fake_registry.prompt_label_for = prompt_label_for
    fake_registry.prompt_management_enabled = prompt_management_enabled
    monkeypatch.setitem(sys.modules, "app.services.prompt_registry", fake_registry)
    monkeypatch.setenv("LANGFUSE_PROMPT_MANAGEMENT_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PROMPT_LABEL_EVIDENCE", "canary")
    monkeypatch.delitem(sys.modules, "app.services.chain", raising=False)
    chain = importlib.import_module("app.services.chain")
    model = _FakeModel()
    messages = [{"role": "user", "content": "judge this evidence"}]

    result = asyncio.run(chain.run_evidence_chain(model, messages=messages))

    assert result == '{"schema_version":"1.0","ok":true}'
    assert prompt_calls[-1]["name"] == "evidence"
    assert prompt_calls[-1]["label"] == "canary"
    assert prompt_calls[-1]["enable_compile"] is True
    assert getattr(model.calls[-1][0], "content", "") == "remote evidence prompt"
    assert any("schema_version" in getattr(message, "content", "") for message in model.calls[-1])
    metadata = _metadata_from_last_observe(captured)
    assert metadata["prompt_name"] == "evidence"
    assert metadata["prompt_version"] == 23
    assert metadata["prompt_label"] == "canary"
    assert metadata["prompt_compile_enabled"] is True


def test_prompt_management_empty_compile_result_falls_back_to_local_messages(monkeypatch):
    captured = _install_observability(monkeypatch)
    fake_registry = types.ModuleType("app.services.prompt_registry")

    from app.services.prompt_registry import prompt_label_for, prompt_management_enabled

    class EmptyRemotePrompt:
        metadata = {
            "prompt_name": "evidence",
            "prompt_version": 24,
            "prompt_label": "production",
            "prompt_source": "langfuse",
            "prompt_fallback_used": False,
            "prompt_compile_enabled": True,
        }

        def compile(self, **kwargs: Any) -> str:
            assert kwargs == {}
            return "   "

    def get_prompt(
        name: str,
        *,
        label: str = "production",
        fallback: Any = None,
        enable_compile: bool = False,
    ) -> EmptyRemotePrompt:
        assert name == "evidence"
        assert label == "production"
        assert enable_compile is True
        assert fallback is not None
        return EmptyRemotePrompt()

    fake_registry.get_prompt = get_prompt
    fake_registry.prompt_label_for = prompt_label_for
    fake_registry.prompt_management_enabled = prompt_management_enabled
    monkeypatch.setitem(sys.modules, "app.services.prompt_registry", fake_registry)
    monkeypatch.setenv("LANGFUSE_PROMPT_MANAGEMENT_ENABLED", "true")
    monkeypatch.delenv("LANGFUSE_PROMPT_LABEL_EVIDENCE", raising=False)
    monkeypatch.delitem(sys.modules, "app.services.chain", raising=False)
    chain = importlib.import_module("app.services.chain")
    model = _FakeModel()
    messages = [{"role": "user", "content": "judge this evidence"}]

    result = asyncio.run(chain.run_evidence_chain(model, messages=messages))

    assert result == '{"schema_version":"1.0","ok":true}'
    assert model.calls[-1][0] == messages[0]
    metadata = _metadata_from_last_observe(captured)
    assert metadata["stage"] == "evidence"
    assert "prompt_name" not in metadata
    assert "prompt_compile_enabled" not in metadata


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
