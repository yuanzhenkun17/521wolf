"""Offline export of high-value samples for Langfuse human annotation.

The exporter is intentionally local-first: it reads JSON payloads produced by
benchmark/eval/review/game flows and writes deterministic queue items to a
JSON file.  A real Langfuse write path can be attached later through the
fail-open adapter hook, but the default path never constructs a network client.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from app.util.redaction import redact, redaction_summary


SCHEMA_VERSION = "langfuse_annotation_queue_export_v1"
DEFAULT_LOW_JUDGE_SCORE = 5.0
DEFAULT_UI_BASE_URL = "/"
DEFAULT_MAX_EVIDENCE_ROWS = 5

PROBLEM_STATUSES = {"failed", "failure", "error", "errored", "timeout", "timed_out", "aborted"}
SENSITIVE_KEY_PARTS = (
    "private_reasoning",
    "hidden_reasoning",
    "chain_of_thought",
    "scratchpad",
    "prompt",
    "raw_messages",
    "messages",
    "raw_output",
    "completion",
)

REASON_WEIGHTS = {
    "llm_error": 100,
    "decision_judge_low_score": 90,
    "fallback": 80,
    "promotion_gate_boundary": 76,
    "release_gate_review_required": 74,
    "leaderboard_gate_failed": 70,
    "problem_game": 68,
    "policy_adjusted": 62,
    "decision_judge_degraded": 58,
}

CONTEXT_KEYS = (
    "batch_id",
    "result_batch_id",
    "source_run_id",
    "run_id",
    "report_id",
    "benchmark_id",
    "benchmark_version",
    "evaluation_set_id",
    "seed_set_id",
    "target_type",
    "target_role",
    "target_version_id",
    "model_id",
    "model_config_hash",
    "langfuse_dataset_name",
    "langfuse_dataset_item_id",
    "langfuse_experiment_name",
    "langfuse_run_name",
)

METADATA_KEYS = (
    "game_id",
    "batch_id",
    "result_batch_id",
    "seed",
    "trace_id",
    "trace_url",
    "experiment_url",
    "ui_deep_link",
    "source_run_id",
    "run_id",
    "report_id",
    "benchmark_id",
    "benchmark_version",
    "evaluation_set_id",
    "seed_set_id",
    "target_type",
    "target_role",
    "target_version_id",
    "model_id",
    "model_config_hash",
    "langfuse_dataset_name",
    "langfuse_dataset_item_id",
    "langfuse_experiment_name",
    "langfuse_run_name",
    "langfuse_dataset_run_id",
    "langfuse_dataset_run_item_id",
)


@dataclass
class Candidate:
    """Internal candidate before final queue item serialization."""

    key: str
    scope: str
    source_type: str
    reason_codes: set[str]
    metadata: dict[str, Any]
    summary: dict[str, Any]
    evidence: dict[str, Any]
    priority_score: int = 0
    decision_ids: set[str] = field(default_factory=set)


def build_annotation_queue(
    payloads: Iterable[Any],
    *,
    ui_base_url: str = DEFAULT_UI_BASE_URL,
    low_judge_score: float = DEFAULT_LOW_JUDGE_SCORE,
    max_items: int | None = None,
) -> dict[str, Any]:
    """Build a deterministic, privacy-bounded annotation queue export."""

    candidates: dict[str, Candidate] = {}
    for payload_index, payload in enumerate(payloads):
        root_context = _payload_context(_as_mapping(payload))
        for candidate in _extract_candidates(
            payload,
            context=root_context,
            ui_base_url=ui_base_url,
            low_judge_score=low_judge_score,
            path=f"payload[{payload_index}]",
        ):
            _merge_candidate(candidates, candidate)

    items = [_candidate_to_queue_item(candidate) for candidate in candidates.values()]
    items.sort(
        key=lambda item: (
            -int(item["priority_score"]),
            item["metadata"].get("batch_id") or "",
            item["metadata"].get("result_batch_id") or "",
            item["metadata"].get("game_id") or "",
            item["id"],
        )
    )
    if max_items is not None:
        items = items[: max(0, int(max_items))]

    return {
        "schema_version": SCHEMA_VERSION,
        "dry_run": True,
        "item_count": len(items),
        "items": items,
        "langfuse": {
            "write_enabled": False,
            "adapter": "fail_open_placeholder",
            "note": "Default export writes local JSON only. Attach an adapter later to enqueue in Langfuse.",
        },
    }


def export_annotation_queue(
    input_paths: Iterable[str | Path],
    *,
    output_path: str | Path | None = None,
    ui_base_url: str = DEFAULT_UI_BASE_URL,
    low_judge_score: float = DEFAULT_LOW_JUDGE_SCORE,
    max_items: int | None = None,
    apply: bool = False,
    adapter: Any | None = None,
) -> dict[str, Any]:
    """Load JSON inputs, build the queue, optionally write it to disk."""

    payloads = [load_json(path) for path in input_paths]
    report = build_annotation_queue(
        payloads,
        ui_base_url=ui_base_url,
        low_judge_score=low_judge_score,
        max_items=max_items,
    )

    if apply:
        report["langfuse"] = _write_langfuse_fail_open(report["items"], adapter=adapter)

    if output_path is not None:
        Path(output_path).write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return report


def load_json(path: str | Path) -> Any:
    """Load one JSON payload from disk."""

    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _extract_candidates(
    value: Any,
    *,
    context: dict[str, Any],
    ui_base_url: str,
    low_judge_score: float,
    path: str,
) -> list[Candidate]:
    if isinstance(value, list):
        candidates: list[Candidate] = []
        for index, item in enumerate(value):
            candidates.extend(
                _extract_candidates(
                    item,
                    context=context,
                    ui_base_url=ui_base_url,
                    low_judge_score=low_judge_score,
                    path=f"{path}[{index}]",
                )
            )
        return candidates

    data = _as_mapping(value)
    if not data:
        return []

    payload_context = _payload_context(data)
    merged_context = {**context, **payload_context}
    if context.get("batch_id") and payload_context.get("batch_id") and (
        payload_context.get("result_batch_id")
        or data.get("games") is not None
        or data.get("score_summary") is not None
        or data.get("leaderboard_gate") is not None
    ):
        result_batch_id = payload_context.get("result_batch_id") or payload_context.get("batch_id")
        merged_context["batch_id"] = context["batch_id"]
        if result_batch_id:
            merged_context["result_batch_id"] = result_batch_id
    candidates = _candidates_from_mapping(
        data,
        context=merged_context,
        ui_base_url=ui_base_url,
        low_judge_score=low_judge_score,
        path=path,
    )

    for key in ("results", "games", "problem_games", "affected_games", "rows", "items"):
        child_value = data.get(key)
        if isinstance(child_value, list):
            child_context = _context_for_child(data, merged_context, key)
            for index, item in enumerate(child_value):
                candidates.extend(
                    _extract_candidates(
                        item,
                        context=child_context,
                        ui_base_url=ui_base_url,
                        low_judge_score=low_judge_score,
                        path=f"{path}.{key}[{index}]",
                    )
                )

    for key in ("result", "review", "battle_result", "gate_report", "promotion_gate", "release_gate"):
        child_value = data.get(key)
        if isinstance(child_value, Mapping):
            candidates.extend(
                _extract_candidates(
                    child_value,
                    context=_context_for_child(data, merged_context, key),
                    ui_base_url=ui_base_url,
                    low_judge_score=low_judge_score,
                    path=f"{path}.{key}",
                )
            )

    return candidates


def _candidates_from_mapping(
    data: dict[str, Any],
    *,
    context: dict[str, Any],
    ui_base_url: str,
    low_judge_score: float,
    path: str,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    if _looks_like_game(data):
        candidates.extend(
            _game_candidates(
                data,
                context=context,
                ui_base_url=ui_base_url,
                low_judge_score=low_judge_score,
                path=path,
            )
        )

    batch_candidate = _batch_quality_candidate(
        data,
        context=context,
        ui_base_url=ui_base_url,
        low_judge_score=low_judge_score,
        path=path,
    )
    if batch_candidate is not None:
        candidates.append(batch_candidate)

    gate_candidate = _gate_candidate(data, context=context, ui_base_url=ui_base_url, path=path)
    if gate_candidate is not None:
        candidates.append(gate_candidate)

    return candidates


def _game_candidates(
    game: dict[str, Any],
    *,
    context: dict[str, Any],
    ui_base_url: str,
    low_judge_score: float,
    path: str,
) -> list[Candidate]:
    reason_codes: set[str] = set()
    score_boost = 0
    diagnostics = _list_of_mappings(game.get("diagnostics"))
    decisions = _list_of_mappings(game.get("decisions"))

    diagnostic_kinds = {_normalized_text(item.get("kind") or item.get("code") or item.get("type")) for item in diagnostics}
    if any("llm_error" in kind or "model_error" in kind for kind in diagnostic_kinds):
        reason_codes.add("llm_error")
    if _positive_count_or_rate(game, "fallback_count", "fallback_rate") or _decisions_have_fallback(decisions):
        reason_codes.add("fallback")
    if _positive_count_or_rate(game, "policy_adjusted_count", "policy_adjusted_rate") or _decisions_have_policy_adjustment(decisions):
        reason_codes.add("policy_adjusted")
    if _is_problem_game(game, diagnostics):
        reason_codes.add("problem_game")

    low_judge_decisions = _low_judge_decisions(game, low_judge_score=low_judge_score)
    if low_judge_decisions:
        reason_codes.add("decision_judge_low_score")
        lowest = min(_safe_float(item.get("score"), low_judge_score) for item in low_judge_decisions)
        score_boost += max(0, int(round((low_judge_score - lowest) * 5)))

    if not reason_codes:
        return []

    metadata = _metadata(data=game, context=context, ui_base_url=ui_base_url)
    metadata["source_path"] = path
    decision_ids = {
        str(item.get("decision_id"))
        for item in low_judge_decisions
        if item.get("decision_id") not in (None, "")
    }
    summary = _compact_game_summary(game, low_judge_decisions=low_judge_decisions)
    evidence = {
        "diagnostics": _sanitize(diagnostics[:DEFAULT_MAX_EVIDENCE_ROWS]),
        "decisions": _sanitize(_compact_decisions(decisions)),
        "low_judge_decisions": _sanitize(low_judge_decisions[:DEFAULT_MAX_EVIDENCE_ROWS]),
        "errors": _sanitize(_list_value(game.get("errors"))[:DEFAULT_MAX_EVIDENCE_ROWS]),
        "error": _sanitize(game.get("error")),
    }
    candidate = Candidate(
        key=_candidate_key("game", metadata, reason_codes),
        scope="game",
        source_type="game",
        reason_codes=reason_codes,
        metadata=metadata,
        summary=summary,
        evidence=evidence,
        priority_score=_priority(reason_codes) + score_boost,
        decision_ids=decision_ids,
    )
    return [candidate]


def _batch_quality_candidate(
    data: dict[str, Any],
    *,
    context: dict[str, Any],
    ui_base_url: str,
    low_judge_score: float,
    path: str,
) -> Candidate | None:
    reason_codes: set[str] = set()
    evidence: dict[str, Any] = {}

    leaderboard_gate = _as_mapping(data.get("leaderboard_gate"))
    if leaderboard_gate and leaderboard_gate.get("accepted") is False:
        reason_codes.add("leaderboard_gate_failed")
        evidence["leaderboard_gate"] = leaderboard_gate
    if data.get("rankable") is False:
        reason_codes.add("leaderboard_gate_failed")
        evidence["rankable_reason"] = data.get("rankable_reason")

    aggregate = _decision_judge_aggregate(data)
    aggregate_score = _safe_float(
        aggregate.get("avg_score", aggregate.get("average_score")),
        default=None,
    )
    if aggregate_score is not None and aggregate_score < low_judge_score:
        reason_codes.add("decision_judge_low_score")
        evidence["decision_judge_aggregate"] = aggregate
    elif _normalized_text(aggregate.get("status")) in {"degraded", "failed"}:
        reason_codes.add("decision_judge_degraded")
        evidence["decision_judge_aggregate"] = aggregate

    if not reason_codes:
        return None

    metadata = _metadata(data=data, context=context, ui_base_url=ui_base_url)
    metadata["source_path"] = path
    return Candidate(
        key=_candidate_key("batch", metadata, reason_codes),
        scope="batch",
        source_type="batch_result",
        reason_codes=reason_codes,
        metadata=metadata,
        summary=_compact_batch_summary(data),
        evidence=_sanitize(evidence),
        priority_score=_priority(reason_codes),
    )


def _gate_candidate(
    data: dict[str, Any],
    *,
    context: dict[str, Any],
    ui_base_url: str,
    path: str,
) -> Candidate | None:
    gate = _gate_payload(data)
    if not gate:
        return None

    reason_codes: set[str] = set()
    decision = _normalized_text(gate.get("decision") or gate.get("recommendation") or data.get("release_decision"))
    promote_allowed = gate.get("promote_allowed", data.get("promote_allowed"))
    significant = _nested_bool(gate, "significance", "passed")
    review_reasons = _list_value(gate.get("review_reasons") or gate.get("reasons"))

    if decision in {"review", "review_required"}:
        reason_codes.add("promotion_gate_boundary")
    if decision == "review_required":
        reason_codes.add("release_gate_review_required")
    if promote_allowed is False and (significant is True or review_reasons):
        reason_codes.add("promotion_gate_boundary")

    if not reason_codes:
        return None

    metadata = _metadata(data=data, context=context, ui_base_url=ui_base_url)
    metadata["source_path"] = path
    return Candidate(
        key=_candidate_key("gate", metadata, reason_codes),
        scope="gate",
        source_type="promotion_gate",
        reason_codes=reason_codes,
        metadata=metadata,
        summary={
            "decision": decision,
            "promote_allowed": promote_allowed,
            "review_reasons": _sanitize(review_reasons[:DEFAULT_MAX_EVIDENCE_ROWS]),
            "gate_report_id": data.get("gate_report_id") or gate.get("gate_report_id"),
        },
        evidence=_sanitize(
            {
                "gate": gate,
                "proposal_attribution": data.get("proposal_attribution") or data.get("proposal_attribution_report"),
                "trust_bundle_completeness": data.get("trust_bundle_completeness"),
            }
        ),
        priority_score=_priority(reason_codes),
    )


def _candidate_to_queue_item(candidate: Candidate) -> dict[str, Any]:
    reason_codes = sorted(candidate.reason_codes)
    metadata = {key: candidate.metadata.get(key) for key in METADATA_KEYS if candidate.metadata.get(key) not in (None, "")}
    metadata.update(
        {
            "source_type": candidate.source_type,
            "annotation_scope": candidate.scope,
            "source_path": candidate.metadata.get("source_path"),
            "reason_codes": reason_codes,
        }
    )
    if candidate.decision_ids:
        metadata["decision_ids"] = sorted(candidate.decision_ids)

    item_id = _stable_item_id(candidate)
    return {
        "id": item_id,
        "queue_item_id": item_id,
        "priority_score": int(candidate.priority_score),
        "priority_label": _priority_label(candidate.priority_score),
        "reason_codes": reason_codes,
        "annotation_task": {
            "type": "human_annotation",
            "rubric": "werewolf_decision_quality_v1",
            "instructions": "Review the compact evidence and score whether the sample needs skill/policy follow-up.",
        },
        "input": {
            "summary": _sanitize(candidate.summary),
            "evidence": _sanitize(candidate.evidence),
        },
        "metadata": _sanitize(metadata),
        "privacy": {
            "raw_prompt_exported": False,
            "private_reasoning_exported": False,
            "payload_policy": "public_redacted_compact_evidence",
        },
    }


def _write_langfuse_fail_open(items: list[dict[str, Any]], *, adapter: Any | None) -> dict[str, Any]:
    """Best-effort adapter placeholder for a future Langfuse annotation queue write."""

    if adapter is None:
        return {
            "write_enabled": False,
            "applied_count": 0,
            "error": "No Langfuse annotation adapter configured; local JSON export completed.",
            "todo": "Wire this to Langfuse Human Annotation when the project queue API is selected.",
        }
    try:
        result = adapter(items)
        if isinstance(result, Mapping):
            return {"write_enabled": True, **dict(result)}
        return {"write_enabled": True, "applied_count": len(items), "result": str(result)}
    except Exception as exc:  # noqa: BLE001 - annotation export must remain fail-open
        return {
            "write_enabled": True,
            "applied_count": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _merge_candidate(candidates: dict[str, Candidate], candidate: Candidate) -> None:
    existing = candidates.get(candidate.key)
    if existing is None:
        candidates[candidate.key] = candidate
        return

    existing.reason_codes.update(candidate.reason_codes)
    existing.decision_ids.update(candidate.decision_ids)
    existing.priority_score = max(existing.priority_score, candidate.priority_score)
    for key, value in candidate.metadata.items():
        if value in (None, ""):
            continue
        if existing.metadata.get(key) in (None, ""):
            existing.metadata[key] = value
    existing.summary.update({key: value for key, value in candidate.summary.items() if value not in (None, "", [], {})})
    for key, value in candidate.evidence.items():
        if value in (None, "", [], {}):
            continue
        if key not in existing.evidence or existing.evidence[key] in (None, "", [], {}):
            existing.evidence[key] = value
        elif isinstance(existing.evidence[key], list) and isinstance(value, list):
            existing.evidence[key] = _dedupe_list(existing.evidence[key] + value)[:DEFAULT_MAX_EVIDENCE_ROWS]


def _metadata(*, data: dict[str, Any], context: dict[str, Any], ui_base_url: str) -> dict[str, Any]:
    payload_context = _payload_context(data)
    combined = {**context, **payload_context}
    if context.get("batch_id") and payload_context.get("batch_id") and (
        payload_context.get("result_batch_id")
        or data.get("games") is not None
        or data.get("score_summary") is not None
        or data.get("leaderboard_gate") is not None
    ):
        result_batch_id = payload_context.get("result_batch_id") or payload_context.get("batch_id")
        combined["batch_id"] = context["batch_id"]
        if result_batch_id:
            combined["result_batch_id"] = result_batch_id
    game_id = _first_text(data.get("game_id"), data.get("history_game_id"), combined.get("game_id"), data.get("id"))
    seed = _first_present(data.get("seed"), combined.get("seed"))
    result = {
        **combined,
        "game_id": game_id,
        "seed": seed,
        "trace_id": _first_text(
            data.get("langfuse_trace_id"),
            data.get("trace_id"),
            _nested_text(data, "langfuse", "trace_id"),
        ),
        "trace_url": _first_text(
            data.get("langfuse_trace_url"),
            data.get("trace_url"),
            _nested_text(data, "langfuse", "trace_url"),
        ),
        "experiment_url": _first_text(
            data.get("langfuse_experiment_url"),
            data.get("experiment_url"),
            _nested_text(data, "langfuse", "experiment_url"),
            _nested_text(data, "langfuse", "dataset_run_url"),
        ),
        "langfuse_dataset_run_id": _first_text(
            data.get("langfuse_dataset_run_id"),
            _nested_text(data, "langfuse", "dataset_run_id"),
        ),
        "langfuse_dataset_run_item_id": _first_text(
            data.get("langfuse_dataset_run_item_id"),
            _nested_text(data, "langfuse", "dataset_run_item_id"),
        ),
    }
    if not result.get("result_batch_id"):
        result["result_batch_id"] = _first_text(data.get("batch_id"), combined.get("result_batch_id"))
    result["ui_deep_link"] = _ui_deep_link(result, ui_base_url=ui_base_url)
    return {key: value for key, value in result.items() if value not in (None, "")}


def _payload_context(data: Mapping[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for key in CONTEXT_KEYS:
        value = data.get(key)
        if value not in (None, ""):
            context[key] = value
    benchmark = _as_mapping(data.get("benchmark"))
    for key in ("benchmark_id", "benchmark_version", "evaluation_set_id", "seed_set_id", "target_type"):
        benchmark_key = "id" if key == "benchmark_id" else "version" if key == "benchmark_version" else key
        if key not in context and benchmark.get(benchmark_key) not in (None, ""):
            context[key] = benchmark[benchmark_key]
    config = _as_mapping(data.get("config") or data.get("batch_config"))
    for key in CONTEXT_KEYS:
        if key not in context and config.get(key) not in (None, ""):
            context[key] = config[key]
    return context


def _context_for_child(data: dict[str, Any], context: dict[str, Any], key: str) -> dict[str, Any]:
    child_context = dict(context)
    payload_context = _payload_context(data)
    child_context.update(payload_context)
    if context.get("batch_id") and payload_context.get("batch_id") and (
        payload_context.get("result_batch_id")
        or data.get("games") is not None
        or data.get("score_summary") is not None
        or data.get("leaderboard_gate") is not None
    ):
        result_batch_id = payload_context.get("result_batch_id") or payload_context.get("batch_id")
        child_context["batch_id"] = context["batch_id"]
        if result_batch_id:
            child_context["result_batch_id"] = result_batch_id
    if key == "results":
        child_context.setdefault("batch_id", data.get("batch_id"))
    if key in {"games", "problem_games", "affected_games"}:
        child_context.setdefault("result_batch_id", data.get("result_batch_id") or data.get("batch_id"))
    return {k: v for k, v in child_context.items() if v not in (None, "")}


def _looks_like_game(data: dict[str, Any]) -> bool:
    if data.get("game_id") or data.get("history_game_id"):
        return True
    game_signals = {"seed", "winner", "status", "decisions", "events", "game_events", "diagnostics", "fallback_count"}
    return bool(game_signals.intersection(data)) and not _gate_payload(data)


def _is_problem_game(game: dict[str, Any], diagnostics: list[dict[str, Any]]) -> bool:
    status = _normalized_text(game.get("status") or game.get("terminal_status"))
    if status in PROBLEM_STATUSES:
        return True
    if game.get("error") not in (None, "") or _list_value(game.get("errors")):
        return True
    if _safe_int(game.get("diagnostic_count"), 0) > 0 or _safe_int(game.get("error_count"), 0) > 0:
        return True
    for diagnostic in diagnostics:
        level = _normalized_text(diagnostic.get("level") or diagnostic.get("severity"))
        kind = _normalized_text(diagnostic.get("kind") or diagnostic.get("code") or diagnostic.get("type"))
        if level in {"warning", "error", "critical", "fatal"}:
            return True
        if kind in {"llm_error", "game_failure", "game_error", "timeout"}:
            return True
    return False


def _decision_judge_aggregate(data: dict[str, Any]) -> dict[str, Any]:
    summary = _as_mapping(data.get("score_summary"))
    aggregate = _as_mapping(data.get("decision_judge_aggregate"))
    if not aggregate:
        aggregate = _as_mapping(summary.get("decision_judge_aggregate"))
    decision_judge = _as_mapping(data.get("decision_judge"))
    if not aggregate and decision_judge:
        aggregate = _as_mapping(decision_judge.get("summary"))
        aggregate.update({k: v for k, v in decision_judge.items() if k in {"status", "reason", "metrics"}})
    return aggregate


def _low_judge_decisions(game: dict[str, Any], *, low_judge_score: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for judgment in _iter_judgments(game):
        score = _safe_float(judgment.get("score"), default=None)
        if score is not None and score < low_judge_score:
            rows.append(
                {
                    "decision_id": judgment.get("decision_id"),
                    "score": score,
                    "quality": judgment.get("quality"),
                    "reason": judgment.get("reason"),
                    "mistake_tags": _list_value(judgment.get("mistake_tags")),
                    "rubric_misses": _list_value(judgment.get("rubric_misses")),
                    "suggestion": judgment.get("suggestion"),
                }
            )
    aggregate = _decision_judge_aggregate(game)
    aggregate_score = _safe_float(aggregate.get("avg_score", aggregate.get("average_score")), default=None)
    if not rows and aggregate_score is not None and aggregate_score < low_judge_score:
        rows.append(
            {
                "decision_id": "",
                "score": aggregate_score,
                "quality": "aggregate_low",
                "reason": aggregate.get("reason") or aggregate.get("status"),
            }
        )
    return rows


def _iter_judgments(data: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for judgment in _list_of_mappings(data.get("judgments")):
        yield judgment
    decision_judge = _as_mapping(data.get("decision_judge"))
    for judgment in _list_of_mappings(decision_judge.get("judgments")):
        yield judgment
    review = _as_mapping(data.get("review"))
    review_judge = _as_mapping(review.get("decision_judge"))
    for judgment in _list_of_mappings(review_judge.get("judgments")):
        yield judgment
    for decision in _list_of_mappings(data.get("decisions")):
        judge = _as_mapping(decision.get("judge") or decision.get("decision_judge"))
        if judge:
            if "decision_id" not in judge and decision.get("decision_id"):
                judge["decision_id"] = decision.get("decision_id")
            yield judge


def _gate_payload(data: dict[str, Any]) -> dict[str, Any]:
    for key in ("promotion_gate", "release_gate", "gate"):
        gate = _as_mapping(data.get(key))
        if gate:
            return gate
    if any(key in data for key in ("promote_allowed", "recommendation", "review_reasons", "release_decision")):
        return data
    return {}


def _compact_game_summary(game: dict[str, Any], *, low_judge_decisions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "game_id": game.get("game_id") or game.get("history_game_id"),
        "status": game.get("status"),
        "winner": game.get("winner"),
        "seed": game.get("seed"),
        "day_count": game.get("days") or game.get("total_days"),
        "event_count": _safe_int(game.get("event_count"), len(_list_value(game.get("events") or game.get("game_events")))),
        "decision_count": _safe_int(game.get("decision_count"), len(_list_value(game.get("decisions")))),
        "diagnostic_count": _safe_int(game.get("diagnostic_count"), len(_list_value(game.get("diagnostics")))),
        "fallback_count": _safe_int(game.get("fallback_count"), 0),
        "error_count": _safe_int(game.get("error_count"), len(_list_value(game.get("errors")))),
        "lowest_decision_judge_score": min(
            (_safe_float(item.get("score"), 0.0) for item in low_judge_decisions),
            default=None,
        ),
    }


def _compact_batch_summary(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "batch_id": data.get("batch_id"),
        "result_batch_id": data.get("result_batch_id") or data.get("batch_id"),
        "rankable": data.get("rankable"),
        "rankable_reason": data.get("rankable_reason"),
        "completed": data.get("completed"),
        "errored": data.get("errored"),
        "game_count": data.get("game_count"),
        "target_role": data.get("target_role") or _as_mapping(data.get("config")).get("target_role"),
        "leaderboard_gate": _as_mapping(data.get("leaderboard_gate")),
        "decision_judge_aggregate": _decision_judge_aggregate(data),
    }


def _compact_decisions(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for decision in decisions[:DEFAULT_MAX_EVIDENCE_ROWS]:
        result = _as_mapping(decision.get("decision_result"))
        rows.append(
            {
                "decision_id": decision.get("decision_id"),
                "day": decision.get("day"),
                "phase": decision.get("phase"),
                "player_id": decision.get("player_id"),
                "role": decision.get("role"),
                "action_type": decision.get("action_type"),
                "selected_target": _first_present(decision.get("selected_target"), result.get("selected_target")),
                "selected_choice": _first_present(decision.get("selected_choice"), result.get("selected_choice")),
                "public_text": _first_text(decision.get("public_text"), result.get("public_text")),
                "source": _first_text(decision.get("source"), result.get("source")),
                "errors": _list_value(decision.get("errors") or result.get("errors"))[:DEFAULT_MAX_EVIDENCE_ROWS],
                "policy_adjustments": _list_value(
                    decision.get("policy_adjustments") or result.get("policy_adjustments")
                )[:DEFAULT_MAX_EVIDENCE_ROWS],
                "judge": _sanitize(decision.get("judge") or decision.get("decision_judge")),
            }
        )
    return rows


def _priority(reason_codes: Iterable[str]) -> int:
    return min(250, sum(REASON_WEIGHTS.get(code, 40) for code in set(reason_codes)))


def _priority_label(score: int) -> str:
    if score >= 150:
        return "critical"
    if score >= 90:
        return "high"
    if score >= 65:
        return "medium"
    return "low"


def _stable_item_id(candidate: Candidate) -> str:
    digest = hashlib.sha256(candidate.key.encode("utf-8")).hexdigest()[:16]
    return f"annotation:{digest}"


def _candidate_key(scope: str, metadata: dict[str, Any], reason_codes: Iterable[str]) -> str:
    del reason_codes
    trace_id = metadata.get("trace_id")
    game_id = metadata.get("game_id")
    if scope == "game" and (trace_id or game_id):
        return f"game:{trace_id or game_id}"
    if scope == "gate":
        gate_id = _first_text(
            metadata.get("gate_report_id"),
            metadata.get("run_id"),
            metadata.get("batch_id"),
            metadata.get("result_batch_id"),
        )
        return f"gate:{gate_id or _metadata_fingerprint(metadata)}"
    batch_id = _first_text(metadata.get("result_batch_id"), metadata.get("batch_id"), metadata.get("run_id"))
    return f"{scope}:{batch_id or _metadata_fingerprint(metadata)}"


def _metadata_fingerprint(metadata: Mapping[str, Any]) -> str:
    material = json.dumps(_sanitize(dict(metadata)), ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def _ui_deep_link(metadata: Mapping[str, Any], *, ui_base_url: str) -> str:
    base = (ui_base_url or DEFAULT_UI_BASE_URL).rstrip("/") or "/"
    run_id = metadata.get("run_id")
    batch_id = metadata.get("batch_id") or metadata.get("source_run_id")
    if run_id and not batch_id and not metadata.get("result_batch_id"):
        return f"{base}/evolution-runs/{run_id}"
    game_id = metadata.get("game_id")
    if game_id and batch_id:
        return f"{base}/benchmark/batch/{batch_id}/games?{urlencode({'game_id': str(game_id)})}"
    if batch_id:
        return f"{base}/benchmark/batch/{batch_id}"
    if run_id:
        return f"{base}/evolution-runs/{run_id}"
    return base


def _sanitize(value: Any) -> Any:
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for raw_key, raw_item in value.items():
            key = str(raw_key)
            if _is_sensitive_key(key):
                output[key] = redaction_summary(raw_item)
            else:
                output[key] = _sanitize(raw_item)
        return redact(output, context="public")
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    return redact(value, context="public")


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower()
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _decisions_have_fallback(decisions: list[dict[str, Any]]) -> bool:
    for decision in decisions:
        source = _normalized_text(
            decision.get("source") or _as_mapping(decision.get("decision_result")).get("source")
        )
        if "fallback" in source or decision.get("fallback") is True:
            return True
        if _list_value(decision.get("errors") or _as_mapping(decision.get("decision_result")).get("errors")):
            return True
    return False


def _decisions_have_policy_adjustment(decisions: list[dict[str, Any]]) -> bool:
    for decision in decisions:
        if decision.get("policy_adjusted") is True:
            return True
        result = _as_mapping(decision.get("decision_result"))
        if _list_value(decision.get("policy_adjustments") or result.get("policy_adjustments")):
            return True
    return False


def _positive_count_or_rate(data: Mapping[str, Any], count_key: str, rate_key: str) -> bool:
    if _safe_float(data.get(count_key), 0.0) > 0:
        return True
    return _safe_float(data.get(rate_key), 0.0) > 0.0


def _dedupe_list(items: list[Any]) -> list[Any]:
    seen: set[str] = set()
    output: list[Any] = []
    for item in items:
        marker = json.dumps(_sanitize(item), ensure_ascii=False, sort_keys=True, default=str)
        if marker in seen:
            continue
        seen.add(marker)
        output.append(item)
    return output


def _nested_text(data: Mapping[str, Any], *keys: str) -> str:
    current: Any = data
    for key in keys:
        current = _as_mapping(current).get(key)
    return _first_text(current)


def _nested_bool(data: Mapping[str, Any], *keys: str) -> bool | None:
    current: Any = data
    for key in keys:
        current = _as_mapping(current).get(key)
    if isinstance(current, bool):
        return current
    if current in (None, ""):
        return None
    text = _normalized_text(current)
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    if hasattr(value, "dict"):
        dumped = value.dict()
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    return {}


def _list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _list_of_mappings(value: Any) -> list[dict[str, Any]]:
    return [_as_mapping(item) for item in _list_value(value) if _as_mapping(item)]


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return None


def _normalized_text(value: Any) -> str:
    return _first_text(value).strip().lower()


def _safe_float(value: Any, default: float | None = 0.0) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export a local Langfuse human annotation prep queue.")
    parser.add_argument("inputs", nargs="+", help="Input benchmark/eval/review/game JSON payload(s).")
    parser.add_argument("-o", "--output", help="Output queue JSON path. Prints to stdout when omitted.")
    parser.add_argument("--ui-base-url", default=DEFAULT_UI_BASE_URL, help="Base URL used for local UI deep links.")
    parser.add_argument("--low-judge-score", type=float, default=DEFAULT_LOW_JUDGE_SCORE)
    parser.add_argument("--max-items", type=int, default=None)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Invoke the fail-open adapter placeholder. Does not create a network client by default.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = export_annotation_queue(
        args.inputs,
        output_path=args.output,
        ui_base_url=args.ui_base_url,
        low_judge_score=args.low_judge_score,
        max_items=args.max_items,
        apply=bool(args.apply),
    )
    if args.output is None:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
