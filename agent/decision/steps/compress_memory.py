"""compress_memory_step – LLM-compress old closed segments.

When the number of closed segments exceeds ``max_recent_closed_segments``,
the oldest un-compressed segment is sent to the LLM for summarisation.
Failure never blocks the decision; each segment gets at most 2 retries.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from agent.core.context import AgentContext
from agent.core.memory import AgentMemory
from agent.core.memory_segments import CompressedSegmentSummary, Segment
from agent.infrastructure.llm import ModelAdapter
from agent.infrastructure.tracing import observe

_log = logging.getLogger(__name__)

_MAX_RETRIES = 2

_COMPRESS_PROMPT = """\
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
- events: 该玩家在该阶段可见的事件列表

请输出合法 JSON，格式如下:
{{
  "segment_key": "{segment_key}",
  "summary": "本阶段简要摘要",
  "key_events": ["重要事件1", "重要事件2"],
  "player_notes": {{"3": "对该玩家的观察", "5": "对该玩家的观察"}},
  "unknowns": ["不确定的事项"]
}}

事件列表:
{events_text}
"""


@observe(name="compress_memory_step")
async def compress_memory_step(
    ctx: AgentContext,
    memory: AgentMemory,
    model: ModelAdapter,
    *,
    max_recent_closed_segments: int = 4,
    max_retries: int = _MAX_RETRIES,
) -> AgentContext:
    """Compress old closed segments that exceed the retention window.

    Only one segment is compressed per call to avoid blocking the decision.
    """
    closed = [s for s in memory.segments if s.closed]
    if len(closed) <= max_recent_closed_segments:
        return ctx

    # Find the oldest segment that hasn't failed and hasn't been compressed yet
    compressed_keys = set(memory.compressed_segment_summaries.keys())
    candidate: Segment | None = None
    for seg in closed:
        if seg.segment_key in compressed_keys:
            continue
        if seg.compression_failed:
            continue
        candidate = seg
        break

    if candidate is None:
        return ctx

    # Try LLM compression
    try:
        summary = await _compress_segment(candidate, memory, model)
        if summary is not None:
            memory.compressed_segment_summaries[candidate.segment_key] = summary
            ctx.compressed_segments_added.append(candidate.segment_key)
            _log.debug(
                "Compressed segment %s for player %s", candidate.segment_key, memory.player_id
            )
        else:
            candidate.compression_retry_count += 1
            if candidate.compression_retry_count >= max_retries:
                candidate.compression_failed = True
                _log.warning(
                    "Segment %s compression failed after %d retries, keeping full events",
                    candidate.segment_key,
                    candidate.compression_retry_count,
                )
    except Exception as exc:
        candidate.compression_retry_count += 1
        if candidate.compression_retry_count >= max_retries:
            candidate.compression_failed = True
        ctx.compression_errors.append(f"{candidate.segment_key}: {exc}")
        _log.warning(
            "compress_memory_step error for segment %s: %s",
            candidate.segment_key,
            exc,
            exc_info=True,
        )

    return ctx


async def _compress_segment(
    segment: Segment,
    memory: AgentMemory,
    model: ModelAdapter,
) -> CompressedSegmentSummary | None:
    """Call the LLM to compress a single segment. Returns None on failure."""
    events_text = "\n".join(
        f"- {e.to_prompt_text()}" for e in segment.events
    )
    prompt = _COMPRESS_PROMPT.format(
        game_id=getattr(memory, "game_id", "unknown"),
        player_id=memory.player_id,
        role=memory.role.value if hasattr(memory.role, "value") else str(memory.role),
        segment_key=segment.segment_key,
        events_text=events_text,
    )

    raw = await model.complete(
        messages=[
            {"role": "system", "content": "你是记忆压缩助手，只输出合法 JSON。"},
            {"role": "user", "content": prompt},
        ],
    )

    if not raw or not raw.strip():
        return None

    # Parse JSON response
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError:
        # Try to extract JSON from markdown code block
        if "```" in raw:
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(raw[start:end])
            else:
                return None
        else:
            return None

    # Validate required fields
    if "summary" not in data:
        return None

    return CompressedSegmentSummary(
        segment_key=data.get("segment_key", segment.segment_key),
        summary=data["summary"],
        key_events=data.get("key_events", []),
        player_notes=data.get("player_notes", {}),
        unknowns=data.get("unknowns", []),
    )
