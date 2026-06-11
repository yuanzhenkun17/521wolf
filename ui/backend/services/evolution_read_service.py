"""Evolution run read/detail service for the UI backend."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from fastapi import HTTPException

from ui.backend.evolution_serializers import (
    _evolution_batch_summary,
    _evolution_games_for_query,
    _evolution_run_summary,
    _normalize_decision,
    _normalize_event,
    _sample_game_archive_payload,
)
from ui.backend.task_state import (
    _background_source,
    _filter_values,
    _history_time_key,
    _match_filter,
    _pagination,
)

_log = logging.getLogger(__name__)


class EvolutionReadServiceStoreProtocol(Protocol):
    evolution_runs: dict[str, dict[str, Any]]
    evolution_batches: dict[str, dict[str, Any]]


class EvolutionReadService:
    """Build evolution read/detail payloads while routes stay as HTTP adapters."""

    def __init__(self, store: EvolutionReadServiceStoreProtocol) -> None:
        self._store = store

    def list_runs(
        self,
        *,
        history_requested: bool,
        limit: int | None = None,
        offset: int = 0,
        source: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        task_rows = self._task_queue_rows(
            [*self._store.evolution_runs.values(), *self._store.evolution_batches.values()]
        )
        runs = [
            self._with_task_queue_state(_evolution_run_summary(run), run, task_rows=task_rows)
            for run in self._store.evolution_runs.values()
        ]
        batches = [
            self._with_task_queue_state(_evolution_batch_summary(batch), batch, task_rows=task_rows)
            for batch in self._store.evolution_batches.values()
        ]
        runs.sort(key=_history_time_key, reverse=True)
        batches.sort(key=_history_time_key, reverse=True)
        if source:
            sources = _filter_values(source)
            if sources is not None and "evolution" not in sources:
                runs = []
            if sources is not None:
                batches = [batch for batch in batches if _background_source(batch) in sources]
        statuses = _filter_values(status)
        if statuses is not None:
            runs = [run for run in runs if _match_filter(run.get("status"), statuses)]
            batches = [batch for batch in batches if _match_filter(batch.get("status"), statuses)]
        payload = {
            "kind": "evolution_runs",
            "schema_version": 1,
            "runs": runs,
            "batches": batches,
        }
        if not history_requested:
            return payload
        combined: list[tuple[str, dict[str, Any]]] = [
            *[("run", run) for run in runs],
            *[("batch", batch) for batch in batches],
        ]
        combined.sort(key=lambda item: _history_time_key(item[1]), reverse=True)
        page, pagination = _pagination([item for _, item in combined], limit=limit, offset=offset)
        page_ids = {str(item.get("run_id") or item.get("batch_id")) for item in page}
        payload["runs"] = [run for run in runs if str(run.get("run_id")) in page_ids]
        payload["batches"] = [batch for batch in batches if str(batch.get("batch_id")) in page_ids]
        payload["pagination"] = pagination
        return payload

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = self._store.evolution_runs.get(run_id)
        if run is not None:
            return self._with_task_queue_state(run, run)
        batch = self._store.evolution_batches.get(run_id)
        if batch is not None:
            return self._with_task_queue_state(_evolution_batch_summary(batch), batch)
        raise HTTPException(status_code=404, detail="run not found")

    def _with_task_queue_state(
        self,
        payload: dict[str, Any],
        entity: dict[str, Any],
        *,
        task_rows: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        task_id = str(entity.get("task_id") or "")
        if not task_id and entity.get("task_queue_status"):
            task_id = str(entity.get("run_id") or entity.get("batch_id") or "")
        if not task_id:
            return payload
        task = task_rows.get(task_id) if task_rows is not None else self._task_queue_row(task_id)
        if task is None:
            if entity.get("task_id") or entity.get("task_queue_status"):
                payload.setdefault("task_id", task_id)
                payload.setdefault("task_queue_status", entity.get("task_queue_status"))
            return payload
        task_status = str(task.get("status") or "")
        task_progress = task.get("progress") if isinstance(task.get("progress"), dict) else {}
        existing_progress = payload.get("progress") if isinstance(payload.get("progress"), dict) else {}
        progress = dict(existing_progress)
        if task_progress:
            progress.update(task_progress)
        progress.setdefault("stage", task_progress.get("stage") or payload.get("current_stage") or task_status)
        progress["task_status"] = task_status
        if task.get("updated_at"):
            progress["updated_at"] = task.get("updated_at")

        entity_id = str(entity.get("run_id") or entity.get("batch_id") or "")
        direct_task = task_id == entity_id
        overlaid = dict(payload)
        overlaid["task_id"] = task_id
        overlaid["task_kind"] = task.get("kind")
        overlaid["task_queue_status"] = task_status
        overlaid["task_cancel_requested"] = bool(task.get("cancel_requested"))
        artifact_ids = _task_artifact_ids(task)
        if artifact_ids and direct_task:
            overlaid["task_artifact_ids"] = artifact_ids
        if not direct_task:
            return overlaid
        overlaid["progress"] = progress
        overlaid["current_stage"] = str(progress.get("stage") or overlaid.get("current_stage") or task_status)
        overlaid["status"] = self._status_with_task_queue(entity, task)
        overlaid["last_heartbeat_at"] = task.get("updated_at") or overlaid.get("last_heartbeat_at")
        if task.get("started_at"):
            overlaid.setdefault("started_at", task.get("started_at"))
        if task.get("finished_at"):
            overlaid["finished_at"] = task.get("finished_at")
        if task.get("error") and (task_status in {"failed", "cancelled", "interrupted"} or not overlaid.get("error")):
            overlaid["error"] = task.get("error")
        existing_overall = overlaid.get("overall_progress") if isinstance(overlaid.get("overall_progress"), dict) else {}
        overall = dict(existing_overall)
        overall["stage"] = overlaid["current_stage"]
        overall["updated_at"] = progress.get("updated_at")
        if "percent" in progress:
            overall["percent"] = progress["percent"]
        overlaid["overall_progress"] = overall
        overlaid["stage_progress"] = dict(progress)
        return overlaid

    def _task_queue_rows(self, entities: list[dict[str, Any]]) -> dict[str, dict[str, Any]] | None:
        task_ids = {
            str(entity.get("task_id") or entity.get("run_id") or entity.get("batch_id") or "")
            for entity in entities
            if entity.get("task_id") or entity.get("task_queue_status")
        }
        task_ids.discard("")
        if not task_ids:
            return {}
        task_service = getattr(self._store, "task_service", None)
        getter = getattr(task_service, "get_task_queue_rows", None)
        if not callable(getter):
            return None
        try:
            tasks = getter(task_ids)
        except Exception as exc:  # noqa: BLE001 - task queue state is an optional overlay
            _log.debug("failed to batch load task queue rows: %s", exc)
            return {}
        return tasks if isinstance(tasks, dict) else {}

    def _task_queue_row(self, task_id: str) -> dict[str, Any] | None:
        task_service = getattr(self._store, "task_service", None)
        getter = getattr(task_service, "get_task_queue_row", None)
        if not callable(getter):
            return None
        try:
            task = getter(task_id)
        except Exception as exc:  # noqa: BLE001 - task queue state is an overlay, not the runtime source of truth
            _log.debug("failed to load task queue row for evolution entity %s: %s", task_id, exc)
            return None
        return task if isinstance(task, dict) else None

    @staticmethod
    def _status_with_task_queue(entity: dict[str, Any], task: dict[str, Any]) -> str:
        task_status = str(task.get("status") or "")
        if task_status == "succeeded":
            result = task.get("result") if isinstance(task.get("result"), dict) else {}
            return str(result.get("status") or entity.get("status") or "completed")
        if task_status in {"queued", "running", "failed", "cancelled", "interrupted"}:
            return task_status
        return str(entity.get("status") or task_status)

    @staticmethod
    def trust_bundle_payload_from_run(run: dict[str, Any]) -> dict[str, Any] | None:
        bundle = run.get("trust_bundle")
        if not isinstance(bundle, dict) and isinstance(run.get("result"), dict):
            bundle = run["result"].get("trust_bundle")
        if not isinstance(bundle, dict) and isinstance(run.get("battle_result"), dict):
            bundle = run["battle_result"].get("trust_bundle")
        if not isinstance(bundle, dict):
            return None
        return {
            "kind": "evolution_trust_bundle",
            "schema_version": 1,
            "trust_bundle_id": bundle.get("trust_bundle_id"),
            "run_id": run.get("run_id") or bundle.get("run_id"),
            "role": run.get("role") or bundle.get("role"),
            "baseline_version": bundle.get("baseline_version"),
            "candidate_version": bundle.get("candidate_version"),
            "bundle_hash": bundle.get("bundle_hash"),
            "gate_report_id": bundle.get("gate_report_id"),
            "attribution_report_id": bundle.get("attribution_report_id"),
            "created_at": run.get("started_at"),
            "updated_at": run.get("finished_at") or run.get("last_heartbeat_at") or run.get("started_at"),
            "trust_bundle": bundle,
        }

    def trust_bundle_payload(self, run_id: str) -> dict[str, Any]:
        if run_id in self._store.evolution_batches:
            raise HTTPException(status_code=400, detail="batch does not support trust bundle; select a child run")
        run = self._store.evolution_runs.get(run_id)
        try:
            from storage.evolution.state_gateway import EvolutionStateGateway

            payload = EvolutionStateGateway(paths=getattr(self._store, "paths", None)).get_trust_bundle(run_id)
            if isinstance(payload, dict):
                return payload
        except Exception as exc:  # noqa: BLE001 - API falls back to in-memory run artifact
            _log.debug("failed to load trust bundle from PostgreSQL for %s: %s", run_id, exc)

        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        payload = self.trust_bundle_payload_from_run(run)
        if payload is None:
            raise HTTPException(status_code=404, detail="trust bundle not found")
        return payload

    def diff(self, run_id: str) -> dict[str, Any]:
        run = self._store.evolution_runs.get(run_id)
        if run is None:
            if run_id in self._store.evolution_batches:
                raise HTTPException(status_code=400, detail="batch does not support diff; select a child run")
            raise HTTPException(status_code=404, detail="run not found")
        return {"kind": "role_evolution_diff", "schema_version": 1, "run_id": run_id, "diffs": run.get("diff", [])}

    def games(
        self,
        run_id: str,
        *,
        phase: str = "training",
        side: str | None = None,
        limit: int | None = None,
        offset: int = 0,
        status: str | None = None,
        paginate: bool,
    ) -> dict[str, Any]:
        run = self._store.evolution_runs.get(run_id)
        if run is None:
            if run_id in self._store.evolution_batches:
                raise HTTPException(status_code=400, detail="batch does not support games; select a child run")
            raise HTTPException(status_code=404, detail="run not found")
        games = _evolution_games_for_query(run, phase=phase, side=side)
        statuses = _filter_values(status)
        if statuses is not None:
            games = [game for game in games if _match_filter(game.get("status", "completed"), statuses)]
        payload = {
            "kind": "role_evolution_games",
            "schema_version": 1,
            "run_id": run_id,
            "phase": phase,
            "side": side,
            "games": games,
        }
        if not paginate:
            return payload
        page, pagination = _pagination(games, limit=limit, offset=offset)
        payload["games"] = page
        payload["pagination"] = pagination
        return payload

    def game_detail(
        self,
        run_id: str,
        game_id: str,
        detail_type: str,
        *,
        phase: str = "training",
        side: str | None = None,
    ) -> dict[str, Any]:
        run = self._store.evolution_runs.get(run_id)
        if run is None:
            if run_id in self._store.evolution_batches:
                raise HTTPException(status_code=400, detail="batch does not support game details; select a child run")
            raise HTTPException(status_code=404, detail="run not found")
        games = _evolution_games_for_query(run, phase=phase, side=side, include_details=True)
        game = next((item for item in games if item.get("game_id") == game_id or item.get("id") == game_id), None)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        if detail_type == "archive":
            return _sample_game_archive_payload(run_id, game_id, game, phase=phase, side=side)
        if detail_type == "decisions":
            return {
                "run_id": run_id,
                "game_id": game_id,
                "decisions": [
                    _normalize_decision(decision, index)
                    for index, decision in enumerate(game.get("decisions", []) or [], start=1)
                ],
            }
        if detail_type == "events":
            return {
                "run_id": run_id,
                "game_id": game_id,
                "events": [_normalize_event(event) for event in game.get("events", []) or []],
            }
        raise HTTPException(status_code=404, detail="detail type not found")


def _task_artifact_ids(task: dict[str, Any]) -> list[str]:
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    values = result.get("artifact_ids")
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if str(value)]


__all__ = ["EvolutionReadService", "EvolutionReadServiceStoreProtocol"]
