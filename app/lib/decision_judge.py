"""LLM-backed decision judging built on top of rule-selected evidence.

The selector is deterministic and comes from ``app.lib.evidence``. LLM calls
are routed through ``app.services.chain`` so this module does not talk to a
model directly.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.util.json import DictMixin, compact_json
from app.util.text import extract_json

JudgeCall = Callable[[list[dict[str, str]]], Awaitable[str]]


@dataclass(slots=True)
class DecisionJudgment(DictMixin):
    schema_version: str = "1.0"
    decision_id: str = ""
    player_id: int | None = None
    role: str = ""
    action_type: str = ""
    day: int | None = None
    phase: str = ""
    score: float = 5.0
    quality: str = "unknown"
    reason: str = ""
    evidence: list[str] = field(default_factory=list)
    evidence_refs: list[str] = field(default_factory=list)
    counterfactual: str = ""
    mistake_tags: list[str] = field(default_factory=list)
    rubric_hits: list[str] = field(default_factory=list)
    rubric_misses: list[str] = field(default_factory=list)
    related_skills: list[str] = field(default_factory=list)
    recommended_skill_files: list[str] = field(default_factory=list)
    suggestion: str = ""
    confidence: float = 0.0
    source: str = "llm_judge"


@dataclass(slots=True)
class GameJudgmentReport(DictMixin):
    schema_version: str = "1.0"
    status: str = "skipped"
    reason: str = ""
    game_id: str = ""
    winner: str = ""
    selection: dict[str, Any] = field(default_factory=dict)
    judgments: list[DecisionJudgment] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    degraded_reasons: list[str] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)


async def judge_key_decisions(
    model: Any = None,
    *,
    game_id: str = "",
    winner: Any = "",
    roles: Any = None,
    events: Any = None,
    decisions: Any = None,
    review: Any = None,
    max_decisions: int = 8,
    concurrency: int = 3,
    timeout_seconds: float | None = None,
    judge_fn: JudgeCall | None = None,
) -> dict[str, Any]:
    """Judge rule-selected key decisions and return an explainable report.

    The LLM stage is advisory. Individual decision failures become report
    warnings and do not abort the whole report.
    """
    decision_rows = [d for d in _list_value(decisions) if isinstance(d, dict)]
    event_rows = [e for e in _list_value(events) if isinstance(e, dict)]
    player_roles = _normalize_role_map(roles)
    winner_text = _enum_value(winner)
    max_count = max(0, int(max_decisions or 0))
    effective_concurrency = max(1, int(concurrency or 1))
    effective_timeout = _as_positive_float(timeout_seconds)

    if judge_fn is None and model is None:
        return _skipped_report(
            game_id=game_id,
            winner=winner_text,
            reason="no_model",
            total_decisions=len(decision_rows),
        )
    if not decision_rows:
        return _skipped_report(
            game_id=game_id,
            winner=winner_text,
            reason="no_decisions",
            total_decisions=0,
        )
    if max_count <= 0:
        return _skipped_report(
            game_id=game_id,
            winner=winner_text,
            reason="max_decisions_zero",
            total_decisions=len(decision_rows),
        )

    from app.lib.evidence import GameEvidenceBundle, normalize_decisions, select_key_decisions

    bundle = GameEvidenceBundle(
        game_dir=Path(game_id or "."),
        game_id=str(game_id or ""),
        archive={
            "winner": winner_text,
            "player_roles": player_roles,
            "decisions": decision_rows,
        },
        agent_decisions=decision_rows,
        game_events=event_rows,
        meta={
            "winner": winner_text,
            "player_roles": player_roles,
            "review": _dict_value(review),
        },
    )
    evidence_inputs = normalize_decisions(bundle)
    key_decisions = select_key_decisions(evidence_inputs, bundle)
    selected = key_decisions[:max_count]
    input_by_id = {item.decision_id: item for item in evidence_inputs}
    selection = {
        "method": "app.lib.evidence.select_key_decisions",
        "total_decisions": len(evidence_inputs),
        "key_decisions": len(key_decisions),
        "selected_for_judge": len(selected),
        "max_decisions": max_count,
    }
    if not selected:
        return GameJudgmentReport(
            status="skipped",
            reason="no_key_decisions",
            game_id=str(game_id or ""),
            winner=winner_text,
            selection=selection,
            summary={"reason": "no_key_decisions"},
            metrics={
                "total_decisions": len(evidence_inputs),
                "key_decisions": 0,
                "judged": 0,
                "failed": 0,
            },
        ).to_dict()

    call_judge = judge_fn or _chain_judge_call(model)
    semaphore = asyncio.Semaphore(effective_concurrency)

    async def _judge_one(key: Any) -> tuple[DecisionJudgment | None, str | None, dict[str, Any] | None]:
        evidence_input = input_by_id.get(key.decision_id)
        if evidence_input is None:
            message = f"decision judge skipped {key.decision_id}: missing evidence input"
            return None, message, _judge_diagnostic(
                reason="missing_evidence_input",
                decision_id=key.decision_id,
                message=message,
            )
        messages = build_decision_judge_messages(
            game_id=str(game_id or ""),
            winner=winner_text,
            roles=player_roles,
            events=event_rows,
            decision_input=evidence_input,
            key_decision=key,
            heuristic_review=review,
        )
        async with semaphore:
            try:
                pending = call_judge(messages)
                raw = await asyncio.wait_for(pending, timeout=effective_timeout) if effective_timeout else await pending
                return parse_decision_judgment(
                    raw,
                    decision_input=evidence_input,
                    key_decision=key,
                ), None, None
            except asyncio.TimeoutError as exc:
                message = (
                    f"decision judge failed for {key.decision_id}: "
                    f"TimeoutError: timed out after {effective_timeout:g}s"
                )
                return None, message, _judge_diagnostic(
                    reason="timeout",
                    decision_id=key.decision_id,
                    message=message,
                    exc=exc,
                )
            except Exception as exc:  # noqa: BLE001 - advisory report, not graph failure
                reason = "parse_error" if isinstance(exc, (TypeError, ValueError)) else "model_error"
                message = (
                    f"decision judge failed for {key.decision_id}: "
                    f"{type(exc).__name__}: {exc}"
                )
                return None, message, _judge_diagnostic(
                    reason=reason,
                    decision_id=key.decision_id,
                    message=message,
                    exc=exc,
                )

    results = await asyncio.gather(*(_judge_one(key) for key in selected))
    judgments = [judgment for judgment, _warning, _diagnostic in results if judgment is not None]
    warnings = [warning for _judgment, warning, _diagnostic in results if warning]
    diagnostics = [diagnostic for _judgment, _warning, diagnostic in results if diagnostic]
    failed = len(selected) - len(judgments)
    status = "ok" if judgments and not warnings else "degraded" if judgments else "failed"
    degraded_reasons = _unique_str(diagnostic.get("reason") for diagnostic in diagnostics if diagnostic)
    reason = ""
    if status == "degraded":
        reason = "partial_fail"
    elif status == "failed":
        reason = degraded_reasons[0] if len(degraded_reasons) == 1 else "all_calls_failed"
    report = GameJudgmentReport(
        status=status,
        reason=reason,
        game_id=str(game_id or ""),
        winner=winner_text,
        selection=selection,
        judgments=judgments,
        summary=summarize_judgments(judgments),
        metrics={
            "total_decisions": len(evidence_inputs),
            "key_decisions": len(key_decisions),
            "judged": len(judgments),
            "failed": failed,
        },
        warnings=warnings,
        degraded_reasons=degraded_reasons,
        diagnostics=diagnostics,
    )
    return report.to_dict()


def build_decision_judge_messages(
    *,
    game_id: str,
    winner: str,
    roles: dict[str, str],
    events: list[dict[str, Any]],
    decision_input: Any,
    key_decision: Any,
    heuristic_review: Any = None,
) -> list[dict[str, str]]:
    """Build compact judge messages for one selected decision."""
    payload = {
        "game": {
            "game_id": game_id,
            "winner": winner,
            "roles": roles,
        },
        "selection_reason": _compact_key_decision(key_decision),
        "decision": _compact_decision_input(decision_input),
        "heuristic_review": _compact_review(
            heuristic_review,
            player_id=getattr(decision_input.player_view, "player_id", None),
        ),
        "local_events": _compact_events(
            events,
            day=getattr(decision_input, "day", None),
            phase=getattr(decision_input, "phase", ""),
        ),
    }
    role = str(getattr(key_decision, "role", "") or getattr(decision_input.player_view, "role", ""))
    action_type = str(getattr(key_decision, "action_type", "") or getattr(decision_input, "action_type", ""))
    try:
        from app.lib.evidence import get_decision_rubric

        payload["rubric"] = get_decision_rubric(role, action_type)
    except Exception:  # noqa: BLE001 - rubric context is advisory
        payload["rubric"] = {}
    system = (
        "You are a Werewolf decision judge. Judge one selected key decision "
        "using only supplied evidence. Distinguish decision-time information "
        "from after-game truth. Output JSON only."
    )
    user = (
        "Score 0-10. Use concise Chinese. If evidence is insufficient, set "
        "quality=unknown and score near 5.\n"
        "Return JSON exactly:\n"
        '{"schema_version":"1.0","decision_id":"...","score":0.0,'
        '"quality":"good|ok|bad|unknown","reason":"...",'
        '"evidence":["..."],"evidence_refs":["..."],'
        '"counterfactual":"如果采取更优动作，局面可能如何变化",'
        '"mistake_tags":["..."],'
        '"rubric_hits":["..."],"rubric_misses":["..."],'
        '"related_skills":["..."],"recommended_skill_files":["role/file.md"],'
        '"suggestion":"...","confidence":0.0}\n'
        f"Input JSON:\n{compact_json(payload)}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_decision_judgment(
    raw: Any,
    *,
    decision_input: Any,
    key_decision: Any,
) -> DecisionJudgment:
    """Parse and normalize one LLM judgment."""
    data = extract_json(str(raw))
    score = _clamp_float(data.get("score"), default=5.0, minimum=0.0, maximum=10.0)
    quality = _normalize_quality(data.get("quality"), score=score)
    player_view = getattr(decision_input, "player_view", None)
    role = str(data.get("role") or getattr(key_decision, "role", "") or getattr(player_view, "role", ""))
    action_type = str(
        data.get("action_type")
        or getattr(key_decision, "action_type", "")
        or getattr(decision_input, "action_type", "")
    )
    evidence = (
        _list_str(data.get("evidence"))
        or _list_str(data.get("evidence_refs"))
        or _list_str(getattr(key_decision, "selection_notes", []))
    )
    evidence_refs = _list_str(data.get("evidence_refs")) or evidence
    rubric_skill_files = _rubric_skill_files(role, action_type)
    raw_recommended_skill_files = (
        _list_str(data.get("recommended_skill_files"))
        or _list_str(data.get("recommended_skills"))
    )
    related_skills = _list_str(data.get("related_skills")) or raw_recommended_skill_files or rubric_skill_files
    recommended_skill_files = raw_recommended_skill_files or related_skills or rubric_skill_files
    return DecisionJudgment(
        schema_version=str(data.get("schema_version") or "1.0"),
        decision_id=str(data.get("decision_id") or getattr(key_decision, "decision_id", "")),
        player_id=_as_int(data.get("player_id")) or getattr(player_view, "player_id", None),
        role=role,
        action_type=action_type,
        day=_as_int(data.get("day")) or getattr(key_decision, "day", None) or getattr(decision_input, "day", None),
        phase=str(data.get("phase") or getattr(key_decision, "phase", "") or getattr(decision_input, "phase", "")),
        score=score,
        quality=quality,
        reason=str(data.get("reason") or ""),
        evidence=evidence,
        evidence_refs=evidence_refs,
        counterfactual=str(data.get("counterfactual") or ""),
        mistake_tags=_list_str(data.get("mistake_tags")),
        rubric_hits=_list_str(data.get("rubric_hits")),
        rubric_misses=_list_str(data.get("rubric_misses")),
        related_skills=related_skills,
        recommended_skill_files=recommended_skill_files,
        suggestion=str(data.get("suggestion") or ""),
        confidence=_clamp_float(data.get("confidence"), default=0.0, minimum=0.0, maximum=1.0),
    )


def summarize_judgments(judgments: list[DecisionJudgment]) -> dict[str, Any]:
    """Build a deterministic summary over parsed judgments."""
    if not judgments:
        return {
            "judged": 0,
            "average_score": None,
            "quality_counts": {},
            "top_mistake_tags": [],
            "top_rubric_misses": [],
            "related_skills": [],
            "recommended_skill_files": [],
            "lowest_decisions": [],
        }
    average = sum(item.score for item in judgments) / len(judgments)
    quality_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    miss_counts: dict[str, int] = {}
    skill_counts: dict[str, int] = {}
    recommended_skill_counts: dict[str, int] = {}
    for item in judgments:
        quality_counts[item.quality] = quality_counts.get(item.quality, 0) + 1
        for tag in item.mistake_tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        for miss in item.rubric_misses:
            miss_counts[miss] = miss_counts.get(miss, 0) + 1
        for skill in item.related_skills:
            skill_counts[skill] = skill_counts.get(skill, 0) + 1
        for skill_file in item.recommended_skill_files:
            recommended_skill_counts[skill_file] = recommended_skill_counts.get(skill_file, 0) + 1
    lowest = sorted(judgments, key=lambda item: (item.score, item.decision_id))[:3]
    return {
        "judged": len(judgments),
        "average_score": round(average, 2),
        "quality_counts": quality_counts,
        "top_mistake_tags": [
            {"tag": tag, "count": count}
            for tag, count in sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
        ],
        "top_rubric_misses": [
            {"miss": miss, "count": count}
            for miss, count in sorted(miss_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
        ],
        "related_skills": [
            {"skill": skill, "count": count}
            for skill, count in sorted(skill_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
        ],
        "recommended_skill_files": [
            {"path": path, "count": count}
            for path, count in sorted(recommended_skill_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
        ],
        "lowest_decisions": [
            {
                "decision_id": item.decision_id,
                "player_id": item.player_id,
                "role": item.role,
                "action_type": item.action_type,
                "score": round(item.score, 2),
                "reason": item.reason,
                "evidence": item.evidence[:3],
                "counterfactual": item.counterfactual,
                "rubric_misses": item.rubric_misses[:3],
                "related_skills": item.related_skills[:3],
                "recommended_skill_files": item.recommended_skill_files[:3],
                "suggestion": item.suggestion,
            }
            for item in lowest
        ],
    }


def _rubric_skill_files(role: str, action_type: str) -> list[str]:
    try:
        from app.lib.evidence import get_decision_rubric

        rubric = get_decision_rubric(role, action_type)
    except Exception:  # noqa: BLE001 - rubric fallback should not fail parsing
        return []
    return _list_str(rubric.get("recommended_skill_files") or rubric.get("related_skills"))


def attach_judgments_to_evidence_summary(
    evidence_summary: dict[str, Any],
    judge_report: dict[str, Any],
) -> dict[str, Any]:
    """Attach parsed judgments to an existing compact evidence summary."""
    summary = dict(evidence_summary or {})
    judgments = [
        item for item in judge_report.get("judgments", [])
        if isinstance(item, dict) and item.get("decision_id")
    ]
    by_id = {str(item["decision_id"]): item for item in judgments}
    for key in ("key_decisions", "role_key_decisions"):
        rows = []
        for item in summary.get(key, []) or []:
            if not isinstance(item, dict):
                rows.append(item)
                continue
            row = dict(item)
            judgment = by_id.get(str(row.get("decision_id")))
            if judgment:
                row["judge"] = judgment
            rows.append(row)
        if key in summary:
            summary[key] = rows
    summary["decision_judge"] = {
        "status": judge_report.get("status"),
        "reason": judge_report.get("reason"),
        "summary": judge_report.get("summary", {}),
        "metrics": judge_report.get("metrics", {}),
        "warnings": judge_report.get("warnings", []),
        "degraded_reasons": judge_report.get("degraded_reasons", []),
        "diagnostics": judge_report.get("diagnostics", []),
    }
    return summary


def _chain_judge_call(model: Any) -> JudgeCall:
    async def _call(messages: list[dict[str, str]]) -> str:
        from app.services.chain import run_decision_judge_chain

        return await run_decision_judge_chain(model, messages=messages)

    return _call


def _skipped_report(
    *,
    game_id: str,
    winner: str,
    reason: str,
    total_decisions: int,
) -> dict[str, Any]:
    return GameJudgmentReport(
        status="skipped",
        reason=reason,
        game_id=str(game_id or ""),
        winner=winner,
        selection={
            "method": "app.lib.evidence.select_key_decisions",
            "total_decisions": total_decisions,
            "key_decisions": 0,
            "selected_for_judge": 0,
        },
        summary={"reason": reason},
        metrics={
            "total_decisions": total_decisions,
            "key_decisions": 0,
            "judged": 0,
            "failed": 0,
        },
    ).to_dict()


def _compact_decision_input(item: Any) -> dict[str, Any]:
    view = getattr(item, "player_view", None)
    reasoning = getattr(item, "agent_reasoning", None)
    result = getattr(item, "decision_result", None)
    god_view = getattr(item, "god_view_after_game", None)
    return {
        "decision_id": getattr(item, "decision_id", ""),
        "decision_index": getattr(item, "decision_index", None),
        "day": getattr(item, "day", None),
        "phase": getattr(item, "phase", ""),
        "action_type": getattr(item, "action_type", ""),
        "player_view": {
            "player_id": getattr(view, "player_id", None),
            "role": getattr(view, "role", ""),
            "candidates": _list_value(getattr(view, "candidates", []))[:12],
            "observation_summary": _trim_value(_dict_value(getattr(view, "observation_summary", None)), 600),
            "belief_context": _trim_value(_dict_value(getattr(view, "belief_context", {})), 450),
            "selected_skills": _list_str(getattr(view, "selected_skills", []))[:6],
        },
        "agent_reasoning": {
            "private_reasoning": _trim_text(getattr(reasoning, "private_reasoning", ""), 420),
            "alternatives": _trim_value(_list_value(getattr(reasoning, "alternatives", []))[:5], 500),
            "rejected_reasons": _list_str(getattr(reasoning, "rejected_reasons", []))[:5],
            "confidence": getattr(reasoning, "confidence", None),
            "memory_summary": _trim_value(_list_value(getattr(reasoning, "memory_summary", []))[:3], 450),
        },
        "decision_result": {
            "selected_target": getattr(result, "selected_target", None),
            "selected_choice": getattr(result, "selected_choice", None),
            "public_text": _trim_text(getattr(result, "public_text", ""), 260),
            "source": getattr(result, "source", ""),
            "errors": _list_value(getattr(result, "errors", []))[:5],
            "policy_adjustments": _list_value(getattr(result, "policy_adjustments", []))[:5],
        },
        "god_view_after_game": {
            "player_roles": _dict_value(getattr(god_view, "player_roles", {})),
            "winner": getattr(god_view, "winner", ""),
            "target_true_role": getattr(god_view, "target_true_role", None),
        },
    }


def _compact_key_decision(key: Any) -> dict[str, Any]:
    return {
        "decision_id": getattr(key, "decision_id", ""),
        "day": getattr(key, "day", None),
        "phase": getattr(key, "phase", ""),
        "action_type": getattr(key, "action_type", ""),
        "player_id": getattr(key, "player_id", None),
        "role": getattr(key, "role", ""),
        "key_reason": getattr(key, "key_reason", ""),
        "impact_level": getattr(key, "impact_level", ""),
        "turning_point_id": getattr(key, "turning_point_id", None),
        "selection_notes": _list_str(getattr(key, "selection_notes", []))[:4],
    }


def _compact_review(review: Any, *, player_id: Any = None) -> dict[str, Any]:
    data = _dict_value(review)
    if not data:
        return {}
    player_key = str(player_id) if player_id is not None else ""
    agent_scores = _dict_value(data.get("agent_scores"))
    return {
        "winner": data.get("winner"),
        "total_days": data.get("total_days"),
        "key_turning_points": _list_str(data.get("key_turning_points"))[:4],
        "global_mistakes": _list_str(data.get("global_mistakes"))[:4],
        "recommendations": _list_str(data.get("recommendations"))[:4],
        "player_score": agent_scores.get(player_key, {}) if player_key else {},
    }


def _compact_events(
    events: list[dict[str, Any]],
    *,
    day: Any = None,
    phase: str = "",
    limit: int = 10,
) -> list[dict[str, Any]]:
    if not events:
        return []
    day_int = _as_int(day)
    phase_text = str(phase or "").lower()
    matching: list[dict[str, Any]] = []
    fallback: list[dict[str, Any]] = []
    for event in events:
        compact = {
            "day": event.get("day"),
            "phase": event.get("phase"),
            "event_type": event.get("event_type") or event.get("type"),
            "actor": event.get("actor"),
            "target": event.get("target"),
            "message": _trim_text(event.get("message") or event.get("content") or "", 120),
            "payload": _trim_value(_dict_value(event.get("payload")), 260),
        }
        fallback.append(compact)
        event_day = _as_int(event.get("day"))
        event_phase = str(event.get("phase") or "").lower()
        same_day = day_int is None or event_day == day_int
        same_phase = not phase_text or phase_text in event_phase or event_phase in phase_text
        if same_day and same_phase:
            matching.append(compact)
    rows = matching or fallback
    if len(rows) <= limit:
        return rows
    half = max(1, limit // 2)
    return rows[:half] + rows[-(limit - half):]


def _normalize_role_map(raw: Any) -> dict[str, str]:
    data = _dict_value(raw)
    return {str(key): _enum_value(value) for key, value in data.items()}


def _normalize_quality(value: Any, *, score: float) -> str:
    text = str(value or "").strip().lower()
    if text in {"good", "ok", "bad", "unknown"}:
        return text
    if score >= 7.5:
        return "good"
    if score >= 5.0:
        return "ok"
    return "bad"


def _clamp_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _as_positive_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _enum_value(value: Any) -> str:
    if hasattr(value, "value"):
        return str(value.value)
    return str(value or "")


def _list_str(value: Any) -> list[str]:
    return [str(item) for item in _list_value(value) if str(item)]


def _unique_str(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _judge_diagnostic(
    *,
    reason: str,
    decision_id: Any = "",
    message: str = "",
    exc: BaseException | None = None,
) -> dict[str, Any]:
    diagnostic = {
        "reason": str(reason or "unknown"),
        "decision_id": str(decision_id or ""),
        "message": str(message or ""),
    }
    if exc is not None:
        diagnostic["exception_type"] = type(exc).__name__
        diagnostic["exception_message"] = str(exc)
    return diagnostic


def _dict_value(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        data = value.to_dict()
        return dict(data) if isinstance(data, dict) else {}
    return {}


def _list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _trim_text(value: Any, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + f"...[truncated {len(text) - limit} chars]"


def _trim_value(value: Any, limit: int) -> Any:
    text = compact_json(value)
    if len(text) <= limit:
        return value
    return {"truncated": True, "preview": _trim_text(text, limit)}
