"""Optional Langfuse observability helpers.

The integration is deliberately fail-open: if tracing is disabled, keys are
missing, or the self-hosted base URL is not set, every public helper becomes a
no-op. This keeps tests and local fake-model runs independent from Langfuse.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import quote

from dotenv import load_dotenv

from app.config import LLM_ENV_PATH
from app.util.redaction import redact

_log = logging.getLogger(__name__)

_CLIENT: Any | None = None
_CLIENT_CONFIG: tuple[str, str, str, str | None, str | None, float | None] | None = None
_DOTENV_LOADED = False


@dataclass(frozen=True)
class LangfuseExperimentLink:
    """Best-effort links between local eval runs and Langfuse experiments."""

    trace_id: str | None = None
    trace_url: str | None = None
    dataset_name: str | None = None
    dataset_id: str | None = None
    dataset_item_id: str | None = None
    dataset_run_id: str | None = None
    dataset_run_item_id: str | None = None
    experiment_name: str | None = None
    run_name: str | None = None
    experiment_url: str | None = None
    observation_id: str | None = None
    linked: bool = False
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a compact serializable representation for API responses/logs."""
        data = {
            "trace_id": self.trace_id,
            "trace_url": self.trace_url,
            "dataset_name": self.dataset_name,
            "dataset_id": self.dataset_id,
            "dataset_item_id": self.dataset_item_id,
            "dataset_run_id": self.dataset_run_id,
            "dataset_run_item_id": self.dataset_run_item_id,
            "experiment_name": self.experiment_name,
            "run_name": self.run_name,
            "experiment_url": self.experiment_url,
            "observation_id": self.observation_id,
            "linked": self.linked,
            "metadata": self.metadata,
        }
        return {key: value for key, value in data.items() if value is not None}


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
    if callable(get_url):
        try:
            url = get_url(trace_id=trace_id)
            return str(url) if url else None
        except Exception:  # noqa: BLE001
            _log.debug("Langfuse trace URL lookup failed", exc_info=True)
    return _build_langfuse_trace_url(client, trace_id)


def build_langfuse_dataset_item_id(
    *,
    evaluation_set_id: str | None,
    seed_set_id: str | None,
    seed: int | str | None,
) -> str | None:
    """Build the canonical benchmark dataset item id, if all parts are present."""
    if evaluation_set_id in {None, ""} or seed_set_id in {None, ""} or seed in {None, ""}:
        return None
    return f"{evaluation_set_id}:{seed_set_id}:{seed}"


def langfuse_experiment_metadata(
    *,
    dataset_name: str | None = None,
    dataset_item_id: str | None = None,
    experiment_name: str | None = None,
    run_name: str | None = None,
    trace_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge local metadata with standard Langfuse dataset/experiment keys."""
    result = dict(metadata or {})
    additions = {
        "langfuse_dataset_name": dataset_name,
        "langfuse_dataset_item_id": dataset_item_id,
        "langfuse_experiment_name": experiment_name,
        "langfuse_run_name": run_name,
        "langfuse_trace_id": trace_id,
    }
    for key, value in additions.items():
        if value is not None and value != "":
            result.setdefault(key, value)
    return result


def get_langfuse_dataset_item(
    dataset_name: str | None,
    dataset_item_id: str | None,
    *,
    client: Any | None = None,
) -> Any | None:
    """Fetch a Langfuse dataset item by id/name, failing open when unavailable."""
    if not dataset_name or not dataset_item_id:
        return None
    resolved_client = _resolve_langfuse_client(client)
    if resolved_client is None:
        return None
    try:
        dataset = _get_langfuse_dataset(resolved_client, dataset_name)
        for item in _iter_langfuse_dataset_items(dataset):
            if _langfuse_dataset_item_matches(item, dataset_item_id):
                return item
    except Exception:  # noqa: BLE001 - observability must not affect eval
        _log.debug("Langfuse dataset item lookup failed for %s/%s", dataset_name, dataset_item_id, exc_info=True)
    return None


def get_experiment_url(
    *,
    dataset_name: str | None = None,
    run_name: str | None = None,
    dataset_id: str | None = None,
    dataset_run_id: str | None = None,
    client: Any | None = None,
) -> str | None:
    """Return a best-effort Langfuse dataset run/experiment URL."""
    resolved_client = _resolve_langfuse_client(client)
    if resolved_client is None:
        return None

    resolved_dataset_id = dataset_id
    resolved_dataset_run_id = dataset_run_id
    try:
        if (not resolved_dataset_id or not resolved_dataset_run_id) and dataset_name and run_name:
            dataset_run = _get_langfuse_dataset_run(resolved_client, dataset_name, run_name)
            resolved_dataset_id = resolved_dataset_id or _string_attr(dataset_run, "dataset_id", "datasetId")
            resolved_dataset_run_id = resolved_dataset_run_id or _string_attr(dataset_run, "id")
        if not resolved_dataset_id and dataset_name:
            dataset = _get_langfuse_dataset(resolved_client, dataset_name, fetch_items_page_size=1)
            resolved_dataset_id = _string_attr(dataset, "id")
        return _build_langfuse_dataset_run_url(
            resolved_client,
            dataset_id=resolved_dataset_id,
            dataset_run_id=resolved_dataset_run_id,
        )
    except Exception:  # noqa: BLE001
        _log.debug("Langfuse experiment URL lookup failed", exc_info=True)
        return None


def link_langfuse_dataset_run_item(
    *,
    dataset_name: str | None,
    dataset_item_id: str | None,
    run_name: str | None,
    trace_id: str | None = None,
    observation_id: str | None = None,
    experiment_name: str | None = None,
    run_description: str | None = None,
    metadata: dict[str, Any] | None = None,
    dataset_version: Any | None = None,
    client: Any | None = None,
) -> LangfuseExperimentLink:
    """Link a trace to a Langfuse dataset run item, returning best-effort URLs."""
    resolved_trace_id = trace_id or get_current_trace_id()
    base_metadata = langfuse_experiment_metadata(
        dataset_name=dataset_name,
        dataset_item_id=dataset_item_id,
        experiment_name=experiment_name,
        run_name=run_name,
        trace_id=resolved_trace_id,
        metadata=metadata,
    )
    trace_url = get_trace_url(resolved_trace_id) if resolved_trace_id else None
    base_link = LangfuseExperimentLink(
        trace_id=resolved_trace_id,
        trace_url=trace_url,
        dataset_name=dataset_name,
        dataset_item_id=dataset_item_id,
        experiment_name=experiment_name,
        run_name=run_name,
        observation_id=observation_id,
        linked=False,
        metadata=base_metadata or None,
    )

    if not dataset_item_id or not run_name:
        return base_link

    resolved_client = _resolve_langfuse_client(client)
    if resolved_client is None:
        return base_link

    try:
        run_item = _create_langfuse_dataset_run_item(
            resolved_client,
            run_name=run_name,
            dataset_item_id=dataset_item_id,
            run_description=run_description,
            metadata=base_metadata or None,
            observation_id=observation_id,
            trace_id=resolved_trace_id,
            dataset_version=dataset_version,
        )
        dataset_run_id = _string_attr(run_item, "dataset_run_id", "datasetRunId")
        dataset_run_item_id = _string_attr(run_item, "id")
        dataset_id = _string_attr(run_item, "dataset_id", "datasetId")
        if (not dataset_id or not dataset_run_id) and dataset_name:
            dataset_run = _get_langfuse_dataset_run(resolved_client, dataset_name, run_name)
            dataset_id = dataset_id or _string_attr(dataset_run, "dataset_id", "datasetId")
            dataset_run_id = dataset_run_id or _string_attr(dataset_run, "id")
        experiment_url = get_experiment_url(
            dataset_name=dataset_name,
            run_name=run_name,
            dataset_id=dataset_id,
            dataset_run_id=dataset_run_id,
            client=resolved_client,
        )
        return LangfuseExperimentLink(
            trace_id=resolved_trace_id,
            trace_url=trace_url or _build_langfuse_trace_url(resolved_client, resolved_trace_id),
            dataset_name=dataset_name,
            dataset_id=dataset_id,
            dataset_item_id=dataset_item_id,
            dataset_run_id=dataset_run_id,
            dataset_run_item_id=dataset_run_item_id,
            experiment_name=experiment_name,
            run_name=run_name,
            experiment_url=experiment_url,
            observation_id=observation_id,
            linked=True,
            metadata=base_metadata or None,
        )
    except Exception:  # noqa: BLE001
        _log.debug("Langfuse dataset run item link failed", exc_info=True)
        return LangfuseExperimentLink(
            **{
                **base_link.__dict__,
                "experiment_url": get_experiment_url(
                    dataset_name=dataset_name,
                    run_name=run_name,
                    client=resolved_client,
                ),
            }
        )


def score_dataset_run(
    dataset_run_id: str | None,
    name: str,
    value: float | str | bool,
    *,
    data_type: str | None = None,
    comment: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Best-effort score on a Langfuse dataset run/experiment."""
    if not dataset_run_id:
        return
    client = get_langfuse_client()
    if client is None:
        return
    create_score = getattr(client, "create_score", None)
    if not callable(create_score):
        return
    try:
        create_score(
            dataset_run_id=str(dataset_run_id),
            name=name,
            value=value,
            data_type=data_type,
            comment=comment,
            metadata=metadata,
        )
    except Exception:  # noqa: BLE001
        _log.debug("Langfuse dataset run scoring failed for %s on %s", name, dataset_run_id, exc_info=True)


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


def _resolve_langfuse_client(client: Any | None = None) -> Any | None:
    if not langfuse_enabled():
        return None
    if client is not None:
        return client
    return get_langfuse_client()


def _get_langfuse_dataset(client: Any, dataset_name: str, **kwargs: Any) -> Any | None:
    get_dataset = getattr(client, "get_dataset", None)
    if not callable(get_dataset):
        return None
    try:
        return get_dataset(dataset_name, **kwargs)
    except TypeError:
        return get_dataset(dataset_name)


def _iter_langfuse_dataset_items(dataset: Any | None) -> Iterator[Any]:
    if dataset is None:
        return
    items = getattr(dataset, "items", None)
    if items is None and isinstance(dataset, dict):
        items = dataset.get("items")
    if items is None:
        return
    try:
        yield from items
    except TypeError:
        return


def _langfuse_dataset_item_matches(item: Any, dataset_item_id: str) -> bool:
    item_id = _string_attr(item, "id", "item_id", "itemId")
    if item_id == dataset_item_id:
        return True
    metadata = _value_attr(item, "metadata")
    if isinstance(metadata, dict):
        return str(metadata.get("item_name") or metadata.get("item_id") or "") == dataset_item_id
    return False


def _create_langfuse_dataset_run_item(
    client: Any,
    *,
    run_name: str,
    dataset_item_id: str,
    run_description: str | None = None,
    metadata: dict[str, Any] | None = None,
    observation_id: str | None = None,
    trace_id: str | None = None,
    dataset_version: Any | None = None,
) -> Any | None:
    create_run_item = getattr(client, "create_dataset_run_item", None)
    kwargs = {
        "run_name": run_name,
        "dataset_item_id": dataset_item_id,
        "run_description": run_description,
        "metadata": metadata,
        "observation_id": observation_id,
        "trace_id": trace_id,
        "dataset_version": dataset_version,
    }
    if callable(create_run_item):
        return _call_with_non_none_kwargs(create_run_item, **kwargs)

    create = _langfuse_dataset_run_items_create(client)
    if callable(create):
        return _call_with_non_none_kwargs(create, **kwargs)

    raise RuntimeError("Langfuse client does not expose dataset run item creation")


def _langfuse_dataset_run_items_create(client: Any) -> Any | None:
    api = getattr(client, "api", None)
    dataset_run_items = getattr(api, "dataset_run_items", None)
    create = getattr(dataset_run_items, "create", None)
    return create if callable(create) else None


def _get_langfuse_dataset_run(client: Any, dataset_name: str, run_name: str) -> Any | None:
    get_dataset_run = getattr(client, "get_dataset_run", None)
    if callable(get_dataset_run):
        return get_dataset_run(dataset_name=dataset_name, run_name=run_name)
    api = getattr(client, "api", None)
    datasets = getattr(api, "datasets", None)
    get_run = getattr(datasets, "get_run", None)
    if callable(get_run):
        try:
            return get_run(dataset_name=dataset_name, run_name=run_name)
        except TypeError:
            return get_run(dataset_name, run_name)
    return None


def _call_with_non_none_kwargs(func: Any, **kwargs: Any) -> Any:
    compact = {key: value for key, value in kwargs.items() if value is not None}
    try:
        return func(**compact)
    except TypeError:
        return func(**kwargs)


def _build_langfuse_trace_url(client: Any, trace_id: str | None) -> str | None:
    if not trace_id:
        return None
    project_id = _langfuse_project_id(client)
    base_url = _langfuse_base_url(client)
    if not project_id or not base_url:
        return None
    return f"{base_url}/project/{quote(project_id, safe='')}/traces/{quote(str(trace_id), safe='')}"


def _build_langfuse_dataset_run_url(
    client: Any,
    *,
    dataset_id: str | None,
    dataset_run_id: str | None,
) -> str | None:
    if not dataset_id or not dataset_run_id:
        return None
    project_id = _langfuse_project_id(client)
    base_url = _langfuse_base_url(client)
    if not project_id or not base_url:
        return None
    return (
        f"{base_url}/project/{quote(project_id, safe='')}/datasets/"
        f"{quote(str(dataset_id), safe='')}/runs/{quote(str(dataset_run_id), safe='')}"
    )


def _langfuse_project_id(client: Any) -> str | None:
    project_id = _string_attr(client, "project_id", "_project_id")
    if project_id:
        return project_id
    get_project_id = getattr(client, "_get_project_id", None)
    if callable(get_project_id):
        try:
            return _string_or_none(get_project_id())
        except Exception:  # noqa: BLE001
            _log.debug("Langfuse project id lookup failed", exc_info=True)
    return None


def _langfuse_base_url(client: Any) -> str | None:
    base_url = _string_attr(client, "base_url", "_base_url")
    if base_url:
        return base_url.rstrip("/")
    env_base_url = os.environ.get("LANGFUSE_BASE_URL")
    return env_base_url.rstrip("/") if env_base_url else None


def _string_attr(value: Any, *names: str) -> str | None:
    for name in names:
        attr = _value_attr(value, name)
        text = _string_or_none(attr)
        if text:
            return text
    return None


def _value_attr(value: Any, name: str) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _string_or_none(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


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
