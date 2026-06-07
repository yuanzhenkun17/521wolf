"""LCEL chains — the **only** file in app/ that calls the LLM.

5 chains:
1. decision_chain   — per-step agent decision (tool calling / JSON output)
2. compress_chain   — memory segment compression (prompt | llm | parser)
3. consolidate_chain — experience → skill proposals
4. apply_chain      — proposals → skill file diffs
5. evidence_chain   — evidence evaluation

All other app/ code that needs LLM must go through a chain function here.
"""

from __future__ import annotations

import logging
import time
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

def build_decision_chain(llm: Any, tools: list | None = None):
    """Build the decision chain: prompt -> LLM[.bind_tools(tools)] -> parser.

    Uses tool calling if tools are provided, else JSON output parsing.
    """
    from app.services.prompt import build_decision_prompt_template, DecisionOutput
    from langchain_core.output_parsers import PydanticOutputParser

    prompt = build_decision_prompt_template()
    bound_llm = llm.bind_tools(tools) if tools and hasattr(llm, "bind_tools") else llm
    parser = PydanticOutputParser(pydantic_object=DecisionOutput) if tools else JsonOutputParser()
    return prompt | _llm_runnable(bound_llm, stage="decision") | RunnableLambda(_message_content) | parser


def create_decision_chain(llm: Any, tools: list | None = None):
    """Backward-compatible alias for build_decision_chain."""
    return build_decision_chain(llm, tools)


async def run_decision_chain(
    model: Any,
    *,
    messages: list[dict[str, str]],
) -> str:
    """Call the LLM for a single agent decision. Returns raw output text."""
    return await build_raw_message_chain(model, stage="decision").ainvoke(messages)


# ===========================================================================
# Chain 3/4/5: consolidate, apply, evidence
# ===========================================================================

def build_raw_message_chain(llm: Any, *, stage: str = "raw_message"):
    """Build a raw message chain: messages -> LLM -> content string."""
    return RunnableLambda(_identity) | _llm_runnable(llm, stage=stage) | RunnableLambda(_message_content)


def build_consolidate_chain(llm: Any):
    """Build the skill-consolidation chain."""
    return build_raw_message_chain(llm, stage="consolidate")


def create_consolidate_chain(llm: Any):
    """Backward-compatible alias for build_consolidate_chain."""
    return build_consolidate_chain(llm)


def build_apply_chain(llm: Any):
    """Build the skill-apply chain."""
    return build_raw_message_chain(llm, stage="apply")


def create_apply_chain(llm: Any):
    """Backward-compatible alias for build_apply_chain."""
    return build_apply_chain(llm)


def build_evidence_chain(llm: Any):
    """Build the evidence-judging chain."""
    return build_raw_message_chain(llm, stage="evidence")


def create_evidence_chain(llm: Any):
    """Backward-compatible alias for build_evidence_chain."""
    return build_evidence_chain(llm)


async def run_consolidate_chain(
    model: Any,
    *,
    messages: list[dict[str, str]],
) -> str:
    """Call the LLM for skill consolidation. Returns raw output text."""
    return await build_consolidate_chain(model).ainvoke(messages)


async def run_apply_chain(
    model: Any,
    *,
    messages: list[dict[str, str]],
) -> str:
    """Call the LLM to apply skill proposals to markdown files."""
    return await build_apply_chain(model).ainvoke(messages)


async def run_evidence_chain(
    model: Any,
    *,
    messages: list[dict[str, str]],
) -> str:
    """Call the LLM for evidence evaluation/judging."""
    return await build_evidence_chain(model).ainvoke(messages)


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


def _llm_runnable(llm: Any, *, stage: str) -> RunnableLambda:
    async def _call(messages: Any) -> Any:
        prepared_messages = prepare_llm_messages(messages, stage=stage)
        started = time.perf_counter()
        try:
            return await invoke_llm_with_policy(
                llm,
                prepared_messages,
                stage=stage,
                circuit_key=f"{stage}:{_model_identifier(llm) or 'unknown'}",
            )
        except LLMCallError:
            raise
        except Exception as exc:
            elapsed_ms = int(round((time.perf_counter() - started) * 1000))
            raise LLMCallError(
                stage=stage,
                model=_model_identifier(llm),
                elapsed_ms=elapsed_ms,
                exc=exc,
                messages=prepared_messages,
            ) from exc

    return RunnableLambda(_call)


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


_SCHEMA_VERSIONED_STAGES = frozenset({"decision", "consolidate", "apply", "evidence"})


def _output_diagnostic(text: str) -> dict[str, Any]:
    parsed = try_extract_json(text)
    observed = parsed.get("schema_version") if isinstance(parsed, dict) else None
    return {
        "observed_schema_version": str(observed) if observed is not None else None,
        "expected_schema_version": EXPECTED_LLM_SCHEMA_VERSION,
    }
