"""Benchmark batch detail, report, game, and diagnostic service helpers."""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import HTTPException

from ui.backend.task_state import _filter_values, _match_filter, _pagination
from ui.backend.services.benchmark_report_exports import (
    _benchmark_run_report_csv,
    _benchmark_run_report_markdown,
    _text_content_hash,
)
from ui.backend.services.benchmark_report_payloads import (
    _benchmark_annotated_diagnostic,
    _benchmark_batch_boundary,
    _benchmark_batch_langfuse_summary,
    _benchmark_diagnostic_affected_games,
    _benchmark_diagnostic_aggregate_summary,
    _benchmark_diagnostic_entries,
    _benchmark_diagnostic_matches,
    _benchmark_diagnostic_run_payload,
    _benchmark_diagnostic_summary,
    _benchmark_game_matches_status_filter,
    _benchmark_game_summary,
    _benchmark_games_for_batch,
    _benchmark_report_history_summary,
    _benchmark_result_batch_id,
    _benchmark_result_game_count,
    _benchmark_result_role,
    _benchmark_results,
    _benchmark_run_report_payload,
    _benchmark_run_report_reproducibility_manifest,
    _benchmark_run_report_summary,
    _benchmark_run_sort_key,
    _dict_items,
    _json_clone,
    _text_items,
)
from ui.backend.services.benchmark_payload_utils import (
    sanitize_model_runtime,
    sanitize_model_runtime_containers,
)


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
                summary_payload = sanitize_model_runtime_containers(summary)
                result_summaries.append(
                    {
                        **summary_payload,
                        "result_batch_id": _benchmark_result_batch_id(result),
                        "target_role": _benchmark_result_role(result),
                        "game_count": _benchmark_result_game_count(result),
                        "diagnostic_count": len(_dict_items(result.get("diagnostics"))),
                        "warning_count": len(_text_items(result.get("warnings"))),
                    }
                )
        games = _benchmark_games_for_batch(batch)
        langfuse = _benchmark_batch_langfuse_summary(batch, games=games)
        batch_summary = sanitize_model_runtime_containers(_evolution_batch_summary(batch))
        run_plan = sanitize_model_runtime_containers(batch.get("run_plan") if isinstance(batch.get("run_plan"), dict) else {})
        return {
            "kind": "benchmark_batch_detail",
            "schema_version": 1,
            "batch": batch_summary,
            "batch_id": batch_id,
            "status": batch.get("status"),
            "benchmark": batch.get("benchmark"),
            "target_type": batch.get("target_type"),
            "model_runtime": sanitize_model_runtime(batch.get("model_runtime") or {}),
            "roles": list(batch.get("roles", []) or []),
            "run_plan": run_plan,
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
