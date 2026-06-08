"""Side-effecting evolution action helpers for the UI backend."""

from __future__ import annotations

import uuid
import hashlib
from collections import Counter
from typing import Any

from fastapi import HTTPException

from app.util.time import beijing_now_iso

_ACCEPTED_STATUS = "accepted"
_REJECTED_STATUS = "rejected"
_PENDING_STATUSES = {"", "pending", "proposed", "reviewing"}
_REVIEW_STATUSES = {_ACCEPTED_STATUS, _REJECTED_STATUS}


def _promote_evolution_run(store: Any, run: dict[str, Any]) -> None:
    role = str(run.get("role") or "").strip()
    if not role:
        raise HTTPException(status_code=400, detail="evolution run has no role")
    version_id = _safe_registry_id(
        str(run.get("candidate_hash") or f"{role}_{run.get('run_id', 'run')}_candidate")
    )
    proposals, explicit_review = _promotion_proposals(run)
    if explicit_review and not proposals:
        raise HTTPException(status_code=409, detail="no accepted proposals to promote")
    proposal_ids = [str(item.get("proposal_id")) for item in proposals if item.get("proposal_id")]
    try:
        published = store.registry.publish_skills(
            role,
            _evolution_skill_contents(role, run, proposals=proposals),
            parent_id=str(run.get("parent_hash") or "") or None,
            source="evolution",
            run_id=str(run.get("run_id") or ""),
            proposal_ids=proposal_ids,
            version_id=version_id,
            set_as_baseline=True,
            expected_current=store.registry.get_baseline(role),
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"failed to promote evolution run: {exc}") from exc
    run["candidate_hash"] = published
    run["published_version_id"] = published
    run["promoted_version_id"] = published
    run["promoted_proposal_ids"] = proposal_ids
    run["proposal_review"] = _proposal_review_summary(run)
    run["finished_at"] = run.get("finished_at") or beijing_now_iso()


def _reject_evolution_run(store: Any, run: dict[str, Any]) -> None:
    role = str(run.get("role") or "").strip()
    if not role:
        raise HTTPException(status_code=400, detail="evolution run has no role")
    proposals = _normalize_run_proposals(run, mutate=True)
    now = beijing_now_iso()
    for proposal in proposals:
        if _proposal_status(proposal) != _REJECTED_STATUS:
            _mark_proposal_rejected(proposal, reason="run rejected", tags=[], timestamp=now)
    if proposals:
        store.registry.save_rejected(role, proposals, run.get("battle_result") if isinstance(run.get("battle_result"), dict) else None)
    run["proposal_review"] = _proposal_review_summary(run)
    run["rejected_at"] = now
    run["finished_at"] = run.get("finished_at") or run["rejected_at"]


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
    run["proposal_review"] = _proposal_review_summary(run)
    return _proposal_action_payload(run, proposal)


def reject_evolution_proposal(
    store: Any,
    run: dict[str, Any],
    proposal_id: str,
    *,
    reason: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    role = str(run.get("role") or "").strip()
    if not role:
        raise HTTPException(status_code=400, detail="evolution run has no role")
    proposal = _find_proposal(run, proposal_id)
    now = beijing_now_iso()
    clean_tags = [str(item).strip() for item in tags or [] if str(item).strip()]
    _mark_proposal_rejected(proposal, reason=reason, tags=clean_tags, timestamp=now)
    rejected_row = _rejected_buffer_row(run, proposal, reason=reason, tags=clean_tags, timestamp=now)
    reject_buffer = dict(rejected_row.get("reject_buffer") or {})
    try:
        store.registry.save_rejected(
            role,
            [rejected_row],
            run.get("battle_result") if isinstance(run.get("battle_result"), dict) else None,
        )
        reject_buffer["saved"] = True
    except Exception as exc:  # noqa: BLE001 - expose reject-buffer write failure to callers
        reject_buffer["saved"] = False
        reject_buffer["error"] = str(exc)
        proposal["reject_buffer"] = reject_buffer
        run["proposal_review"] = _proposal_review_summary(run)
        raise HTTPException(status_code=409, detail=f"failed to save rejected proposal: {exc}") from exc
    proposal["reject_buffer"] = reject_buffer
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


def _evolution_skill_contents(
    role: str,
    run: dict[str, Any],
    *,
    proposals: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    run_id = str(run.get("run_id") or "evolution_run")
    proposals = list(proposals) if proposals is not None else _promotion_proposals(run)[0]
    diff = [item for item in run.get("diff", []) or [] if isinstance(item, dict)]
    lines = [
        "## Runtime",
        "",
        f"Generated from evolution run `{run_id}`.",
        "",
    ]
    if proposals:
        lines.append("### Accepted proposals")
        for index, proposal in enumerate(proposals, start=1):
            title = proposal.get("section") or proposal.get("target_file") or proposal.get("proposal_id") or f"proposal {index}"
            content = str(proposal.get("content") or proposal.get("rationale") or "").strip()
            lines.extend([f"{index}. {title}", ""])
            if content:
                lines.extend([content, ""])
            if proposal.get("rationale"):
                lines.extend([f"Rationale: {proposal['rationale']}", ""])
    elif diff:
        lines.append("### Applied diff")
        for item in diff:
            after = str(item.get("after") or item.get("content") or "").strip()
            if after:
                lines.extend([after, ""])
    else:
        lines.extend(["No concrete proposal content was available; keep baseline strategy unchanged.", ""])
    content = "\n".join(lines).strip()
    name = _safe_registry_id(f"{role}_{run_id}_skill")
    return {
        "evolution.md": (
            "---\n"
            f"name: {name}\n"
            f"role: {role}\n"
            "applicable_actions:\n"
            "  - speak\n"
            "status: active\n"
            "evolution:\n"
            "  enabled: true\n"
            "  allowed_actions:\n"
            "    - append_rule\n"
            "    - rewrite_section\n"
            "    - deprecate_rule\n"
            "---\n"
            f"{content}\n"
        )
    }


def _safe_registry_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value.strip())
    return safe.strip("_-")[:96] or f"version_{uuid.uuid4().hex[:8]}"


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


def _has_explicit_review(proposals: list[dict[str, Any]]) -> bool:
    for proposal in proposals:
        status = _proposal_status(proposal)
        if status in _REVIEW_STATUSES:
            return True
        if any(key in proposal for key in ("accepted_at", "rejected_at", "reviewed_at", "rejection_reason")):
            return True
    return False


def _promotion_proposals(run: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    proposals = _normalize_run_proposals(run, mutate=True)
    explicit_review = _has_explicit_review(proposals)
    if not explicit_review:
        return proposals, False
    return [proposal for proposal in proposals if _proposal_status(proposal) == _ACCEPTED_STATUS], True


def _mark_proposal_rejected(
    proposal: dict[str, Any],
    *,
    reason: str,
    tags: list[str],
    timestamp: str,
) -> None:
    proposal["status"] = _REJECTED_STATUS
    proposal["rejected_at"] = proposal.get("rejected_at") or timestamp
    proposal["reviewed_at"] = timestamp
    proposal["rejection_reason"] = reason
    proposal["rejection_tags"] = list(tags)
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
    row.update(
        {
            "source_run_id": run.get("run_id"),
            "source_proposal_id": proposal.get("proposal_id"),
            "rejection_reason": reason,
            "rejection_tags": list(tags),
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
                "rejected_at": timestamp,
            },
        }
    )
    return row


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
    accepted_ids = [
        str(proposal.get("proposal_id"))
        for proposal in proposals
        if _proposal_status(proposal) == _ACCEPTED_STATUS and proposal.get("proposal_id")
    ]
    rejected_ids = [
        str(proposal.get("proposal_id"))
        for proposal in proposals
        if _proposal_status(proposal) == _REJECTED_STATUS and proposal.get("proposal_id")
    ]
    pending_ids = [
        str(proposal.get("proposal_id"))
        for proposal in proposals
        if _proposal_status(proposal) not in _REVIEW_STATUSES and proposal.get("proposal_id")
    ]
    stored = run.get("proposal_review") if isinstance(run.get("proposal_review"), dict) else {}
    applied_ids = [
        str(item)
        for item in (run.get("applied_proposal_ids") or stored.get("applied_proposal_ids") or [])
        if str(item)
    ]
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
    return {
        "schema_version": 1,
        "status": review_status,
        "total": len(proposals),
        "accepted_count": len(accepted_ids),
        "rejected_count": len(rejected_ids),
        "pending_count": len(pending_ids),
        "accepted_proposal_ids": accepted_ids,
        "rejected_proposal_ids": rejected_ids,
        "pending_proposal_ids": pending_ids,
        "applied_proposal_ids": applied_ids,
        "counts": dict(counts),
        "updated_at": stored.get("updated_at") or run.get("last_heartbeat_at") or run.get("finished_at"),
    }


def _proposal_action_payload(run: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "role_evolution_proposal",
        "schema_version": 1,
        "run_id": run.get("run_id"),
        "role": run.get("role"),
        "proposal": dict(proposal),
        "proposal_review": _proposal_review_summary(run),
    }
