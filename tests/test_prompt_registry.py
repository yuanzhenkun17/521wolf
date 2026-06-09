from __future__ import annotations

import sys
import types
from typing import Any


def test_langfuse_disabled_returns_local_fallback_without_sdk(monkeypatch):
    from app.services.prompt_registry import LOCAL_FALLBACK_SOURCE, get_prompt

    calls: list[str] = []

    class _Langfuse:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            calls.append("constructed")
            raise AssertionError("Langfuse SDK must not be constructed")

    langfuse_mod = types.ModuleType("langfuse")
    langfuse_mod.Langfuse = _Langfuse
    monkeypatch.setitem(sys.modules, "langfuse", langfuse_mod)
    monkeypatch.setenv("LANGFUSE_TRACING_ENABLED", "false")

    prompt = get_prompt("decision_judge", fallback="local prompt")

    assert prompt.prompt == "local prompt"
    assert prompt.compile() == "local prompt"
    assert prompt.metadata == {
        "prompt_name": "decision_judge",
        "prompt_label": "production",
        "prompt_version": None,
        "prompt_source": LOCAL_FALLBACK_SOURCE,
        "prompt_fallback_used": True,
    }
    assert prompt.to_observation_metadata() == prompt.metadata
    assert calls == []


def test_fake_client_prompt_success_exposes_metadata_and_compile():
    from app.services.prompt_registry import LANGFUSE_SOURCE, get_prompt

    captured: list[dict[str, Any]] = []

    class FakePrompt:
        name = "remote-decision-judge"
        version = 17
        labels = ["production"]
        prompt = "remote template"

        def compile(self, **kwargs: Any) -> str:
            captured.append({"name": "compile", "kwargs": kwargs})
            return f"remote prompt for {kwargs['role']}"

    class FakeClient:
        def get_prompt(self, name: str, *, label: str) -> FakePrompt:
            captured.append({"name": "get_prompt", "prompt_name": name, "label": label})
            return FakePrompt()

    prompt = get_prompt(
        "decision_judge",
        label="canary",
        fallback="local prompt for {role}",
        client=FakeClient(),
    )

    assert prompt.prompt == "remote template"
    assert prompt.compile(role="seer") == "remote prompt for seer"
    assert prompt.metadata == {
        "prompt_name": "decision_judge",
        "prompt_label": "canary",
        "prompt_version": 17,
        "prompt_source": LANGFUSE_SOURCE,
        "prompt_fallback_used": False,
    }
    assert captured == [
        {"name": "get_prompt", "prompt_name": "decision_judge", "label": "canary"},
        {"name": "compile", "kwargs": {"role": "seer"}},
    ]


def test_prompt_not_found_returns_local_fallback():
    from app.services.prompt_registry import LOCAL_FALLBACK_SOURCE, get_prompt

    class FakeClient:
        def get_prompt(self, name: str, *, label: str) -> None:
            return None

    prompt = get_prompt(
        "missing_prompt",
        label="production",
        fallback="fallback for {stage}",
        client=FakeClient(),
    )

    assert prompt.compile(stage="evidence") == "fallback for evidence"
    assert prompt.metadata["prompt_source"] == LOCAL_FALLBACK_SOURCE
    assert prompt.metadata["prompt_fallback_used"] is True
    assert prompt.metadata["prompt_version"] is None


def test_client_or_sdk_errors_return_local_fallback(monkeypatch):
    from app.services import prompt_registry
    from app.services.prompt_registry import LOCAL_FALLBACK_SOURCE, get_prompt

    class FailingClient:
        def get_prompt(self, name: str, *, label: str) -> Any:
            raise RuntimeError("prompt service down")

    prompt = get_prompt("apply", fallback="local apply", client=FailingClient())

    assert prompt.prompt == "local apply"
    assert prompt.metadata["prompt_source"] == LOCAL_FALLBACK_SOURCE
    assert prompt.metadata["prompt_fallback_used"] is True

    fake_observability = types.SimpleNamespace(
        langfuse_enabled=lambda: True,
        get_langfuse_client=lambda: (_ for _ in ()).throw(RuntimeError("sdk unavailable")),
    )
    monkeypatch.setattr(
        prompt_registry.importlib,
        "import_module",
        lambda module_name: fake_observability
        if module_name == "app.services.observability"
        else __import__(module_name),
    )

    sdk_error_prompt = get_prompt("evidence", fallback="local evidence")

    assert sdk_error_prompt.prompt == "local evidence"
    assert sdk_error_prompt.metadata["prompt_source"] == LOCAL_FALLBACK_SOURCE
    assert sdk_error_prompt.metadata["prompt_fallback_used"] is True


def test_compile_error_switches_to_local_fallback_metadata():
    from app.services.prompt_registry import LOCAL_FALLBACK_SOURCE, get_prompt

    class FailingPrompt:
        version = "v9"
        prompt = "remote template"

        def compile(self, **kwargs: Any) -> str:
            raise ValueError("bad prompt variables")

    class FakeClient:
        def get_prompt(self, name: str, *, label: str) -> FailingPrompt:
            return FailingPrompt()

    prompt = get_prompt(
        "consolidate",
        label="production",
        fallback="local prompt for {role}",
        client=FakeClient(),
    )

    assert prompt.metadata["prompt_source"] == "langfuse"
    assert prompt.metadata["prompt_fallback_used"] is False

    assert prompt.compile(role="villager") == "local prompt for villager"
    assert prompt.prompt == "local prompt for {role}"
    assert prompt.metadata == {
        "prompt_name": "consolidate",
        "prompt_label": "production",
        "prompt_version": None,
        "prompt_source": LOCAL_FALLBACK_SOURCE,
        "prompt_fallback_used": True,
    }


def test_dict_prompt_and_fallback_compile_are_supported():
    from app.services.prompt_registry import get_prompt

    class FallbackPrompt:
        def compile(self, **kwargs: Any) -> str:
            return f"fallback {kwargs['stage']}"

    class FakeClient:
        def get_prompt(self, name: str, *, label: str) -> dict[str, Any]:
            return {
                "name": name,
                "version": 3,
                "prompt": [{"role": "system", "content": "remote"}],
            }

    prompt = get_prompt("evidence", fallback=FallbackPrompt(), client=FakeClient())

    assert prompt.prompt == [{"role": "system", "content": "remote"}]
    assert prompt.compile() == [{"role": "system", "content": "remote"}]
    assert prompt.metadata["prompt_version"] == 3
