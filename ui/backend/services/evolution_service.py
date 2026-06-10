"""Evolution action service for backend business orchestration."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.util.time import beijing_now_iso
from ui.backend.schemas import normalize_rejection_tags


class EvolutionService:
    """Own side-effecting evolution actions for the UI backend."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def reject_proposal(
        self,
        run: dict[str, Any],
        proposal_id: str,
        *,
        reason: str = "",
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
