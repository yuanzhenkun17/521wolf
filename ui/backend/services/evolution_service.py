"""Evolution read/proposal service for the UI backend."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any, Protocol

from fastapi import HTTPException

from app.util.time import beijing_now_iso
from ui.backend.constants import MANUAL_STOP_REASON
from ui.backend.evolution_actions import (
    _promote_evolution_run,
    _reject_evolution_run,
    accept_evolution_proposal,
    apply_accepted_evolution_proposals,
)
from ui.backend.evolution_serializers import (
    _evolution_batch_summary,
    _evolution_games_for_query,
    _evolution_run_summary,
    _evolution_sse_event,
    _normalize_decision,
    _normalize_event,
    _sample_game_archive_payload,
)
from ui.backend.schemas import normalize_rejection_tags
from ui.backend.services.task_service import BackgroundTaskServiceProtocol
from ui.backend.sse import _sse, stream_task_event_log_sse, task_event_log_matches_entity
from ui.backend.task_state import (
    _background_source,
    _filter_values,
    _history_time_key,
    _match_filter,
    _pagination,
    _set_task_contract,
)

_log = logging.getLogger(__name__)
_TERMINAL_TASK_STATUSES = {"reviewing", "promoted", "rejected", "failed", "completed", "cancelled", "interrupted"}
_FINISHED_ACTION_STATUSES = {"failed", "promoted", "rejected", "reviewing"}
_TERMINAL_SSE_STATUSES = {"reviewing", "promoted", "rejected", "failed", "completed", "cancelled", "interrupted"}


class EvolutionServiceStoreProtocol(Protocol):
    evolution_runs: dict[str, dict[str, Any]]
    evolution_batches: dict[str, dict[str, Any]]
    registry: Any

    @property
    def task_service(self) -> BackgroundTaskServiceProtocol:
        ...


class EvolutionService:
    """Build evolution API payloads while routes stay as HTTP adapters."""

    def __init__(self, store: EvolutionServiceStoreProtocol) -> None:
        self._store = store
        self._tasks = store.task_service

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

    def stream_events(self, run_id: str, last_event_id: int) -> AsyncIterator[str]:
        entity = self._store.evolution_runs.get(run_id) or self._store.evolution_batches.get(run_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="run not found")
        task_event_log = self._tasks.task_event_log

        async def stream() -> AsyncIterator[str]:
            if task_event_log_matches_entity(
                task_event_log,
                run_id,
                entity,
                terminal_statuses=_TERMINAL_SSE_STATUSES,
            ):
                async for frame in stream_task_event_log_sse(
                    task_event_log,
                    run_id,
                    after_event_id=last_event_id,
                    ping_payload=lambda: {"run_id": run_id, "status": entity.get("status")},
                    event_name=lambda item: str(item.get("event") or _evolution_sse_event(item.get("status"))),
                    terminal_statuses=_TERMINAL_SSE_STATUSES,
                ):
                    yield frame
                return
            payload = (
                _evolution_run_summary(entity)
                if entity.get("run_id")
                else _evolution_batch_summary(entity)
            )
            if last_event_id < 1:
                yield _sse(_evolution_sse_event(entity.get("status")), payload, event_id=1)

        return stream()

    def run_action(self, run_id: str, action: str) -> dict[str, Any]:
        entity = self._action_entity(run_id)
        action = action.lower()
        if action == "promote":
            return self._promote_run_entity(entity)
        if action == "reject":
            return self._reject_run_entity(entity)
        if action in {"stop", "terminate"}:
            return self._stop_run_entity(entity)
        if action == "resume":
            return self._resume_run_entity(entity)
        return self._persist_run_action_mutation(entity)

    def promote_run(self, run_id: str) -> dict[str, Any]:
        return self._promote_run_entity(self._action_entity(run_id))

    def reject_run(self, run_id: str) -> dict[str, Any]:
        return self._reject_run_entity(self._action_entity(run_id))

    def stop_run(self, run_id: str) -> dict[str, Any]:
        return self._stop_run_entity(self._action_entity(run_id))

    def resume_run(self, run_id: str) -> dict[str, Any]:
        return self._resume_run_entity(self._action_entity(run_id))

    def _promote_run_entity(self, entity: dict[str, Any]) -> dict[str, Any]:
        if "role" not in entity:
            raise HTTPException(status_code=400, detail="batch does not support promote; select a child run")
        _promote_evolution_run(self._store, entity)
        entity["status"] = "promoted"
        return self._persist_run_action_mutation(entity)

    def _reject_run_entity(self, entity: dict[str, Any]) -> dict[str, Any]:
        if "role" not in entity:
            raise HTTPException(status_code=400, detail="batch does not support reject; select a child run")
        _reject_evolution_run(self._store, entity)
        entity["status"] = "rejected"
        return self._persist_run_action_mutation(entity)

    def _stop_run_entity(self, entity: dict[str, Any]) -> dict[str, Any]:
        if hasattr(self._store, "_mark_evolution_stopped"):
            self._store._mark_evolution_stopped(entity)
            if entity.get("kind") == "role_evolution_batch":
                for child_id in list(entity.get("runs", []) or []):
                    child = self._store.evolution_runs.get(str(child_id))
                    if child is None:
                        continue
                    if str(child.get("status") or "").lower() not in _TERMINAL_TASK_STATUSES:
                        self._store._mark_evolution_stopped(child)
                self._store._refresh_evolution_batch(entity.get("batch_id"))
        else:
            entity["status"] = "failed"
            entity["error"] = entity.get("error") or MANUAL_STOP_REASON
            _set_task_contract(entity, stop_requested=True, cancelled=True, interrupted=False, failed=False)
        return self._persist_run_action_mutation(entity)

    def _resume_run_entity(self, entity: dict[str, Any]) -> dict[str, Any]:
        entity["status"] = "reviewing"
        _set_task_contract(entity, stop_requested=False, cancelled=False, interrupted=False, failed=False)
        return self._persist_run_action_mutation(entity)

    def _action_entity(self, run_id: str) -> dict[str, Any]:
        entity = self._store.evolution_runs.get(run_id) or self._store.evolution_batches.get(run_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="run not found")
        return entity

    def _persist_run_action_mutation(self, entity: dict[str, Any]) -> dict[str, Any]:
        self._tasks.touch_background_task(entity)
        if entity.get("status") in _FINISHED_ACTION_STATUSES:
            entity["finished_at"] = entity.get("finished_at") or beijing_now_iso()
        self._tasks.persist_background_tasks()
        return entity

    def proposal_run(self, run_id: str) -> dict[str, Any]:
        run = self._store.evolution_runs.get(run_id)
        if run is not None:
            return run
        if run_id in self._store.evolution_batches:
            raise HTTPException(status_code=400, detail="batch does not support proposals; select a child run")
        raise HTTPException(status_code=404, detail="run not found")

    @staticmethod
    def proposal_pairs(run: dict[str, Any]) -> list[dict[str, Any]]:
        battle = run.get("battle_result") if isinstance(run.get("battle_result"), dict) else {}
        for value in (
            run.get("paired_seed_pairs"),
            run.get("paired_seed_battle_table"),
            run.get("battle_pairs"),
            battle.get("paired_seed_pairs"),
            battle.get("paired_seed_battle_table"),
            battle.get("battle_pairs"),
        ):
            if isinstance(value, list):
                return [dict(item) for item in value if isinstance(item, dict)]
        return []

    @classmethod
    def proposal_payload(cls, run: dict[str, Any], *, action: dict[str, Any] | None = None) -> dict[str, Any]:
        summary = _evolution_run_summary(run)
        review = summary.get("proposal_review") if isinstance(summary.get("proposal_review"), dict) else {}
        pairs = cls.proposal_pairs(run)
        payload: dict[str, Any] = {
            "kind": "role_evolution_proposals",
            "schema_version": 1,
            "run_id": run.get("run_id"),
            "role": run.get("role"),
            "proposals": [dict(item) for item in run.get("proposals", []) or [] if isinstance(item, dict)],
            "generated_proposal_ids": list(review.get("generated_proposal_ids", []) or []),
            "preflight_passed_proposal_ids": list(review.get("preflight_passed_proposal_ids", []) or []),
            "accepted_proposal_ids": list(review.get("accepted_proposal_ids", []) or []),
            "rejected_proposal_ids": list(review.get("rejected_proposal_ids", []) or []),
            "applied_proposal_ids": list(review.get("applied_proposal_ids", []) or []),
            "proposal_review": review,
            "gate_report": summary.get("gate_report", {}),
            "release_gate": summary.get("release_gate", {}),
            "release_decision": summary.get("release_decision"),
            "trust_bundle": summary.get("trust_bundle", {}),
            "scenario_replay_report": summary.get("scenario_replay_report", {}),
            "scenario_replay_summary": summary.get("scenario_replay_summary", {}),
            "proposal_attribution_report": summary.get("proposal_attribution_report", {}),
            "promotion_gate": summary.get("promotion_gate", {}),
            "paired_seed_summary": summary.get("paired_seed_summary", {}),
            "paired_seed_pairs": pairs,
            "paired_seed_battle_table": pairs,
            "paired_seeds": pairs,
            "battle_pairs": pairs,
            "run": summary,
        }
        if action is not None:
            payload["action"] = action
        return payload

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

    def persist_proposal_mutation(self, run: dict[str, Any]) -> None:
        self._tasks.touch_background_task(run)
        self._tasks.persist_background_tasks()

    def proposals(self, run_id: str) -> dict[str, Any]:
        return self.proposal_payload(self.proposal_run(run_id))

    def accept_proposal(self, run_id: str, proposal_id: str) -> dict[str, Any]:
        run = self.proposal_run(run_id)
        action = accept_evolution_proposal(self._store, run, proposal_id)
        self.persist_proposal_mutation(run)
        return self.proposal_payload(run, action=action)

    def reject_proposal(
        self,
        run_or_id: str | dict[str, Any],
        proposal_id: str,
        *,
        reason: str | None = "",
        tags: list[str] | None,
    ) -> dict[str, Any]:
        if isinstance(run_or_id, dict):
            return self._reject_proposal_in_run(
                run_or_id,
                proposal_id,
                reason=reason,
                tags=tags,
            )
        run = self.proposal_run(run_or_id)
        action = self._reject_proposal_in_run(run, proposal_id, reason=reason, tags=tags)
        self.persist_proposal_mutation(run)
        return self.proposal_payload(run, action=action)

    def _reject_proposal_in_run(
        self,
        run: dict[str, Any],
        proposal_id: str,
        *,
        reason: str | None = "",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        from ui.backend import evolution_actions as actions

        role = str(run.get("role") or "").strip()
        if not role:
            raise HTTPException(status_code=400, detail="evolution run has no role")
        proposal = actions._find_proposal(run, proposal_id)
        now = beijing_now_iso()
        clean_reason = str(reason or "").strip()
        clean_tags = normalize_rejection_tags(tags)
        actions._mark_proposal_rejected(
            proposal,
            reason=clean_reason,
            tags=clean_tags,
            timestamp=now,
            run=run,
        )
        rejected_row = actions._rejected_buffer_row(
            run,
            proposal,
            reason=clean_reason,
            tags=clean_tags,
            timestamp=now,
        )
        reject_buffer = dict(rejected_row.get("reject_buffer") or {})
        try:
            self._store.registry.save_rejected(
                role,
                [rejected_row],
                run.get("battle_result")
                if isinstance(run.get("battle_result"), dict)
                else None,
            )
            reject_buffer["saved"] = True
        except Exception as exc:  # noqa: BLE001 - expose reject-buffer failures
            reject_buffer["saved"] = False
            reject_buffer["error"] = str(exc)
            proposal["reject_buffer"] = reject_buffer
            run["proposal_review"] = actions._proposal_review_summary(run)
            raise HTTPException(
                status_code=409,
                detail=f"failed to save rejected proposal: {exc}",
            ) from exc
        proposal["reject_buffer"] = reject_buffer
        run["proposal_review"] = actions._proposal_review_summary(run)
        return actions._proposal_action_payload(run, proposal)

    def apply_accepted_proposals(self, run_id: str) -> dict[str, Any]:
        run = self.proposal_run(run_id)
        action = apply_accepted_evolution_proposals(self._store, run)
        self.persist_proposal_mutation(run)
        return self.proposal_payload(run, action=action)

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


__all__ = ["EvolutionService", "EvolutionServiceStoreProtocol"]
