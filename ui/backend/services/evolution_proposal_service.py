"""Evolution proposal review service for the UI backend."""

from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

from fastapi import HTTPException

from app.util.time import beijing_now_iso
from ui.backend.schemas import normalize_rejection_tags

_ACCEPTED_STATUS = "accepted"
_REJECTED_STATUS = "rejected"
_APPLIED_STATUS = "applied"
_PENDING_STATUSES = {"", "pending", "proposed", "reviewing"}
_REVIEW_STATUSES = {_ACCEPTED_STATUS, _REJECTED_STATUS, _APPLIED_STATUS}


class EvolutionProposalService:
    """Mutate proposal reviews while preserving API payload contracts."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def accept_proposal(self, run: dict[str, Any], proposal_id: str) -> dict[str, Any]:
        return accept_evolution_proposal(self._store, run, proposal_id)

    def reject_proposal(
        self,
        run: dict[str, Any],
        proposal_id: str,
        *,
        reason: str | None = "",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        role = str(run.get("role") or "").strip()
        if not role:
            raise HTTPException(status_code=400, detail="evolution run has no role")
        proposal = _find_proposal(run, proposal_id)
        now = beijing_now_iso()
        clean_reason = str(reason or "").strip()
        clean_tags = normalize_rejection_tags(tags)
        _mark_proposal_rejected(
            proposal,
            reason=clean_reason,
            tags=clean_tags,
            timestamp=now,
            run=run,
        )
        rejected_row = _rejected_buffer_row(
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
                run.get("battle_result") if isinstance(run.get("battle_result"), dict) else None,
            )
            reject_buffer["saved"] = True
        except Exception as exc:  # noqa: BLE001 - expose reject-buffer failures
            reject_buffer["saved"] = False
            reject_buffer["error"] = str(exc)
            proposal["reject_buffer"] = reject_buffer
            run["proposal_review"] = _proposal_review_summary(run)
            raise HTTPException(
                status_code=409,
                detail=f"failed to save rejected proposal: {exc}",
            ) from exc
        proposal["reject_buffer"] = reject_buffer
        run["proposal_review"] = _proposal_review_summary(run)
        return _proposal_action_payload(run, proposal)

    def apply_accepted_proposals(self, run: dict[str, Any]) -> dict[str, Any]:
        return apply_accepted_evolution_proposals(self._store, run)


def accept_evolution_proposal(store: Any, run: dict[str, Any], proposal_id: str) -> dict[str, Any]:
    del store
    proposal = _find_proposal(run, proposal_id)
    if _proposal_status(proposal) == _REJECTED_STATUS:
        raise HTTPException(status_code=409, detail="rejected proposal cannot be accepted")
    now = beijing_now_iso()
    proposal["status"] = _ACCEPTED_STATUS
    proposal["accepted_at"] = proposal.get("accepted_at") or now
    proposal["reviewed_at"] = now
    proposal.pop("rejection_reason", None)
    proposal.pop("rejection_tags", None)
    proposal.pop("rejection_metadata", None)
    proposal.pop("reject_buffer", None)
    run["proposal_review"] = _proposal_review_summary(run)
    return _proposal_action_payload(run, proposal)


def apply_accepted_evolution_proposals(store: Any, run: dict[str, Any]) -> dict[str, Any]:
    del store
    proposals = _normalize_run_proposals(run, mutate=True)
    accepted = [proposal for proposal in proposals if _proposal_status(proposal) == _ACCEPTED_STATUS]
    if not accepted:
        raise HTTPException(status_code=409, detail="no accepted proposals to apply")
    accepted_ids = {str(proposal.get("proposal_id")) for proposal in accepted if proposal.get("proposal_id")}
    accepted_diff = _diff_for_proposals(run, accepted_ids)
    now = beijing_now_iso()
    run["accepted_proposals"] = [dict(proposal) for proposal in accepted]
    run["accepted_proposal_ids"] = sorted(accepted_ids)
    run["accepted_diff"] = accepted_diff
    run["applied_proposal_ids"] = sorted(accepted_ids)
    run["accepted_applied_at"] = now
    run["proposal_review"] = _proposal_review_summary(run)
    return {
        "kind": "role_evolution_apply_accepted",
        "schema_version": 1,
        "run_id": run.get("run_id"),
        "role": run.get("role"),
        "accepted_proposal_ids": sorted(accepted_ids),
        "accepted_count": len(accepted),
        "accepted_diff_count": len(accepted_diff),
        "proposal_review": run["proposal_review"],
    }


def _normalize_run_proposals(run: dict[str, Any], *, mutate: bool = False) -> list[dict[str, Any]]:
    raw = run.get("proposals", []) or []
    proposals: list[dict[str, Any]] = []
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        proposal = item if mutate else dict(item)
        proposal_id = str(proposal.get("proposal_id") or "").strip()
        if not proposal_id:
            proposal_id = f"proposal_{index}"
            proposal["proposal_id"] = proposal_id
        proposal["status"] = _proposal_status(proposal)
        proposals.append(proposal)
    if mutate:
        run["proposals"] = proposals
    return proposals


def _find_proposal(run: dict[str, Any], proposal_id: str) -> dict[str, Any]:
    target = str(proposal_id or "").strip()
    if not target:
        raise HTTPException(status_code=404, detail="proposal not found")
    proposals = _normalize_run_proposals(run, mutate=True)
    for proposal in proposals:
        if str(proposal.get("proposal_id") or "") == target:
            return proposal
    raise HTTPException(status_code=404, detail="proposal not found")


def _proposal_status(proposal: dict[str, Any]) -> str:
    status = str(proposal.get("status") or proposal.get("review_status") or "proposed").strip().lower()
    if status in {"accept", "approved", "approve"}:
        return _ACCEPTED_STATUS
    if status in {"reject", "declined", "deny", "denied"}:
        return _REJECTED_STATUS
    if status in _REVIEW_STATUSES:
        return status
    if status in _PENDING_STATUSES:
        return "proposed"
    return status


def _clean_id_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _first_id_list(*values: Any) -> list[str] | None:
    for value in values:
        if isinstance(value, list):
            return _clean_id_list(value)
    return None


def _merge_id_lists(*values: list[str] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in value or []:
            text = str(item).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            result.append(text)
    return result


def _proposal_id(proposal: dict[str, Any], index: int | None = None) -> str:
    proposal_id = str(proposal.get("proposal_id") or "").strip()
    if proposal_id:
        return proposal_id
    if index is not None:
        return f"proposal_{index}"
    return ""


def _preflight_status(proposal: dict[str, Any]) -> str:
    raw = proposal.get("preflight")
    if isinstance(raw, dict):
        status = str(raw.get("status") or raw.get("decision") or "").strip().lower()
        passed = raw.get("passed")
        if passed is True or status in {"passed", "pass", "ok", "accepted", "approved"}:
            return "passed"
        if passed is False or status in {"failed", "fail", "rejected", "blocked", "deny", "denied"}:
            return "failed"
    raw = proposal.get("preflight_status")
    status = str(raw or "").strip().lower()
    if status in {"passed", "pass", "ok", "accepted", "approved"}:
        return "passed"
    if status in {"failed", "fail", "rejected", "blocked", "deny", "denied"}:
        return "failed"
    if proposal.get("preflight_passed") is True:
        return "passed"
    if proposal.get("preflight_passed") is False:
        return "failed"
    return "unknown"


def _proposal_id_sets(run: dict[str, Any], proposals: list[dict[str, Any]]) -> dict[str, list[str]]:
    stored = run.get("proposal_review") if isinstance(run.get("proposal_review"), dict) else {}
    explicit_generated_ids = _first_id_list(run.get("generated_proposal_ids"), stored.get("generated_proposal_ids"))
    if explicit_generated_ids is not None:
        generated_ids = explicit_generated_ids
    else:
        generated_ids = [
            proposal_id
            for index, proposal in enumerate(proposals, start=1)
            if (proposal_id := _proposal_id(proposal, index))
        ]
    explicit_preflight_ids = _first_id_list(
        run.get("preflight_passed_proposal_ids"),
        run.get("candidate_proposal_ids"),
        stored.get("preflight_passed_proposal_ids"),
    )
    if explicit_preflight_ids is not None:
        preflight_ids = explicit_preflight_ids
    else:
        failed_ids = {
            proposal_id
            for index, proposal in enumerate(proposals, start=1)
            if (proposal_id := _proposal_id(proposal, index)) and _preflight_status(proposal) == "failed"
        }
        preflight_ids = [proposal_id for proposal_id in generated_ids if proposal_id not in failed_ids]
    status_accepted_ids = [
        str(proposal.get("proposal_id"))
        for proposal in proposals
        if _proposal_status(proposal) in {_ACCEPTED_STATUS, _APPLIED_STATUS} and proposal.get("proposal_id")
    ]
    explicit_accepted_ids = _first_id_list(run.get("accepted_proposal_ids"), stored.get("accepted_proposal_ids"))
    accepted_ids = _merge_id_lists(explicit_accepted_ids, status_accepted_ids)
    rejected_ids = [
        str(proposal.get("proposal_id"))
        for proposal in proposals
        if _proposal_status(proposal) == _REJECTED_STATUS and proposal.get("proposal_id")
    ]
    status_applied_ids = [
        str(proposal.get("proposal_id"))
        for proposal in proposals
        if _proposal_status(proposal) == _APPLIED_STATUS and proposal.get("proposal_id")
    ]
    explicit_applied_ids = _first_id_list(run.get("applied_proposal_ids"), stored.get("applied_proposal_ids"))
    applied_ids = _merge_id_lists(explicit_applied_ids, status_applied_ids)
    accepted_id_set = set(accepted_ids)
    rejected_id_set = set(rejected_ids)
    applied_id_set = set(applied_ids)
    pending_ids = [
        proposal_id
        for proposal_id in preflight_ids
        if proposal_id not in accepted_id_set
        and proposal_id not in rejected_id_set
        and proposal_id not in applied_id_set
    ]
    return {
        "generated": generated_ids,
        "preflight": preflight_ids,
        "accepted": accepted_ids,
        "rejected": rejected_ids,
        "pending": pending_ids,
        "applied": applied_ids,
    }


def _promotion_proposals(run: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    proposals = _normalize_run_proposals(run, mutate=True)
    id_sets = _proposal_id_sets(run, proposals)
    promotion_ids = _merge_id_lists(id_sets["accepted"], id_sets["applied"])
    promotion_id_set = set(promotion_ids)
    selected: list[dict[str, Any]] = []
    for index, proposal in enumerate(proposals, start=1):
        proposal_id = _proposal_id(proposal, index)
        status = _proposal_status(proposal)
        if status in {_ACCEPTED_STATUS, _APPLIED_STATUS} or (proposal_id and proposal_id in promotion_id_set):
            selected.append(proposal)
    return selected, promotion_ids


def _mark_proposal_rejected(
    proposal: dict[str, Any],
    *,
    reason: str,
    tags: list[str],
    timestamp: str,
    run: dict[str, Any] | None = None,
) -> None:
    metadata = _proposal_rejection_metadata(
        proposal,
        reason=reason,
        tags=tags,
        timestamp=timestamp,
        run=run,
    )
    proposal["status"] = _REJECTED_STATUS
    proposal["rejected_at"] = proposal.get("rejected_at") or timestamp
    proposal["reviewed_at"] = timestamp
    proposal["rejection_reason"] = reason
    proposal["rejection_tags"] = list(tags)
    proposal["rejection_metadata"] = metadata
    proposal.pop("accepted_at", None)


def _rejected_buffer_row(
    run: dict[str, Any],
    proposal: dict[str, Any],
    *,
    reason: str,
    tags: list[str],
    timestamp: str,
) -> dict[str, Any]:
    row = dict(proposal)
    dedupe_key = _proposal_dedupe_key(row)
    metadata = _proposal_rejection_metadata(
        proposal,
        reason=reason,
        tags=tags,
        timestamp=timestamp,
        run=run,
    )
    row.update(
        {
            "source_run_id": run.get("run_id"),
            "source_proposal_id": proposal.get("proposal_id"),
            "rejection_reason": reason,
            "rejection_tags": list(tags),
            "rejection_metadata": metadata,
            "rejected_at": timestamp,
            "dedupe_key": dedupe_key,
            "reject_buffer": {
                "role": run.get("role"),
                "saved": False,
                "source_run_id": run.get("run_id"),
                "source_proposal_id": proposal.get("proposal_id"),
                "dedupe_key": dedupe_key,
                "reason": reason,
                "tags": list(tags),
                "rejection_metadata": metadata,
                "rejected_at": timestamp,
            },
        }
    )
    return row


def _proposal_rejection_metadata(
    proposal: dict[str, Any],
    *,
    reason: str,
    tags: list[str],
    timestamp: str,
    run: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "action": "reject",
        "status": _REJECTED_STATUS,
        "proposal_id": str(proposal.get("proposal_id") or ""),
        "source_run_id": run.get("run_id") if isinstance(run, dict) else proposal.get("source_run_id"),
        "role": run.get("role") if isinstance(run, dict) else proposal.get("role"),
        "reason": str(reason or "").strip(),
        "tags": normalize_rejection_tags(tags),
        "reviewed_at": timestamp,
        "rejected_at": timestamp,
        "review_source": "ui_api",
    }


def _stored_rejection_metadata(proposal: dict[str, Any]) -> dict[str, Any]:
    raw = proposal.get("rejection_metadata")
    metadata = dict(raw) if isinstance(raw, dict) else {}
    tags = normalize_rejection_tags(
        metadata.get("tags")
        if "tags" in metadata
        else proposal.get("rejection_tags") or proposal.get("reject_buffer_tags") or []
    )
    reason = str(metadata.get("reason") or proposal.get("rejection_reason") or "").strip()
    timestamp = str(
        metadata.get("reviewed_at")
        or proposal.get("reviewed_at")
        or proposal.get("rejected_at")
        or ""
    )
    if not metadata and not (reason or tags or timestamp):
        return {}
    metadata.update(
        {
            "schema_version": int(metadata.get("schema_version") or 1),
            "action": str(metadata.get("action") or "reject"),
            "status": str(metadata.get("status") or _REJECTED_STATUS),
            "proposal_id": str(metadata.get("proposal_id") or proposal.get("proposal_id") or ""),
            "reason": reason,
            "tags": tags,
            "reviewed_at": timestamp,
            "rejected_at": str(metadata.get("rejected_at") or proposal.get("rejected_at") or timestamp),
            "review_source": str(metadata.get("review_source") or "ui_api"),
        }
    )
    return metadata


def _proposal_review_actions(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for proposal in proposals:
        if _proposal_status(proposal) != _REJECTED_STATUS:
            continue
        metadata = _stored_rejection_metadata(proposal)
        if not metadata:
            continue
        actions.append(
            {
                "schema_version": 1,
                "action": "reject",
                "status": _REJECTED_STATUS,
                "proposal_id": metadata.get("proposal_id"),
                "reason": metadata.get("reason", ""),
                "tags": list(metadata.get("tags") or []),
                "reviewed_at": metadata.get("reviewed_at", ""),
                "rejection_metadata": metadata,
            }
        )
    return actions


def _rejection_metadata_by_proposal_id(proposals: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for proposal in proposals:
        if _proposal_status(proposal) != _REJECTED_STATUS:
            continue
        metadata = _stored_rejection_metadata(proposal)
        proposal_id = str(metadata.get("proposal_id") or proposal.get("proposal_id") or "").strip()
        if proposal_id and metadata:
            result[proposal_id] = metadata
    return result


def _proposal_dedupe_key(proposal: dict[str, Any]) -> str:
    payload = {
        "target_file": str(proposal.get("target_file") or ""),
        "action_type": str(proposal.get("action_type") or ""),
        "rationale": str(proposal.get("rationale") or ""),
        "content_hash": hashlib.sha256(str(proposal.get("content") or "").encode("utf-8")).hexdigest()[:16],
    }
    return hashlib.sha256(repr(sorted(payload.items())).encode("utf-8")).hexdigest()[:16]


def _diff_for_proposals(run: dict[str, Any], proposal_ids: set[str]) -> list[dict[str, Any]]:
    if not proposal_ids:
        return []
    result: list[dict[str, Any]] = []
    for item in run.get("diff", []) or []:
        if not isinstance(item, dict):
            continue
        ref = str(item.get("proposal_ref") or item.get("proposal_id") or item.get("source_proposal_id") or "")
        if ref and ref in proposal_ids:
            result.append(dict(item))
    return result


def _proposal_review_summary(run: dict[str, Any]) -> dict[str, Any]:
    proposals = _normalize_run_proposals(run, mutate=False)
    counts = Counter(_proposal_status(proposal) for proposal in proposals)
    stored = run.get("proposal_review") if isinstance(run.get("proposal_review"), dict) else {}
    id_sets = _proposal_id_sets(run, proposals)
    generated_ids = id_sets["generated"]
    preflight_ids = id_sets["preflight"]
    accepted_ids = id_sets["accepted"]
    rejected_ids = id_sets["rejected"]
    pending_ids = id_sets["pending"]
    applied_ids = id_sets["applied"]
    counts["generated"] = len(generated_ids)
    counts["preflight"] = len(preflight_ids)
    counts["pending"] = len(pending_ids)
    counts["accepted"] = len(accepted_ids)
    counts["rejected"] = len(rejected_ids)
    counts["applied"] = len(applied_ids)
    if not proposals:
        review_status = "empty"
    elif pending_ids:
        review_status = "partial" if accepted_ids or rejected_ids else "unreviewed"
    elif accepted_ids and rejected_ids:
        review_status = "mixed"
    elif accepted_ids:
        review_status = "accepted"
    else:
        review_status = "rejected"
    if applied_ids:
        review_status = "applied"
    review_actions = _proposal_review_actions(proposals)
    rejection_metadata = _rejection_metadata_by_proposal_id(proposals)
    return {
        "schema_version": 1,
        "status": review_status,
        "total": len(proposals),
        "generated_count": len(generated_ids),
        "preflight_passed_count": len(preflight_ids),
        "accepted_count": len(accepted_ids),
        "rejected_count": len(rejected_ids),
        "pending_count": len(pending_ids),
        "applied_count": len(applied_ids),
        "generated_proposal_ids": generated_ids,
        "preflight_passed_proposal_ids": preflight_ids,
        "accepted_proposal_ids": accepted_ids,
        "rejected_proposal_ids": rejected_ids,
        "pending_proposal_ids": pending_ids,
        "applied_proposal_ids": applied_ids,
        "review_actions": review_actions,
        "rejection_metadata": rejection_metadata,
        "rejection_metadata_by_proposal_id": rejection_metadata,
        "counts": dict(counts),
        "updated_at": stored.get("updated_at") or run.get("last_heartbeat_at") or run.get("finished_at"),
    }


def _proposal_action_payload(run: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "kind": "role_evolution_proposal",
        "schema_version": 1,
        "run_id": run.get("run_id"),
        "role": run.get("role"),
        "proposal": dict(proposal),
        "proposal_review": _proposal_review_summary(run),
    }
    if _proposal_status(proposal) == _REJECTED_STATUS:
        metadata = _stored_rejection_metadata(proposal)
        payload["review_action"] = {
            "schema_version": 1,
            "action": "reject",
            "status": _REJECTED_STATUS,
            "proposal_id": metadata.get("proposal_id"),
            "reason": metadata.get("reason", ""),
            "tags": list(metadata.get("tags") or []),
            "reviewed_at": metadata.get("reviewed_at", ""),
            "rejection_metadata": metadata,
        }
        payload["rejection_metadata"] = metadata
    return payload


__all__ = [
    "EvolutionProposalService",
    "accept_evolution_proposal",
    "apply_accepted_evolution_proposals",
]
