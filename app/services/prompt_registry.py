"""Fail-open facade for Langfuse Prompt Management.

This module keeps prompt lookup optional: callers always get a prompt handle
back, and the handle carries metadata that can be merged into Langfuse
observation metadata without exposing prompt content.
"""

from __future__ import annotations

import importlib
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping


LOCAL_FALLBACK_SOURCE = "local_fallback"
LANGFUSE_SOURCE = "langfuse"
DEFAULT_PROMPT_LABEL = "production"


def prompt_management_enabled(env: Mapping[str, str] = os.environ) -> bool:
    """Return whether remote prompt compilation is explicitly enabled."""
    value = env.get("LANGFUSE_PROMPT_MANAGEMENT_ENABLED")
    return _truthy(value)


def prompt_label_for(name: str, env: Mapping[str, str] = os.environ) -> str:
    """Return the Langfuse prompt label for a prompt name.

    ``LANGFUSE_PROMPT_LABEL_<UPPER_NAME>`` overrides the global
    ``LANGFUSE_PROMPT_LABEL`` value. Empty values are ignored.
    """
    global_label = _clean_label(env.get("LANGFUSE_PROMPT_LABEL"))
    specific_key = f"LANGFUSE_PROMPT_LABEL_{_env_suffix(name)}"
    specific_label = _clean_label(env.get(specific_key))
    return specific_label or global_label or DEFAULT_PROMPT_LABEL


@dataclass
class PromptReference:
    """Resolved prompt plus Langfuse-friendly metadata.

    ``compile`` delegates to a Langfuse prompt when available. If that fails,
    the reference switches to the local fallback and returns the fallback
    render instead.
    """

    prompt: Any
    metadata: dict[str, Any]
    _fallback: Any
    _langfuse_prompt: Any | None = None
    _requested_name: str = ""
    _requested_label: str = DEFAULT_PROMPT_LABEL

    @property
    def prompt_name(self) -> Any:
        return self.metadata.get("prompt_name")

    @property
    def prompt_label(self) -> Any:
        return self.metadata.get("prompt_label")

    @property
    def prompt_version(self) -> Any:
        return self.metadata.get("prompt_version")

    @property
    def prompt_source(self) -> Any:
        return self.metadata.get("prompt_source")

    @property
    def prompt_fallback_used(self) -> bool:
        return bool(self.metadata.get("prompt_fallback_used"))

    @property
    def prompt_compile_enabled(self) -> bool:
        return bool(self.metadata.get("prompt_compile_enabled"))

    @property
    def prompt_error_type(self) -> Any:
        return self.metadata.get("prompt_error_type")

    def compile(self, *args: Any, **kwargs: Any) -> Any:
        """Compile a remote prompt, falling back locally on any failure."""
        if not self.prompt_compile_enabled:
            return _render_fallback(self._fallback, *args, **kwargs)
        if self._langfuse_prompt is not None and not self.prompt_fallback_used:
            compile_prompt = getattr(self._langfuse_prompt, "compile", None)
            if callable(compile_prompt):
                try:
                    return compile_prompt(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001 - prompt lookup must fail open
                    self._use_fallback(error_type=type(exc).__name__)
                    return _render_fallback(self._fallback, *args, **kwargs)
            return self.prompt
        return _render_fallback(self._fallback, *args, **kwargs)

    def to_observation_metadata(self) -> dict[str, Any]:
        """Return a copy suitable for chain/generation observation metadata."""
        return dict(self.metadata)

    def _use_fallback(self, *, error_type: str | None = None) -> None:
        self.prompt = self._fallback
        self._langfuse_prompt = None
        self.metadata = _prompt_metadata(
            self._requested_name,
            self._requested_label,
            version=None,
            source=LOCAL_FALLBACK_SOURCE,
            fallback_used=True,
            compile_enabled=self.prompt_compile_enabled,
            error_type=error_type,
        )


def get_prompt(
    name: str,
    label: str = DEFAULT_PROMPT_LABEL,
    fallback: Any = "",
    *,
    client: Any | None = None,
    enable_compile: Any | None = None,
    compile_enabled: Any | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> PromptReference:
    """Return a Langfuse-managed prompt handle, or a local fallback handle.

    Passing ``client`` is intended for tests and offline callers. Without an
    explicit client, the optional Langfuse observability client is used only
    when tracing is enabled and configured.
    """
    prompt_name = str(name)
    prompt_label = str(label)
    prompt_compile_enabled = _resolve_compile_enabled(
        enable_compile=enable_compile,
        compile_enabled=compile_enabled,
        metadata=metadata,
    )

    resolved_client = client
    if resolved_client is None:
        resolved_client = _configured_langfuse_client()
    if resolved_client is None:
        return _fallback_reference(prompt_name, prompt_label, fallback, compile_enabled=prompt_compile_enabled)

    get_remote_prompt = getattr(resolved_client, "get_prompt", None)
    if not callable(get_remote_prompt):
        return _fallback_reference(prompt_name, prompt_label, fallback, compile_enabled=prompt_compile_enabled)

    try:
        remote_prompt = _call_get_prompt(get_remote_prompt, prompt_name, prompt_label)
    except Exception as exc:  # noqa: BLE001 - prompt lookup must fail open
        return _fallback_reference(
            prompt_name,
            prompt_label,
            fallback,
            compile_enabled=prompt_compile_enabled,
            error_type=type(exc).__name__,
        )

    if remote_prompt is None:
        return _fallback_reference(prompt_name, prompt_label, fallback, compile_enabled=prompt_compile_enabled)

    version = _value_attr(remote_prompt, "version", "prompt_version", "promptVersion")
    return PromptReference(
        prompt=_prompt_content(remote_prompt),
        metadata=_prompt_metadata(
            prompt_name,
            prompt_label,
            version=version,
            source=LANGFUSE_SOURCE,
            fallback_used=False,
            compile_enabled=prompt_compile_enabled,
        ),
        _fallback=fallback,
        _langfuse_prompt=remote_prompt,
        _requested_name=prompt_name,
        _requested_label=prompt_label,
    )


def _configured_langfuse_client() -> Any | None:
    try:
        observability = importlib.import_module("app.services.observability")
    except Exception:  # noqa: BLE001 - missing/failed SDK path must fail open
        return None

    enabled = getattr(observability, "langfuse_enabled", None)
    if not callable(enabled):
        return None
    try:
        if not enabled():
            return None
    except Exception:  # noqa: BLE001
        return None

    get_client = getattr(observability, "get_langfuse_client", None)
    if not callable(get_client):
        return None
    try:
        return get_client()
    except Exception:  # noqa: BLE001
        return None


def _fallback_reference(
    name: str,
    label: str,
    fallback: Any,
    *,
    compile_enabled: bool,
    error_type: str | None = None,
) -> PromptReference:
    return PromptReference(
        prompt=fallback,
        metadata=_prompt_metadata(
            name,
            label,
            version=None,
            source=LOCAL_FALLBACK_SOURCE,
            fallback_used=True,
            compile_enabled=compile_enabled,
            error_type=error_type,
        ),
        _fallback=fallback,
        _requested_name=name,
        _requested_label=label,
    )


def _prompt_metadata(
    name: str,
    label: str,
    *,
    version: Any,
    source: str,
    fallback_used: bool,
    compile_enabled: bool,
    error_type: str | None = None,
) -> dict[str, Any]:
    metadata = {
        "prompt_name": name,
        "prompt_label": label,
        "prompt_version": version,
        "prompt_source": source,
        "prompt_fallback_used": fallback_used,
        "prompt_compile_enabled": compile_enabled,
    }
    if error_type:
        metadata["prompt_error_type"] = error_type
    return metadata


def _resolve_compile_enabled(
    *,
    enable_compile: Any | None,
    compile_enabled: Any | None,
    metadata: Mapping[str, Any] | None,
) -> bool:
    for value in (
        enable_compile,
        compile_enabled,
        _metadata_value(metadata, "prompt_compile_enabled"),
        _metadata_value(metadata, "compile_enabled"),
        _metadata_value(metadata, "enable_compile"),
    ):
        if value is not None:
            return _truthy(value)
    return prompt_management_enabled()


def _metadata_value(metadata: Mapping[str, Any] | None, key: str) -> Any | None:
    if not metadata:
        return None
    return metadata.get(key)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y", "t"}


def _clean_label(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _env_suffix(name: str) -> str:
    text = re.sub(r"[^0-9A-Za-z]+", "_", str(name).strip().upper())
    return text.strip("_")


def _call_get_prompt(get_prompt: Any, name: str, label: str) -> Any:
    try:
        return get_prompt(name, label=label)
    except TypeError as first_error:
        try:
            return get_prompt(name=name, label=label)
        except TypeError:
            try:
                return get_prompt(name)
            except TypeError:
                raise first_error


def _prompt_content(prompt: Any) -> Any:
    value = _value_attr(prompt, "prompt", "content", "template")
    return prompt if value is None else value


def _value_attr(value: Any, *names: str) -> Any:
    if value is None:
        return None
    for name in names:
        if isinstance(value, dict):
            attr = value.get(name)
        else:
            attr = getattr(value, name, None)
        if attr is not None:
            return attr
    return None


def _render_fallback(fallback: Any, *args: Any, **kwargs: Any) -> Any:
    compile_prompt = getattr(fallback, "compile", None)
    if callable(compile_prompt):
        try:
            return compile_prompt(*args, **kwargs)
        except Exception:  # noqa: BLE001
            return fallback

    format_prompt = getattr(fallback, "format", None)
    if callable(format_prompt) and (args or kwargs):
        try:
            return format_prompt(*args, **kwargs)
        except Exception:  # noqa: BLE001
            return fallback

    if callable(fallback):
        try:
            return fallback(*args, **kwargs)
        except Exception:  # noqa: BLE001
            return fallback

    return fallback
