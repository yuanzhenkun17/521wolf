"""Decide node, Langfuse scoring, and registry operations for evolution pipeline."""

from __future__ import annotations

import importlib
import logging
from typing import Any

from app.graphs.shared.state import EvolveState
from app.lib.evolve import (
    EvolutionStatus,
    SkillConsolidation,
    build_evolution_gate_report,
    build_paired_seed_battle_table,
    build_trust_bundle,
    normalize_run_id,
)

from ._shared import (
    _STAGE_ORDER,
    _mark_stage,
    _read_skill_contents,
    _record_diagnostic,
    _registry,
    _resumed_past_stage,
    _safe_id,
    _unique_str,
)

_log = logging.getLogger(__name__)

async def decide_node(state: EvolveState) -> dict:
    """Decide promote/reject/review, optionally writing the registry.

    Recommendation:
      - reject  : no proposals, or battle says candidate is not significant
      - promote : battle gate passed (or skipped with proposals present)
      - review  : ambiguous — leave for human review

    Registry side effects only happen when auto_promote is enabled:
      - promote → publish candidate skills according to the release gate stage
      - reject  → persist rejected proposals for future dedup
    The run state is always persisted to PostgreSQL.
    """
    _log.info("decide: role=%s", state.get("role"))
    _mark_stage(state, "decide", status=state.get("status"))
    role = state.get("role", "")
    battle = state.get("battle_result") or {}
    proposals = state.get("proposals", [])
    cfg = state.get("config", {})
    if isinstance(battle, dict):
        from .nodes import _attach_trust_loop_artifacts
        _attach_trust_loop_artifacts(state, battle, cfg=cfg)
        state["battle_result"] = battle

    recommendation = _recommendation(proposals, battle, cfg=cfg)
    auto_promote = bool(cfg.get("auto_promote"))
    state["recommendation"] = recommendation

    # Convergence detection: check if evolution has plateaued
    convergence_rounds = int(cfg.get("convergence_rounds", 3) or 3)
    min_improvement_ratio = float(cfg.get("min_improvement_ratio", 0.01) or 0.01)
    history_runs = state.get("evolution_history") or []
    if history_runs and convergence_rounds > 0:
        from app.lib.evolve import detect_evolution_convergence
        convergence = detect_evolution_convergence(
            role,
            history_runs,
            convergence_rounds=convergence_rounds,
            min_improvement_ratio=min_improvement_ratio,
        )
        state["convergence"] = convergence
        if convergence.get("converged") and recommendation == "promote":
            _log.info("decide: evolution converged for role=%s: %s", role, convergence.get("reason"))
            recommendation = "converged"
            state["recommendation"] = recommendation

    # Record regression reason for audit trail
    if recommendation == "reject" and isinstance(battle, dict) and battle.get("significant"):
        regression_threshold = float(cfg.get("regression_threshold", 0.05) or 0.05)
        win_rate_delta = float(battle.get("win_rate_delta") or 0.0)
        if win_rate_delta < -regression_threshold:
            state["rollback_reason"] = {
                "type": "auto_regression",
                "win_rate_delta": win_rate_delta,
                "threshold": -regression_threshold,
                "message": f"Candidate regressed: win_rate_delta={win_rate_delta:.3f} < -{regression_threshold}",
            }

    status = EvolutionStatus.REVIEWING.value
    published_version_id: str | None = None
    published_release_stage: str | None = None
    if auto_promote and recommendation in {"promote", "converged"}:
        published = _registry_promote(state)
        if published is not None:
            published_version_id = published["version_id"]
            published_release_stage = published["release_stage"]
        status = EvolutionStatus.PROMOTED.value if published_version_id else EvolutionStatus.REVIEWING.value
    elif auto_promote and recommendation == "reject":
        _registry_reject(state)
        status = EvolutionStatus.REJECTED.value

    state["status"] = status
    if published_version_id:
        state["published_version_id"] = published_version_id
    if published_release_stage:
        state["published_release_stage"] = published_release_stage
        state["release_stage"] = published_release_stage
    state["promoted_version_id"] = published_version_id if published_release_stage == "baseline" else None
    state["result"] = {
        "run_id": state.get("run_id"),
        "role": role,
        "parent_hash": state.get("parent_hash"),
        "baseline_skill_dir": state.get("baseline_skill_dir"),
        "candidate_hash": state.get("candidate_hash"),
        "candidate_skill_dir": state.get("candidate_skill_dir"),
        "published_version_id": published_version_id,
        "published_release_stage": published_release_stage,
        "promoted_version_id": published_version_id if published_release_stage == "baseline" else None,
        "status": status,
        "recommendation": recommendation,
        "training_games": state.get("training_games", []),
        "battle_games": state.get("battle_games", []),
        "battle_result": battle,
        "promotion_gate": state.get("promotion_gate") or battle.get("promotion_gate"),
        "gate_report": state.get("gate_report") or battle.get("gate_report"),
        "release_gate": state.get("release_gate") or battle.get("release_gate"),
        "release_decision": state.get("release_decision") or battle.get("release_decision"),
        "trust_bundle": state.get("trust_bundle") or battle.get("trust_bundle"),
        "scenario_snapshots": list(state.get("scenario_snapshots") or []),
        "scenario_replay_report": state.get("scenario_replay_report"),
        "scenario_replay_summary": state.get("scenario_replay_summary"),
        "proposal_attribution_report": state.get("proposal_attribution_report") or battle.get("proposal_attribution_report"),
        "paired_seed_pairs": state.get("paired_seed_pairs") or battle.get("paired_seed_pairs") or [],
        "paired_seed_battle_table": state.get("paired_seed_battle_table") or battle.get("paired_seed_battle_table") or [],
        "paired_seed_summary": state.get("paired_seed_summary") or battle.get("paired_seed_summary"),
        "proposals": proposals,
        "generated_proposal_ids": list(state.get("generated_proposal_ids") or []),
        "preflight_passed_proposal_ids": list(state.get("preflight_passed_proposal_ids") or []),
        "preflight_rejected_proposal_ids": list(state.get("preflight_rejected_proposal_ids") or []),
        "accepted_proposal_ids": list(state.get("accepted_proposal_ids") or []),
        "rejected_proposal_ids": list(state.get("rejected_proposal_ids") or []),
        "preflight_reports": list(state.get("preflight_reports") or []),
        "diff": state.get("diff", []),
        "current_stage": state.get("current_stage"),
        "progress": state.get("progress", {}),
        "last_heartbeat_at": state.get("last_heartbeat_at"),
        "started_at": state.get("started_at"),
        "diagnostics": state.get("diagnostics", []),
        "warnings": state.get("warnings", []),
        "errors": state.get("errors", []),
    }
    _mark_stage(state, "done", status=status, progress={"recommendation": recommendation}, persist=False)
    finished_at = state.get("finished_at") or state.get("last_heartbeat_at")
    if finished_at:
        state["finished_at"] = finished_at
        state["result"]["finished_at"] = finished_at
    state["result"]["current_stage"] = state.get("current_stage")
    state["result"]["progress"] = state.get("progress", {})
    state["result"]["last_heartbeat_at"] = state.get("last_heartbeat_at")
    state["result"]["started_at"] = state.get("started_at")
    state["result"]["diagnostics"] = state.get("diagnostics", [])
    from .nodes import _persist_run_state
    _persist_run_state(state)
    if isinstance(state.get("result"), dict):
        state["result"]["warnings"] = state.get("warnings", [])
        state["result"]["errors"] = state.get("errors", [])
        state["result"]["diagnostics"] = state.get("diagnostics", [])
    _score_langfuse_evolve_run(state)
    return state


def _score_langfuse_evolve_run(state: dict) -> None:
    """Best-effort Langfuse scores for one evolution run."""
    try:
        observability = _observability()
        metadata = _langfuse_evolve_metadata(state)
        scores = _langfuse_evolve_scores(state)
        if not scores:
            return
        with _langfuse_evolve_context(observability, state, metadata):
            for name, value, data_type in scores:
                _score_langfuse_value(
                    observability,
                    name,
                    value,
                    data_type=data_type,
                    metadata=metadata,
                )
    except Exception:  # noqa: BLE001 - observability must not affect evolution
        _log.debug("Langfuse evolve scoring failed", exc_info=True)


def _observability() -> Any:
    return importlib.import_module("app.services.observability")


def _langfuse_evolve_context(observability: Any, state: dict, metadata: dict[str, Any]):
    from contextlib import nullcontext

    context_fn = getattr(observability, "langfuse_context", None)
    if not callable(context_fn):
        return nullcontext()
    try:
        trace_id = _langfuse_evolve_trace_id(observability, state)
        return context_fn(
            trace_name="evolve.run",
            trace_id=trace_id,
            session_id=str(state.get("run_id") or "") or None,
            metadata=metadata,
            tags=_langfuse_evolve_tags(state),
            input={
                "run_id": state.get("run_id"),
                "role": state.get("role"),
                "candidate_hash": state.get("candidate_hash"),
                "parent_hash": state.get("parent_hash"),
            },
        )
    except Exception:  # noqa: BLE001
        _log.debug("Langfuse evolve context creation failed", exc_info=True)
        return nullcontext()


def _langfuse_evolve_trace_id(observability: Any, state: dict) -> str | None:
    trace_id = state.get("langfuse_trace_id")
    if trace_id:
        return str(trace_id)
    create_trace_id = getattr(observability, "create_trace_id", None)
    if not callable(create_trace_id):
        return None
    run_id = str(state.get("run_id") or "")
    try:
        trace_id = create_trace_id(seed=f"evolve:{run_id}" if run_id else None)
    except Exception:  # noqa: BLE001
        _log.debug("Langfuse evolve trace id creation failed", exc_info=True)
        return None
    if trace_id:
        state["langfuse_trace_id"] = str(trace_id)
        return str(trace_id)
    return None


def _langfuse_evolve_metadata(state: dict) -> dict[str, Any]:
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    battle = _nested_dict(result, "battle_result") or _nested_dict(state, "battle_result")
    gate = _nested_dict(result, "promotion_gate") or _nested_dict(battle, "promotion_gate")
    gate_report = _nested_dict(result, "gate_report") or _nested_dict(battle, "gate_report")
    proposals = result.get("proposals") if isinstance(result.get("proposals"), list) else state.get("proposals")
    battle_games = result.get("battle_games") if isinstance(result.get("battle_games"), list) else state.get("battle_games")
    training_games = result.get("training_games") if isinstance(result.get("training_games"), list) else state.get("training_games")
    metadata = {
        "metric_family": "evolve",
        "run_id": state.get("run_id") or result.get("run_id"),
        "role": state.get("role") or result.get("role"),
        "status": state.get("status") or result.get("status"),
        "recommendation": state.get("recommendation") or result.get("recommendation"),
        "parent_hash": state.get("parent_hash") or result.get("parent_hash"),
        "candidate_hash": state.get("candidate_hash") or result.get("candidate_hash"),
        "auto_promote": (state.get("config") or {}).get("auto_promote") if isinstance(state.get("config"), dict) else None,
        "promote_allowed": gate.get("promote_allowed", gate_report.get("promote_allowed")),
        "promotion_gate_reasons": gate.get("reasons", gate_report.get("reasons")),
        "proposal_count": len(proposals) if isinstance(proposals, list) else None,
        "training_game_count": len(training_games) if isinstance(training_games, list) else None,
        "battle_game_count": len(battle_games) if isinstance(battle_games, list) else None,
    }
    return {key: value for key, value in metadata.items() if value is not None}


def _langfuse_evolve_tags(state: dict) -> list[str]:
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    tags = ["werewolf", "evolve"]
    role = state.get("role") or result.get("role")
    status = state.get("status") or result.get("status")
    recommendation = state.get("recommendation") or result.get("recommendation")
    if role:
        tags.append(f"role:{role}")
    if status:
        tags.append(f"status:{status}")
    if recommendation:
        tags.append(f"recommendation:{recommendation}")
    return tags


def _langfuse_evolve_scores(state: dict) -> list[tuple[str, Any, str]]:
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    battle = _nested_dict(result, "battle_result") or _nested_dict(state, "battle_result")
    gate = _nested_dict(result, "promotion_gate") or _nested_dict(battle, "promotion_gate")
    gate_report = _nested_dict(result, "gate_report") or _nested_dict(battle, "gate_report")
    decision_quality = _nested_dict(gate, "decision_quality") or _nested_dict(gate_report, "decision_quality")
    proposal_quality = _nested_dict(gate, "proposal_quality")
    baseline = _nested_dict(battle, "baseline")
    candidate = _nested_dict(battle, "candidate")
    proposals = result.get("proposals") if isinstance(result.get("proposals"), list) else state.get("proposals")

    scores: list[tuple[str, Any, str]] = []
    _append_score(scores, "evolve.recommendation", result.get("recommendation") or state.get("recommendation"), "CATEGORICAL")
    _append_score(scores, "evolve.status", result.get("status") or state.get("status"), "CATEGORICAL")
    _append_score(scores, "evolve.candidate_win_rate", battle.get("candidate_win_rate", candidate.get("target_win_rate")), "NUMERIC")
    _append_score(scores, "evolve.baseline_win_rate", battle.get("baseline_win_rate", baseline.get("target_win_rate")), "NUMERIC")
    _append_score(scores, "evolve.win_rate_delta", _evolve_win_rate_delta(battle, candidate, baseline), "NUMERIC")
    _append_score(scores, "evolve.significant", battle.get("significant"), "BOOLEAN")
    _append_score(scores, "evolve.promote_allowed", gate.get("promote_allowed", gate_report.get("promote_allowed")), "BOOLEAN")
    _append_score(scores, "evolve.candidate_error_rate", candidate.get("error_rate"), "NUMERIC")
    _append_score(scores, "evolve.baseline_error_rate", baseline.get("error_rate"), "NUMERIC")
    _append_score(
        scores,
        "evolve.candidate_decision_issue_rate",
        _evolve_decision_issue_rate(_nested_dict(decision_quality, "candidate")),
        "NUMERIC",
    )
    _append_score(
        scores,
        "evolve.baseline_decision_issue_rate",
        _evolve_decision_issue_rate(_nested_dict(decision_quality, "baseline")),
        "NUMERIC",
    )
    _append_score(scores, "evolve.proposal_count", _proposal_count(proposals, proposal_quality), "NUMERIC")
    _append_score(scores, "evolve.proposal_min_quality", proposal_quality.get("min_score"), "NUMERIC")
    _append_score(scores, "evolve.proposal_high_risk_count", _proposal_high_risk_count(proposals, proposal_quality), "NUMERIC")
    return scores


def _append_score(scores: list[tuple[str, Any, str]], name: str, value: Any, data_type: str) -> None:
    if value is None:
        return
    if data_type == "CATEGORICAL":
        text = str(value)
        if text:
            scores.append((name, text, data_type))
        return
    if data_type == "BOOLEAN":
        parsed = _score_bool(value)
        if parsed is not None:
            scores.append((name, parsed, data_type))
        return
    if data_type == "NUMERIC":
        number = _score_number(value)
        if number is not None:
            scores.append((name, number, data_type))


def _score_langfuse_value(
    observability: Any,
    name: str,
    value: Any,
    *,
    data_type: str,
    metadata: dict[str, Any],
) -> None:
    score_current_trace = getattr(observability, "score_current_trace", None)
    if not callable(score_current_trace):
        return
    try:
        score_current_trace(name, value, data_type=data_type, metadata=metadata)
    except Exception:  # noqa: BLE001
        _log.debug("Langfuse evolve score failed for %s", name, exc_info=True)


def _nested_dict(mapping: dict[str, Any], key: str) -> dict[str, Any]:
    value = mapping.get(key) if isinstance(mapping, dict) else None
    return value if isinstance(value, dict) else {}


def _evolve_win_rate_delta(battle: dict[str, Any], candidate: dict[str, Any], baseline: dict[str, Any]) -> Any:
    if battle.get("win_rate_delta") is not None:
        return battle.get("win_rate_delta")
    candidate_rate = _score_number(battle.get("candidate_win_rate", candidate.get("target_win_rate")))
    baseline_rate = _score_number(battle.get("baseline_win_rate", baseline.get("target_win_rate")))
    if candidate_rate is None or baseline_rate is None:
        return None
    return candidate_rate - baseline_rate


def _evolve_decision_issue_rate(metrics: dict[str, Any]) -> Any:
    if not metrics:
        return None
    if metrics.get("issue_rate") is not None:
        return metrics.get("issue_rate")
    return _decision_issue_rate(metrics)


def _proposal_count(proposals: Any, proposal_quality: dict[str, Any]) -> Any:
    if proposal_quality.get("count") is not None:
        return proposal_quality.get("count")
    if isinstance(proposals, list):
        return len(proposals)
    return None


def _proposal_high_risk_count(proposals: Any, proposal_quality: dict[str, Any]) -> Any:
    if proposal_quality.get("high_risk") is not None:
        return proposal_quality.get("high_risk")
    if not isinstance(proposals, list):
        return None
    total = 0
    for proposal in proposals:
        if not isinstance(proposal, dict):
            continue
        quality = proposal.get("quality_score") if isinstance(proposal.get("quality_score"), dict) else {}
        if str(proposal.get("risk") or "").lower() == "high" or quality.get("risk") == "high":
            total += 1
    return total


def _score_number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _score_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _recommendation(proposals: list[dict[str, Any]], battle: dict[str, Any], *, cfg: dict[str, Any] | None = None) -> str:
    """Map proposals + battle outcome to promote|reject|review."""
    if not proposals:
        return "reject"
    # Auto-rollback: if candidate regresses significantly, reject immediately
    if cfg and isinstance(battle, dict) and battle.get("significant"):
        regression_threshold = float(cfg.get("regression_threshold", 0.05) or 0.05)
        win_rate_delta = float(battle.get("win_rate_delta") or 0.0)
        if win_rate_delta < -regression_threshold:
            _log.info("recommendation: regression detected (delta=%.3f < -%.3f), rejecting", win_rate_delta, regression_threshold)
            return "reject"
    if battle.get("skipped"):
        return "reject" if battle.get("reason") == "no_candidate_changes" else "review"
    gate = battle.get("promotion_gate")
    if isinstance(gate, dict):
        recommendation = str(gate.get("recommendation") or "")
        if recommendation in {"promote", "review", "reject"}:
            return recommendation
        if gate.get("promote_allowed"):
            return "promote"
        return "review" if battle.get("significant") else "reject"
    if battle.get("significant"):
        return "promote"
    return "reject"


def _registry_promote(state: EvolveState) -> dict[str, str] | None:
    """Publish candidate skills to the registry according to release gate stage.

    Returns published version metadata, or None on failure (degrade to review).
    """
    role = state.get("role", "")
    candidate_dir = state.get("candidate_skill_dir")
    if not role:
        message = "promote: missing role"
        state.setdefault("errors", []).append(message)
        _record_diagnostic(state, kind="registry_error", stage="registry.promote", message=message)
        return None
    if not candidate_dir:
        message = "promote: missing candidate_skill_dir"
        state.setdefault("errors", []).append(message)
        _record_diagnostic(state, kind="registry_error", stage="registry.promote", message=message)
        return None
    try:
        skills = _read_skill_contents(candidate_dir)
    except Exception as exc:  # noqa: BLE001 — degrade to review with a concrete reason
        message = f"promote: failed to read candidate skills: {exc}"
        state.setdefault("errors", []).append(message)
        _record_diagnostic(state, kind="registry_error", stage="registry.read_candidate", message=message, exc=exc)
        return None
    if not skills:
        message = f"promote: no skill files found in candidate_skill_dir={candidate_dir}"
        state.setdefault("errors", []).append(message)
        _record_diagnostic(state, kind="registry_error", stage="registry.promote", message=message)
        return None
    registry = None
    try:
        registry = _registry(state)
        release_stage = _release_stage_for_registry_publish(state)
        version_id = _safe_id(str(state.get("candidate_hash") or f"{role}_{state.get('run_id', 'run')}"))
        proposal_ids = [str(p.get("proposal_id")) for p in state.get("proposals", []) if p.get("proposal_id")]
        published = registry.publish_skills(
            role,
            skills,
            parent_id=str(state.get("parent_hash") or "") or None,
            source="evolution",
            run_id=str(state.get("run_id") or ""),
            proposal_ids=proposal_ids,
            version_id=version_id,
            release_stage=release_stage,
            set_as_baseline=release_stage == "baseline",
            expected_current=registry.get_baseline(role) if release_stage == "baseline" else None,
            provenance=_registry_publish_provenance(state, release_stage=release_stage),
        )
        state["published_release_stage"] = release_stage
        state["release_stage"] = release_stage
        if release_stage == "baseline":
            state["promoted_version_id"] = published
        _record_diagnostic(
            state,
            kind="registry_publish",
            stage="registry.promote",
            message=f"published {role}/{published} as {release_stage}",
            level="info",
        )
        _log.info("decide: published %s/%s as %s", role, published, release_stage)
        return {"version_id": published, "release_stage": release_stage}
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        _log.error("decide: registry promote failed for role=%s: %s", role, exc, exc_info=True)
        message = f"promote: {exc}"
        state.setdefault("errors", []).append(message)
        _record_diagnostic(state, kind="registry_error", stage="registry.promote", message=message, exc=exc)
        return None
    finally:
        if registry is not None:
            registry.close()


def _release_stage_for_registry_publish(state: EvolveState) -> str:
    decision = str(
        state.get("release_decision")
        or (state.get("release_gate") or {}).get("decision")
        or ((state.get("battle_result") or {}).get("release_gate") or {}).get("decision")
        or ((state.get("battle_result") or {}).get("release_decision"))
        or ""
    ).strip().lower()
    return {
        "shadow_candidate": "shadow",
        "canary_candidate": "canary",
        "baseline_promote": "baseline",
    }.get(decision, "shadow")


def _registry_publish_provenance(state: EvolveState, *, release_stage: str) -> dict[str, Any]:
    battle = state.get("battle_result") if isinstance(state.get("battle_result"), dict) else {}
    gate_report = state.get("gate_report") if isinstance(state.get("gate_report"), dict) else {}
    if not gate_report and isinstance(battle.get("gate_report"), dict):
        gate_report = battle["gate_report"]
    trust_bundle = state.get("trust_bundle") if isinstance(state.get("trust_bundle"), dict) else {}
    if not trust_bundle and isinstance(battle.get("trust_bundle"), dict):
        trust_bundle = battle["trust_bundle"]
    release_decision = str(
        state.get("release_decision")
        or (state.get("release_gate") or {}).get("decision")
        or battle.get("release_decision")
        or (battle.get("release_gate") or {}).get("decision")
        or ""
    ).strip()
    return {
        "automatic_action": "auto_promote",
        "release_stage": release_stage,
        "release_decision": release_decision or None,
        "trust_bundle_id": trust_bundle.get("trust_bundle_id"),
        "bundle_hash": trust_bundle.get("bundle_hash"),
        "gate_report_id": trust_bundle.get("gate_report_id") or gate_report.get("gate_report_id"),
        "attribution_report_id": trust_bundle.get("attribution_report_id"),
    }


def _registry_reject(state: EvolveState) -> None:
    """Persist rejected proposals so future consolidation can dedup against them."""
    role = state.get("role", "")
    proposals = [p for p in state.get("proposals", []) if isinstance(p, dict)]
    if not role or not proposals:
        return
    registry = None
    try:
        registry = _registry(state)
        battle = state.get("battle_result") if isinstance(state.get("battle_result"), dict) else None
        registry.save_rejected(role, proposals, battle)
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        _log.error("decide: registry reject failed for role=%s: %s", role, exc, exc_info=True)
        message = f"reject: {exc}"
        state.setdefault("errors", []).append(message)
        _record_diagnostic(state, kind="registry_error", stage="registry.reject", message=message, exc=exc)
    finally:
        if registry is not None:
            registry.close()


def _registry(state: EvolveState):
    """Build the configured runtime registry."""
    from app.lib.version import version_registry_from_env

    paths = state.get("paths")
    return version_registry_from_env(paths=paths)


def _freeze_baseline(
    state: EvolveState,
    role: str,
    cfg: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Freeze the baseline version config used by this evolution run."""
    explicit_parent = state.get("parent_hash") or cfg.get("parent_hash")
    if explicit_parent:
        version_id = str(explicit_parent)
        registry = None
        try:
            from app.lib.version import ensure_version_allowed_for_default_use

            registry = _registry(state)
            ensure_version_allowed_for_default_use(registry, role, version_id)
        except FileNotFoundError as exc:
            raise ValueError(
                f"role version {role}/{version_id} not found; explicit parent_hash must resolve in registry"
            ) from exc
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001 - explicit registry parents must be verifiable.
            raise RuntimeError(
                f"init: explicit parent release-stage check failed for role={role}: {exc}"
            ) from exc
        finally:
            if registry is not None:
                registry.close()
        return version_id, {
            "name": "explicit",
            "role_versions": {role: version_id},
            "notes": ["explicit parent_hash supplied"],
        }

    fallback = f"baseline_{role}"
    registry = None
    try:
        from app.lib.version import build_baseline_config

        registry = _registry(state)
        config = build_baseline_config(registry)
        baseline = config.role_versions.get(role)
        if baseline:
            return baseline, config.to_dict()
        message = f"init: no registry baseline found for role={role}; using {fallback}"
    except Exception as exc:  # noqa: BLE001 — init can still run with explicit fallback
        message = f"init: baseline freeze failed for role={role}: {exc}; using {fallback}"
    finally:
        if registry is not None:
            registry.close()

    _log.warning(message, exc_info=True)
    state.setdefault("warnings", []).append(message)
    return fallback, {
        "name": "fallback",
        "role_versions": {role: fallback},
        "notes": [message],
    }


def _resolve_baseline_skill_dir(state: EvolveState, baseline_config: dict[str, Any]) -> str | None:
    """Materialize the frozen registry baseline as this run's skill root.

    If the registry baseline cannot be materialized, fall back to the incoming
    skill_dir so older/dev flows keep working.
    """
    fallback = _baseline_skill_dir(state, state.get("config", {}), include_materialized=False)
    registry = None
    try:
        from app.lib.version import SkillVersionConfig, build_composite_skill_dir

        config = SkillVersionConfig.from_dict(baseline_config)
        if not config.role_versions:
            return str(fallback) if fallback is not None else None
        if config.name == "fallback" or (config.name == "explicit" and fallback is not None):
            return str(fallback) if fallback is not None else None
        registry = _registry(state)
        skill_dir = build_composite_skill_dir(registry, config)
        if skill_dir is not None:
            return str(skill_dir)
    except Exception as exc:  # noqa: BLE001 — registry-backed baseline is best-effort
        message = f"init: failed to materialize baseline skills: {exc}"
        _log.warning(message, exc_info=True)
        state.setdefault("warnings", []).append(message)
    finally:
        if registry is not None:
            registry.close()
    return str(fallback) if fallback is not None else None


def _baseline_skill_dir(
    state: EvolveState,
    cfg: dict[str, Any] | None = None,
    *,
    include_materialized: bool = True,
) -> Any:
    """Return the skill root for the frozen baseline, with legacy fallback."""
    cfg = cfg if cfg is not None else state.get("config", {})
    if include_materialized and state.get("baseline_skill_dir") is not None:
        return state.get("baseline_skill_dir")
    return cfg.get("skill_dir") or state.get("skill_dir")


