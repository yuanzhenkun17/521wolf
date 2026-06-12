"""Evolution action/proposal facade service for the UI backend."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import nullcontext as _nullcontext
from typing import Any, Protocol

from fastapi import HTTPException

from app.util.time import beijing_now_iso
from ui.backend.constants import MANUAL_STOP_REASON
from ui.backend.evolution_actions import (
    _promote_evolution_run,
    _reject_evolution_run,
)
from ui.backend.evolution_serializers import (
    _evolution_batch_summary,
    _evolution_run_summary,
    _evolution_sse_event,
)
from ui.backend.services.evolution_proposal_service import EvolutionProposalService
from ui.backend.services.evolution_read_service import EvolutionReadService, EvolutionReadServiceStoreProtocol
from ui.backend.services.task_service import BackgroundTaskServiceProtocol
from ui.backend.sse import _sse, stream_task_event_log_sse, task_event_log_matches_entity
from ui.backend.task_state import (
    _set_task_contract,
)

_TERMINAL_TASK_STATUSES = {"reviewing", "promoted", "rejected", "failed", "completed", "cancelled", "interrupted"}
_FINISHED_ACTION_STATUSES = {"failed", "promoted", "rejected", "reviewing"}
_TERMINAL_SSE_STATUSES = {"reviewing", "promoted", "rejected", "failed", "completed", "cancelled", "interrupted"}


class EvolutionServiceStoreProtocol(EvolutionReadServiceStoreProtocol, Protocol):
    registry: Any

    @property
    def task_service(self) -> BackgroundTaskServiceProtocol:
        ...


class EvolutionService:
    """Build evolution API payloads while routes stay as HTTP adapters."""

    def __init__(self, store: EvolutionServiceStoreProtocol) -> None:
        self._store = store
        self._tasks = store.task_service
        self._reads = EvolutionReadService(store)
        self._proposals = EvolutionProposalService(store)

    def list_runs(
        self,
        *,
        history_requested: bool,
        limit: int | None = None,
        offset: int = 0,
        source: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        self._tasks.load_background_tasks()
        return self._reads.list_runs(
            history_requested=history_requested,
            limit=limit,
            offset=offset,
            source=source,
            status=status,
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        self._tasks.load_background_tasks()
        return self._reads.get_run(run_id)

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
                lock = getattr(self._store, "_evolution_state_lock", None)
                with lock if lock is not None else _nullcontext():
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
        self._request_queue_cancel(entity)
        return self._persist_run_action_mutation(entity)

    def _request_queue_cancel(self, entity: dict[str, Any]) -> None:
        cancel_task = getattr(self._tasks, "cancel_task", None)
        if not callable(cancel_task):
            return
        task_id = str(
            entity.get("task_id")
            or entity.get("queue_task_id")
            or entity.get("batch_id")
            or entity.get("run_id")
            or ""
        ).strip()
        if not task_id:
            return
        try:
            cancel_task(task_id)
        except Exception:  # noqa: BLE001 - legacy action must remain best-effort when queue storage is unavailable
            return

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

    def trust_bundle_payload(self, run_id: str) -> dict[str, Any]:
        return self._reads.trust_bundle_payload(run_id)

    def persist_proposal_mutation(self, run: dict[str, Any]) -> None:
        self._tasks.touch_background_task(run)
        self._tasks.persist_background_tasks()

    def proposals(self, run_id: str) -> dict[str, Any]:
        return self.proposal_payload(self.proposal_run(run_id))

    def accept_proposal(self, run_id: str, proposal_id: str) -> dict[str, Any]:
        run = self.proposal_run(run_id)
        action = self._proposals.accept_proposal(run, proposal_id)
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
            return self._proposals.reject_proposal(
                run_or_id,
                proposal_id,
                reason=reason,
                tags=tags,
            )
        run = self.proposal_run(run_or_id)
        action = self._proposals.reject_proposal(run, proposal_id, reason=reason, tags=tags)
        self.persist_proposal_mutation(run)
        return self.proposal_payload(run, action=action)

    def apply_accepted_proposals(self, run_id: str) -> dict[str, Any]:
        run = self.proposal_run(run_id)
        action = self._proposals.apply_accepted_proposals(run)
        self.persist_proposal_mutation(run)
        return self.proposal_payload(run, action=action)

    def diff(self, run_id: str) -> dict[str, Any]:
        return self._reads.diff(run_id)

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
        return self._reads.games(
            run_id,
            phase=phase,
            side=side,
            limit=limit,
            offset=offset,
            status=status,
            paginate=paginate,
        )

    def game_detail(
        self,
        run_id: str,
        game_id: str,
        detail_type: str,
        *,
        phase: str = "training",
        side: str | None = None,
    ) -> dict[str, Any]:
        return self._reads.game_detail(run_id, game_id, detail_type, phase=phase, side=side)


__all__ = ["EvolutionService", "EvolutionServiceStoreProtocol"]
