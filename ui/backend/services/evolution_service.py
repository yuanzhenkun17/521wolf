"""Evolution read/proposal service for the UI backend."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from app.util.time import beijing_now_iso
from ui.backend.schemas import normalize_rejection_tags
from ui.backend.evolution_actions import (
    accept_evolution_proposal,
    apply_accepted_evolution_proposals,
)
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


class EvolutionService:
    """Build evolution API payloads while routes stay as HTTP adapters."""

    def __init__(self, store: Any) -> None:
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
        self._store._touch_background_task(run)
        self._store._persist_background_tasks()

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


__all__ = ["EvolutionService"]
