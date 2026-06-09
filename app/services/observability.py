"""Optional Langfuse observability helpers.

The integration is deliberately fail-closed: if tracing is disabled, keys are
missing, or the self-hosted base URL is not set, every public helper becomes a
no-op. This keeps tests and local fake-model runs independent from Langfuse.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Iterator

from dotenv import load_dotenv

from app.config import LLM_ENV_PATH
from app.util.redaction import redact

_log = logging.getLogger(__name__)

_CLIENT: Any | None = None
_CLIENT_CONFIG: tuple[str, str, str, str | None, str | None, float | None] | None = None
_DOTENV_LOADED = False


def langfuse_enabled() -> bool:
    """Return True only when tracing is explicitly enabled and configured."""
    _load_env_once()
    if not _env_bool("LANGFUSE_TRACING_ENABLED", default=False):
        return False
    return bool(
        os.environ.get("LANGFUSE_PUBLIC_KEY")
        and os.environ.get("LANGFUSE_SECRET_KEY")
        and os.environ.get("LANGFUSE_BASE_URL")
    )


def get_langfuse_client() -> Any | None:
    """Return a cached Langfuse client, or None when tracing is unavailable."""
    global _CLIENT, _CLIENT_CONFIG

    if not langfuse_enabled():
        return None

    public_key = str(os.environ.get("LANGFUSE_PUBLIC_KEY") or "")
    secret_key = str(os.environ.get("LANGFUSE_SECRET_KEY") or "")
    base_url = str(os.environ.get("LANGFUSE_BASE_URL") or "").rstrip("/")
    environment = _optional_env("LANGFUSE_ENVIRONMENT")
    release = _optional_env("LANGFUSE_RELEASE")
    sample_rate = _env_float_or_none("LANGFUSE_SAMPLE_RATE")
    config = (public_key, secret_key, base_url, environment, release, sample_rate)
    if _CLIENT is not None and _CLIENT_CONFIG == config:
        return _CLIENT

    try:
        from langfuse import Langfuse

        _CLIENT = Langfuse(
            public_key=public_key,
            secret_key=secret_key,
            base_url=base_url,
            tracing_enabled=True,
            environment=environment,
            release=release,
            sample_rate=sample_rate,
            mask=_langfuse_mask,
        )
        _CLIENT_CONFIG = config
    except Exception as exc:  # noqa: BLE001 - observability must not break runtime
        _log.warning("Langfuse client initialization failed: %s", exc, exc_info=True)
        _CLIENT = None
        _CLIENT_CONFIG = None
    return _CLIENT


def langfuse_callbacks(
    *,
    trace_id: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> list[Any]:
    """Build LangChain callback handlers for the current trace context."""
    del session_id, metadata, tags
    if not langfuse_enabled():
        return []
    try:
        from langfuse.langchain import CallbackHandler

        trace_context = {"trace_id": trace_id} if trace_id else None
        return [CallbackHandler(trace_context=trace_context)]
    except Exception as exc:  # noqa: BLE001
        _log.warning("Langfuse callback initialization failed: %s", exc, exc_info=True)
        return []


@contextmanager
def langfuse_context(
    *,
    trace_name: str,
    trace_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    input: Any | None = None,
) -> Iterator[Any | None]:
    """Create a top-level Langfuse chain observation around a run."""
    if not langfuse_enabled():
        with nullcontext(None) as value:
            yield value
        return

    client = get_langfuse_client()
    if client is None:
        with nullcontext(None) as value:
            yield value
        return

    try:
        from langfuse import propagate_attributes
    except Exception as exc:  # noqa: BLE001
        _log.warning("Langfuse context setup failed open: %s", exc, exc_info=True)
        with nullcontext(None) as value:
            yield value
        return

    try:
        attribute_context = propagate_attributes(
            user_id=user_id,
            session_id=session_id,
            metadata=_string_metadata(metadata),
            tags=tags,
            trace_name=trace_name,
        )
        observation_context = client.start_as_current_observation(
            trace_context={"trace_id": trace_id} if trace_id else None,
            name=trace_name,
            as_type="chain",
            input=input if capture_input_output() else None,
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("Langfuse context failed open: %s", exc, exc_info=True)
        with nullcontext(None) as value:
            yield value
        return

    with _fail_open_context(
        attribute_context,
        observation_context,
        label="Langfuse context",
    ) as observation:
        yield observation


@contextmanager
def langfuse_run_context(
    *,
    trace_name: str,
    trace_id: str | None = None,
    trace_id_seed: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    input: Any | None = None,
) -> Iterator[Any | None]:
    """Open a best-effort trace context for a batch/run-level scoring step."""
    resolved_trace_id = trace_id or create_trace_id(seed=trace_id_seed)
    with langfuse_context(
        trace_name=trace_name,
        trace_id=resolved_trace_id,
        session_id=session_id,
        user_id=user_id,
        metadata=metadata,
        tags=tags,
        input=input,
    ) as observation:
        yield observation


def observe_llm_call(
    *,
    stage: str,
    model: str | None,
    messages: Any,
    metadata: dict[str, Any] | None = None,
    trace_id: str | None = None,
) -> Any:
    """Return a context manager for one LLM generation observation."""
    client = get_langfuse_client()
    if client is None:
        return nullcontext(None)

    try:
        context = client.start_as_current_observation(
            trace_context={"trace_id": trace_id} if trace_id else None,
            name=f"llm.{stage}",
            as_type="generation",
            input=messages if capture_input_output() else None,
            metadata=metadata,
            model=model,
        )
        return _fail_open_context(context, label="Langfuse LLM observation")
    except Exception as exc:  # noqa: BLE001
        _log.warning("Langfuse LLM observation failed open: %s", exc, exc_info=True)
        return nullcontext(None)


def update_observation(
    observation: Any,
    *,
    output: Any | None = None,
    metadata: dict[str, Any] | None = None,
    usage_details: dict[str, int] | None = None,
    cost_details: dict[str, float] | None = None,
    level: str | None = None,
    status_message: str | None = None,
) -> None:
    """Best-effort update for an active Langfuse observation."""
    if observation is None:
        return
    update = getattr(observation, "update", None)
    if not callable(update):
        return
    kwargs: dict[str, Any] = {}
    if capture_input_output() and output is not None:
        kwargs["output"] = output
    if metadata is not None:
        kwargs["metadata"] = metadata
    if usage_details is not None:
        kwargs["usage_details"] = usage_details
    if cost_details is not None:
        kwargs["cost_details"] = cost_details
    if level is not None:
        kwargs["level"] = level
    if status_message is not None:
        kwargs["status_message"] = status_message
    if not kwargs:
        return
    try:
        update(**kwargs)
    except Exception:  # noqa: BLE001
        _log.debug("Langfuse observation update failed", exc_info=True)


def create_trace_id(seed: str | None = None) -> str | None:
    """Create a deterministic Langfuse trace id when tracing is active."""
    client = get_langfuse_client()
    if client is None:
        return None
    try:
        return str(client.create_trace_id(seed=seed))
    except Exception:  # noqa: BLE001
        _log.debug("Langfuse trace id creation failed", exc_info=True)
        return None


def get_current_trace_id() -> str | None:
    """Return the current Langfuse trace id, when one is active."""
    client = get_langfuse_client()
    if client is None:
        return None
    get_trace_id = getattr(client, "get_current_trace_id", None)
    if not callable(get_trace_id):
        return None
    try:
        trace_id = get_trace_id()
        return str(trace_id) if trace_id else None
    except Exception:  # noqa: BLE001
        _log.debug("Langfuse current trace id lookup failed", exc_info=True)
        return None


def get_trace_url(trace_id: str | None = None) -> str | None:
    """Return a best-effort Langfuse UI URL for a trace."""
    client = get_langfuse_client()
    if client is None:
        return None
    get_url = getattr(client, "get_trace_url", None)
    if not callable(get_url):
        return None
    try:
        url = get_url(trace_id=trace_id)
        return str(url) if url else None
    except Exception:  # noqa: BLE001
        _log.debug("Langfuse trace URL lookup failed", exc_info=True)
        return None


def score_current_trace(
    name: str,
    value: float | str | bool,
    *,
    data_type: str | None = None,
    comment: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Best-effort score on the current Langfuse trace."""
    client = get_langfuse_client()
    if client is None:
        return
    try:
        client.score_current_trace(
            name=name,
            value=value,
            data_type=data_type,
            comment=comment,
            metadata=metadata,
        )
    except Exception:  # noqa: BLE001
        _log.debug("Langfuse trace scoring failed for %s", name, exc_info=True)


def score_trace(
    trace_id: str | None,
    name: str,
    value: float | str | bool,
    *,
    data_type: str | None = None,
    comment: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Best-effort score on an explicit Langfuse trace."""
    if not trace_id:
        score_current_trace(
            name,
            value,
            data_type=data_type,
            comment=comment,
            metadata=metadata,
        )
        return
    client = get_langfuse_client()
    if client is None:
        return
    create_score = getattr(client, "create_score", None)
    if not callable(create_score):
        return
    try:
        create_score(
            trace_id=str(trace_id),
            name=name,
            value=value,
            data_type=data_type,
            comment=comment,
            metadata=metadata,
        )
    except Exception:  # noqa: BLE001
        _log.debug("Langfuse trace scoring failed for %s on %s", name, trace_id, exc_info=True)


def flush_langfuse() -> None:
    """Flush pending Langfuse events, if a client exists."""
    client = _CLIENT
    if client is None:
        return
    flush = getattr(client, "flush", None)
    if not callable(flush):
        return
    try:
        flush()
    except Exception:  # noqa: BLE001
        _log.debug("Langfuse flush failed", exc_info=True)


def capture_input_output() -> bool:
    """Whether raw prompt/response payloads should be sent to Langfuse."""
    _load_env_once()
    return _env_bool("LANGFUSE_CAPTURE_INPUT_OUTPUT", default=False)


def _langfuse_mask(data: Any) -> Any:
    """Redact sensitive payload fields before the SDK exports them."""
    try:
        return redact(data, context="diagnostic")
    except Exception:  # noqa: BLE001 - masking must never break tracing
        _log.debug("Langfuse masking failed", exc_info=True)
        return data


def _load_env_once() -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    env_path = Path(LLM_ENV_PATH)
    if env_path.exists():
        load_dotenv(env_path, override=False)
    _DOTENV_LOADED = True


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on", "enabled"}


def _env_float_or_none(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _optional_env(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value not in {None, ""} else None


def _string_metadata(metadata: dict[str, Any] | None) -> dict[str, str] | None:
    if not metadata:
        return None
    result: dict[str, str] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        result[str(key)] = str(value)
    return result or None


@contextmanager
def _fail_open_context(*contexts: Any, label: str) -> Iterator[Any | None]:
    """Enter context managers fail-open, while preserving body exceptions."""
    entered: list[Any] = []
    value: Any | None = None
    try:
        for context in contexts:
            if context is None:
                continue
            value = context.__enter__()
            entered.append(context)
    except Exception as exc:  # noqa: BLE001
        _log.warning("%s failed open: %s", label, exc, exc_info=True)
        while entered:
            context = entered.pop()
            try:
                context.__exit__(*sys.exc_info())
            except Exception:
                _log.debug("%s cleanup failed", label, exc_info=True)
        yield None
        return

    try:
        yield value
    except BaseException:
        exc_info = sys.exc_info()
        suppress = False
        while entered:
            context = entered.pop()
            try:
                suppress = bool(context.__exit__(*exc_info)) or suppress
            except Exception:
                _log.debug("%s exception cleanup failed", label, exc_info=True)
        if not suppress:
            raise
    else:
        while entered:
            context = entered.pop()
            try:
                context.__exit__(None, None, None)
            except Exception:
                _log.debug("%s cleanup failed", label, exc_info=True)
