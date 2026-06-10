"""Benchmark batch detail, report, game, and diagnostic service helpers."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from typing import Any, Protocol

from fastapi import HTTPException

from app.lib.benchmark_reproducibility import build_benchmark_reproducibility_manifest
from app.util.time import beijing_now_iso
from ui.backend.task_state import _filter_values, _match_filter, _pagination


class BenchmarkReportServiceContextProtocol(Protocol):
    """Context capabilities required by ``BenchmarkReportService``."""

    evolution_batches: dict[str, dict[str, Any]]


class BenchmarkReportService:
    """Read-only benchmark batch/report/diagnostic payload service."""

    def __init__(self, context: BenchmarkReportServiceContextProtocol) -> None:
        self._context = context

    def benchmark_batch_detail(self, batch_id: str) -> dict[str, Any]:
        """Return an auditable benchmark batch detail payload."""
        batch = self.benchmark_batch_or_404(batch_id)
        from ui.backend.evolution_serializers import _benchmark_result_summary, _evolution_batch_summary

        results = _benchmark_results(batch)
        result_summaries = []
        for result in results:
            summary = _benchmark_result_summary(result)
            if isinstance(summary, dict):
                result_summaries.append(
                    {
                        **summary,
                        "result_batch_id": _benchmark_result_batch_id(result),
                        "target_role": _benchmark_result_role(result),
                        "game_count": _benchmark_result_game_count(result),
                        "diagnostic_count": len(_dict_items(result.get("diagnostics"))),
                        "warning_count": len(_text_items(result.get("warnings"))),
                    }
                )
        games = _benchmark_games_for_batch(batch)
        langfuse = _benchmark_batch_langfuse_summary(batch, games=games)
        return {
            "kind": "benchmark_batch_detail",
            "schema_version": 1,
            "batch": _evolution_batch_summary(batch),
            "batch_id": batch_id,
            "status": batch.get("status"),
            "benchmark": batch.get("benchmark"),
            "target_type": batch.get("target_type"),
            "model_runtime": _json_clone(batch.get("model_runtime") or {}),
            "roles": list(batch.get("roles", []) or []),
            "run_plan": batch.get("run_plan"),
            "result_count": len(results),
            "results": result_summaries,
            "game_summary": _benchmark_game_summary(games),
            "diagnostic_summary": _benchmark_diagnostic_summary(_benchmark_diagnostic_entries(batch)),
            "langfuse": langfuse,
        }

    def benchmark_batch_games(
        self,
        batch_id: str,
        *,
        result_batch_id: str | None = None,
        target_role: str | None = None,
        status: str | None = None,
        seed: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return paginated benchmark game summaries for a batch."""
        batch = self.benchmark_batch_or_404(batch_id)
        games = _benchmark_games_for_batch(batch)
        if result_batch_id:
            games = [game for game in games if game.get("result_batch_id") == result_batch_id]
        if target_role:
            role_text = str(target_role).strip().lower()
            games = [game for game in games if str(game.get("target_role") or "").lower() == role_text]
        statuses = _filter_values(status)
        if statuses is not None:
            games = [game for game in games if _benchmark_game_matches_status_filter(game, statuses)]
        seeds = _filter_values(seed)
        if seeds is not None:
            games = [game for game in games if _match_filter(game.get("seed"), seeds)]
        page, pagination = _pagination(games, limit=limit, offset=offset)
        return {
            "kind": "benchmark_batch_games",
            "schema_version": 1,
            "batch_id": batch_id,
            "result_batch_id": result_batch_id,
            "target_role": target_role,
            "status": status,
            "seed": seed,
            "games": page,
            "pagination": pagination,
        }

    def benchmark_batch_diagnostics(
        self,
        batch_id: str,
        *,
        target_role: str | None = None,
        kind: str | None = None,
        level: str | None = None,
        status: str | None = None,
        stage: str | None = None,
        seed: str | None = None,
    ) -> dict[str, Any]:
        """Return aggregated benchmark run diagnostics."""
        batch = self.benchmark_batch_or_404(batch_id)
        diagnostics = _benchmark_diagnostic_entries(batch)
        meta = _benchmark_batch_boundary(batch)
        kind_filter = _filter_values(kind)
        level_filter = _filter_values(level)
        status_filter = _filter_values(status)
        stage_filter = _filter_values(stage)
        seed_filter = _filter_values(seed)
        normalized_target_role = str(target_role or "").strip().lower()
        if any(value is not None for value in (kind_filter, level_filter, status_filter, stage_filter, seed_filter)) or normalized_target_role:
            diagnostics = [
                item
                for item in diagnostics
                if _benchmark_diagnostic_matches(
                    item,
                    meta,
                    target_role=normalized_target_role,
                    kind_filter=kind_filter,
                    level_filter=level_filter,
                    status_filter=status_filter,
                    stage_filter=stage_filter,
                    seed_filter=seed_filter,
                )
            ]
        return {
            "kind": "benchmark_batch_diagnostics",
            "schema_version": 1,
            "batch_id": batch_id,
            "status": batch.get("status"),
            "benchmark": batch.get("benchmark"),
            "target_type": batch.get("target_type"),
            "filters": {
                "target_role": target_role,
                "kind": kind,
                "level": level,
                "status": status,
                "stage": stage,
                "seed": seed,
            },
            "diagnostics": diagnostics,
            "summary": _benchmark_diagnostic_summary(diagnostics),
        }

    def benchmark_batch_report(self, batch_id: str, *, format: str = "json") -> dict[str, Any]:
        """Return a canonical benchmark run report or a text export wrapper."""
        batch = self.benchmark_batch_or_404(batch_id)
        report = _benchmark_run_report_payload(batch)
        normalized_format = str(format or "json").strip().lower()
        if normalized_format in {"json", ""}:
            return report
        if normalized_format in {"markdown", "md"}:
            content = _benchmark_run_report_markdown(report)
            export_content_hash = _text_content_hash(content)
            export_manifest = _benchmark_run_report_reproducibility_manifest(
                batch,
                report,
                export_format="markdown",
                export_content_hash=export_content_hash,
            )
            return {
                "kind": "benchmark_run_report_export",
                "schema_version": 1,
                "run_id": report["run_id"],
                "report_id": report["report_id"],
                "format": "markdown",
                "content": content,
                "content_type": "text/markdown",
                "content_hash": report["content_hash"],
                "export_content_hash": export_content_hash,
                "artifact_hash": export_content_hash,
                "reproducibility_manifest": export_manifest,
                "reproducibility_manifest_hash": export_manifest["manifest_hash"],
                "report": report,
            }
        if normalized_format == "csv":
            content = _benchmark_run_report_csv(report)
            export_content_hash = _text_content_hash(content)
            export_manifest = _benchmark_run_report_reproducibility_manifest(
                batch,
                report,
                export_format="csv",
                export_content_hash=export_content_hash,
            )
            return {
                "kind": "benchmark_run_report_export",
                "schema_version": 1,
                "run_id": report["run_id"],
                "report_id": report["report_id"],
                "format": "csv",
                "content": content,
                "content_type": "text/csv",
                "content_hash": report["content_hash"],
                "export_content_hash": export_content_hash,
                "artifact_hash": export_content_hash,
                "reproducibility_manifest": export_manifest,
                "reproducibility_manifest_hash": export_manifest["manifest_hash"],
                "report": report,
            }
        raise HTTPException(status_code=422, detail="unsupported benchmark report format")

    def benchmark_reports(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        model_id: str | None = None,
        model_config_hash: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return reportable benchmark run summaries for the selected boundary."""
        normalized_scope = str(scope or "").strip().lower()
        normalized_evaluation_set_id = str(evaluation_set_id or "").strip()
        normalized_benchmark_id = str(benchmark_id or "").strip()
        normalized_target_role = str(target_role or "").strip().lower()
        normalized_model_id = str(model_id or "").strip()
        normalized_model_config_hash = str(model_config_hash or "").strip()
        status_filter = _filter_values(status)
        batches = [
            batch
            for batch in self._context.evolution_batches.values()
            if isinstance(batch, dict) and batch.get("kind") == "benchmark_batch"
        ]
        batches.sort(key=_benchmark_run_sort_key, reverse=True)
        items: list[dict[str, Any]] = []
        for batch in batches:
            meta = _benchmark_batch_boundary(batch)
            if normalized_scope and meta["target_type"] != normalized_scope:
                continue
            if normalized_evaluation_set_id and meta["evaluation_set_id"] != normalized_evaluation_set_id:
                continue
            if normalized_benchmark_id and meta["benchmark_id"] != normalized_benchmark_id:
                continue
            if normalized_model_id and meta["model_id"] != normalized_model_id:
                continue
            if normalized_model_config_hash and meta["model_config_hash"] != normalized_model_config_hash:
                continue
            if status_filter is not None and not _match_filter(meta["status"], status_filter):
                continue
            report = _benchmark_run_report_payload(batch)
            subject_role = str(report.get("subject", {}).get("target_role") or "").strip().lower()
            if normalized_target_role and meta["target_type"] == "role_version":
                if subject_role and subject_role != normalized_target_role:
                    continue
                if not subject_role and normalized_target_role not in meta.get("roles", []):
                    continue
            items.append(_benchmark_run_report_summary(batch, report, meta))

        page, pagination = _pagination(items, limit=limit, offset=offset)
        return {
            "kind": "benchmark_run_reports",
            "schema_version": 1,
            "scope": normalized_scope or None,
            "evaluation_set_id": normalized_evaluation_set_id or None,
            "benchmark_id": normalized_benchmark_id or None,
            "target_role": normalized_target_role or None,
            "model_id": normalized_model_id or None,
            "model_config_hash": normalized_model_config_hash or None,
            "filters": {"status": status},
            "items": page,
            "summary": _benchmark_report_history_summary(items),
            "pagination": pagination,
        }

    def benchmark_diagnostics(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        model_id: str | None = None,
        model_config_hash: str | None = None,
        kind: str | None = None,
        level: str | None = None,
        status: str | None = None,
        stage: str | None = None,
        seed: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Return diagnostics aggregated across benchmark runs in the selected boundary."""
        kind_filter = _filter_values(kind)
        level_filter = _filter_values(level)
        status_filter = _filter_values(status)
        stage_filter = _filter_values(stage)
        seed_filter = _filter_values(seed)
        normalized_scope = str(scope or "").strip().lower()
        normalized_evaluation_set_id = str(evaluation_set_id or "").strip()
        normalized_benchmark_id = str(benchmark_id or "").strip()
        normalized_target_role = str(target_role or "").strip().lower()
        normalized_model_id = str(model_id or "").strip()
        normalized_model_config_hash = str(model_config_hash or "").strip()

        all_diagnostics: list[dict[str, Any]] = []
        matched_batches: list[tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]] = []
        batches = [
            batch
            for batch in self._context.evolution_batches.values()
            if isinstance(batch, dict) and batch.get("kind") == "benchmark_batch"
        ]
        batches.sort(key=_benchmark_run_sort_key, reverse=True)
        for batch in batches:
            meta = _benchmark_batch_boundary(batch)
            if normalized_scope and meta["target_type"] != normalized_scope:
                continue
            if normalized_evaluation_set_id and meta["evaluation_set_id"] != normalized_evaluation_set_id:
                continue
            if normalized_benchmark_id and meta["benchmark_id"] != normalized_benchmark_id:
                continue
            if normalized_model_id and meta["model_id"] != normalized_model_id:
                continue
            if normalized_model_config_hash and meta["model_config_hash"] != normalized_model_config_hash:
                continue

            diagnostics = [
                _benchmark_annotated_diagnostic(item, meta)
                for item in _benchmark_diagnostic_entries(batch)
                if _benchmark_diagnostic_matches(
                    item,
                    meta,
                    target_role=normalized_target_role,
                    kind_filter=kind_filter,
                    level_filter=level_filter,
                    status_filter=status_filter,
                    stage_filter=stage_filter,
                    seed_filter=seed_filter,
                )
            ]
            if not diagnostics:
                continue
            all_diagnostics.extend(diagnostics)
            matched_batches.append((batch, diagnostics, meta))

        page, pagination = _pagination(all_diagnostics, limit=limit, offset=offset)
        affected_runs = [
            _benchmark_diagnostic_run_payload(batch, diagnostics, meta)
            for batch, diagnostics, meta in matched_batches
        ]
        affected_games = _benchmark_diagnostic_affected_games(matched_batches)
        return {
            "kind": "benchmark_diagnostics",
            "schema_version": 1,
            "scope": normalized_scope or None,
            "evaluation_set_id": normalized_evaluation_set_id or None,
            "benchmark_id": normalized_benchmark_id or None,
            "target_role": normalized_target_role or None,
            "model_id": normalized_model_id or None,
            "model_config_hash": normalized_model_config_hash or None,
            "filters": {
                "kind": kind,
                "level": level,
                "status": status,
                "stage": stage,
                "seed": seed,
            },
            "diagnostics": page,
            "affected_runs": affected_runs,
            "affected_games": affected_games,
            "summary": _benchmark_diagnostic_aggregate_summary(all_diagnostics),
            "pagination": pagination,
        }

    def benchmark_batch_or_404(self, batch_id: str) -> dict[str, Any]:
        batch = self._context.evolution_batches.get(batch_id)
        if batch is None or str(batch.get("kind") or "") != "benchmark_batch":
            raise HTTPException(status_code=404, detail="batch not found")
        return batch


def _benchmark_results(batch: dict[str, Any]) -> list[dict[str, Any]]:
    results = batch.get("results")
    if isinstance(results, list):
        return [dict(item) for item in results if isinstance(item, dict)]
    result = batch.get("result")
    return [dict(result)] if isinstance(result, dict) else []


def _benchmark_result_batch_id(result: dict[str, Any]) -> str:
    config = result.get("config") if isinstance(result.get("config"), dict) else {}
    return str(result.get("batch_id") or config.get("batch_id") or "")


def _benchmark_result_role(result: dict[str, Any]) -> str | None:
    config = result.get("config") if isinstance(result.get("config"), dict) else {}
    role = result.get("target_role") or config.get("target_role")
    return str(role) if role else None


def _benchmark_result_game_count(result: dict[str, Any]) -> int:
    for key in ("game_count", "completed", "attempted_game_count"):
        try:
            if result.get(key) is not None:
                return max(0, int(result.get(key) or 0))
        except (TypeError, ValueError):
            continue
    games = result.get("games")
    return len([item for item in games if isinstance(item, dict)]) if isinstance(games, list) else 0


def _benchmark_games_for_batch(batch: dict[str, Any]) -> list[dict[str, Any]]:
    parent_batch_id = str(batch.get("batch_id") or "")
    games_out: list[dict[str, Any]] = []
    for result in _benchmark_results(batch):
        result_batch_id = _benchmark_result_batch_id(result)
        target_role = _benchmark_result_role(result)
        games = result.get("games")
        if not isinstance(games, list):
            continue
        for index, game in enumerate(games, start=1):
            if not isinstance(game, dict):
                continue
            games_out.append(
                _benchmark_game_item(
                    parent_batch_id=parent_batch_id,
                    result_batch_id=result_batch_id,
                    target_role=target_role,
                    target_type=str(batch.get("target_type") or ""),
                    result=result,
                    game=game,
                    index=index,
                )
            )
    return games_out


def _benchmark_game_item(
    *,
    parent_batch_id: str,
    result_batch_id: str,
    target_role: str | None,
    target_type: str,
    result: dict[str, Any],
    game: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    game_id = str(game.get("game_id") or game.get("id") or game.get("source_game_id") or "")
    history_game_id = str(game.get("history_game_id") or game_id or "")
    events = game.get("events") if isinstance(game.get("events"), list) else []
    decisions = game.get("decisions") if isinstance(game.get("decisions"), list) else []
    diagnostics = _dict_items(game.get("diagnostics"))
    item = {
        "batch_id": parent_batch_id,
        "result_batch_id": result_batch_id,
        "target_type": target_type,
        "target_role": target_role,
        "index": index,
        "game_id": game_id,
        "id": str(game.get("id") or game_id),
        "history_game_id": history_game_id or None,
        "replay_available": bool(history_game_id),
        "replay_unavailable_reason": None if history_game_id else "missing game id for replay",
        "status": _benchmark_game_status(game),
        "seed": game.get("seed"),
        "winner": game.get("winner"),
        "phase": game.get("phase") or "benchmark",
        "side": game.get("side"),
        "event_count": int(game.get("event_count") or len(events)),
        "decision_count": int(game.get("decision_count") or len(decisions)),
        "day": game.get("day", game.get("days", 0)),
        "days": game.get("days", game.get("day", 0)),
        "in_progress": bool(game.get("in_progress", False)),
        "source_run_id": game.get("source_run_id") or result_batch_id,
        "source_game_id": game.get("source_game_id") or game_id,
        "diagnostic_count": len(diagnostics),
    }
    errors = _text_items(game.get("errors"))
    if errors and "error_count" not in item:
        item["error_count"] = len(errors)
    fallbacks = _dict_items(game.get("fallbacks"))
    if fallbacks and "fallback_count" not in item:
        item["fallback_count"] = len(fallbacks)
    llm_errors = _text_items(game.get("llm_errors"))
    if llm_errors and "llm_error_count" not in item:
        item["llm_error_count"] = len(llm_errors)
    policy_adjustments = _dict_items(game.get("policy_adjustments"))
    if policy_adjustments and "policy_adjusted_count" not in item:
        item["policy_adjusted_count"] = len(policy_adjustments)
    for key in (
        "error",
        "rankable",
        "rankable_reason",
        "timeout",
        "abnormal",
        "fallback",
        "fallback_count",
        "llm_error",
        "llm_error_count",
        "policy_adjusted",
        "policy_adjusted_count",
    ):
        if key in game:
            item[key] = game.get(key)
    langfuse = _benchmark_game_langfuse_block(
        game=game,
        result=result,
        result_batch_id=result_batch_id,
        index=index,
    )
    if langfuse:
        item["langfuse"] = langfuse
        item["observability"] = {"langfuse": _json_clone(langfuse)}
    return item


def _benchmark_game_langfuse_block(
    *,
    game: dict[str, Any],
    result: dict[str, Any],
    result_batch_id: str,
    index: int,
) -> dict[str, Any]:
    result_config = result.get("config") if isinstance(result.get("config"), dict) else {}
    score_summary = result.get("score_summary") if isinstance(result.get("score_summary"), dict) else {}
    game_sources = _langfuse_sources(game)
    batch_sources = [result_config, result, score_summary]
    seed = game.get("seed")
    dataset_item_id = (
        _langfuse_text(game_sources, "dataset_item_id")
        or _benchmark_langfuse_dataset_item_id_from_config(result_config, seed=seed, index=index)
        or _langfuse_text(batch_sources, "dataset_item_id")
    )
    dataset_run_url = _langfuse_text(game_sources, "dataset_run_url")
    experiment_url = _langfuse_text(game_sources, "experiment_url")
    if dataset_run_url is None:
        dataset_run_url = experiment_url
    if experiment_url is None:
        experiment_url = dataset_run_url

    block = {
        "trace_id": _langfuse_text(game_sources, "trace_id"),
        "trace_url": _langfuse_text(game_sources, "trace_url"),
        "dataset_name": _langfuse_text(game_sources, "dataset_name")
        or _langfuse_text(batch_sources, "dataset_name")
        or _optional_text(result_config.get("evaluation_set_id")),
        "dataset_id": _langfuse_text(game_sources, "dataset_id"),
        "dataset_item_id": dataset_item_id,
        "dataset_item_url": _langfuse_text(game_sources, "dataset_item_url"),
        "dataset_run_id": _langfuse_text(game_sources, "dataset_run_id")
        or _langfuse_text(batch_sources, "dataset_run_id"),
        "dataset_run_item_id": _langfuse_text(game_sources, "dataset_run_item_id"),
        "dataset_run_url": dataset_run_url,
        "experiment_name": _langfuse_text(game_sources, "experiment_name")
        or _langfuse_text(batch_sources, "experiment_name")
        or _optional_text(result_config.get("benchmark_id"))
        or _optional_text(result_config.get("evaluation_set_id")),
        "run_name": _langfuse_text(game_sources, "run_name")
        or _langfuse_text(batch_sources, "run_name")
        or _optional_text(result_config.get("batch_id"))
        or _optional_text(result_batch_id),
        "experiment_url": experiment_url,
    }
    return {key: value for key, value in block.items() if value is not None}


_LANGFUSE_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "trace_id": ("trace_id", "langfuse_trace_id"),
    "trace_url": ("trace_url", "langfuse_trace_url"),
    "dataset_name": ("dataset_name", "langfuse_dataset_name"),
    "dataset_id": ("dataset_id", "langfuse_dataset_id"),
    "dataset_item_id": ("dataset_item_id", "langfuse_dataset_item_id"),
    "dataset_item_url": ("dataset_item_url", "langfuse_dataset_item_url"),
    "dataset_run_id": ("dataset_run_id", "langfuse_dataset_run_id"),
    "dataset_run_item_id": ("dataset_run_item_id", "langfuse_dataset_run_item_id"),
    "dataset_run_url": ("dataset_run_url", "langfuse_dataset_run_url"),
    "experiment_name": ("experiment_name", "langfuse_experiment_name"),
    "run_name": ("run_name", "langfuse_run_name"),
    "experiment_url": ("experiment_url", "langfuse_experiment_url"),
}


def _langfuse_sources(value: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    langfuse = value.get("langfuse")
    if isinstance(langfuse, dict):
        sources.append(langfuse)
    observability = value.get("observability")
    if isinstance(observability, dict):
        observed_langfuse = observability.get("langfuse")
        if isinstance(observed_langfuse, dict):
            sources.append(observed_langfuse)
    sources.append(value)
    return sources


def _langfuse_text(sources: list[dict[str, Any]], field: str) -> str | None:
    for source in sources:
        for key in _LANGFUSE_FIELD_ALIASES.get(field, (field,)):
            text = _optional_text(source.get(key))
            if text is not None:
                return text
    return None


def _benchmark_langfuse_dataset_item_id_from_config(
    cfg: dict[str, Any],
    *,
    seed: Any,
    index: int,
) -> str | None:
    configured = cfg.get("langfuse_dataset_item_id")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    zero_index = max(0, int(index or 1) - 1)
    if isinstance(configured, list):
        for candidate_index in (zero_index, index):
            if 0 <= candidate_index < len(configured):
                value = _optional_text(configured[candidate_index])
                if value is not None:
                    return value
    if isinstance(configured, dict):
        for key in (seed, str(seed) if seed is not None else None, zero_index, str(zero_index), index, str(index)):
            if key is not None and key in configured:
                value = _optional_text(configured[key])
                if value is not None:
                    return value

    evaluation_set_id = _optional_text(cfg.get("evaluation_set_id"))
    seed_set_id = _optional_text(cfg.get("seed_set_id"))
    seed_text = _optional_text(seed)
    if evaluation_set_id is None or seed_set_id is None or seed_text is None:
        return None
    return f"{evaluation_set_id}:{seed_set_id}:{seed_text}"


def _benchmark_batch_langfuse_summary(batch: dict[str, Any], *, games: list[dict[str, Any]]) -> dict[str, Any]:
    config = batch.get("config") if isinstance(batch.get("config"), dict) else {}
    results = _benchmark_results(batch)
    result_configs = [
        result.get("config")
        for result in results
        if isinstance(result.get("config"), dict)
    ]
    config_sources = [source for source in [config, *result_configs] if isinstance(source, dict)]
    game_blocks = [game.get("langfuse") for game in games if isinstance(game.get("langfuse"), dict)]
    return {
        "dataset_names": _unique_texts(
            *[_langfuse_text(config_sources, "dataset_name")],
            *[block.get("dataset_name") for block in game_blocks if isinstance(block, dict)],
        ),
        "experiment_names": _unique_texts(
            *[_langfuse_text(config_sources, "experiment_name")],
            *[block.get("experiment_name") for block in game_blocks if isinstance(block, dict)],
        ),
        "run_names": _unique_texts(
            *[_langfuse_text(config_sources, "run_name")],
            *[block.get("run_name") for block in game_blocks if isinstance(block, dict)],
        ),
        "trace_count": len(_unique_texts(*[block.get("trace_id") for block in game_blocks if isinstance(block, dict)])),
        "dataset_run_count": len(
            _unique_texts(*[block.get("dataset_run_id") for block in game_blocks if isinstance(block, dict)])
        ),
        "dataset_run_item_count": len(
            _unique_texts(*[block.get("dataset_run_item_id") for block in game_blocks if isinstance(block, dict)])
        ),
        "dataset_item_count": len(
            _unique_texts(*[block.get("dataset_item_id") for block in game_blocks if isinstance(block, dict)])
        ),
        "links": {
            "trace_urls": _unique_texts(*[block.get("trace_url") for block in game_blocks if isinstance(block, dict)]),
            "dataset_run_urls": _unique_texts(
                *[block.get("dataset_run_url") for block in game_blocks if isinstance(block, dict)]
            ),
            "experiment_urls": _unique_texts(
                *[block.get("experiment_url") for block in game_blocks if isinstance(block, dict)]
            ),
        },
    }


def _benchmark_game_matches_status_filter(game: dict[str, Any], statuses: set[str]) -> bool:
    if "problem" in statuses and _benchmark_game_is_problem(game):
        return True
    explicit = {status for status in statuses if status != "problem"}
    if not explicit:
        return False
    return _match_filter(game.get("status", "completed"), explicit)


def _benchmark_game_is_problem(game: dict[str, Any]) -> bool:
    status = str(game.get("status") or "").strip().lower()
    if status in {"failed", "timeout", "abnormal", "cancelled", "interrupted"}:
        return True
    if int(game.get("diagnostic_count") or 0) > 0:
        return True
    if game.get("error") or game.get("timeout") or game.get("abnormal"):
        return True
    for key in ("fallback", "llm_error", "policy_adjusted", "errors", "fallbacks", "llm_errors", "policy_adjustments"):
        if game.get(key):
            return True
    for key in ("error_count", "fallback_count", "llm_error_count", "policy_adjusted_count"):
        try:
            if int(game.get(key) or 0) > 0:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _benchmark_game_status(game: dict[str, Any]) -> str:
    status = str(game.get("status") or "").strip().lower()
    if status:
        return status
    if game.get("error") or game.get("failed"):
        return "failed"
    if game.get("timeout"):
        return "timeout"
    if game.get("abnormal"):
        return "abnormal"
    return "completed"


def _benchmark_game_summary(games: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(game.get("status") or "unknown") for game in games)
    return {
        "total": len(games),
        "by_status": dict(sorted(counts.items())),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "timeout": counts.get("timeout", 0),
        "abnormal": counts.get("abnormal", 0),
    }


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
        result_batch_id = _benchmark_result_batch_id(result) or f"{batch_id}_result_{index}"
        target_role = _benchmark_result_role(result)
        rankable = result.get("rankable")
        result_rows.append(
            {
                **summary,
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
            runtime = _json_clone(candidate)
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
    model_runtime = report.get("model_runtime") if isinstance(report.get("model_runtime"), dict) else {}
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
        "request": _json_clone(config),
        "planner": _json_clone(batch.get("run_plan") if isinstance(batch.get("run_plan"), dict) else {}),
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


def _benchmark_run_report_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# 评测运行报告：{_markdown_value(report.get('run_id'))}",
        "",
        "## 报告头",
        f"- 报告 ID: {_markdown_value(report.get('report_id'))}",
        f"- 运行 ID: {_markdown_value(report.get('run_id'))}",
        f"- 套件: {_markdown_value(report.get('suite', {}).get('label'))}",
        f"- 状态: {_markdown_value(report.get('status'))}",
        f"- 对象类型: {_markdown_value(report.get('suite', {}).get('target_type'))}",
        f"- 评测集: {_markdown_value(report.get('suite', {}).get('evaluation_set_id'))}",
        f"- 种子集: {_markdown_value(report.get('suite', {}).get('seed_set_id'))}",
        f"- 评测对象: {_markdown_value(report.get('subject', {}).get('label'))}",
        f"- 内容 Hash: {_markdown_value(report.get('content_hash'))}",
        "",
        "## 摘要",
    ]
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    game_summary = summary.get("game_summary") if isinstance(summary.get("game_summary"), dict) else {}
    diagnostic_summary = summary.get("diagnostic_summary") if isinstance(summary.get("diagnostic_summary"), dict) else {}
    lines.extend(
        [
            f"- 可入榜: {summary.get('rankable_count', 0)}/{summary.get('result_count', 0)}",
            f"- 结果数: {summary.get('result_count', 0)}",
            f"- 对局数: {game_summary.get('total', 0)}（{summary.get('problem_game_count', 0)} 个问题样本）",
            f"- 诊断数: {diagnostic_summary.get('total', 0)}",
            "",
            "## 门禁摘要",
        ]
    )
    gates = report.get("gates") if isinstance(report.get("gates"), list) else []
    lines.extend(
        [
            f"- {_markdown_value(row.get('title'))}: {_markdown_value(row.get('status'))} - {_markdown_value(row.get('reason'))}"
            for row in gates[:16]
            if isinstance(row, dict)
        ]
        or ["- 未加载门禁行"]
    )
    lines.extend(["", "## 问题对局"])
    problem_games = report.get("problem_games") if isinstance(report.get("problem_games"), list) else []
    lines.extend(
        [
            f"- {_markdown_value(game.get('game_id'))}: {_markdown_value(game.get('status'))} / 种子 {_markdown_value(game.get('seed'))} / 诊断 {game.get('diagnostic_count', 0)} / 回放 {_markdown_value(game.get('history_game_id') or game.get('replay_unavailable_reason') or '不可用')}"
            for game in problem_games[:8]
            if isinstance(game, dict)
        ]
        or ["- 未加载对局样本"]
    )
    lines.extend(["", "## 诊断与标签"])
    diagnostics = report.get("diagnostics") if isinstance(report.get("diagnostics"), list) else []
    tags = report.get("tags") if isinstance(report.get("tags"), list) else []
    if diagnostics:
        lines.extend(
            f"- {_markdown_value(group.get('label'))}: {group.get('total', 0)} ({_markdown_value(group.get('level'))})"
            for group in diagnostics[:12]
            if isinstance(group, dict)
        )
    elif tags:
        lines.extend(
            f"- {_markdown_value(tag.get('label'))}: {tag.get('count', 0)}"
            for tag in tags[:12]
            if isinstance(tag, dict)
        )
    else:
        lines.append("- 未加载诊断")
    lines.extend(["", "## 复现包"])
    reproducibility = report.get("reproducibility") if isinstance(report.get("reproducibility"), dict) else {}
    lines.extend(f"- {_markdown_value(key)}: {_markdown_value(value)}" for key, value in reproducibility.items())
    model_runtime = report.get("model_runtime") if isinstance(report.get("model_runtime"), dict) else {}
    if model_runtime:
        lines.extend(
            [
                "",
                "## 模型运行配置",
                f"- 来源: {_markdown_value(model_runtime.get('source'))}",
                f"- 模型 ID: {_markdown_value(model_runtime.get('model_id'))}",
                f"- 配置 Hash: {_markdown_value(model_runtime.get('model_config_hash'))}",
                f"- Hash 来源: {'请求提供' if model_runtime.get('hash_provided') else '后端自动生成'}",
            ]
        )
    return "\n".join(lines)


def _benchmark_run_report_csv(report: dict[str, Any]) -> str:
    rows: list[list[Any]] = [["区段", "标签", "值", "详情"]]
    suite = report.get("suite") if isinstance(report.get("suite"), dict) else {}
    subject = report.get("subject") if isinstance(report.get("subject"), dict) else {}
    rows.extend(
        [
            ["报告头", "运行 ID", report.get("run_id"), ""],
            ["报告头", "报告 ID", report.get("report_id"), ""],
            ["报告头", "套件", suite.get("label"), ""],
            ["报告头", "状态", report.get("status"), ""],
            ["报告头", "对象类型", suite.get("target_type"), ""],
            ["报告头", "评测集", suite.get("evaluation_set_id"), ""],
            ["报告头", "种子集", suite.get("seed_set_id"), ""],
            ["报告头", "评测对象", subject.get("label"), ""],
            ["报告头", "内容 Hash", report.get("content_hash"), ""],
        ]
    )
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}
    rows.extend(
        [
            ["摘要", "结果数", summary.get("result_count", 0), ""],
            ["摘要", "可入榜", summary.get("rankable_count", 0), f"{summary.get('unrankable_count', 0)} 个未入榜"],
            ["摘要", "问题对局", summary.get("problem_game_count", 0), ""],
        ]
    )
    for gate in report.get("gates", []) or []:
        if isinstance(gate, dict):
            rows.append(["门禁", gate.get("title"), gate.get("status"), gate.get("reason")])
    for game in report.get("problem_games", []) or []:
        if isinstance(game, dict):
            rows.append(
                [
                    "对局",
                    game.get("game_id"),
                    game.get("status"),
                    f"种子 {game.get('seed')} / 诊断 {game.get('diagnostic_count', 0)} / 日志 {game.get('history_game_id') or ''}",
                ]
            )
    for group in report.get("diagnostics", []) or []:
        if isinstance(group, dict):
            rows.append(["诊断", group.get("label"), group.get("total"), group.get("level")])
    reproducibility = report.get("reproducibility") if isinstance(report.get("reproducibility"), dict) else {}
    rows.extend(["复现包", key, value, ""] for key, value in reproducibility.items())
    model_runtime = report.get("model_runtime") if isinstance(report.get("model_runtime"), dict) else {}
    if model_runtime:
        rows.extend(
            [
                ["模型运行配置", "来源", model_runtime.get("source"), ""],
                ["模型运行配置", "模型 ID", model_runtime.get("model_id"), ""],
                ["模型运行配置", "配置 Hash", model_runtime.get("model_config_hash"), ""],
                ["模型运行配置", "Hash 来源", "请求提供" if model_runtime.get("hash_provided") else "后端自动生成", ""],
            ]
        )
    return "\n".join(",".join(_csv_value(value) for value in row) for row in rows)


def _markdown_value(value: Any) -> str:
    return str(value if value is not None else "--").replace("\n", " ").replace("|", "\\|")


def _csv_value(value: Any) -> str:
    text = str(value if value is not None else "")
    if any(char in text for char in [",", "\"", "\n", "\r"]):
        return '"' + text.replace('"', '""') + '"'
    return text


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


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _text_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _unique_texts(*values: Any) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _stable_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _text_content_hash(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


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
