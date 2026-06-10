"""Benchmark report payload, export, and diagnostic helpers."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any

from app.lib.benchmark_reproducibility import build_benchmark_reproducibility_manifest
from app.util.time import beijing_now_iso
from ui.backend.services.benchmark_payload_utils import (
    dict_items as _dict_items,
    json_clone as _json_clone,
    sanitize_config_model_runtime,
    sanitize_model_runtime,
    sanitize_model_runtime_containers,
    text_items as _text_items,
)
from ui.backend.services.benchmark_report_games import (
    _benchmark_batch_langfuse_summary,
    _benchmark_game_is_problem as _benchmark_game_is_problem,
    _benchmark_game_matches_status_filter as _benchmark_game_matches_status_filter,
    _benchmark_game_status,
    _benchmark_game_summary,
    _benchmark_games_for_batch,
    _benchmark_result_batch_id,
    _benchmark_result_game_count,
    _benchmark_result_role,
    _benchmark_results,
)
from ui.backend.task_state import _match_filter


def _benchmark_diagnostic_entries(batch: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    batch_id = str(batch.get("batch_id") or "")
    for diagnostic in _dict_items(batch.get("diagnostics")):
        entries.append(_benchmark_diagnostic_entry(diagnostic, batch_id=batch_id, origin="batch"))
    if batch.get("error"):
        entries.append(
            _benchmark_diagnostic_entry(
                {
                    "kind": "benchmark_error",
                    "stage": batch.get("current_stage") or batch.get("status"),
                    "level": "error",
                    "message": str(batch.get("error")),
                },
                batch_id=batch_id,
                origin="batch",
            )
        )

    for result in _benchmark_results(batch):
        result_batch_id = _benchmark_result_batch_id(result)
        target_role = _benchmark_result_role(result)
        for diagnostic in _dict_items(result.get("diagnostics")):
            entries.append(
                _benchmark_diagnostic_entry(
                    diagnostic,
                    batch_id=batch_id,
                    result_batch_id=result_batch_id,
                    target_role=target_role,
                    origin="result",
                )
            )
        for warning in _text_items(result.get("warnings")):
            entries.append(
                _benchmark_diagnostic_entry(
                    {
                        "kind": "result_warning",
                        "stage": "result.warning",
                        "level": "warning",
                        "message": warning,
                    },
                    batch_id=batch_id,
                    result_batch_id=result_batch_id,
                    target_role=target_role,
                    origin="result",
                )
            )
        for error in _text_items(result.get("errors")):
            entries.append(
                _benchmark_diagnostic_entry(
                    {
                        "kind": "result_error",
                        "stage": "result.error",
                        "level": "error",
                        "message": error,
                    },
                    batch_id=batch_id,
                    result_batch_id=result_batch_id,
                    target_role=target_role,
                    origin="result",
                )
            )
        entries.extend(_benchmark_quality_diagnostics(batch_id, result_batch_id, target_role, result))
        entries.extend(_benchmark_game_diagnostics(batch_id, result_batch_id, target_role, result))
    return _dedupe_benchmark_diagnostics(entries)


def _benchmark_quality_diagnostics(
    batch_id: str,
    result_batch_id: str,
    target_role: str | None,
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if result.get("rankable") is False:
        entries.append(
            _benchmark_diagnostic_entry(
                {
                    "kind": "rankable_failed",
                    "stage": "leaderboard.rankable",
                    "level": "warning",
                    "message": str(result.get("rankable_reason") or "result is not rankable"),
                },
                batch_id=batch_id,
                result_batch_id=result_batch_id,
                target_role=target_role,
                origin="result",
            )
        )
    fairness = result.get("fairness") if isinstance(result.get("fairness"), dict) else {}
    if fairness and fairness.get("is_fair") is False:
        entries.append(
            _benchmark_diagnostic_entry(
                {
                    "kind": "fairness_failed",
                    "stage": "fairness.validate",
                    "level": "warning",
                    "message": str(fairness.get("reason") or "fairness check failed"),
                },
                batch_id=batch_id,
                result_batch_id=result_batch_id,
                target_role=target_role,
                origin="result",
            )
        )
    gate = result.get("leaderboard_gate") if isinstance(result.get("leaderboard_gate"), dict) else {}
    if gate and gate.get("accepted") is False:
        entries.append(
            _benchmark_diagnostic_entry(
                {
                    "kind": "leaderboard_gate_failed",
                    "stage": "leaderboard.gate",
                    "level": "warning",
                    "message": str(gate.get("reason") or result.get("leaderboard_skipped_reason") or "leaderboard gate failed"),
                    "metrics": gate.get("metrics") if isinstance(gate.get("metrics"), dict) else {},
                },
                batch_id=batch_id,
                result_batch_id=result_batch_id,
                target_role=target_role,
                origin="result",
            )
        )
    summary = result.get("score_summary") if isinstance(result.get("score_summary"), dict) else {}
    judge = summary.get("decision_judge_aggregate") if isinstance(summary.get("decision_judge_aggregate"), dict) else {}
    judge_status = str(judge.get("status") or "").lower()
    if judge_status and judge_status not in {"ok", "disabled"}:
        entries.append(
            _benchmark_diagnostic_entry(
                {
                    "kind": "decision_judge_degraded",
                    "stage": "aggregate.decision_judge",
                    "level": "warning" if judge_status in {"degraded", "skipped"} else "error",
                    "message": str(judge.get("reason") or f"decision judge status: {judge_status}"),
                    "status": judge_status,
                    "metrics": judge.get("metrics") if isinstance(judge.get("metrics"), dict) else {},
                },
                batch_id=batch_id,
                result_batch_id=result_batch_id,
                target_role=target_role,
                origin="result",
            )
        )
    return entries


def _benchmark_game_diagnostics(
    batch_id: str,
    result_batch_id: str,
    target_role: str | None,
    result: dict[str, Any],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for game in result.get("games", []) or []:
        if not isinstance(game, dict):
            continue
        game_id = str(game.get("game_id") or game.get("id") or game.get("source_game_id") or "")
        status = _benchmark_game_status(game)
        message = str(game.get("error") or game.get("rankable_reason") or status)
        if status not in {"completed", "reviewing"} or game.get("error") or game.get("timeout") or game.get("abnormal"):
            entries.append(
                _benchmark_diagnostic_entry(
                    {
                        "kind": "game_failure",
                        "stage": "game.run",
                        "level": "warning" if status in {"timeout", "abnormal"} else "error",
                        "message": message,
                        "game_id": game_id,
                        "status": status,
                        "seed": game.get("seed"),
                    },
                    batch_id=batch_id,
                    result_batch_id=result_batch_id,
                    target_role=target_role,
                    history_game_id=game.get("history_game_id") or game_id,
                    origin="game",
                )
            )
        for diagnostic in _dict_items(game.get("diagnostics")):
            entries.append(
                _benchmark_diagnostic_entry(
                    diagnostic,
                    batch_id=batch_id,
                    result_batch_id=result_batch_id,
                    target_role=target_role,
                    game_id=game_id,
                    seed=game.get("seed"),
                    status=status,
                    history_game_id=game.get("history_game_id") or game_id,
                    origin="game",
                )
            )
    return entries


def _benchmark_diagnostic_entry(
    diagnostic: dict[str, Any],
    *,
    batch_id: str,
    origin: str,
    result_batch_id: str | None = None,
    target_role: str | None = None,
    game_id: str | None = None,
    seed: Any = None,
    status: str | None = None,
    history_game_id: str | None = None,
) -> dict[str, Any]:
    item = dict(diagnostic)
    item.setdefault("kind", "diagnostic")
    item.setdefault("stage", origin)
    item.setdefault("level", "warning")
    item["origin"] = origin
    item["batch_id"] = batch_id
    if result_batch_id:
        item["result_batch_id"] = result_batch_id
    if target_role:
        item["target_role"] = target_role
    if game_id:
        item["game_id"] = game_id
    if seed is not None:
        item.setdefault("seed", seed)
    if status:
        item.setdefault("status", status)
    if history_game_id:
        item.setdefault("history_game_id", history_game_id)
    if "message" not in item:
        item["message"] = str(item.get("kind") or "diagnostic")
    return item


def _benchmark_diagnostic_summary(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    by_kind = Counter(str(item.get("kind") or "diagnostic") for item in diagnostics)
    by_level = Counter(str(item.get("level") or "warning") for item in diagnostics)
    by_origin = Counter(str(item.get("origin") or "unknown") for item in diagnostics)
    return {
        "total": len(diagnostics),
        "by_kind": dict(sorted(by_kind.items())),
        "by_level": dict(sorted(by_level.items())),
        "by_origin": dict(sorted(by_origin.items())),
        "has_errors": bool(by_level.get("error")),
    }


_BENCHMARK_DIAGNOSTIC_KIND_LABELS = {
    "diagnostic": "诊断",
    "leaderboard_gate_failed": "门禁失败",
    "rankable_gate_failed": "门禁失败",
    "game_failure": "失败局",
    "game_timeout": "超时局",
    "timeout": "超时",
    "llm_error": "LLM 错误",
    "fallback": "Fallback",
    "decision_judge_degraded": "决策 Judge 降级",
    "decision_judge_skipped": "决策 Judge 跳过",
    "judge_degraded": "Judge 降级",
    "judge_skipped": "Judge 跳过",
}

_BENCHMARK_DIAGNOSTIC_LEVEL_LABELS = {
    "info": "信息",
    "warning": "警告",
    "warn": "警告",
    "error": "错误",
    "failed": "失败",
    "failure": "失败",
    "timeout": "超时",
}


def _benchmark_report_diagnostic_kind_label(value: Any) -> str:
    text = str(value or "diagnostic").strip()
    return _BENCHMARK_DIAGNOSTIC_KIND_LABELS.get(text) or _BENCHMARK_DIAGNOSTIC_KIND_LABELS.get(text.lower()) or text


def _benchmark_report_diagnostic_level_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "无等级"
    return _BENCHMARK_DIAGNOSTIC_LEVEL_LABELS.get(text.lower()) or text


def _benchmark_diagnostic_aggregate_summary(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _benchmark_diagnostic_summary(diagnostics)
    by_stage = Counter(str(item.get("stage") or "unknown") for item in diagnostics)
    by_target_role = Counter(str(item.get("target_role") or "all") for item in diagnostics)
    by_batch = Counter(str(item.get("batch_id") or "unknown") for item in diagnostics)
    by_seed = Counter(str(item.get("seed") or "unknown") for item in diagnostics if item.get("seed") is not None)
    summary.update(
        {
            "by_stage": dict(sorted(by_stage.items())),
            "by_target_role": dict(sorted(by_target_role.items())),
            "by_batch": dict(sorted(by_batch.items())),
            "by_seed": dict(sorted(by_seed.items())),
            "affected_run_count": len(by_batch),
            "affected_game_count": len(
                {
                    (str(item.get("batch_id") or ""), str(item.get("game_id") or ""))
                    for item in diagnostics
                    if item.get("game_id")
                }
            ),
        }
    )
    return summary


def _benchmark_run_report_payload(batch: dict[str, Any]) -> dict[str, Any]:
    from ui.backend.evolution_serializers import _benchmark_result_summary

    batch_id = str(batch.get("batch_id") or "")
    benchmark = batch.get("benchmark") if isinstance(batch.get("benchmark"), dict) else {}
    config = batch.get("config") if isinstance(batch.get("config"), dict) else {}
    meta = _benchmark_batch_boundary(batch)
    results = _benchmark_results(batch)
    result_rows: list[dict[str, Any]] = []
    for index, result in enumerate(results, start=1):
        result_config = result.get("config") if isinstance(result.get("config"), dict) else {}
        summary = _benchmark_result_summary(result)
        if not isinstance(summary, dict):
            summary = {}
        summary_payload = sanitize_model_runtime_containers(summary)
        result_batch_id = _benchmark_result_batch_id(result) or f"{batch_id}_result_{index}"
        target_role = _benchmark_result_role(result)
        rankable = result.get("rankable")
        result_rows.append(
            {
                **summary_payload,
                "result_batch_id": result_batch_id,
                "target_role": target_role,
                "target_version_id": result.get("target_version_id") or result_config.get("target_version_id"),
                "model_id": result.get("model_id") or result_config.get("model_id"),
                "model_config_hash": result.get("model_config_hash") or result_config.get("model_config_hash"),
                "game_count": _benchmark_result_game_count(result),
                "diagnostic_count": len(_dict_items(result.get("diagnostics"))),
                "warning_count": len(_text_items(result.get("warnings"))),
                "rankable": rankable,
                "rankable_label": "可入榜" if rankable is not False else "未入榜",
                "rankable_reason": str(result.get("rankable_reason") or result.get("leaderboard_skipped_reason") or ""),
                "completed": result.get("completed"),
                "errored": result.get("errored"),
            }
        )

    games = _benchmark_games_for_batch(batch)
    diagnostics = _benchmark_diagnostic_entries(batch)
    problem_games = [
        game
        for game in games
        if (
            _benchmark_problem_status_weight(game.get("status")) > 0
            or int(game.get("diagnostic_count") or 0) > 0
        )
    ]
    problem_games.sort(
        key=lambda game: (
            _benchmark_problem_status_weight(game.get("status")),
            int(game.get("diagnostic_count") or 0),
            str(game.get("game_id") or ""),
        ),
        reverse=True,
    )
    diagnostic_groups = _benchmark_report_diagnostic_groups(diagnostics)
    top_tags = _benchmark_report_top_tags(results, diagnostics)
    subject = _benchmark_report_subject(results, config, meta)
    model_runtime = _benchmark_report_model_runtime(batch, results, config, meta)
    evaluation_set_id = meta.get("evaluation_set_id") or str(benchmark.get("evaluation_set_id") or "")
    seed_set_id = meta.get("seed_set_id") or str(benchmark.get("seed_set_id") or config.get("seed_set_id") or "")
    benchmark_config_hash = str(
        benchmark.get("config_hash")
        or benchmark.get("benchmark_config_hash")
        or config.get("benchmark_config_hash")
        or config.get("config_hash")
        or ""
    )
    summary = {
        "result_count": len(result_rows),
        "rankable_count": sum(1 for row in result_rows if row.get("rankable") is not False),
        "unrankable_count": sum(1 for row in result_rows if row.get("rankable") is False),
        "game_summary": _benchmark_game_summary(games),
        "problem_game_count": len(problem_games),
        "diagnostic_summary": _benchmark_diagnostic_summary(diagnostics),
        "diagnostic_group_count": len(diagnostic_groups),
    }
    report_id = f"benchmark_report:{batch_id}"
    payload = {
        "kind": "benchmark_run_report",
        "schema_version": 1,
        "report_id": report_id,
        "generated_at": beijing_now_iso(),
        "run_id": batch_id,
        "batch_id": batch_id,
        "status": batch.get("status"),
        "evaluation_set_id": evaluation_set_id or "ad-hoc",
        "seed_set_id": seed_set_id or "ad-hoc",
        "benchmark_config_hash": benchmark_config_hash,
        "suite": {
            "label": str(benchmark.get("name") or benchmark.get("label") or benchmark.get("id") or meta.get("benchmark_id") or "临时评测"),
            "benchmark_id": meta.get("benchmark_id") or "",
            "benchmark_version": meta.get("benchmark_version"),
            "target_type": meta.get("target_type"),
            "evaluation_set_id": evaluation_set_id or "ad-hoc",
            "seed_set_id": seed_set_id or "ad-hoc",
            "benchmark_config_hash": benchmark_config_hash,
        },
        "subject": subject,
        "model_runtime": model_runtime,
        "summary": summary,
        "results": result_rows,
        "gates": _benchmark_report_gate_rows(result_rows, diagnostic_groups),
        "problem_games": [
            {
                "game_id": game.get("game_id") or game.get("id"),
                "status": game.get("status"),
                "seed": game.get("seed"),
                "target_role": game.get("target_role"),
                "result_batch_id": game.get("result_batch_id"),
                "diagnostic_count": int(game.get("diagnostic_count") or 0),
                "replay_available": bool(game.get("replay_available")),
                "history_game_id": game.get("history_game_id"),
                "replay_unavailable_reason": game.get("replay_unavailable_reason"),
            }
            for game in problem_games[:80]
        ],
        "diagnostics": diagnostic_groups,
        "tags": top_tags,
        "reproducibility": {
            "套件": str(benchmark.get("name") or benchmark.get("id") or meta.get("benchmark_id") or "临时评测"),
            "评测 ID": meta.get("benchmark_id") or "ad-hoc",
            "评测集": evaluation_set_id or "ad-hoc",
            "种子集": seed_set_id or "ad-hoc",
            "Config Hash": benchmark_config_hash or "未上报",
            "模型 ID": subject.get("model_id") or "未上报",
            "模型配置 Hash": subject.get("model_config_hash") or "未上报",
            "模型运行来源": model_runtime.get("source") or "未上报",
            "目标角色": subject.get("target_role") or "未上报",
            "目标版本": subject.get("target_version_id") or "基线版本",
        },
        "leaderboard": {
            "scope": "model" if meta.get("target_type") == "model" else "role_version",
            "evaluation_set_id": evaluation_set_id,
            "target_role": subject.get("target_role"),
        },
    }
    payload["langfuse"] = _benchmark_batch_langfuse_summary(batch, games=games)
    payload["content_hash"] = _benchmark_report_content_hash(payload)
    payload["artifacts"] = {
        "schema_version": 1,
        "report_id": report_id,
        "content_hash": payload["content_hash"],
        "exports": {
            "json": f"/api/benchmark/batch/{batch_id}/report",
            "markdown": f"/api/benchmark/batch/{batch_id}/report?format=markdown",
            "csv": f"/api/benchmark/batch/{batch_id}/report?format=csv",
        },
    }
    manifest = _benchmark_run_report_reproducibility_manifest(batch, payload)
    payload["reproducibility_manifest"] = manifest
    payload["reproducibility_manifest_hash"] = manifest["manifest_hash"]
    payload["artifacts"]["reproducibility_manifest_hash"] = manifest["manifest_hash"]
    return payload


def _benchmark_run_report_summary(
    batch: dict[str, Any],
    report: dict[str, Any],
    meta: dict[str, Any],
) -> dict[str, Any]:
    batch_id = str(report.get("batch_id") or report.get("run_id") or meta.get("batch_id") or "")
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    diagnostic_summary = summary.get("diagnostic_summary") if isinstance(summary.get("diagnostic_summary"), dict) else {}
    suite = report.get("suite") if isinstance(report.get("suite"), dict) else {}
    subject = report.get("subject") if isinstance(report.get("subject"), dict) else {}
    return {
        "kind": "benchmark_run_report_summary",
        "schema_version": 1,
        "report_id": str(report.get("report_id") or f"benchmark_report:{batch_id}"),
        "run_id": str(report.get("run_id") or batch_id),
        "batch_id": batch_id,
        "status": report.get("status") or meta.get("status"),
        "generated_at": report.get("generated_at"),
        "created_at": batch.get("finished_at") or batch.get("updated_at") or batch.get("started_at"),
        "started_at": batch.get("started_at"),
        "finished_at": batch.get("finished_at"),
        "scope": meta.get("target_type"),
        "target_type": meta.get("target_type"),
        "benchmark_id": meta.get("benchmark_id"),
        "benchmark_version": meta.get("benchmark_version"),
        "evaluation_set_id": report.get("evaluation_set_id") or suite.get("evaluation_set_id"),
        "seed_set_id": report.get("seed_set_id") or suite.get("seed_set_id"),
        "benchmark_config_hash": report.get("benchmark_config_hash") or suite.get("benchmark_config_hash"),
        "suite": _json_clone(suite),
        "subject": _json_clone(subject),
        "model_runtime": _json_clone(report.get("model_runtime") or {}),
        "summary": _json_clone(summary),
        "result_count": int(summary.get("result_count") or 0),
        "rankable_count": int(summary.get("rankable_count") or 0),
        "unrankable_count": int(summary.get("unrankable_count") or 0),
        "problem_game_count": int(summary.get("problem_game_count") or 0),
        "diagnostic_count": int(diagnostic_summary.get("total") or 0),
        "content_hash": report.get("content_hash") or _benchmark_report_content_hash(report),
        "reproducibility_manifest_hash": report.get("reproducibility_manifest_hash"),
        "links": {
            "json": f"/api/benchmark/batch/{batch_id}/report",
            "markdown": f"/api/benchmark/batch/{batch_id}/report?format=markdown",
            "csv": f"/api/benchmark/batch/{batch_id}/report?format=csv",
        },
    }


def _benchmark_report_history_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    by_status = Counter(str(item.get("status") or "unknown") for item in items)
    by_scope = Counter(str(item.get("scope") or "unknown") for item in items)
    return {
        "total": len(items),
        "by_status": dict(sorted(by_status.items())),
        "by_scope": dict(sorted(by_scope.items())),
        "rankable_count": sum(int(item.get("rankable_count") or 0) for item in items),
        "unrankable_count": sum(int(item.get("unrankable_count") or 0) for item in items),
        "problem_game_count": sum(int(item.get("problem_game_count") or 0) for item in items),
        "diagnostic_count": sum(int(item.get("diagnostic_count") or 0) for item in items),
    }


def _benchmark_report_subject(
    results: list[dict[str, Any]],
    batch_config: dict[str, Any],
    meta: dict[str, Any],
) -> dict[str, Any]:
    first_result = results[0] if results else {}
    result_config = first_result.get("config") if isinstance(first_result.get("config"), dict) else {}
    target_role = _benchmark_result_role(first_result) if first_result else None
    target_version_id = first_result.get("target_version_id") or result_config.get("target_version_id")
    model_id = (
        first_result.get("model_id")
        or result_config.get("model_id")
        or batch_config.get("model_id")
        or meta.get("model_id")
    )
    model_config_hash = (
        first_result.get("model_config_hash")
        or result_config.get("model_config_hash")
        or batch_config.get("model_config_hash")
        or meta.get("model_config_hash")
    )
    if meta.get("target_type") == "model":
        label = " / ".join([value for value in (str(model_id or ""), str(model_config_hash or "")) if value]) or "当前后端模型"
    else:
        label = " / ".join([value for value in (str(target_role or ""), str(target_version_id or "基线版本")) if value])
    return {
        "label": label,
        "target_role": target_role,
        "target_version_id": target_version_id,
        "model_id": model_id,
        "model_config_hash": model_config_hash,
    }


def _benchmark_report_model_runtime(
    batch: dict[str, Any],
    results: list[dict[str, Any]],
    batch_config: dict[str, Any],
    meta: dict[str, Any],
) -> dict[str, Any]:
    first_result = results[0] if results else {}
    result_config = first_result.get("config") if isinstance(first_result.get("config"), dict) else {}
    candidates = (
        batch.get("model_runtime"),
        batch_config.get("model_runtime"),
        first_result.get("model_runtime"),
        result_config.get("model_runtime"),
    )
    for candidate in candidates:
        if isinstance(candidate, dict) and candidate:
            runtime = sanitize_model_runtime(candidate)
            runtime.setdefault("model_id", meta.get("model_id") or first_result.get("model_id") or result_config.get("model_id"))
            runtime.setdefault(
                "model_config_hash",
                meta.get("model_config_hash") or first_result.get("model_config_hash") or result_config.get("model_config_hash"),
            )
            return runtime
    return {
        "schema_version": 1,
        "source": "unknown",
        "model_id": meta.get("model_id") or first_result.get("model_id") or result_config.get("model_id") or "",
        "model_config_hash": (
            meta.get("model_config_hash")
            or first_result.get("model_config_hash")
            or result_config.get("model_config_hash")
            or ""
        ),
        "hash_provided": False,
        "hash_input": {},
    }


def _benchmark_run_report_reproducibility_manifest(
    batch: dict[str, Any],
    report: dict[str, Any],
    *,
    export_format: str | None = None,
    export_content_hash: str | None = None,
) -> dict[str, Any]:
    benchmark = batch.get("benchmark") if isinstance(batch.get("benchmark"), dict) else {}
    config = batch.get("config") if isinstance(batch.get("config"), dict) else {}
    suite = report.get("suite") if isinstance(report.get("suite"), dict) else {}
    model_runtime = sanitize_model_runtime(report.get("model_runtime") if isinstance(report.get("model_runtime"), dict) else {})
    request_config = sanitize_config_model_runtime(config)
    planner = sanitize_config_model_runtime(batch.get("run_plan") if isinstance(batch.get("run_plan"), dict) else {})
    content_hash = str(report.get("content_hash") or "")
    run_payload = {
        "benchmark": {
            "id": suite.get("benchmark_id") or benchmark.get("id") or config.get("benchmark_id"),
            "version": suite.get("benchmark_version") or benchmark.get("version") or config.get("benchmark_version"),
            "evaluation_set_id": report.get("evaluation_set_id") or suite.get("evaluation_set_id"),
            "config_hash": report.get("benchmark_config_hash") or suite.get("benchmark_config_hash"),
            "seed_set_id": report.get("seed_set_id") or suite.get("seed_set_id"),
            "seed_set_version": benchmark.get("seed_set_version") or config.get("seed_set_version"),
            "seed_set_config_hash": benchmark.get("seed_set_config_hash") or config.get("seed_set_config_hash"),
            "source_filter": config.get("source_filter") if isinstance(config.get("source_filter"), dict) else {},
        },
        "model_runtime": _json_clone(model_runtime),
        "request": _json_clone(request_config),
        "planner": _json_clone(planner),
        "artifacts": {
            "content_hash": content_hash,
            "json": {"artifact_hash": content_hash},
        },
        "created_at": batch.get("finished_at") or batch.get("updated_at") or batch.get("started_at") or report.get("generated_at"),
    }
    report_payload = {
        "subject": _json_clone(report.get("subject") or {}),
        "model_runtime": _json_clone(model_runtime),
        "artifacts": _json_clone(report.get("artifacts") or {"content_hash": content_hash}),
        "content_hash": content_hash,
    }
    export_payload = None
    if export_format:
        export_payload = {
            "export": {
                "format": export_format,
                "export_content_hash": export_content_hash,
                "artifact_hash": export_content_hash,
            }
        }
    return build_benchmark_reproducibility_manifest(
        run_payload=run_payload,
        report_payload=report_payload,
        export_payload=export_payload,
        created_at=str(run_payload.get("created_at") or ""),
    )


def _benchmark_report_content_hash(report: dict[str, Any]) -> str:
    stable_report = _json_clone(report)
    if isinstance(stable_report, dict):
        stable_report.pop("generated_at", None)
        stable_report.pop("content_hash", None)
        stable_report.pop("artifacts", None)
        stable_report.pop("reproducibility_manifest", None)
        stable_report.pop("reproducibility_manifest_hash", None)
    return _stable_payload_hash(stable_report if isinstance(stable_report, dict) else {})


def _benchmark_report_gate_rows(
    result_rows: list[dict[str, Any]],
    diagnostic_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, result in enumerate(result_rows, start=1):
        rows.append(
            {
                "key": result.get("result_batch_id") or f"result-{index}",
                "title": result.get("target_role") or result.get("model_id") or result.get("result_batch_id") or f"结果 {index}",
                "status": result.get("rankable_label") or ("可入榜" if result.get("rankable") is not False else "未入榜"),
                "reason": result.get("rankable_reason") or "未上报门禁原因",
                "meta": " / ".join(
                    str(value)
                    for value in (
                        result.get("target_version_id"),
                        f"{result.get('completed')} 局完成" if result.get("completed") is not None else "",
                        f"{result.get('game_count')} 局" if result.get("game_count") is not None else "",
                    )
                    if value
                ),
                "blocked": result.get("rankable") is False,
            }
        )
    for group in diagnostic_groups[:8]:
        rows.append(
            {
                "key": f"kind-{group.get('kind')}",
                "title": group.get("label") or _benchmark_report_diagnostic_kind_label(group.get("kind")),
                "status": f"{group.get('total', 0)} 条诊断",
                "reason": "所选运行上报了该诊断类型",
                "meta": "诊断类型",
                "blocked": False,
            }
        )
    return rows[:16]


def _benchmark_report_diagnostic_groups(diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for item in diagnostics:
        kind = str(item.get("kind") or "diagnostic")
        level = str(item.get("level") or "info").lower()
        group = groups.setdefault(
            kind,
            {
                "kind": kind,
                "label": _benchmark_report_diagnostic_kind_label(kind),
                "total": 0,
                "levels": Counter(),
                "games": set(),
                "stages": set(),
            },
        )
        group["total"] += 1
        group["levels"][level] += 1
        if item.get("game_id"):
            group["games"].add(str(item.get("game_id")))
        if item.get("stage"):
            group["stages"].add(str(item.get("stage")))
    rows: list[dict[str, Any]] = []
    for group in groups.values():
        level_label = ", ".join(
            f"{_benchmark_report_diagnostic_level_label(level)}: {count}"
            for level, count in group["levels"].most_common(2)
        )
        rows.append(
            {
                "kind": group["kind"],
                "label": group["label"],
                "total": group["total"],
                "level": level_label or "无等级",
                "game_count": len(group["games"]),
                "stage_count": len(group["stages"]),
            }
        )
    rows.sort(key=lambda row: (-int(row.get("total") or 0), str(row.get("label") or "")))
    return rows[:24]


def _benchmark_report_top_tags(
    results: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    for result in results:
        summary = result.get("score_summary") if isinstance(result.get("score_summary"), dict) else {}
        judge = summary.get("decision_judge_aggregate") if isinstance(summary.get("decision_judge_aggregate"), dict) else {}
        for tag in judge.get("top_mistake_tags", []) or []:
            if not isinstance(tag, dict):
                continue
            label = str(tag.get("tag") or "").strip()
            if label:
                counts[label] += int(tag.get("count") or 1)
    for item in diagnostics:
        label = str(item.get("kind") or "").strip()
        if label:
            counts[label] += 1
    return [{"label": label, "count": count} for label, count in counts.most_common(12)]


def _benchmark_problem_status_weight(status: Any) -> int:
    text = str(status or "").strip().lower()
    if text == "failed":
        return 5
    if text == "timeout":
        return 4
    if text == "abnormal":
        return 3
    if text in {"cancelled", "interrupted"}:
        return 2
    if text == "completed":
        return 0
    return 1 if text else 0


def _benchmark_batch_boundary(batch: dict[str, Any]) -> dict[str, Any]:
    benchmark = batch.get("benchmark") if isinstance(batch.get("benchmark"), dict) else {}
    config = batch.get("config") if isinstance(batch.get("config"), dict) else {}
    results = _benchmark_results(batch)

    def first_result_value(*keys: str) -> Any:
        for result in results:
            result_config = result.get("config") if isinstance(result.get("config"), dict) else {}
            for key in keys:
                value = result.get(key)
                if value not in (None, ""):
                    return value
                value = result_config.get(key)
                if value not in (None, ""):
                    return value
        return None

    target_type = str(
        batch.get("target_type")
        or benchmark.get("target_type")
        or config.get("target_type")
        or first_result_value("target_type", "comparison_type")
        or "role_version"
    ).strip().lower()
    roles = batch.get("roles") if isinstance(batch.get("roles"), list) else []
    return {
        "batch_id": str(batch.get("batch_id") or batch.get("run_id") or ""),
        "status": str(batch.get("status") or "").strip().lower(),
        "target_type": "model" if target_type == "model" else "role_version",
        "benchmark_id": str(benchmark.get("id") or batch.get("benchmark_id") or config.get("benchmark_id") or first_result_value("benchmark_id") or ""),
        "benchmark_version": benchmark.get("version") or batch.get("benchmark_version") or config.get("benchmark_version") or first_result_value("benchmark_version"),
        "evaluation_set_id": str(benchmark.get("evaluation_set_id") or batch.get("evaluation_set_id") or config.get("evaluation_set_id") or first_result_value("evaluation_set_id") or ""),
        "seed_set_id": str(benchmark.get("seed_set_id") or batch.get("seed_set_id") or config.get("seed_set_id") or first_result_value("seed_set_id") or ""),
        "model_id": str(batch.get("model_id") or config.get("model_id") or first_result_value("model_id") or ""),
        "model_config_hash": str(batch.get("model_config_hash") or config.get("model_config_hash") or first_result_value("model_config_hash") or ""),
        "roles": [str(role).strip().lower() for role in roles if str(role).strip()],
    }


def _benchmark_diagnostic_matches(
    item: dict[str, Any],
    meta: dict[str, Any],
    *,
    target_role: str,
    kind_filter: set[str] | None,
    level_filter: set[str] | None,
    status_filter: set[str] | None,
    stage_filter: set[str] | None,
    seed_filter: set[str] | None,
) -> bool:
    if target_role:
        item_role = str(item.get("target_role") or "").strip().lower()
        if item_role and item_role != target_role:
            return False
        if not item_role and meta.get("target_type") == "role_version" and target_role not in meta.get("roles", []):
            return False
    return (
        _match_filter(item.get("kind"), kind_filter)
        and _match_filter(item.get("level"), level_filter)
        and _match_filter(item.get("status") or meta.get("status"), status_filter)
        and _match_filter(item.get("stage"), stage_filter)
        and _match_filter(item.get("seed"), seed_filter)
    )


def _benchmark_annotated_diagnostic(item: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    annotated = dict(item)
    annotated["batch_id"] = meta["batch_id"]
    annotated["batch_status"] = meta["status"]
    annotated["target_type"] = meta["target_type"]
    annotated["benchmark_id"] = meta["benchmark_id"]
    annotated["evaluation_set_id"] = meta["evaluation_set_id"]
    annotated["seed_set_id"] = meta["seed_set_id"]
    if meta.get("model_id"):
        annotated["model_id"] = meta["model_id"]
    if meta.get("model_config_hash"):
        annotated["model_config_hash"] = meta["model_config_hash"]
    return annotated


def _benchmark_diagnostic_run_payload(
    batch: dict[str, Any],
    diagnostics: list[dict[str, Any]],
    meta: dict[str, Any],
) -> dict[str, Any]:
    payload = _benchmark_latest_run_payload(batch)
    payload.update(
        {
            "id": meta["batch_id"],
            "batch_id": meta["batch_id"],
            "status": meta["status"] or payload.get("status"),
            "benchmark_id": meta["benchmark_id"],
            "benchmark_version": meta["benchmark_version"],
            "evaluation_set_id": meta["evaluation_set_id"],
            "seed_set_id": meta["seed_set_id"],
            "target_type": meta["target_type"],
            "roles": meta["roles"],
            "model_id": meta["model_id"] or None,
            "model_config_hash": meta["model_config_hash"] or None,
            "diagnostic_count": len(diagnostics),
            "diagnostic_summary": _benchmark_diagnostic_summary(diagnostics),
        }
    )
    return payload


def _benchmark_diagnostic_affected_games(
    matched_batches: list[tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]]
) -> list[dict[str, Any]]:
    affected: list[dict[str, Any]] = []
    for batch, diagnostics, _meta in matched_batches:
        diagnostic_counts = Counter(
            str(item.get("game_id") or "") for item in diagnostics if item.get("game_id")
        )
        if not diagnostic_counts:
            continue
        game_by_id = {
            str(game.get("game_id") or game.get("id") or ""): game
            for game in _benchmark_games_for_batch(batch)
        }
        for game_id, count in diagnostic_counts.items():
            game = dict(game_by_id.get(game_id) or {"game_id": game_id, "id": game_id})
            game["batch_id"] = str(batch.get("batch_id") or game.get("batch_id") or "")
            game["diagnostic_count"] = int(count)
            affected.append(game)
    affected.sort(
        key=lambda game: (
            int(game.get("diagnostic_count") or 0),
            str(game.get("batch_id") or ""),
            str(game.get("game_id") or ""),
        ),
        reverse=True,
    )
    return affected[:80]


def _dedupe_benchmark_diagnostics(diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for item in diagnostics:
        key = (
            str(item.get("origin") or ""),
            str(item.get("result_batch_id") or ""),
            str(item.get("game_id") or ""),
            str(item.get("kind") or ""),
            str(item.get("stage") or ""),
            str(item.get("message") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _stable_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _benchmark_run_sort_key(batch: dict[str, Any]) -> tuple[str, str, str]:
    activity_at = batch.get("finished_at") or batch.get("last_heartbeat_at") or batch.get("updated_at") or batch.get("started_at")
    return (
        str(activity_at or ""),
        str(batch.get("started_at") or ""),
        str(batch.get("batch_id") or batch.get("run_id") or ""),
    )


def _benchmark_latest_run_payload(batch: dict[str, Any]) -> dict[str, Any]:
    progress = batch.get("progress") if isinstance(batch.get("progress"), dict) else {}
    diagnostics = batch.get("diagnostics") if isinstance(batch.get("diagnostics"), list) else []
    roles = batch.get("roles") if isinstance(batch.get("roles"), list) else []
    benchmark = batch.get("benchmark") if isinstance(batch.get("benchmark"), dict) else {}
    return {
        "batch_id": batch.get("batch_id") or batch.get("run_id"),
        "status": batch.get("status"),
        "current_stage": batch.get("current_stage") or batch.get("stage") or progress.get("stage"),
        "target_type": batch.get("target_type") or benchmark.get("target_type"),
        "started_at": batch.get("started_at"),
        "finished_at": batch.get("finished_at"),
        "last_heartbeat_at": batch.get("last_heartbeat_at"),
        "role_count": len(roles),
        "result_count": int(batch.get("result_count") or len(batch.get("results") or []) or (1 if batch.get("result") else 0)),
        "diagnostic_count": int(batch.get("diagnostic_count") or len(diagnostics)),
    }
