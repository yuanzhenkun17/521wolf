"""Side-effecting evolution action helpers for the UI backend."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException

from app.lib.version import ReleaseStageNotAllowedError
from app.util.time import beijing_now_iso
from ui.backend.errors import domain_error_detail, release_stage_not_allowed_detail
from ui.backend.services.evolution_proposal_service import _clean_id_list, _merge_id_lists


def _promote_evolution_run(store: Any, run: dict[str, Any]) -> None:
    from ui.backend.services.evolution_proposal_service import (
        _promotion_proposals,
        _proposal_review_summary,
    )

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
    from ui.backend.services.evolution_proposal_service import _proposal_review_summary

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
    from ui.backend.services.evolution_proposal_service import (
        _REJECTED_STATUS,
        _mark_proposal_rejected,
        _normalize_run_proposals,
        _proposal_review_summary,
        _proposal_status,
    )

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


def _evolution_skill_contents(
    role: str,
    run: dict[str, Any],
    *,
    proposals: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    from ui.backend.services.evolution_proposal_service import (
        _promotion_proposals,
    )

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
        raise ValueError(
            f"Evolution run {run_id}: no accepted proposals with content and no diff available; "
            "cannot build candidate skill package."
        )
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

