"""Side-effecting evolution action helpers for the UI backend."""

from __future__ import annotations

import uuid
import hashlib
from collections import Counter
from typing import Any

from fastapi import HTTPException

from app.lib.version import ReleaseStageNotAllowedError
from app.util.time import beijing_now_iso
from ui.backend.errors import domain_error_detail, release_stage_not_allowed_detail
from ui.backend.schemas import normalize_rejection_tags

_ACCEPTED_STATUS = "accepted"
_REJECTED_STATUS = "rejected"
_APPLIED_STATUS = "applied"
_PENDING_STATUSES = {"", "pending", "proposed", "reviewing"}
_REVIEW_STATUSES = {_ACCEPTED_STATUS, _REJECTED_STATUS, _APPLIED_STATUS}


def _promote_evolution_run(store: Any, run: dict[str, Any]) -> None:
    role = str(run.get("role") or "").strip()
    if not role:
        raise HTTPException(status_code=400, detail="evolution run has no role")
    version_id = _safe_registry_id(
        str(run.get("candidate_hash") or f"{role}_{run.get('run_id', 'run')}_candidate")
    )
    proposals, proposal_ids = _promotion_proposals(run)
    if not proposal_ids:
        run["proposal_review"] = _proposal_review_summary(run)
        raise _proposal_review_required_error(run)
    release_stage = _release_stage_for_run(run)
    set_as_baseline = release_stage == "baseline"
    _ensure_baseline_promotion_trust_complete(run, release_stage=release_stage)
    _ensure_evolution_parent_allowed(store, role, run)
    try:
        published = store.registry.publish_skills(
            role,
            _evolution_skill_contents(role, run, proposals=proposals),
            parent_id=str(run.get("parent_hash") or "") or None,
            source="evolution",
            run_id=str(run.get("run_id") or ""),
            proposal_ids=proposal_ids,
            version_id=version_id,
            release_stage=release_stage,
            set_as_baseline=set_as_baseline,
            expected_current=store.registry.get_baseline(role) if set_as_baseline else None,
            provenance=_promotion_provenance(run, release_stage=release_stage),
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"failed to promote evolution run: {exc}") from exc
    run["candidate_hash"] = published
    run["published_version_id"] = published
    run["published_release_stage"] = release_stage
    run["release_stage"] = release_stage
    run["promoted_version_id"] = published if set_as_baseline else None
    run["promoted_proposal_ids"] = proposal_ids
    run["proposal_review"] = _proposal_review_summary(run)
    run["finished_at"] = run.get("finished_at") or beijing_now_iso()
    invalidate = getattr(store, "invalidate_role_overview_cache", None)
    if callable(invalidate):
        invalidate()


def _ensure_evolution_parent_allowed(store: Any, role: str, run: dict[str, Any]) -> None:
    parent_hash = str(run.get("parent_hash") or "").strip()
    if not parent_hash:
        return
    try:
        store.registry.read_skill_contents(role, parent_hash)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=409,
            detail=domain_error_detail(
                code="evolution_parent_version_not_found",
                message="Evolution parent version was not found.",
                detail=f"evolution parent not found: {role}/{parent_hash}",
                diagnostics=[{
                    "kind": "evolution_parent_version_not_found",
                    "role": role,
                    "version_id": parent_hash,
                }],
            ),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=409,
            detail=domain_error_detail(
                code="evolution_parent_version_unverifiable",
                message="Evolution parent version could not be verified.",
                detail=f"evolution parent could not be verified: {exc}",
                diagnostics=[{
                    "kind": "evolution_parent_version_unverifiable",
                    "role": role,
                    "version_id": parent_hash,
                    "exception_type": type(exc).__name__,
                }],
            ),
        ) from exc
    try:
        from app.lib.version import ensure_version_allowed_for_default_use

        ensure_version_allowed_for_default_use(store.registry, role, parent_hash)
    except ReleaseStageNotAllowedError as exc:
        raise HTTPException(
            status_code=409,
            detail=domain_error_detail(
                code="evolution_parent_release_stage_not_allowed",
                message="Evolution parent version is not allowed.",
                detail=f"evolution parent not allowed: {exc}",
                diagnostics=[exc.diagnostic(kind="evolution_parent_release_stage_not_allowed")],
            ),
        ) from exc
    except ValueError as exc:
        release_stage_detail = release_stage_not_allowed_detail(
            exc,
            code="evolution_parent_release_stage_not_allowed",
            message="Evolution parent version is not allowed.",
            detail_prefix="evolution parent not allowed",
            kind="evolution_parent_release_stage_not_allowed",
        )
        if release_stage_detail is not None:
            raise HTTPException(status_code=409, detail=release_stage_detail) from exc
        raise


def _proposal_review_required_error(run: dict[str, Any]) -> HTTPException:
    summary = run.get("proposal_review") if isinstance(run.get("proposal_review"), dict) else _proposal_review_summary(run)
    return HTTPException(
        status_code=409,
        detail=domain_error_detail(
            code="evolution_proposal_review_required",
            message="Evolution promote requires an accepted or applied proposal review.",
            detail="evolution promote requires at least one accepted or applied proposal before publishing",
            diagnostics=[
                {
                    "kind": "evolution_proposal_review_required",
                    "run_id": str(run.get("run_id") or ""),
                    "role": str(run.get("role") or ""),
                    "status": str(run.get("status") or ""),
                    "proposal_count": str(summary.get("total") or 0),
                    "accepted_count": str(summary.get("accepted_count") or 0),
                    "applied_count": str(summary.get("applied_count") or 0),
                    "pending_count": str(summary.get("pending_count") or 0),
                }
            ],
        ),
    )


def _ensure_baseline_promotion_trust_complete(run: dict[str, Any], *, release_stage: str) -> None:
    if not _baseline_promotion_requires_trust(run, release_stage=release_stage):
        return
    trust_bundle = _trust_bundle_for_run(run)
    if not trust_bundle:
        raise _trust_bundle_required_error(run, release_stage=release_stage)
    completeness = _trust_completeness_for_run(run, trust_bundle)
    missing = _trust_bundle_missing_items(run, trust_bundle, completeness)
    complete = completeness.get("complete") is True
    if not complete or missing:
        raise _trust_bundle_incomplete_error(run, release_stage=release_stage, missing=missing, completeness=completeness)


def _baseline_promotion_requires_trust(run: dict[str, Any], *, release_stage: str) -> bool:
    decision = _release_decision_for_run(run)
    return release_stage in {"baseline", "official"} or decision in {"baseline_promote", "official_publish"}


def _trust_bundle_for_run(run: dict[str, Any]) -> dict[str, Any]:
    for source in (
        run,
        run.get("result") if isinstance(run.get("result"), dict) else {},
        run.get("battle_result") if isinstance(run.get("battle_result"), dict) else {},
    ):
        bundle = source.get("trust_bundle") if isinstance(source, dict) and isinstance(source.get("trust_bundle"), dict) else None
        if bundle:
            return bundle
    return {}


def _gate_report_for_run(run: dict[str, Any]) -> dict[str, Any]:
    candidates: list[Any] = [
        run.get("gate_report"),
        run.get("promotion_gate"),
        run.get("release_gate"),
    ]
    result = run.get("result") if isinstance(run.get("result"), dict) else {}
    battle = run.get("battle_result") if isinstance(run.get("battle_result"), dict) else {}
    candidates.extend([
        result.get("gate_report"),
        result.get("promotion_gate"),
        result.get("release_gate"),
        battle.get("gate_report"),
        battle.get("promotion_gate"),
        battle.get("release_gate"),
    ])
    for value in candidates:
        if isinstance(value, dict) and value:
            return value
    return {}


def _trust_completeness_for_run(run: dict[str, Any], trust_bundle: dict[str, Any]) -> dict[str, Any]:
    gate_report = _gate_report_for_run(run)
    for value in (
        trust_bundle.get("completeness"),
        run.get("trust_bundle_completeness"),
        gate_report.get("trust_bundle_completeness"),
        (run.get("result") or {}).get("trust_bundle_completeness") if isinstance(run.get("result"), dict) else None,
        (run.get("battle_result") or {}).get("trust_bundle_completeness") if isinstance(run.get("battle_result"), dict) else None,
    ):
        if isinstance(value, dict) and value:
            return value
    return {}


def _trust_bundle_missing_items(
    run: dict[str, Any],
    trust_bundle: dict[str, Any],
    completeness: dict[str, Any],
) -> list[str]:
    missing = _merge_id_lists([
        _trust_missing_item_name(item)
        for item in _clean_id_list(completeness.get("missing"))
    ])
    if not completeness:
        missing.append("trust_bundle")
    if not trust_bundle.get("trust_bundle_id") or not trust_bundle.get("bundle_hash"):
        missing.append("trust_bundle")
    if not _has_gate_reference(run, trust_bundle):
        missing.append("gate_report")
    if not _has_training_evidence_reference(trust_bundle):
        missing.append("training_evidence")
    if not _has_proposal_reference(trust_bundle):
        missing.append("proposals")
    return _merge_id_lists(missing)


def _trust_missing_item_name(value: Any) -> str:
    name = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if name in {
        "evidence",
        "training_evidence",
        "training_game",
        "training_games",
        "training_game_ids",
        "training_evidence_ids",
        "evidence_ids",
        "paired_seed_table",
        "paired_seed_pairs",
        "battle_pair_seeds",
    }:
        return "training_evidence"
    if name in {
        "proposal",
        "proposals",
        "proposal_ids",
        "accepted_proposal_ids",
        "applied_proposal_ids",
        "generated_proposal_ids",
        "preflight_passed_proposal_ids",
        "rejected_proposal_ids",
    }:
        return "proposals"
    if name in {
        "gate",
        "release_gate",
        "promotion_gate",
        "gate_report",
        "gate_report_id",
        "promotion_gate_report",
    }:
        return "gate_report"
    if name in {
        "bundle",
        "bundle_hash",
        "trust_bundle",
        "trust_bundle_id",
        "completeness",
        "trust_completeness",
        "trust_bundle_completeness",
    }:
        return "trust_bundle"
    return name


def _has_gate_reference(run: dict[str, Any], trust_bundle: dict[str, Any]) -> bool:
    if trust_bundle.get("gate_report_id"):
        return True
    gate_report = _gate_report_for_run(run)
    if gate_report.get("gate_report_id"):
        return True
    release_gate = gate_report.get("release_gate") if isinstance(gate_report.get("release_gate"), dict) else gate_report
    return isinstance(release_gate, dict) and bool(release_gate.get("decision") or release_gate.get("release_decision"))


def _has_training_evidence_reference(trust_bundle: dict[str, Any]) -> bool:
    return any(
        _clean_id_list(trust_bundle.get(field))
        for field in ("training_game_ids", "training_evidence_ids", "evidence_ids")
    )


def _has_proposal_reference(trust_bundle: dict[str, Any]) -> bool:
    return any(
        _clean_id_list(trust_bundle.get(field))
        for field in ("proposal_ids", "accepted_proposal_ids", "applied_proposal_ids")
    )


def _trust_bundle_required_error(run: dict[str, Any], *, release_stage: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=domain_error_detail(
            code="evolution_trust_bundle_required",
            message="Evolution baseline promote requires a trust bundle.",
            detail=f"evolution baseline promote requires a complete trust bundle before publishing: release_stage={release_stage}",
            diagnostics=[_trust_bundle_diagnostic(run, release_stage=release_stage, kind="evolution_trust_bundle_required")],
        ),
    )


def _trust_bundle_incomplete_error(
    run: dict[str, Any],
    *,
    release_stage: str,
    missing: list[str],
    completeness: dict[str, Any],
) -> HTTPException:
    diagnostic = _trust_bundle_diagnostic(run, release_stage=release_stage, kind="evolution_trust_bundle_incomplete")
    diagnostic["missing"] = list(missing or [])
    diagnostic["completeness_score"] = str(completeness.get("score") if completeness.get("score") is not None else "")
    return HTTPException(
        status_code=409,
        detail=domain_error_detail(
            code="evolution_trust_bundle_incomplete",
            message="Evolution baseline promote requires a complete trust bundle.",
            detail=(
                f"evolution baseline promote requires complete trust bundle/gate/evidence before publishing: release_stage={release_stage}"
                + (f"; missing={','.join(missing)}" if missing else "")
            ),
            diagnostics=[diagnostic],
        ),
    )


def _trust_bundle_diagnostic(run: dict[str, Any], *, release_stage: str, kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "run_id": str(run.get("run_id") or ""),
        "role": str(run.get("role") or ""),
        "status": str(run.get("status") or ""),
        "release_stage": str(release_stage or ""),
        "release_decision": _release_decision_for_run(run),
    }


def _reject_evolution_run(store: Any, run: dict[str, Any]) -> None:
    role = str(run.get("role") or "").strip()
    if not role:
        raise HTTPException(status_code=400, detail="evolution run has no role")
    proposals = _normalize_run_proposals(run, mutate=True)
    now = beijing_now_iso()
    for proposal in proposals:
        if _proposal_status(proposal) != _REJECTED_STATUS:
            _mark_proposal_rejected(proposal, reason="run rejected", tags=[], timestamp=now, run=run)
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
    proposal.pop("rejection_metadata", None)
    proposal.pop("reject_buffer", None)
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
    from ui.backend.services.evolution_service import EvolutionService

    return EvolutionService(store).reject_proposal(
        run,
        proposal_id,
        reason=reason,
        tags=tags,
    )


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


def _clean_id_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _release_stage_for_run(run: dict[str, Any]) -> str:
    decision = _release_decision_for_run(run)
    return {
        "shadow_candidate": "shadow",
        "canary_candidate": "canary",
        "baseline_promote": "baseline",
    }.get(decision, "shadow")


def _release_decision_for_run(run: dict[str, Any]) -> str:
    for value in _release_decision_candidates(run):
        text = str(value or "").strip().lower()
        if text:
            return text
    return ""


def _release_decision_candidates(run: dict[str, Any]) -> list[Any]:
    result = run.get("result") if isinstance(run.get("result"), dict) else {}
    battle = run.get("battle_result") if isinstance(run.get("battle_result"), dict) else {}
    gate_report = run.get("gate_report") if isinstance(run.get("gate_report"), dict) else {}
    release_gate = run.get("release_gate") if isinstance(run.get("release_gate"), dict) else {}
    trust_bundle = run.get("trust_bundle") if isinstance(run.get("trust_bundle"), dict) else {}
    result_gate = result.get("release_gate") if isinstance(result.get("release_gate"), dict) else {}
    result_gate_report = result.get("gate_report") if isinstance(result.get("gate_report"), dict) else {}
    battle_gate = battle.get("release_gate") if isinstance(battle.get("release_gate"), dict) else {}
    battle_gate_report = battle.get("gate_report") if isinstance(battle.get("gate_report"), dict) else {}
    gate_report_gate = gate_report.get("release_gate") if isinstance(gate_report.get("release_gate"), dict) else {}
    result_gate_report_gate = (
        result_gate_report.get("release_gate") if isinstance(result_gate_report.get("release_gate"), dict) else {}
    )
    battle_gate_report_gate = (
        battle_gate_report.get("release_gate") if isinstance(battle_gate_report.get("release_gate"), dict) else {}
    )
    trust_gate = trust_bundle.get("release_gate") if isinstance(trust_bundle.get("release_gate"), dict) else {}
    return [
        run.get("release_decision"),
        release_gate.get("decision"),
        gate_report.get("release_decision"),
        gate_report_gate.get("decision"),
        result.get("release_decision"),
        result_gate.get("decision"),
        result_gate_report.get("release_decision"),
        result_gate_report_gate.get("decision"),
        battle.get("release_decision"),
        battle_gate.get("decision"),
        battle_gate_report.get("release_decision"),
        battle_gate_report_gate.get("decision"),
        trust_bundle.get("release_decision"),
        trust_gate.get("decision"),
    ]


def _promotion_provenance(run: dict[str, Any], *, release_stage: str) -> dict[str, Any]:
    trust_bundle = run.get("trust_bundle") if isinstance(run.get("trust_bundle"), dict) else {}
    if not trust_bundle and isinstance(run.get("result"), dict) and isinstance(run["result"].get("trust_bundle"), dict):
        trust_bundle = run["result"]["trust_bundle"]
    gate_report = run.get("gate_report") if isinstance(run.get("gate_report"), dict) else {}
    if not gate_report and isinstance(run.get("result"), dict) and isinstance(run["result"].get("gate_report"), dict):
        gate_report = run["result"]["gate_report"]
    release_decision = _release_decision_for_run(run)
    return {
        "manual_action": "promote",
        "release_stage": release_stage,
        "release_decision": release_decision or None,
        "trust_bundle_id": trust_bundle.get("trust_bundle_id"),
        "bundle_hash": trust_bundle.get("bundle_hash"),
        "gate_report_id": trust_bundle.get("gate_report_id") or gate_report.get("gate_report_id"),
        "attribution_report_id": trust_bundle.get("attribution_report_id"),
    }


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


def _has_explicit_review(proposals: list[dict[str, Any]]) -> bool:
    for proposal in proposals:
        status = _proposal_status(proposal)
        if status in _REVIEW_STATUSES:
            return True
        if any(key in proposal for key in ("accepted_at", "rejected_at", "reviewed_at", "rejection_reason")):
            return True
    return False


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
