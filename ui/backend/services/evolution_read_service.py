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
        runs = [_evolution_run_summary(run) for run in self._store.evolution_runs.values()]
        batches = [_evolution_batch_summary(batch) for batch in self._store.evolution_batches.values()]
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
            return run
        batch = self._store.evolution_batches.get(run_id)
        if batch is not None:
            return _evolution_batch_summary(batch)
        raise HTTPException(status_code=404, detail="run not found")

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


__all__ = ["EvolutionReadService", "EvolutionReadServiceStoreProtocol"]
