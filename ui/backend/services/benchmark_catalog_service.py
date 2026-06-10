"""Benchmark catalog service for suites, lifecycle overrides, and seed sets."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol

from fastapi import HTTPException

from app.lib.benchmark_spec import (
    BenchmarkSeedSet,
    BenchmarkSpec,
    BenchmarkSpecError,
    LAUNCHABLE_BENCHMARK_STATUSES,
    VALID_BENCHMARK_STATUSES,
    benchmark_config_hash,
    benchmark_seed_registry_summary,
    benchmark_seed_set_summary,
    benchmark_spec_summary,
    list_benchmark_seed_sets as load_benchmark_seed_sets,
    list_benchmark_specs as load_benchmark_specs,
    load_benchmark_seed_set,
    load_benchmark_spec,
    materialize_benchmark_spec,
    seed_set_config_hash,
)
from app.util.time import beijing_now_iso
from ui.backend.errors import domain_error_detail
from ui.backend.schemas import BenchmarkLifecycleRequest, BenchmarkRequest


class BenchmarkCatalogContextProtocol(Protocol):
    """Context capabilities required by ``BenchmarkCatalogService``."""

    paths: Any


class BenchmarkCatalogService:
    """Own benchmark catalog reads, lifecycle overrides, and seed-set summaries."""

    def __init__(self, context: BenchmarkCatalogContextProtocol) -> None:
        self._context = context

    @property
    def paths(self) -> Any:
        return self._context.paths

    def list_benchmark_specs(self) -> list[dict[str, Any]]:
        """Return configured benchmark suite summaries for API/UI use."""
        return _annotate_benchmark_suite_lineage(
            self._benchmark_spec_summaries(include_activity=True, skip_invalid=False)
        )

    def get_benchmark_spec_summary(self, benchmark_id: str) -> dict[str, Any]:
        """Return a single benchmark suite summary."""
        try:
            spec, lifecycle_override = self.benchmark_spec_with_lifecycle(benchmark_id)
            summary = self._benchmark_spec_summary_from_spec(
                spec,
                lifecycle_override=lifecycle_override,
                include_activity=True,
            )
            self._apply_benchmark_suite_lineage(summary)
            return summary
        except BenchmarkSpecError as exc:
            status = 404 if "not found" in str(exc) else 422
            detail = "benchmark not found" if status == 404 else str(exc)
            raise HTTPException(status_code=status, detail=detail) from exc

    def update_benchmark_lifecycle(
        self,
        benchmark_id: str,
        request: BenchmarkLifecycleRequest,
    ) -> dict[str, Any]:
        """Persist a runtime lifecycle override for a benchmark suite."""
        normalized_id = str(benchmark_id or "").strip()
        if not normalized_id:
            raise HTTPException(status_code=404, detail="benchmark not found")
        status = str(request.status or "").strip().lower()
        if status not in VALID_BENCHMARK_STATUSES:
            raise HTTPException(status_code=422, detail="unsupported benchmark lifecycle status")
        try:
            original = load_benchmark_spec(normalized_id, self.paths)
        except BenchmarkSpecError as exc:
            status_code = 404 if "not found" in str(exc) else 422
            detail = "benchmark not found" if status_code == 404 else str(exc)
            raise HTTPException(status_code=status_code, detail=detail) from exc
        now = beijing_now_iso()
        override = {
            "benchmark_id": original.id,
            "status": status,
            "enabled": status in LAUNCHABLE_BENCHMARK_STATUSES,
            "reason": str(request.reason or ""),
            "updated_at": now,
        }
        overrides = self._benchmark_lifecycle_overrides()
        overrides[original.id] = override
        self._persist_benchmark_lifecycle_overrides(overrides)
        spec, applied_override = _apply_benchmark_lifecycle_override(original, override)
        try:
            summary = self._benchmark_spec_summary_from_spec(
                spec,
                lifecycle_override=applied_override,
                include_activity=True,
            )
            self._apply_benchmark_suite_lineage(summary)
            return {
                "kind": "benchmark_suite_lifecycle",
                "schema_version": 1,
                "benchmark_id": original.id,
                "status": summary["status"],
                "launchable": summary["launchable"],
                "item": summary,
            }
        except BenchmarkSpecError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def list_benchmark_seed_sets(self) -> dict[str, Any]:
        """Return configured benchmark seed-set registry summaries for API/UI use."""
        seed_sets = load_benchmark_seed_sets(self.paths, include_disabled=True)
        return benchmark_seed_registry_summary(seed_sets)

    def get_benchmark_seed_set(self, seed_set_id: str) -> dict[str, Any]:
        """Return one benchmark seed set with full seeds for audit views."""
        try:
            seed_set = load_benchmark_seed_set(seed_set_id, self.paths, include_disabled=True)
            registry = benchmark_seed_registry_summary(
                load_benchmark_seed_sets(self.paths, include_disabled=True)
            )
            registry_item = next(
                (item for item in registry["items"] if item.get("id") == seed_set.id),
                {},
            )
            item = benchmark_seed_set_summary(seed_set)
            item["seeds"] = list(seed_set.seeds)
            item["overlap_warnings"] = list(registry_item.get("overlap_warnings") or [])
            return {
                "kind": "benchmark_seed_set",
                "schema_version": 1,
                "item": item,
            }
        except BenchmarkSpecError as exc:
            status = 404 if "not found" in str(exc) else 422
            detail = "benchmark seed set not found" if status == 404 else str(exc)
            raise HTTPException(status_code=status, detail=detail) from exc

    def benchmark_spec_with_lifecycle(self, benchmark_id: str) -> tuple[BenchmarkSpec, dict[str, Any] | None]:
        spec = load_benchmark_spec(benchmark_id, self.paths)
        override = self._benchmark_lifecycle_overrides().get(spec.id)
        return _apply_benchmark_lifecycle_override(spec, override)

    def resolve_benchmark_spec(
        self,
        request: BenchmarkRequest,
    ) -> tuple[BenchmarkSpec | None, BenchmarkSeedSet | None]:
        if not request.benchmark_id:
            return None, None
        try:
            spec, _lifecycle_override = self.benchmark_spec_with_lifecycle(request.benchmark_id)
            spec, seed_set = materialize_benchmark_spec(spec, paths=self.paths)
            if not spec.launchable:
                reason = benchmark_spec_summary(spec, seed_set).get("launch_disabled_reason") or (
                    f"benchmark suite status={spec.lifecycle_status} cannot be launched"
                )
                raise HTTPException(
                    status_code=409,
                    detail=domain_error_detail(
                        code="benchmark_suite_not_launchable",
                        message="Benchmark suite cannot be launched.",
                        detail=reason,
                        diagnostics=[
                            {
                                "kind": "benchmark_suite_not_launchable",
                                "benchmark_id": spec.id,
                                "status": spec.lifecycle_status,
                            }
                        ],
                    ),
                )
            return spec, seed_set
        except BenchmarkSpecError as exc:
            status = 404 if "not found" in str(exc) else 422
            detail = "benchmark not found" if status == 404 else str(exc)
            raise HTTPException(status_code=status, detail=detail) from exc

    @staticmethod
    def benchmark_summary(spec: BenchmarkSpec, seed_set: BenchmarkSeedSet | None = None) -> dict[str, Any]:
        return benchmark_spec_summary(spec, seed_set)

    @staticmethod
    def benchmark_metadata(spec: BenchmarkSpec, seed_set: BenchmarkSeedSet | None = None) -> dict[str, Any]:
        snapshot = spec.model_dump(mode="json")
        meta = {
            "id": spec.id,
            "version": spec.version,
            "target_type": spec.target_type,
            "config_hash": benchmark_config_hash(snapshot),
            "evaluation_set_id": spec.evaluation_set_id,
            "seed_set_id": spec.seed_set_id,
            "seed_count": len(snapshot.get("seeds") or []) or spec.game_count,
            "seed_preview": list(snapshot.get("seeds") or [])[:5],
            "spec_snapshot": snapshot,
        }
        if seed_set is not None:
            seed_snapshot = seed_set.model_dump(mode="json")
            meta["seed_set"] = benchmark_seed_set_summary(seed_set)
            meta["seed_set_version"] = seed_set.version
            meta["seed_set_config_hash"] = seed_set_config_hash(seed_snapshot)
            meta["seed_set_tier"] = seed_set.tier
            meta["seed_set_usage_boundary"] = seed_set.usage_boundary
            meta["seed_set_immutable"] = seed_set.immutable
            meta["seed_set_non_overlap_group"] = seed_set.non_overlap_group
            meta["seed_set_snapshot"] = seed_snapshot
        return meta

    def _benchmark_spec_summaries(
        self,
        *,
        include_activity: bool,
        skip_invalid: bool,
    ) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        overrides = self._benchmark_lifecycle_overrides()
        for spec in load_benchmark_specs(self.paths, include_inactive=True):
            try:
                spec, lifecycle_override = _apply_benchmark_lifecycle_override(spec, overrides.get(spec.id))
                summary = self._benchmark_spec_summary_from_spec(
                    spec,
                    lifecycle_override=lifecycle_override,
                    include_activity=include_activity,
                )
                summaries.append(summary)
            except BenchmarkSpecError:
                if skip_invalid:
                    continue
                raise
        return summaries

    def _benchmark_spec_summary_from_spec(
        self,
        spec: BenchmarkSpec,
        *,
        lifecycle_override: dict[str, Any] | None,
        include_activity: bool,
    ) -> dict[str, Any]:
        materialized, seed_set = materialize_benchmark_spec(spec, paths=self.paths)
        summary = benchmark_spec_summary(materialized, seed_set)
        summary["lifecycle_override"] = _json_clone(lifecycle_override) if lifecycle_override else None
        if include_activity:
            summary.update(self._benchmark_suite_activity(summary))
        return summary

    def _apply_benchmark_suite_lineage(self, summary: dict[str, Any]) -> dict[str, Any]:
        lineage_summaries = self._benchmark_spec_summaries(include_activity=False, skip_invalid=True)
        if not any(item.get("id") == summary.get("id") for item in lineage_summaries):
            lineage_summaries.append(_json_clone(summary))
        _annotate_benchmark_suite_lineage(lineage_summaries)
        matched = next((item for item in lineage_summaries if item.get("id") == summary.get("id")), None)
        if matched:
            _copy_benchmark_suite_lineage(summary, matched)
        return summary

    def _benchmark_lifecycle_overrides_path(self) -> Any:
        return self.paths.data_dir / "benchmark_suite_lifecycle_overrides.json"

    def _benchmark_lifecycle_overrides(self) -> dict[str, dict[str, Any]]:
        path = self._benchmark_lifecycle_overrides_path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - normalize runtime state read failures
            raise HTTPException(status_code=500, detail=f"failed to read benchmark lifecycle overrides: {exc}") from exc
        raw_items = payload.get("items") if isinstance(payload, dict) else {}
        if not isinstance(raw_items, dict):
            return {}
        overrides: dict[str, dict[str, Any]] = {}
        for key, value in raw_items.items():
            if not isinstance(value, dict):
                continue
            benchmark_id = str(value.get("benchmark_id") or key or "").strip()
            status = str(value.get("status") or "").strip().lower()
            if not benchmark_id or status not in VALID_BENCHMARK_STATUSES:
                continue
            overrides[benchmark_id] = {
                "benchmark_id": benchmark_id,
                "status": status,
                "enabled": bool(value.get("enabled", status in LAUNCHABLE_BENCHMARK_STATUSES)),
                "reason": str(value.get("reason") or ""),
                "updated_at": str(value.get("updated_at") or ""),
            }
        return overrides

    def _persist_benchmark_lifecycle_overrides(self, overrides: dict[str, dict[str, Any]]) -> None:
        path = self._benchmark_lifecycle_overrides_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "kind": "benchmark_suite_lifecycle_overrides",
            "schema_version": 1,
            "items": {
                benchmark_id: _json_clone(override)
                for benchmark_id, override in sorted(overrides.items())
            },
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _benchmark_suite_activity(self, summary: dict[str, Any]) -> dict[str, Any]:
        benchmark_id = str(summary.get("id") or summary.get("benchmark_id") or "")
        evaluation_set_id = str(summary.get("evaluation_set_id") or "")
        batches = getattr(self._context, "evolution_batches", {})
        if isinstance(batches, Mapping):
            batch_values = batches.values()
        else:
            batch_values = []
        runs = [
            batch for batch in batch_values
            if isinstance(batch, dict)
            and _is_benchmark_suite_batch(batch, benchmark_id=benchmark_id, evaluation_set_id=evaluation_set_id)
        ]
        latest_run = _benchmark_latest_run_payload(runs[0]) if runs else None
        if len(runs) > 1:
            runs.sort(key=_benchmark_run_sort_key, reverse=True)
            latest_run = _benchmark_latest_run_payload(runs[0])
        snapshots = self._load_benchmark_snapshot_summaries(
            benchmark_id=benchmark_id or None,
            evaluation_set_id=evaluation_set_id or None,
            limit=1,
        )
        return {
            "last_run": latest_run,
            "latest_snapshot": snapshots[0] if snapshots else None,
        }

    def _load_benchmark_snapshot_summaries(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        loader = getattr(self._context, "_load_benchmark_snapshot_summaries", None)
        if not callable(loader):
            return []
        return loader(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            benchmark_id=benchmark_id,
            target_role=target_role,
            limit=limit,
        )


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _apply_benchmark_lifecycle_override(
    spec: BenchmarkSpec,
    override: dict[str, Any] | None,
) -> tuple[BenchmarkSpec, dict[str, Any] | None]:
    if not isinstance(override, dict) or not override:
        return spec, None
    status = str(override.get("status") or "").strip().lower()
    if status not in VALID_BENCHMARK_STATUSES:
        return spec, None
    applied = {
        "benchmark_id": spec.id,
        "status": status,
        "enabled": bool(override.get("enabled", status in LAUNCHABLE_BENCHMARK_STATUSES)),
        "reason": str(override.get("reason") or ""),
        "updated_at": str(override.get("updated_at") or ""),
    }
    return spec.model_copy(update={"status": status, "enabled": applied["enabled"]}), applied


def _benchmark_suite_lineage_key(item: dict[str, Any]) -> tuple[str, str]:
    target_type = str(item.get("target_type") or "role_version")
    family_id = str(item.get("suite_family_id") or item.get("id") or item.get("benchmark_id") or "")
    return target_type, family_id


def _benchmark_suite_lineage_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "version": item.get("version"),
        "suite_version": item.get("suite_version") or f"v{item.get('version')}",
        "evaluation_set_id": item.get("evaluation_set_id"),
        "config_hash": item.get("config_hash"),
        "status": item.get("status"),
        "launchable": bool(item.get("launchable")),
        "seed_set_id": item.get("seed_set_id"),
        "seed_set_config_hash": (item.get("seed_set") or {}).get("config_hash")
        if isinstance(item.get("seed_set"), dict)
        else None,
    }


def _copy_benchmark_suite_lineage(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key in (
        "suite_family_id",
        "suite_version",
        "version_lineage",
        "version_count",
        "latest_version",
        "latest_launchable_version",
        "is_latest_version",
        "is_latest_launchable_version",
    ):
        target[key] = _json_clone(source.get(key))


def _annotate_benchmark_suite_lineage(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for item in summaries:
        groups.setdefault(_benchmark_suite_lineage_key(item), []).append(item)
    for items in groups.values():
        ordered = sorted(
            items,
            key=lambda item: (int(item.get("version") or 0), str(item.get("id") or "")),
            reverse=True,
        )
        lineage = [_benchmark_suite_lineage_item(item) for item in ordered]
        latest = next((entry for entry in lineage if entry.get("id")), lineage[0] if lineage else None)
        latest_launchable = next((entry for entry in lineage if entry.get("launchable")), None)
        latest_id = latest.get("id") if latest else None
        latest_launchable_id = latest_launchable.get("id") if latest_launchable else None
        for item in items:
            item["version_lineage"] = _json_clone(lineage)
            item["version_count"] = len(lineage)
            item["latest_version"] = _json_clone(latest) if latest else None
            item["latest_launchable_version"] = _json_clone(latest_launchable) if latest_launchable else None
            item["is_latest_version"] = bool(latest_id and item.get("id") == latest_id)
            item["is_latest_launchable_version"] = bool(latest_launchable_id and item.get("id") == latest_launchable_id)
    return summaries


def _is_benchmark_suite_batch(
    batch: dict[str, Any],
    *,
    benchmark_id: str,
    evaluation_set_id: str,
) -> bool:
    if not isinstance(batch, dict):
        return False
    if batch.get("kind") != "benchmark_batch":
        return False
    benchmark = batch.get("benchmark") if isinstance(batch.get("benchmark"), dict) else {}
    config = batch.get("config") if isinstance(batch.get("config"), dict) else {}
    batch_benchmark_id = str(benchmark.get("id") or batch.get("benchmark_id") or "")
    batch_evaluation_set_id = str(
        benchmark.get("evaluation_set_id")
        or batch.get("evaluation_set_id")
        or config.get("evaluation_set_id")
        or ""
    )
    if benchmark_id and batch_benchmark_id != benchmark_id:
        return False
    if evaluation_set_id and batch_evaluation_set_id != evaluation_set_id:
        return False
    return True


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
