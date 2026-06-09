"""LCEL chains — the **only** file in app/ that calls the LLM.

6 chains:
1. decision_chain   — per-step agent decision (tool calling / JSON output)
2. compress_chain   — memory segment compression (prompt | llm | parser)
3. consolidate_chain — experience → skill proposals
4. apply_chain      — proposals → skill file diffs
5. evidence_chain   — evidence evaluation
6. decision_judge_chain — rule-selected decision review

All other app/ code that needs LLM must go through a chain function here.
"""

from __future__ import annotations

import logging
import time
import importlib
from typing import Any

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.runnables import RunnableLambda

from app.services.llm import invoke_llm_with_policy
from app.services.memory import CompressedSegmentSummary, Segment
from app.services.prompt import EXPECTED_LLM_SCHEMA_VERSION, prepare_llm_messages
from app.util.redaction import redact, redaction_summary
from app.util.text import try_extract_json

_log = logging.getLogger(__name__)


class LLMOutputText(str):
    """String output with optional diagnostics attached."""

    def __new__(cls, value: str, *, diagnostic: dict[str, Any] | None = None) -> "LLMOutputText":
        obj = str.__new__(cls, value)
        obj.diagnostic = diagnostic or {}
        return obj


class LLMCallError(RuntimeError):
    """LLM invocation failure with stable diagnostics for upstream callers."""

    def __init__(
        self,
        *,
        stage: str,
        model: str | None,
        elapsed_ms: int,
        exc: Exception,
        messages: Any | None = None,
        observed_schema_version: str | None = None,
    ) -> None:
        self.stage = stage
        self.model = model
        self.elapsed_ms = elapsed_ms
        self.exception_type = type(exc).__name__
        self.attempts = int(getattr(exc, "llm_attempts", 1) or 1)
        self.diagnostic = {
            "stage": stage,
            "model": model,
            "elapsed_ms": elapsed_ms,
            "exception_type": self.exception_type,
            "message": redact(str(exc), context="diagnostic"),
            "attempts": self.attempts,
            "expected_schema_version": EXPECTED_LLM_SCHEMA_VERSION if stage in _SCHEMA_VERSIONED_STAGES else None,
            "observed_schema_version": observed_schema_version,
        }
        if messages is not None:
            self.diagnostic["messages"] = redaction_summary(messages)
        model_label = model or "unknown"
        super().__init__(
            f"stage={stage} model={model_label} elapsed_ms={elapsed_ms} "
            f"attempts={self.attempts} exception_type={self.exception_type}: "
            f"{redact(str(exc), context='diagnostic')}"
        )


# ===========================================================================
# Chain 2: compress_chain — memory segment compression
# ===========================================================================

_COMPRESS_PROMPT = """你是记忆压缩助手，只输出合法 JSON。

你是一个游戏记忆压缩器。你只能根据输入事件总结，不能补充输入中没有出现的信息。

你正在为一名狼人杀玩家压缩历史阶段记忆。该玩家只能看到自己视角可见的事件。
- 不得补充输入中没有的身份真相
- 不得推断上帝视角
- 不确定的信息写入 unknowns

输入:
- game_id: {game_id}
- player_id: {player_id}
- role: {role}
- segment_key: {segment_key}

请输出合法 JSON:
{{"segment_key": "{segment_key}", "summary": "本阶段简要摘要", "key_events": ["重要事件"], "player_notes": {{"3": "观察"}}, "unknowns": ["未知"]}}

事件列表:
{events_text}"""

_COMPRESS_SYSTEM = "你是记忆压缩助手，只输出合法 JSON。"


def build_compress_chain(llm: Any):
    """Build the compression chain: input dict -> messages -> LLM -> JSON."""
    return (
        RunnableLambda(_compress_inputs_to_messages)
        | _llm_runnable(llm, stage="compress")
        | RunnableLambda(_message_content)
        | RunnableLambda(_parse_json_or_none)
    )


async def run_compress_chain(
    model: Any,
    segment: Segment,
    memory: Any,
    *,
    game_id: str = "unknown",
) -> CompressedSegmentSummary | None:
    """Compress a single memory segment via LLM.

    Returns None on any failure (JSON parse, missing fields, LLM error).
    Does not block the game pipeline.
    """
    events_text = "\n".join(f"- {e.to_prompt_text()}" for e in segment.events)
    role_str = memory.role.value if hasattr(memory.role, "value") else str(memory.role)

    try:
        data = await build_compress_chain(model).ainvoke({
            "game_id": game_id,
            "player_id": memory.player_id,
            "role": role_str,
            "segment_key": segment.segment_key,
            "events_text": events_text,
        })
    except Exception as exc:
        _log.warning("compress_chain LLM call failed: %s", exc)
        return None

    if not isinstance(data, dict) or "summary" not in data:
        return None

    return CompressedSegmentSummary(
        segment_key=data.get("segment_key", segment.segment_key),
        summary=data["summary"],
        key_events=data.get("key_events", []),
        player_notes=data.get("player_notes", {}),
        unknowns=data.get("unknowns", []),
    )


# ===========================================================================
# Chain 1: decision_chain — per-step agent decision
# ===========================================================================

def build_decision_chain(
    llm: Any,
    tools: list | None = None,
    *,
    metadata: dict[str, Any] | None = None,
):
    """Build the decision chain: prompt -> LLM[.bind_tools(tools)] -> parser.

    Uses tool calling if tools are provided, else JSON output parsing.
    """
    from app.services.prompt import build_decision_prompt_template, DecisionOutput
    from langchain_core.output_parsers import PydanticOutputParser

    prompt = build_decision_prompt_template()
    bound_llm = llm.bind_tools(tools) if tools and hasattr(llm, "bind_tools") else llm
    parser = PydanticOutputParser(pydantic_object=DecisionOutput) if tools else JsonOutputParser()
    return (
        prompt
        | _llm_runnable(bound_llm, stage="decision", metadata=metadata)
        | RunnableLambda(_message_content)
        | parser
    )


def create_decision_chain(llm: Any, tools: list | None = None):
    """Backward-compatible alias for build_decision_chain."""
    return build_decision_chain(llm, tools)


async def run_decision_chain(
    model: Any,
    *,
    messages: list[dict[str, str]],
    prompt_budget: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Call the LLM for a single agent decision. Returns raw output text."""
    return await build_raw_message_chain(
        model,
        stage="decision",
        prompt_budget=prompt_budget,
        metadata=metadata,
    ).ainvoke(messages)


# ===========================================================================
# Chain 3/4/5: consolidate, apply, evidence
# ===========================================================================

def build_raw_message_chain(
    llm: Any,
    *,
    stage: str = "raw_message",
    prompt_budget: Any | None = None,
    metadata: dict[str, Any] | None = None,
):
    """Build a raw message chain: messages -> LLM -> content string."""
    return (
        RunnableLambda(_identity)
        | _llm_runnable(llm, stage=stage, prompt_budget=prompt_budget, metadata=metadata)
        | RunnableLambda(_message_content)
    )


def build_consolidate_chain(llm: Any, *, metadata: dict[str, Any] | None = None):
    """Build the skill-consolidation chain."""
    return build_raw_message_chain(llm, stage="consolidate", metadata=metadata)


def create_consolidate_chain(llm: Any):
    """Backward-compatible alias for build_consolidate_chain."""
    return build_consolidate_chain(llm)


def build_apply_chain(llm: Any, *, metadata: dict[str, Any] | None = None):
    """Build the skill-apply chain."""
    return build_raw_message_chain(llm, stage="apply", metadata=metadata)


def create_apply_chain(llm: Any):
    """Backward-compatible alias for build_apply_chain."""
    return build_apply_chain(llm)


def build_evidence_chain(llm: Any, *, metadata: dict[str, Any] | None = None):
    """Build the evidence-judging chain."""
    return build_raw_message_chain(llm, stage="evidence", metadata=metadata)


def create_evidence_chain(llm: Any):
    """Backward-compatible alias for build_evidence_chain."""
    return build_evidence_chain(llm)


def build_decision_judge_chain(llm: Any, *, metadata: dict[str, Any] | None = None):
    """Build the decision-judging chain."""
    return build_raw_message_chain(llm, stage="decision_judge", metadata=metadata)


def create_decision_judge_chain(llm: Any):
    """Backward-compatible alias for build_decision_judge_chain."""
    return build_decision_judge_chain(llm)


async def run_consolidate_chain(
    model: Any,
    *,
    messages: list[dict[str, str]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Call the LLM for skill consolidation. Returns raw output text."""
    return await build_consolidate_chain(model, metadata=metadata).ainvoke(messages)


async def run_apply_chain(
    model: Any,
    *,
    messages: list[dict[str, str]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Call the LLM to apply skill proposals to markdown files."""
    return await build_apply_chain(model, metadata=metadata).ainvoke(messages)


async def run_evidence_chain(
    model: Any,
    *,
    messages: list[dict[str, str]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Call the LLM for evidence evaluation/judging."""
    return await build_evidence_chain(model, metadata=metadata).ainvoke(messages)


async def run_decision_judge_chain(
    model: Any,
    *,
    messages: list[dict[str, str]],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Call the LLM for an explainable key-decision judgment."""
    return await build_decision_judge_chain(model, metadata=metadata).ainvoke(messages)


def _compress_inputs_to_messages(inputs: dict[str, Any]) -> list[dict[str, str]]:
    prompt_text = _COMPRESS_PROMPT.format(
        game_id=inputs.get("game_id", "unknown"),
        player_id=inputs.get("player_id", ""),
        role=inputs.get("role", ""),
        segment_key=inputs.get("segment_key", ""),
        events_text=inputs.get("events_text", ""),
    )
    return [
        {"role": "system", "content": _COMPRESS_SYSTEM},
        {"role": "user", "content": prompt_text},
    ]


def _message_content(message: Any) -> str:
    raw = message.content if hasattr(message, "content") else str(message)
    text = raw if isinstance(raw, str) else str(raw)
    diagnostic = _output_diagnostic(text)
    return LLMOutputText(text, diagnostic=diagnostic)


def _parse_json_or_none(raw: str) -> dict[str, Any] | None:
    if not raw or not raw.strip():
        return None
    return try_extract_json(raw)


def _identity(value: Any) -> Any:
    return value


def _llm_runnable(
    llm: Any,
    *,
    stage: str,
    prompt_budget: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> RunnableLambda:
    extra_metadata = dict(metadata or {})

    async def _call(messages: Any) -> Any:
        prepared_messages = prepare_llm_messages(messages, stage=stage, budget=prompt_budget)
        prompt_metadata = _prompt_registry_metadata(stage=stage, messages=prepared_messages)
        model = _model_identifier(llm)
        observation_metadata = _llm_observation_metadata(
            stage=stage,
            model=model,
            prompt_budget=prompt_budget,
            messages=prepared_messages,
            extra_metadata={**extra_metadata, **prompt_metadata},
        )
        started = time.perf_counter()
        try:
            observability = _observability()
            with observability.observe_llm_call(
                stage=stage,
                model=model,
                messages=prepared_messages,
                metadata=observation_metadata,
                trace_id=_trace_id_from_metadata(observation_metadata),
            ) as observation:
                result = await invoke_llm_with_policy(
                    llm,
                    prepared_messages,
                    stage=stage,
                    circuit_key=f"{stage}:{model or 'unknown'}",
                )
                elapsed_ms = int(round((time.perf_counter() - started) * 1000))
                usage = _llm_usage_metadata(result)
                _update_observation(
                    observability,
                    observation,
                    output=_message_raw_content(result),
                    metadata={
                        **observation_metadata,
                        "elapsed_ms": elapsed_ms,
                        "attempts": int(getattr(result, "llm_attempts", 1) or 1),
                        **_output_diagnostic(_message_raw_content(result)),
                        **usage,
                    },
                    usage_details=usage.get("usage_details"),
                )
                return result
        except LLMCallError:
            raise
        except Exception as exc:
            elapsed_ms = int(round((time.perf_counter() - started) * 1000))
            _update_observation(
                _observability(),
                locals().get("observation"),
                metadata={
                    **observation_metadata,
                    "elapsed_ms": elapsed_ms,
                    "attempts": int(getattr(exc, "llm_attempts", 1) or 1),
                    "exception_type": type(exc).__name__,
                    "exception_message": redact(str(exc), context="diagnostic"),
                },
                level="ERROR",
                status_message=redact(str(exc), context="diagnostic"),
            )
            raise LLMCallError(
                stage=stage,
                model=model,
                elapsed_ms=elapsed_ms,
                exc=exc,
                messages=prepared_messages,
            ) from exc

    return RunnableLambda(_call)


def _observability() -> Any:
    return importlib.import_module("app.services.observability")


_PROMPT_REGISTRY_STAGES = frozenset({"decision_judge", "evidence", "consolidate", "apply"})
_PROMPT_METADATA_KEYS = ("prompt_name", "prompt_version", "prompt_label")


def _prompt_registry_metadata(*, stage: str, messages: Any) -> dict[str, Any]:
    if stage not in _PROMPT_REGISTRY_STAGES:
        return {}
    try:
        registry = importlib.import_module("app.services.prompt_registry")
        get_prompt = getattr(registry, "get_prompt", None)
        if not callable(get_prompt):
            return {}
        resolved = get_prompt(stage, label="production", fallback=_prompt_registry_fallback(messages))
        return _extract_prompt_metadata(resolved)
    except Exception:  # noqa: BLE001 - prompt registry must not affect LLM behavior
        _log.debug("prompt registry lookup failed for stage=%s", stage, exc_info=True)
        return {}


def _extract_prompt_metadata(value: Any) -> dict[str, Any]:
    payload = _prompt_metadata_payload(value)
    if _value_at_path(payload, ("prompt_fallback_used",)) is True:
        return {}
    source = _value_at_path(payload, ("prompt_source",))
    if source is not None and str(source) != "langfuse":
        return {}
    metadata: dict[str, Any] = {}
    for key in _PROMPT_METADATA_KEYS:
        item = _value_at_path(payload, (key,))
        if item is not None:
            metadata[key] = item
    return metadata


def _prompt_metadata_payload(value: Any) -> Any:
    if isinstance(value, tuple) and len(value) >= 2:
        tuple_metadata = _prompt_metadata_payload(value[1])
        if tuple_metadata:
            return tuple_metadata
    to_observation_metadata = getattr(value, "to_observation_metadata", None)
    if callable(to_observation_metadata):
        try:
            payload = to_observation_metadata()
            if payload:
                return payload
        except Exception:  # noqa: BLE001 - metadata extraction must fail open
            return {}
    for path in (
        ("metadata",),
        ("prompt_metadata",),
        ("langfuse_metadata",),
        ("prompt", "metadata"),
    ):
        payload = _value_at_path(value, path)
        if payload:
            return payload
    return value


def _prompt_registry_fallback(value: Any) -> Any:
    if isinstance(value, list):
        return [_prompt_registry_fallback(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_prompt_registry_fallback(item) for item in value)
    if isinstance(value, dict):
        return dict(value)
    copy_method = getattr(value, "model_copy", None)
    if callable(copy_method):
        try:
            return copy_method()
        except Exception:  # noqa: BLE001
            pass
    copy_method = getattr(value, "copy", None)
    if callable(copy_method):
        try:
            return copy_method()
        except Exception:  # noqa: BLE001
            pass
    return value


def _update_observation(observability: Any, observation: Any, **kwargs: Any) -> None:
    update = getattr(observability, "update_observation", None)
    if not callable(update):
        return
    try:
        update(observation, **kwargs)
    except Exception:  # noqa: BLE001
        _log.debug("observability update failed", exc_info=True)


def _trace_id_from_metadata(metadata: dict[str, Any]) -> str | None:
    trace_id = metadata.get("langfuse_trace_id")
    if trace_id is None:
        return None
    text = str(trace_id).strip()
    return text or None


def _message_raw_content(message: Any) -> str:
    raw = message.content if hasattr(message, "content") else str(message)
    return raw if isinstance(raw, str) else str(raw)


def _llm_observation_metadata(
    *,
    stage: str,
    model: str | None,
    prompt_budget: Any | None,
    messages: Any,
    extra_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "stage": stage,
        "model": model,
        "message_summary": redaction_summary(messages),
    }
    if stage in _SCHEMA_VERSIONED_STAGES:
        metadata["expected_schema_version"] = EXPECTED_LLM_SCHEMA_VERSION
    if prompt_budget is not None:
        metadata["prompt_budget"] = {
            "max_total_chars": getattr(prompt_budget, "max_total_chars", None),
            "max_message_chars": getattr(prompt_budget, "max_message_chars", None),
            "min_message_chars": getattr(prompt_budget, "min_message_chars", None),
        }
    if extra_metadata:
        for key, value in extra_metadata.items():
            if value is not None:
                metadata[str(key)] = value
    return metadata


def _model_identifier(llm: Any) -> str | None:
    attrs = ("model_name", "model", "model_id", "deployment_name", "azure_deployment", "name")
    current = llm
    seen: set[int] = set()
    for _ in range(4):
        if current is None:
            return None
        marker = id(current)
        if marker in seen:
            return None
        seen.add(marker)
        for attr in attrs:
            value = getattr(current, attr, None)
            if value is None or callable(value):
                continue
            text = str(value).strip()
            if text:
                return text
        current = getattr(current, "bound", None) or getattr(current, "_bound", None)
    return None


def _llm_usage_metadata(result: Any) -> dict[str, Any]:
    try:
        usage = _extract_usage_payload(result)
        if not usage:
            return {}
        normalized = _normalize_usage_payload(usage)
        if not normalized:
            return {"usage": usage}
        payload: dict[str, Any] = {"usage": normalized}
        usage_details = _usage_details(normalized)
        if usage_details:
            payload["usage_details"] = usage_details
        return payload
    except Exception:  # noqa: BLE001 - usage extraction must not affect LLM calls
        _log.debug("LLM usage extraction failed", exc_info=True)
        return {}


def _extract_usage_payload(result: Any) -> dict[str, Any]:
    candidates = (
        _value_at_path(result, ("usage_metadata",)),
        _value_at_path(result, ("response_metadata", "token_usage")),
        _value_at_path(result, ("response_metadata", "usage")),
        _value_at_path(result, ("llm_output", "token_usage")),
        _value_at_path(result, ("llm_output", "usage")),
        _value_at_path(result, ("token_usage",)),
        _value_at_path(result, ("usage",)),
    )
    for candidate in candidates:
        payload = _dict_like(candidate)
        if payload:
            return payload
    return {}


def _value_at_path(value: Any, path: tuple[str, ...]) -> Any:
    current = value
    for key in path:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
    return current


def _dict_like(value: Any) -> dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return dict(value)
    items = getattr(value, "items", None)
    if callable(items):
        try:
            return dict(items())
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _normalize_usage_payload(usage: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    key_groups = {
        "input_tokens": ("input_tokens", "prompt_tokens", "prompt_token_count"),
        "output_tokens": ("output_tokens", "completion_tokens", "completion_token_count"),
        "total_tokens": ("total_tokens", "total_token_count"),
    }
    for canonical, keys in key_groups.items():
        value = _first_number(usage, keys)
        if value is not None:
            normalized[canonical] = value

    for key, value in usage.items():
        if key not in normalized and isinstance(value, (int, float, str, bool, list, dict, type(None))):
            normalized.setdefault(str(key), value)
    return {key: value for key, value in normalized.items() if value is not None}


def _first_number(usage: dict[str, Any], keys: tuple[str, ...]) -> int | float | None:
    for key in keys:
        value = usage.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            return value
        try:
            return int(str(value))
        except (TypeError, ValueError):
            continue
    return None


def _usage_details(usage: dict[str, Any]) -> dict[str, int]:
    details: dict[str, int] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, bool) or value is None:
            continue
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number >= 0:
            details[key] = number
    return details


_SCHEMA_VERSIONED_STAGES = frozenset({"decision", "consolidate", "apply", "evidence", "decision_judge"})


def _output_diagnostic(text: str) -> dict[str, Any]:
    parsed = try_extract_json(text)
    observed = parsed.get("schema_version") if isinstance(parsed, dict) else None
    return {
        "observed_schema_version": str(observed) if observed is not None else None,
        "expected_schema_version": EXPECTED_LLM_SCHEMA_VERSION,
    }
