"""Evolve subgraph nodes — self-evolution pipeline for one role.

Nodes: init → training → consolidate → apply → scenario_replay → battle → decide
"""

from __future__ import annotations

import logging
import importlib
from pathlib import Path
from typing import Any

from app.graphs.shared.nodes.game_batch import BatchAbortedError, valid_completed_games
from app.graphs.shared.state import EvolveState
from app.lib.evolve import (
    EvolutionStatus,
    SkillVersionConfig,
    SkillConsolidation,
    SkillDiff,
    SkillProposal,
    annotate_proposal_quality,
    apply_proposals,
    build_consolidation_messages,
    build_evolution_gate_report,
    build_paired_seed_battle_table,
    build_trust_bundle,
    deduplicate_proposals,
    format_skill_inventory,
    modifiable_skill_files,
    normalize_run_id,
    parse_consolidation,
)

_log = logging.getLogger(__name__)

_STAGE_PROGRESS = {
    "init": 0.05,
    "training": 0.25,
    "consolidating": 0.45,
    "applying": 0.65,
    "scenario_replay": 0.75,
    "battling": 0.85,
    "decide": 0.95,
    "done": 1.0,
}

_AGENT_RUNTIME_CONFIG_KEYS: tuple[str, ...] = (
    "agent_fast_smoke",
    "agent_policy_skip_llm_enabled",
    "agent_policy_skip_llm_preset",
    "agent_policy_skip_llm_actions",
    "agent_memory_compression_enabled",
    "agent_prompt_max_total_chars",
    "agent_prompt_max_message_chars",
    "agent_prompt_min_message_chars",
    "agent_memory_recent_closed_segments",
    "agent_memory_max_events_per_segment",
    "agent_memory_event_max_chars",
)


def _record_diagnostic(
    state: EvolveState,
    *,
    kind: str,
    stage: str,
    message: str,
    exc: BaseException | None = None,
    level: str = "error",
) -> None:
    record: dict[str, Any] = {
        "kind": kind,
        "stage": stage,
        "level": level,
        "message": message,
    }
    if exc is not None:
        record["exception_type"] = type(exc).__name__
        record["exception_message"] = str(exc)
        diagnostic = getattr(exc, "diagnostic", None)
        if isinstance(diagnostic, dict):
            record["diagnostic"] = dict(diagnostic)
    state.setdefault("diagnostics", []).append(record)


def _mark_stage(
    state: EvolveState,
    stage: str,
    *,
    status: str | None = None,
    progress: dict[str, Any] | None = None,
    persist: bool = True,
) -> None:
    from app.util.time import beijing_now_iso

    now = beijing_now_iso()
    if status is not None:
        state["status"] = status
    state["current_stage"] = stage
    state["last_heartbeat_at"] = now
    state["progress"] = {
        "stage": stage,
        "percent": _STAGE_PROGRESS.get(stage, 0.0),
        **dict(progress or {}),
    }
    if persist and _should_persist_stage_state(state):
        _persist_run_state(state, record_warning=False)
    _emit_progress_update(state)
    if _cancel_requested(state):
        raise RuntimeError("stopped")


def _progress_snapshot(state: EvolveState) -> dict[str, Any]:
    result = state.get("result") if isinstance(state.get("result"), dict) else {}
    battle = result.get("battle_result") or state.get("battle_result")
    battle = battle if isinstance(battle, dict) else {}
    return {
        "run_id": state.get("run_id"),
        "role": state.get("role"),
        "batch_id": state.get("batch_id"),
        "status": state.get("status"),
        "current_stage": state.get("current_stage"),
        "progress": dict(state.get("progress", {}) or {}),
        "training_games": list(state.get("training_games", []) or []),
        "battle_games": list(state.get("battle_games", []) or []),
        "training_game_count": state.get("training_game_count") or state.get("config", {}).get("training_games"),
        "battle_game_count": state.get("battle_game_count") or state.get("config", {}).get("battle_games"),
        "parent_hash": state.get("parent_hash"),
        "candidate_hash": state.get("candidate_hash"),
        "candidate_skill_dir": state.get("candidate_skill_dir"),
        "baseline_skill_dir": state.get("baseline_skill_dir"),
        "battle_result": battle,
        "promotion_gate": state.get("promotion_gate") or result.get("promotion_gate") or battle.get("promotion_gate"),
        "gate_report": state.get("gate_report") or result.get("gate_report") or battle.get("gate_report"),
        "release_gate": state.get("release_gate") or result.get("release_gate") or battle.get("release_gate"),
        "release_decision": state.get("release_decision") or result.get("release_decision") or battle.get("release_decision"),
        "trust_bundle": state.get("trust_bundle") or result.get("trust_bundle") or battle.get("trust_bundle"),
        "paired_seed_pairs": list(state.get("paired_seed_pairs") or result.get("paired_seed_pairs") or battle.get("paired_seed_pairs") or []),
        "paired_seed_battle_table": list(
            state.get("paired_seed_battle_table")
            or result.get("paired_seed_battle_table")
            or battle.get("paired_seed_battle_table")
            or []
        ),
        "paired_seed_summary": state.get("paired_seed_summary") or result.get("paired_seed_summary") or battle.get("paired_seed_summary"),
        "proposals": list(state.get("proposals", []) or []),
        "scenario_snapshots": list(state.get("scenario_snapshots") or result.get("scenario_snapshots") or []),
        "scenario_replay_report": state.get("scenario_replay_report") or result.get("scenario_replay_report"),
        "scenario_replay_summary": state.get("scenario_replay_summary") or result.get("scenario_replay_summary"),
        "proposal_attribution_report": (
            state.get("proposal_attribution_report")
            or result.get("proposal_attribution_report")
            or battle.get("proposal_attribution_report")
            or (state.get("gate_report") or result.get("gate_report") or battle.get("gate_report") or {}).get("proposal_attribution")
        ),
        "generated_proposal_ids": list(state.get("generated_proposal_ids") or result.get("generated_proposal_ids") or []),
        "preflight_passed_proposal_ids": list(
            state.get("preflight_passed_proposal_ids") or result.get("preflight_passed_proposal_ids") or []
        ),
        "preflight_rejected_proposal_ids": list(
            state.get("preflight_rejected_proposal_ids") or result.get("preflight_rejected_proposal_ids") or []
        ),
        "accepted_proposal_ids": list(state.get("accepted_proposal_ids") or result.get("accepted_proposal_ids") or []),
        "rejected_proposal_ids": list(state.get("rejected_proposal_ids") or result.get("rejected_proposal_ids") or []),
        "preflight_reports": list(state.get("preflight_reports") or result.get("preflight_reports") or []),
        "diff": list(state.get("diff", []) or []),
        "recommendation": state.get("recommendation") or result.get("recommendation"),
        "diagnostics": list(state.get("diagnostics", []) or []),
        "warnings": list(state.get("warnings", []) or []),
        "errors": list(state.get("errors", []) or []),
        "last_heartbeat_at": state.get("last_heartbeat_at"),
        "started_at": state.get("started_at"),
    }


def _emit_progress_update(state: EvolveState) -> None:
    sink = state.get("progress_sink")
    if not callable(sink):
        return
    try:
        sink(_progress_snapshot(state))
    except Exception as exc:  # noqa: BLE001 - UI progress publishing is best-effort
        _log.warning("failed to publish evolution progress update: %s", exc)


def _cancel_requested(state: EvolveState) -> bool:
    cancel_check = state.get("cancel_check")
    if not callable(cancel_check):
        return False
    try:
        return bool(cancel_check())
    except Exception as exc:  # noqa: BLE001 - cancellation checks should not break graph execution
        _log.warning("failed to check evolution cancellation: %s", exc)
        return False


def _should_persist_stage_state(state: EvolveState) -> bool:
    return bool(
        state.get("run_id")
        and (state.get("paths") is not None or state.get("storage_provider") is not None)
    )


async def init_evolve_node(state: EvolveState) -> dict:
    """Initialize evolution run: freeze baseline, create run_id.

    Defaults are sourced from EvolutionConfig so there is a single source of
    truth for game counts, seeds, and the promotion gate thresholds.
    """
    import uuid

    from app.util.time import beijing_now_iso
    from app.lib.evolve import EvolutionConfig

    defaults = EvolutionConfig()
    role = state.get("role") or state.get("config", {}).get("role") or "villager"
    cfg = dict(state.get("config", {}))
    cfg.setdefault("training_games", state.get("training_game_count", defaults.training_games))
    cfg.setdefault("battle_games", state.get("battle_game_count", defaults.battle_games))
    cfg.setdefault("max_days", defaults.max_days)
    cfg.setdefault("seed_start", defaults.seed_start)
    cfg.setdefault("battle_seed_start", defaults.battle_seed_start)
    cfg.setdefault("auto_promote", defaults.auto_promote)
    cfg.setdefault("max_proposals", defaults.max_proposals)
    cfg.setdefault("game_concurrency", defaults.game_concurrency)
    cfg.setdefault("promote_win_rate_margin", defaults.promote_win_rate_margin)
    cfg.setdefault("battle_error_rate_ceiling", defaults.battle_error_rate_ceiling)
    cfg.setdefault("battle_min_completed_games", defaults.battle_min_completed_games)
    cfg.setdefault("battle_confidence_z", defaults.battle_confidence_z)
    cfg.setdefault("promotion_min_completed_games", defaults.promotion_min_completed_games)
    cfg.setdefault("promotion_min_valid_game_rate", defaults.promotion_min_valid_game_rate)
    cfg.setdefault("promotion_max_decision_issue_rate", defaults.promotion_max_decision_issue_rate)
    cfg.setdefault("promotion_min_proposal_quality", defaults.promotion_min_proposal_quality)

    run_id = normalize_run_id(state.get("run_id"), default=f"evolve_{uuid.uuid4().hex[:12]}")

    state["role"] = role
    state["config"] = cfg
    state["run_id"] = run_id
    state.setdefault("started_at", beijing_now_iso())
    parent_hash, baseline_config = _freeze_baseline(state, role, cfg)
    state["parent_hash"] = parent_hash
    state["baseline_config"] = baseline_config
    baseline_skill_dir = _resolve_baseline_skill_dir(state, baseline_config)
    if baseline_skill_dir is not None:
        state["baseline_skill_dir"] = baseline_skill_dir
    state.setdefault("candidate_hash", None)
    state.setdefault("status", EvolutionStatus.TRAINING.value)
    state.setdefault("training_games", [])
    state.setdefault("battle_games", [])
    state.setdefault("proposals", [])
    state.setdefault("diff", [])
    state.setdefault("warnings", [])
    state.setdefault("errors", [])
    state.setdefault("diagnostics", [])
    _log.info("init: role=%s run_id=%s", state.get("role"), state.get("run_id"))
    _mark_stage(state, "init", status=state.get("status"), persist=True)
    return state


async def training_node(state: EvolveState) -> dict:
    """Run self-play training games through the reusable game subgraph."""
    from app.lib.evolve import EvolutionConfig

    role = state.get("role", "villager")
    cfg = state.get("config", {})
    defaults = EvolutionConfig()
    training_games = int(cfg.get("training_games", defaults.training_games) or 0)
    max_days = int(cfg.get("max_days", 20) or 20)
    seed_start = int(cfg.get("seed_start", 0) or 0)
    _log.info("training: role=%s games=%d", role, training_games)
    _mark_stage(
        state,
        "training",
        status=EvolutionStatus.TRAINING.value,
        progress={"target_games": training_games, "completed_games": len(state.get("training_games", []))},
    )
    try:
        games = await _run_games(
            state,
            count=training_games,
            seed_start=seed_start,
            max_days=max_days,
            label="train",
        )
        state["training_games"] = await _attach_training_evidence(
            games,
            role=role,
            model=state.get("model"),
            enable_judge=_training_judge_enabled(cfg),
            judge_max_decisions=_training_judge_max_decisions(cfg),
            judge_concurrency=_training_judge_concurrency(cfg),
            judge_timeout_seconds=_training_judge_timeout_seconds(cfg),
            judge_fn=state.get("decision_judge_fn"),
            warnings=state.setdefault("warnings", []),
        )
        _mark_stage(
            state,
            "training",
            status=state.get("status"),
            progress={"target_games": training_games, "completed_games": len(state.get("training_games", []))},
        )
    except BatchAbortedError as exc:
        _log.error("training: aborted for role=%s: %s", role, exc)
        state["training_games"] = []
        message = f"training: {exc}"
        state.setdefault("errors", []).append(message)
        _record_diagnostic(state, kind="training_error", stage="training.run_games", message=message, exc=exc)
        state["status"] = EvolutionStatus.FAILED.value
        _mark_stage(state, "training", status=state.get("status"), progress={"target_games": training_games, "completed_games": 0})
    except Exception as exc:  # noqa: BLE001 — keep graph state recoverable
        _log.error("training: failed for role=%s: %s", role, exc)
        state["training_games"] = []
        message = f"training: {exc}"
        state.setdefault("errors", []).append(message)
        _record_diagnostic(state, kind="training_error", stage="training.run_games", message=message, exc=exc)
        state["status"] = EvolutionStatus.FAILED.value
        _mark_stage(state, "training", status=state.get("status"), progress={"target_games": training_games, "completed_games": 0})
    return state


async def consolidate_node(state: EvolveState) -> dict:
    """Consolidate training experience into skill proposals via the LLM.

    Loads the target role's current skills, summarizes the role-relevant
    decisions from training games, and asks consolidate_chain for structured
    proposals. Falls back to empty proposals on any failure (never breaks).
    """
    from app.services.chain import run_consolidate_chain

    role = state.get("role", "")
    _log.info("consolidate: role=%s", role)
    _mark_stage(state, "consolidating", status=EvolutionStatus.CONSOLIDATING.value)
    cfg = state.get("config", {})
    max_proposals = int(cfg.get("max_proposals", 3) or 0)
    games = valid_completed_games(state.get("training_games", []))

    if max_proposals <= 0 or not games:
        state["proposals"] = []
        state["consolidation"] = None
        state["generated_proposal_ids"] = []
        state["preflight_passed_proposal_ids"] = []
        state["preflight_rejected_proposal_ids"] = []
        state["preflight_reports"] = []
        _mark_stage(state, "consolidating", status=state.get("status"), progress={"proposal_count": 0})
        return state

    skills = _load_role_skills(
        role,
        _baseline_skill_dir(state, cfg),
        warnings=state.setdefault("warnings", []),
    )
    source_games = sorted({str(g.get("game_id")) for g in games if g.get("game_id")})
    rejected = _load_rejected(state, role)
    messages = build_consolidation_messages(
        role=role,
        training_games=games,
        skills_inventory=format_skill_inventory(skills),
        modifiable_files=modifiable_skill_files(skills),
        rejected=rejected,
        max_proposals=max_proposals,
    )

    consolidation: SkillConsolidation
    try:
        raw = await run_consolidate_chain(state.get("model"), messages=messages)
        consolidation = parse_consolidation(
            role=role,
            raw_output=raw,
            run_id=str(state.get("run_id", "")),
            parent_hash=str(state.get("parent_hash", "")),
            source_games=source_games,
            source_window=len(games),
            max_proposals=max_proposals,
            rejected=rejected,
            duplicate_threshold=float(
                cfg.get("duplicate_similarity_threshold", cfg.get("trust_duplicate_similarity_threshold", 0.72))
                or 0.72
            ),
        )
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        _log.error("consolidate: failed for role=%s: %s", role, exc)
        message = f"consolidate: {exc}"
        state.setdefault("errors", []).append(message)
        _record_diagnostic(state, kind="consolidation_error", stage="consolidate.llm", message=message, exc=exc)
        consolidation = SkillConsolidation(role=role, run_id=str(state.get("run_id", "")))

    _merge_consolidation_diagnostics(state, consolidation)

    # Drop proposals that repeat a previously rejected direction.
    if rejected and consolidation.proposals:
        try:
            before_ids = [p.proposal_id for p in consolidation.proposals]
            survivors = {
                d["proposal_id"]
                for d in deduplicate_proposals([p.to_dict() for p in consolidation.proposals], rejected)
            }
            dropped = len(consolidation.proposals) - len(survivors)
            if dropped:
                _log.info("consolidate: dropped %d proposal(s) overlapping rejected buffer", dropped)
            dropped_ids = [proposal_id for proposal_id in before_ids if proposal_id not in survivors]
            for proposal_id in dropped_ids:
                if proposal_id not in consolidation.preflight_rejected_proposal_ids:
                    consolidation.preflight_rejected_proposal_ids.append(proposal_id)
                consolidation.preflight_reports.append(
                    {
                        "proposal_id": proposal_id,
                        "status": "blocked",
                        "reasons": ["duplicate rejected proposal direction"],
                        "checks": {"deduplicate_rejected": True},
                    }
                )
                warning = f"consolidate: dropped proposal {proposal_id}: duplicate rejected proposal direction"
                if warning not in consolidation.warnings:
                    consolidation.warnings.append(warning)
                state.setdefault("warnings", []).append(warning)
            consolidation.proposals = [p for p in consolidation.proposals if p.proposal_id in survivors]
            consolidation.preflight_passed_proposal_ids = [
                proposal_id for proposal_id in consolidation.preflight_passed_proposal_ids if proposal_id in survivors
            ]
        except Exception as exc:  # noqa: BLE001 — dedup should not block consolidation
            message = f"consolidate: rejected proposal dedup failed for role={role}: {exc}"
            _log.warning(message)
            state.setdefault("warnings", []).append(message)
            _record_diagnostic(state, kind="consolidation_error", stage="consolidate.dedup_rejected", message=message, exc=exc, level="warning")

    annotate_proposal_quality(consolidation.proposals, rejected=rejected)
    state["rejected_buffer"] = [dict(item) for item in rejected if isinstance(item, dict)]
    state["consolidation"] = consolidation.to_dict()
    state["proposals"] = [p.to_dict() for p in consolidation.proposals]
    state["generated_proposal_ids"] = list(consolidation.generated_proposal_ids)
    state["preflight_passed_proposal_ids"] = list(consolidation.preflight_passed_proposal_ids)
    state["preflight_rejected_proposal_ids"] = list(consolidation.preflight_rejected_proposal_ids)
    state.setdefault("accepted_proposal_ids", list(consolidation.accepted_proposal_ids))
    state["rejected_proposal_ids"] = list(consolidation.rejected_proposal_ids)
    state["preflight_reports"] = [dict(item) for item in consolidation.preflight_reports]
    _mark_stage(state, "consolidating", status=state.get("status"), progress={"proposal_count": len(state.get("proposals", []))})
    return state


def _merge_consolidation_diagnostics(state: EvolveState, consolidation: SkillConsolidation) -> None:
    warnings = state.setdefault("warnings", [])
    for message in consolidation.warnings:
        text = str(message)
        if text and text not in warnings:
            warnings.append(text)
    errors = state.setdefault("errors", [])
    for message in consolidation.errors:
        text = str(message)
        if text and text not in errors:
            errors.append(text)


def _load_rejected(state: EvolveState, role: str) -> list[dict[str, Any]]:
    """Load previously rejected proposals for a role (empty on any failure)."""
    registry = None
    try:
        registry = _registry(state)
        return registry.load_rejected(role)
    except Exception as exc:  # noqa: BLE001 — dedup is best-effort
        message = f"consolidate: failed to load rejected buffer for role={role}: {exc}"
        _log.warning(message)
        state.setdefault("warnings", []).append(message)
        return []
    finally:
        if registry is not None:
            registry.close()


def _load_role_skills(role: str, skill_dir: Any, *, warnings: list[str] | None = None) -> list:
    """Load MarkdownSkills for one role from a skill directory (empty if none)."""
    from pathlib import Path

    from app.services.prompt import load_markdown_skill_report

    if not skill_dir:
        return []
    root = Path(skill_dir)
    if not root.exists():
        return []
    report = load_markdown_skill_report(root)
    if warnings is not None:
        for diagnostic in report.diagnostics:
            warnings.append(f"consolidate: skill load {diagnostic.format()}")
    return [
        s for s in report.skills
        if s.role is None or (s.role is not None and s.role.value == role)
    ]


async def apply_node(state: EvolveState) -> dict:
    """Apply approved proposals to skill files via the LLM, writing a candidate dir.

    Reads the baseline role skills, asks apply_chain to rewrite them, validates
    + smoke-tests the result, then writes the new contents to a candidate skill
    directory that the battle node can mount. On no-op/failure the candidate
    falls back to the parent (baseline) hash with an empty diff.
    """
    from app.services.chain import run_apply_chain

    role = state.get("role", "")
    _log.info("apply: role=%s", role)
    _mark_stage(state, "applying", status=EvolutionStatus.APPLYING.value)

    consolidation_data = state.get("consolidation")
    consolidation = (
        SkillConsolidation.from_dict(consolidation_data)
        if isinstance(consolidation_data, dict)
        else SkillConsolidation(
            role=role,
            run_id=str(state.get("run_id", "")),
            proposals=[SkillProposal.from_dict(p) for p in state.get("proposals", [])],
        )
    )

    if not consolidation.proposals:
        state["candidate_hash"] = state.get("parent_hash")
        state["candidate_skill_dir"] = None
        state["diff"] = []
        _mark_stage(state, "applying", status=state.get("status"), progress={"diff_count": 0})
        return state

    cfg = state.get("config", {})
    skill_dir = _baseline_skill_dir(state, cfg)
    try:
        current_skills = _read_skill_contents(skill_dir)
    except Exception as exc:  # noqa: BLE001 — baseline skill read failure should be visible and recoverable
        message = f"apply: failed to read current skills: {exc}"
        _log.error(message)
        state.setdefault("errors", []).append(message)
        _record_diagnostic(state, kind="apply_error", stage="apply.read_baseline", message=message, exc=exc)
        _merge_apply_warnings(state, [message])
        state["candidate_hash"] = state.get("parent_hash")
        state["candidate_skill_dir"] = None
        state["diff"] = []
        state["consolidation"] = consolidation.to_dict()
        _mark_stage(state, "applying", status=state.get("status"), progress={"diff_count": 0})
        return state

    async def _apply_fn(messages: list[dict[str, str]]) -> str:
        return await run_apply_chain(state.get("model"), messages=messages)

    try:
        new_skills, diffs = await apply_proposals(current_skills, consolidation, _apply_fn)
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        _log.error("apply: failed for role=%s: %s", role, exc)
        message = f"apply: {exc}"
        state.setdefault("errors", []).append(message)
        _record_diagnostic(state, kind="apply_error", stage="apply.proposals", message=message, exc=exc)
        new_skills, diffs = current_skills, []

    _merge_apply_warnings(state, consolidation.errors)
    state["consolidation"] = consolidation.to_dict()

    if not diffs:
        state["candidate_hash"] = state.get("parent_hash")
        state["candidate_skill_dir"] = None
        state["diff"] = []
        if consolidation.errors:
            for message in consolidation.errors:
                _record_diagnostic(state, kind="apply_error", stage="apply.validation", message=str(message), level="warning")
        _mark_stage(state, "applying", status=state.get("status"), progress={"diff_count": 0})
        return state

    try:
        candidate_dir = _write_candidate_skills(state, new_skills)
    except Exception as exc:  # noqa: BLE001 — candidate persistence should not crash evolution
        message = f"apply: failed to write candidate skills: {exc}"
        _log.error(message)
        state.setdefault("errors", []).append(message)
        _record_diagnostic(state, kind="apply_error", stage="apply.write_candidate", message=message, exc=exc)
        _merge_apply_warnings(state, [message])
        state["candidate_hash"] = state.get("parent_hash")
        state["candidate_skill_dir"] = None
        state["diff"] = []
        _mark_stage(state, "applying", status=state.get("status"), progress={"diff_count": 0})
        return state
    state["candidate_hash"] = f"candidate_{state.get('run_id', 'run')}"
    state["candidate_skill_dir"] = str(candidate_dir) if candidate_dir else None
    state["diff"] = [d.to_dict() for d in diffs]
    _mark_stage(state, "applying", status=state.get("status"), progress={"diff_count": len(state.get("diff", []))})
    return state


async def scenario_replay_node(state: EvolveState) -> dict:
    """Freeze scenario snapshots and attach a deterministic replay contract report.

    Phase B starts with a contract-only replay boundary. It freezes the inputs a
    real replay executor must consume later, without claiming baseline/candidate
    LLM decisions have already been rerun.
    """
    _log.info("scenario_replay: role=%s", state.get("role"))
    _mark_stage(state, "scenario_replay", status=EvolutionStatus.SCENARIO_REPLAY.value)
    cfg = state.get("config", {})
    limit = int(cfg.get("scenario_replay_max_snapshots", cfg.get("scenario_max_snapshots", 3)) or 0)
    snapshots = _build_scenario_snapshots(state, limit=max(0, limit))
    report = _build_scenario_replay_report(state, snapshots)
    state["scenario_snapshots"] = snapshots
    state["scenario_replay_report"] = report
    state["scenario_replay_summary"] = report.get("summary")
    _mark_stage(
        state,
        "scenario_replay",
        status=state.get("status"),
        progress={
            "scenario_count": len(snapshots),
            "execution_mode": report.get("execution_mode"),
            "verdict": report.get("summary", {}).get("verdict"),
        },
    )
    return state


def _build_scenario_snapshots(state: EvolveState, *, limit: int = 3) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    from app.util.time import beijing_now_iso

    role = str(state.get("role") or "")
    run_id = normalize_run_id(state.get("run_id"), default="evolve")
    proposals = [dict(item) for item in state.get("proposals", []) or [] if isinstance(item, dict)]
    proposal_ids = [str(item.get("proposal_id")) for item in proposals if item.get("proposal_id")]
    snapshots: list[dict[str, Any]] = []
    for game in state.get("training_games", []) or []:
        if not isinstance(game, dict) or game.get("error"):
            continue
        evidence = game.get("evidence") if isinstance(game.get("evidence"), dict) else {}
        decisions = evidence.get("role_key_decisions") or evidence.get("key_decisions") or []
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            if role and decision.get("role") and str(decision.get("role")) != role:
                continue
            snapshot = _scenario_snapshot_from_decision(
                state,
                game,
                decision,
                proposal_ids=proposal_ids,
                index=len(snapshots) + 1,
                created_at=beijing_now_iso(),
            )
            snapshots.append(snapshot)
            if len(snapshots) >= limit:
                return snapshots
    return snapshots


def _scenario_snapshot_from_decision(
    state: EvolveState,
    game: dict[str, Any],
    decision: dict[str, Any],
    *,
    proposal_ids: list[str],
    index: int,
    created_at: str,
) -> dict[str, Any]:
    run_id = normalize_run_id(state.get("run_id"), default="evolve")
    role = str(state.get("role") or decision.get("role") or "")
    game_id = str(game.get("game_id") or game.get("source_game_id") or f"game_{index}")
    decision_id = str(decision.get("decision_id") or f"decision_{index}")
    phase = str(decision.get("phase") or game.get("phase") or "")
    day = decision.get("day", game.get("day", game.get("days")))
    action_type = str(decision.get("action_type") or "")
    actor_id = decision.get("player_id")
    event_prefix = _scenario_event_prefix(game, day=day, limit=12)
    return {
        "schema_version": "scenario_snapshot_v1",
        "scenario_id": f"{run_id}_{role}_{game_id}_{decision_id}",
        "source_game_id": game_id,
        "source_run_id": run_id,
        "source_decision_id": decision_id,
        "proposal_ids": list(proposal_ids),
        "role": role,
        "actor_id": actor_id,
        "phase": phase,
        "day": day,
        "action_type": action_type,
        "public_event_prefix": event_prefix,
        "actor_observation": {
            "key_reason": decision.get("key_reason"),
            "impact_level": decision.get("impact_level"),
            "reason": decision.get("reason"),
            "public_text": decision.get("public_text"),
            "notes": list(decision.get("notes") or [])[:3],
        },
        "legal_actions": _scenario_legal_actions(action_type),
        "players_public_state": _scenario_players_public_state(game),
        "role_state_visible_to_actor": {
            "target": decision.get("target"),
            "choice": decision.get("choice"),
        },
        "skill_inventory": _scenario_skill_inventory(state),
        "selected_skill_context": _scenario_selected_skill_context(state),
        "prompt_policy_version": str(state.get("config", {}).get("prompt_policy_version") or "agent_prompt_v1"),
        "judge_policy_version": str(state.get("config", {}).get("judge_policy_version") or "judge_policy_v1"),
        "rubric_version": str(state.get("config", {}).get("rubric_version") or f"{role or 'role'}_rubric_v1"),
        "baseline_version": state.get("parent_hash"),
        "candidate_version": state.get("candidate_hash"),
        "baseline_skill_dir": state.get("baseline_skill_dir") or state.get("skill_dir"),
        "candidate_skill_dir": state.get("candidate_skill_dir"),
        "random_seed": game.get("seed"),
        "created_at": created_at,
    }


def _scenario_event_prefix(game: dict[str, Any], *, day: Any, limit: int = 12) -> list[dict[str, Any]]:
    events = game.get("events") or game.get("game_events") or []
    rows: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if day is not None and event.get("day") is not None:
            try:
                if int(event.get("day")) > int(day):
                    continue
            except (TypeError, ValueError):
                pass
        rows.append(
            {
                "event_type": event.get("event_type") or event.get("type"),
                "day": event.get("day"),
                "phase": event.get("phase"),
                "actor": event.get("actor") or event.get("player_id"),
                "target": event.get("target"),
                "payload": event.get("payload") if isinstance(event.get("payload"), dict) else {},
            }
        )
        if len(rows) >= limit:
            break
    return rows


def _scenario_legal_actions(action_type: str) -> list[str]:
    if not action_type:
        return []
    aliases = {
        "seer_check": ["seer_check"],
        "werewolf_kill": ["werewolf_kill"],
        "guard_protect": ["guard_protect"],
        "witch_act": ["witch_save", "witch_poison", "pass"],
        "vote": ["vote", "abstain"],
        "exile_vote": ["vote", "abstain"],
        "speak": ["speak"],
        "hunter_shoot": ["hunter_shoot", "pass"],
        "white_wolf_explode": ["white_wolf_explode", "pass"],
    }
    return aliases.get(action_type, [action_type])


def _scenario_players_public_state(game: dict[str, Any]) -> list[dict[str, Any]]:
    public_roles = _scenario_public_roles(game)
    player_ids = _scenario_public_player_ids(game, public_roles)
    alive = set(str(item) for item in game.get("alive_players", []) or [])
    dead = set(str(item) for item in game.get("dead_players", []) or [])
    players: list[dict[str, Any]] = []
    for player_id in sorted(player_ids, key=lambda value: str(value)):
        text_id = str(player_id)
        row: dict[str, Any] = {
            "player_id": player_id,
            "alive": False if text_id in dead else True if text_id in alive else None,
        }
        public_role = public_roles.get(text_id)
        if public_role:
            row["public_role"] = public_role
        players.append(row)
    return players


def _scenario_public_player_ids(game: dict[str, Any], public_roles: dict[str, Any]) -> set[Any]:
    ids: set[Any] = set()
    for key in ("players_public_state", "public_players", "players"):
        value = game.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                player_id = item.get("player_id") or item.get("id") or item.get("seat")
                if player_id not in (None, ""):
                    ids.add(player_id)
            elif item not in (None, ""):
                ids.add(item)
    ids.update(public_roles.keys())
    ids.update(str(item) for item in game.get("alive_players", []) or [] if item not in (None, ""))
    ids.update(str(item) for item in game.get("dead_players", []) or [] if item not in (None, ""))
    if not ids:
        private_roles = game.get("player_roles") or game.get("roles") or {}
        if isinstance(private_roles, dict):
            ids.update(str(player_id) for player_id in private_roles)
    return ids


def _scenario_public_roles(game: dict[str, Any]) -> dict[str, Any]:
    roles: dict[str, Any] = {}

    def remember(player_id: Any, role: Any) -> None:
        if player_id in (None, "") or role in (None, ""):
            return
        roles[str(player_id)] = role

    for key in ("public_roles", "revealed_roles", "known_public_roles"):
        value = game.get(key)
        if isinstance(value, dict):
            for player_id, role in value.items():
                remember(player_id, role)

    for key in ("players_public_state", "public_players", "players"):
        value = game.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            player_id = item.get("player_id") or item.get("id") or item.get("seat")
            remember(player_id, item.get("public_role") or item.get("revealed_role"))

    for event in game.get("events") or game.get("game_events") or []:
        if not isinstance(event, dict):
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        event_type = str(event.get("event_type") or event.get("type") or "").lower()
        if "reveal" not in event_type and "death" not in event_type and "exile" not in event_type:
            continue
        player_id = event.get("player_id") or event.get("target") or payload.get("player_id") or payload.get("target_id")
        remember(player_id, payload.get("public_role") or payload.get("revealed_role") or payload.get("role"))
    return roles


def _scenario_skill_inventory(state: EvolveState) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for proposal in state.get("proposals", []) or []:
        if not isinstance(proposal, dict):
            continue
        result.append(
            {
                "proposal_id": proposal.get("proposal_id"),
                "target_file": proposal.get("target_file"),
                "action_type": proposal.get("action_type"),
                "hypothesis": proposal.get("hypothesis"),
            }
        )
    return result[:8]


def _scenario_selected_skill_context(state: EvolveState) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in state.get("diff", []) or []:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                "filename": item.get("filename"),
                "action": item.get("action"),
                "proposal_ref": item.get("proposal_ref"),
            }
        )
    return result[:8]


def _build_scenario_replay_report(state: EvolveState, snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [_contract_only_scenario_result(snapshot) for snapshot in snapshots]
    verdict_counts: dict[str, int] = {}
    for row in rows:
        verdict = str(row.get("verdict") or "unknown")
        verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
    missing_count = sum(1 for row in rows if row.get("contract_missing"))
    policy_violation_count = sum(len(row.get("policy_violations") or []) for row in rows)
    if not rows:
        verdict = "not_run"
    elif missing_count or policy_violation_count:
        verdict = "review_required"
    else:
        verdict = "contract_ready"
    return {
        "schema_version": "scenario_replay_report_v1",
        "execution_mode": "contract_only",
        "status": "contract_ready" if rows else "skipped",
        "reason": "" if rows else "no_scenario_snapshots",
        "baseline_version": state.get("parent_hash"),
        "candidate_version": state.get("candidate_hash"),
        "scenario_count": len(rows),
        "results": rows,
        "summary": {
            "verdict": verdict,
            "scenario_count": len(rows),
            "verdict_counts": verdict_counts,
            "policy_violation_count": policy_violation_count,
            "contract_missing_count": missing_count,
        },
    }


def _contract_only_scenario_result(snapshot: dict[str, Any]) -> dict[str, Any]:
    required = (
        "scenario_id",
        "source_game_id",
        "role",
        "actor_id",
        "phase",
        "legal_actions",
        "prompt_policy_version",
        "judge_policy_version",
        "rubric_version",
        "baseline_version",
        "candidate_version",
    )
    missing = [
        key for key in required
        if snapshot.get(key) in (None, "", [], {})
    ]
    return {
        "scenario_id": snapshot.get("scenario_id"),
        "source_game_id": snapshot.get("source_game_id"),
        "role": snapshot.get("role"),
        "phase": snapshot.get("phase"),
        "baseline_decision": None,
        "candidate_decision": None,
        "rubric_score_delta": None,
        "policy_violations": ["missing_contract_fields"] if missing else [],
        "private_info_leaks": [],
        "decision_issue_delta": None,
        "verdict": "contract_incomplete" if missing else "contract_ready",
        "contract_missing": missing,
    }


def _merge_apply_warnings(state: EvolveState, messages: list[str]) -> None:
    warnings = state.setdefault("warnings", [])
    for message in messages:
        text = str(message)
        if text and text not in warnings:
            warnings.append(text)


def _read_skill_contents(skill_dir: Any) -> dict[str, str]:
    """Read all skill files under a directory into {relative_path: content}."""
    from pathlib import Path

    if not skill_dir:
        return {}
    root = Path(skill_dir)
    if not root.exists():
        return {}
    contents: dict[str, str] = {}
    for path in sorted(root.rglob("*.md")):
        if path.is_file():
            contents[path.relative_to(root).as_posix()] = path.read_text(encoding="utf-8")
    return contents


def _write_candidate_skills(state: EvolveState, skills: dict[str, str]):
    """Write candidate skill contents to a per-run directory; return its path."""
    from pathlib import Path

    from app.config import DEFAULT_PATHS

    paths = state.get("paths")
    base = Path(getattr(paths, "evolution_dir", DEFAULT_PATHS.evolution_dir))
    run_id = normalize_run_id(state.get("run_id"), default="evolve")
    candidate_dir = base / run_id / "candidate_skills"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    for rel_path, content in skills.items():
        out = candidate_dir / rel_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
    return candidate_dir


async def battle_node(state: EvolveState) -> dict:
    """Run a fixed-seed A/B battle: baseline skills vs candidate skills.

    Both sides play the same seed range. Only the **evolving role** differs:
    the candidate side overrides that one role with the candidate skill dir
    (via role_skill_dirs) while every other role keeps the baseline skills.
    This isolates the candidate's effect to the role under evolution. We then
    compare the target role's team win rate (werewolves for wolf roles,
    villagers otherwise). When apply produced no candidate (candidate_hash ==
    parent_hash), the battle is skipped — there is nothing to validate.
    """
    from app.lib.evolve import EvolutionConfig

    cfg = state.get("config", {})
    defaults = EvolutionConfig()
    battle_games = int(cfg.get("battle_games", defaults.battle_games) or 0)
    max_days = int(cfg.get("max_days", 20) or 20)
    seed_start = int(cfg.get("battle_seed_start", 10000) or 10000)
    role = state.get("role", "villager")
    _log.info("battle: role=%s games=%d", role, battle_games)
    _mark_stage(
        state,
        "battling",
        status=EvolutionStatus.BATTLING.value,
        progress={"target_games": battle_games * 2, "completed_games": len(state.get("battle_games", []))},
    )

    baseline_dir = _baseline_skill_dir(state, cfg)
    candidate_dir = state.get("candidate_skill_dir")

    # No real candidate to test — skip the battle.
    if not candidate_dir or state.get("candidate_hash") == state.get("parent_hash"):
        state["battle_games"] = []
        state["battle_result"] = {
            "skipped": True,
            "reason": "no_candidate_changes",
            "candidate_hash": state.get("candidate_hash"),
            "baseline_hash": state.get("parent_hash"),
        }
        _mark_stage(state, "battling", status=state.get("status"), progress={"target_games": 0, "completed_games": 0, "skipped": True})
        return state

    target_team = _target_team(role)

    try:
        baseline_games = await _run_games(
            state, count=battle_games, seed_start=seed_start, max_days=max_days,
            label="battle_baseline", skill_dir=baseline_dir,
        )
        # Candidate side: baseline skills for everyone, candidate skills only for
        # the evolving role — isolates the change to that role.
        candidate_games = await _run_games(
            state, count=battle_games, seed_start=seed_start, max_days=max_days,
            label="battle_candidate", skill_dir=baseline_dir,
            role_skill_dirs={role: candidate_dir},
        )
    except BatchAbortedError as exc:
        _log.error("battle: aborted for role=%s: %s", role, exc)
        state["battle_games"] = []
        state["battle_result"] = {
            "skipped": True, "reason": "battle_aborted", "error": str(exc),
            "candidate_hash": state.get("candidate_hash"),
            "baseline_hash": state.get("parent_hash"),
        }
        message = f"battle: {exc}"
        state.setdefault("errors", []).append(message)
        _record_diagnostic(state, kind="battle_error", stage="battle.run_games", message=message, exc=exc)
        state["status"] = EvolutionStatus.FAILED.value
        _mark_stage(state, "battling", status=state.get("status"), progress={"target_games": battle_games * 2, "completed_games": 0})
        return state
    except Exception as exc:  # noqa: BLE001 — keep graph state recoverable
        _log.error("battle: failed for role=%s: %s", role, exc)
        state["battle_games"] = []
        state["battle_result"] = {
            "skipped": True,
            "reason": "battle_failed",
            "error": str(exc),
            "candidate_hash": state.get("candidate_hash"),
            "baseline_hash": state.get("parent_hash"),
        }
        message = f"battle: {exc}"
        state.setdefault("errors", []).append(message)
        _record_diagnostic(state, kind="battle_error", stage="battle.run_games", message=message, exc=exc)
        state["status"] = EvolutionStatus.FAILED.value
        _mark_stage(state, "battling", status=state.get("status"), progress={"target_games": battle_games * 2, "completed_games": 0})
        return state

    baseline_agg = _battle_side_summary(baseline_games, target_team)
    candidate_agg = _battle_side_summary(candidate_games, target_team)

    # Tag each game with its side so the UI can split baseline vs candidate.
    for game in baseline_games:
        game["side"] = "baseline"
    for game in candidate_games:
        game["side"] = "candidate"

    significance = _battle_significance(
        baseline_agg,
        candidate_agg,
        win_rate_margin=float(cfg.get("promote_win_rate_margin", 0.10) or 0.10),
        error_rate_ceiling=float(cfg.get("battle_error_rate_ceiling", 0.30) or 0.30),
        min_completed_games=int(cfg.get("battle_min_completed_games", 4) or 0),
        confidence_z=float(cfg.get("battle_confidence_z", 1.96) or 0.0),
    )

    # battle_games carries both sides; the UI filters by the `side` field.
    state["battle_games"] = [*baseline_games, *candidate_games]
    battle_result = {
        "target_team": target_team,
        "candidate_hash": state.get("candidate_hash"),
        "baseline_hash": state.get("parent_hash"),
        "seeds": list(range(seed_start, seed_start + battle_games)),
        "baseline": baseline_agg,
        "candidate": candidate_agg,
        "baseline_games": baseline_games,
        "candidate_games": candidate_games,
        "candidate_win_rate": candidate_agg["target_win_rate"],
        "baseline_win_rate": baseline_agg["target_win_rate"],
        "win_rate_delta": candidate_agg["target_win_rate"] - baseline_agg["target_win_rate"],
        "significant": bool(significance["significant"]),
        "significance": significance,
    }
    battle_result["promotion_gate"] = _promotion_gate(
        battle_result,
        proposals=state.get("proposals", []),
        baseline_games=baseline_games,
        candidate_games=candidate_games,
        cfg=cfg,
    )
    _attach_trust_loop_artifacts(state, battle_result, cfg=cfg, force=True)
    state["battle_result"] = battle_result
    _mark_stage(
        state,
        "battling",
        status=state.get("status"),
        progress={"target_games": battle_games * 2, "completed_games": len(state.get("battle_games", []))},
    )
    return state


def _attach_trust_loop_artifacts(
    state: EvolveState,
    battle_result: dict[str, Any],
    *,
    cfg: dict[str, Any] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Attach paired-seed and gate-report artifacts without changing promotion_gate."""
    if not isinstance(battle_result, dict):
        return {}
    if not force and not _has_trust_loop_battle_inputs(state, battle_result):
        return battle_result

    role = str(state.get("role") or "")
    target_team = str(battle_result.get("target_team") or _target_team(role))
    run_shape = {
        "run_id": state.get("run_id"),
        "role": role,
        "parent_hash": state.get("parent_hash"),
        "candidate_hash": state.get("candidate_hash"),
        "training_games": list(state.get("training_games", []) or []),
        "battle_games": list(state.get("battle_games", []) or []),
        "battle_result": battle_result,
        "proposals": [dict(item) for item in state.get("proposals", []) or [] if isinstance(item, dict)],
        "diff": [dict(item) for item in state.get("diff", []) or [] if isinstance(item, dict)],
        "generated_proposal_ids": list(state.get("generated_proposal_ids") or []),
        "preflight_passed_proposal_ids": list(state.get("preflight_passed_proposal_ids") or []),
        "accepted_proposal_ids": list(state.get("accepted_proposal_ids") or []),
        "rejected_proposal_ids": list(state.get("rejected_proposal_ids") or []),
        "config": dict(cfg or state.get("config", {}) or {}),
        "scenario_snapshots": [dict(item) for item in state.get("scenario_snapshots", []) or [] if isinstance(item, dict)],
        "scenario_replay_report": state.get("scenario_replay_report") if isinstance(state.get("scenario_replay_report"), dict) else None,
        "proposal_attribution_report": (
            state.get("proposal_attribution_report")
            if isinstance(state.get("proposal_attribution_report"), dict)
            else None
        ),
    }
    rejected = state.get("rejected_buffer")
    rejected_rows = [dict(item) for item in rejected or [] if isinstance(item, dict)] if isinstance(rejected, list) else []

    paired_rows = build_paired_seed_battle_table(
        run_shape,
        battle_result=battle_result,
        role=role,
        target_team=target_team,
    )
    gate_report = build_evolution_gate_report(
        run_shape,
        battle_result=battle_result,
        proposals=run_shape["proposals"],
        rejected=rejected_rows,
        role=role,
        target_team=target_team,
        thresholds=_trust_loop_gate_thresholds(cfg or state.get("config", {})),
    )
    paired_summary = gate_report.get("paired_summary") if isinstance(gate_report.get("paired_summary"), dict) else {}

    battle_result["paired_seed_battle_table"] = paired_rows
    battle_result["paired_seed_pairs"] = paired_rows
    battle_result["paired_seed_summary"] = paired_summary
    battle_result["gate_report"] = gate_report
    release_gate = gate_report.get("release_gate") if isinstance(gate_report.get("release_gate"), dict) else {}
    proposal_attribution_report = (
        gate_report.get("proposal_attribution") if isinstance(gate_report.get("proposal_attribution"), dict) else {}
    )
    trust_bundle = build_trust_bundle(
        run_shape,
        battle_result=battle_result,
        gate_report=gate_report,
        proposals=run_shape["proposals"],
        diff=run_shape["diff"],
    )
    battle_result["release_gate"] = release_gate
    battle_result["release_decision"] = release_gate.get("decision")
    battle_result["trust_bundle"] = trust_bundle
    battle_result["proposal_attribution_report"] = proposal_attribution_report
    if state.get("scenario_replay_report") is not None:
        battle_result["scenario_replay_report"] = state.get("scenario_replay_report")
    if state.get("scenario_replay_summary") is not None:
        battle_result["scenario_replay_summary"] = state.get("scenario_replay_summary")
    state["paired_seed_battle_table"] = paired_rows
    state["paired_seed_pairs"] = paired_rows
    state["paired_seed_summary"] = paired_summary
    state["gate_report"] = gate_report
    state["release_gate"] = release_gate
    state["release_decision"] = release_gate.get("decision")
    state["trust_bundle"] = trust_bundle
    state["proposal_attribution_report"] = proposal_attribution_report
    if isinstance(battle_result.get("promotion_gate"), dict):
        state["promotion_gate"] = battle_result["promotion_gate"]
    return battle_result


def _has_trust_loop_battle_inputs(state: EvolveState, battle_result: dict[str, Any]) -> bool:
    if state.get("battle_games"):
        return True
    return any(
        key in battle_result
        for key in (
            "baseline_games",
            "candidate_games",
            "battle_games",
            "seeds",
            "target_team",
            "significance",
            "promotion_gate",
            "paired_seed_battle_table",
            "paired_seed_pairs",
            "gate_report",
        )
    )


def _trust_loop_gate_thresholds(cfg: dict[str, Any]) -> dict[str, Any]:
    from app.lib.evolve import EvolutionConfig

    defaults = EvolutionConfig()
    return {
        "min_paired_valid_seeds": int(
            cfg.get(
                "trust_min_paired_valid_seeds",
                cfg.get("promotion_min_completed_games", defaults.promotion_min_completed_games),
            )
            or 0
        ),
        "min_role_score_delta": float(cfg.get("promotion_min_role_score_delta", cfg.get("trust_min_role_score_delta", 0.0)) or 0.0),
        "max_decision_issue_rate": float(
            cfg.get("promotion_max_decision_issue_rate", defaults.promotion_max_decision_issue_rate)
            or 0.0
        ),
        "max_decision_issue_delta": float(
            cfg.get("promotion_max_decision_issue_delta", cfg.get("trust_max_decision_issue_delta", 0.05))
            or 0.0
        ),
        "min_candidate_edge_rate": float(
            cfg.get("promotion_min_candidate_edge_rate", cfg.get("trust_min_candidate_edge_rate", 0.50))
            or 0.0
        ),
        "duplicate_similarity_threshold": float(
            cfg.get("duplicate_similarity_threshold", cfg.get("trust_duplicate_similarity_threshold", 0.72))
            or 0.0
        ),
    }


def _target_team(role: str) -> str:
    """Team the evolving role belongs to, as a Winner value (werewolves|villagers)."""
    from engine import Role, Team

    try:
        team = Role(role).team
    except (ValueError, KeyError):
        return "villagers"
    return "werewolves" if team is Team.WEREWOLVES else "villagers"


def _battle_side_summary(games: list[dict[str, Any]], target_team: str) -> dict[str, Any]:
    """Aggregate one side of a battle: completion + target-team win rate."""
    from app.graphs.shared.nodes.game_batch import winner_counts
    from app.util.winner import normalize_winner

    completed = valid_completed_games(games)
    target_wins = sum(1 for g in completed if normalize_winner(g.get("winner")) == target_team)
    total = len(games)
    errored = sum(1 for game in games if game.get("error"))
    invalid = total - errored - len(completed)
    return {
        "games": total,
        "completed": len(completed),
        "errors": errored + invalid,
        "errored": errored,
        "invalid": invalid,
        "error_rate": (total - len(completed)) / total if total else 0.0,
        "winner_counts": winner_counts(games),
        "target_team": target_team,
        "target_wins": target_wins,
        "target_win_rate": target_wins / len(completed) if completed else 0.0,
    }


def _battle_significance(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    win_rate_margin: float = 0.10,
    error_rate_ceiling: float = 0.30,
    min_completed_games: int = 4,
    confidence_z: float = 1.96,
) -> dict[str, Any]:
    reasons: list[str] = []
    baseline_completed = int(baseline.get("completed", 0) or 0)
    candidate_completed = int(candidate.get("completed", 0) or 0)
    baseline_rate = float(baseline.get("target_win_rate", 0.0) or 0.0)
    candidate_rate = float(candidate.get("target_win_rate", 0.0) or 0.0)
    delta = candidate_rate - baseline_rate

    for label, side in (("baseline", baseline), ("candidate", candidate)):
        if side.get("games", 0) > 0 and float(side.get("error_rate", 0.0) or 0.0) > error_rate_ceiling:
            reasons.append(f"{label}_error_rate_above_ceiling")
    if baseline_completed < min_completed_games:
        reasons.append("baseline_completed_below_minimum")
    if candidate_completed < min_completed_games:
        reasons.append("candidate_completed_below_minimum")
    if delta < win_rate_margin:
        reasons.append("win_rate_delta_below_margin")

    baseline_wins = int(baseline.get("target_wins", round(baseline_rate * baseline_completed)) or 0)
    candidate_wins = int(candidate.get("target_wins", round(candidate_rate * candidate_completed)) or 0)
    baseline_wilson_lower = _wilson_lower_bound(baseline_wins, baseline_completed, confidence_z)
    candidate_wilson_lower = _wilson_lower_bound(candidate_wins, candidate_completed, confidence_z)
    conservative_threshold = baseline_rate + win_rate_margin
    if candidate_completed > 0 and candidate_wilson_lower < conservative_threshold:
        reasons.append("candidate_wilson_lower_below_margin")

    return {
        "significant": not reasons,
        "reasons": reasons,
        "win_rate_margin": win_rate_margin,
        "error_rate_ceiling": error_rate_ceiling,
        "min_completed_games": min_completed_games,
        "confidence_z": confidence_z,
        "baseline_completed": baseline_completed,
        "candidate_completed": candidate_completed,
        "baseline_wilson_lower": round(baseline_wilson_lower, 4),
        "candidate_wilson_lower": round(candidate_wilson_lower, 4),
        "conservative_threshold": round(conservative_threshold, 4),
        "win_rate_delta": round(delta, 4),
    }


def _wilson_lower_bound(wins: int, total: int, z: float) -> float:
    if total <= 0:
        return 0.0
    if z <= 0:
        return max(0.0, min(1.0, wins / total))
    p_hat = wins / total
    denominator = 1.0 + (z * z / total)
    centre = p_hat + (z * z / (2 * total))
    margin = z * ((p_hat * (1.0 - p_hat) + (z * z / (4 * total))) / total) ** 0.5
    return max(0.0, min(1.0, (centre - margin) / denominator))


def _promotion_gate(
    battle: dict[str, Any],
    *,
    proposals: list[dict[str, Any]],
    baseline_games: list[dict[str, Any]],
    candidate_games: list[dict[str, Any]],
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Stricter gate for automatic promotion.

    Battle significance can justify a human review. Auto-promotion additionally
    requires enough completed paired games, healthy run quality, and low-risk
    proposal evidence.
    """
    from app.lib.evolve import EvolutionConfig
    from app.lib.score import compute_decision_quality_metrics

    defaults = EvolutionConfig()
    min_completed = int(cfg.get("promotion_min_completed_games", defaults.promotion_min_completed_games) or 0)
    min_valid_rate = float(cfg.get("promotion_min_valid_game_rate", defaults.promotion_min_valid_game_rate) or 0.0)
    max_issue_rate = float(cfg.get("promotion_max_decision_issue_rate", defaults.promotion_max_decision_issue_rate) or 0.0)
    min_proposal_quality = float(cfg.get("promotion_min_proposal_quality", defaults.promotion_min_proposal_quality) or 0.0)

    reasons: list[str] = []
    significance = battle.get("significance") if isinstance(battle.get("significance"), dict) else {}
    if not bool(battle.get("significant")):
        reasons.append("battle_not_significant")

    side_samples: dict[str, dict[str, Any]] = {}
    for label in ("baseline", "candidate"):
        side = battle.get(label) if isinstance(battle.get(label), dict) else {}
        games = int(side.get("games", 0) or 0)
        completed = int(side.get("completed", 0) or 0)
        valid_rate = completed / games if games else 0.0
        side_samples[label] = {
            "games": games,
            "completed": completed,
            "valid_game_rate": round(valid_rate, 4),
        }
        if completed < min_completed:
            reasons.append(f"{label}_completed_below_promotion_minimum")
        if valid_rate < min_valid_rate:
            reasons.append(f"{label}_valid_game_rate_below_minimum")

    baseline_quality = compute_decision_quality_metrics(baseline_games)
    candidate_quality = compute_decision_quality_metrics(candidate_games)
    baseline_issue_rate = _decision_issue_rate(baseline_quality)
    candidate_issue_rate = _decision_issue_rate(candidate_quality)
    if baseline_issue_rate > max_issue_rate:
        reasons.append("baseline_decision_issue_rate_above_ceiling")
    if candidate_issue_rate > max_issue_rate:
        reasons.append("candidate_decision_issue_rate_above_ceiling")

    proposal_summary = _proposal_gate_summary(proposals, min_quality=min_proposal_quality)
    reasons.extend(proposal_summary["reasons"])

    reasons = _unique_str(reasons)
    battle_passed = bool(battle.get("significant"))
    promote_allowed = battle_passed and not reasons
    recommendation = "promote" if promote_allowed else "review" if battle_passed else "reject"
    return {
        "schema_version": "1.0",
        "promote_allowed": promote_allowed,
        "recommendation": recommendation,
        "reasons": reasons,
        "thresholds": {
            "min_completed_games_per_side": min_completed,
            "min_valid_game_rate": min_valid_rate,
            "max_decision_issue_rate": max_issue_rate,
            "min_proposal_quality": min_proposal_quality,
        },
        "samples": side_samples,
        "significance": {
            "passed": battle_passed,
            "reasons": list(significance.get("reasons", []) or []),
            "win_rate_delta": significance.get("win_rate_delta", battle.get("win_rate_delta")),
        },
        "decision_quality": {
            "baseline": {**baseline_quality, "issue_rate": round(baseline_issue_rate, 6)},
            "candidate": {**candidate_quality, "issue_rate": round(candidate_issue_rate, 6)},
        },
        "proposal_quality": proposal_summary["summary"],
    }


def _decision_issue_rate(metrics: dict[str, Any]) -> float:
    rates = [
        metrics.get("fallback_rate"),
        metrics.get("llm_error_rate"),
        metrics.get("policy_skipped_rate"),
        metrics.get("invalid_response_rate"),
        metrics.get("default_action_rate"),
    ]
    parsed: list[float] = []
    for value in rates:
        try:
            parsed.append(float(value or 0.0))
        except (TypeError, ValueError):
            parsed.append(0.0)
    return max(parsed or [0.0])


def _proposal_gate_summary(proposals: list[dict[str, Any]], *, min_quality: float) -> dict[str, Any]:
    reasons: list[str] = []
    rows = [dict(item) for item in proposals or [] if isinstance(item, dict)]
    if not rows:
        return {"reasons": ["no_proposals"], "summary": {"count": 0, "min_score": None, "high_risk": 0}}

    scores: list[float] = []
    high_risk = 0
    for proposal in rows:
        risk = str(proposal.get("risk") or "").lower()
        quality = proposal.get("quality_score") if isinstance(proposal.get("quality_score"), dict) else {}
        score = quality.get("score")
        if score is None:
            score = proposal.get("confidence")
        try:
            number = float(score)
        except (TypeError, ValueError):
            number = 0.0
        scores.append(number)
        if risk == "high" or quality.get("risk") == "high":
            high_risk += 1

    min_score = min(scores) if scores else 0.0
    if min_score < min_quality:
        reasons.append("proposal_quality_below_minimum")
    if high_risk:
        reasons.append("proposal_high_risk")
    return {
        "reasons": reasons,
        "summary": {
            "count": len(rows),
            "min_score": round(min_score, 3) if scores else None,
            "high_risk": high_risk,
        },
    }


def _unique_str(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _is_significant_improvement(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    win_rate_margin: float = 0.10,
    error_rate_ceiling: float = 0.30,
    min_completed_games: int = 4,
    confidence_z: float = 1.96,
) -> bool:
    """Strict A/B gate for candidate-vs-baseline battles.

    Criteria (thresholds sourced from EvolutionConfig):
    1. Both sides must keep error rate <= error_rate_ceiling (else unreliable).
    2. Candidate target-team win rate must beat baseline by >= win_rate_margin.

    Note: the old role_weighted_score >= +0.05 gate is omitted — the app/
    battle runs the game subgraph only and does not compute review scores,
    so that signal is unavailable here.
    """
    return bool(_battle_significance(
        baseline,
        candidate,
        win_rate_margin=win_rate_margin,
        error_rate_ceiling=error_rate_ceiling,
        min_completed_games=min_completed_games,
        confidence_z=confidence_z,
    )["significant"])


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
        _attach_trust_loop_artifacts(state, battle, cfg=cfg)
        state["battle_result"] = battle

    recommendation = _recommendation(proposals, battle)
    auto_promote = bool(cfg.get("auto_promote"))
    state["recommendation"] = recommendation

    status = EvolutionStatus.REVIEWING.value
    published_version_id: str | None = None
    published_release_stage: str | None = None
    if auto_promote and recommendation == "promote":
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


def _recommendation(proposals: list[dict[str, Any]], battle: dict[str, Any]) -> str:
    """Map proposals + battle outcome to promote|reject|review."""
    if not proposals:
        return "reject"
    if battle.get("skipped"):
        # Proposals exist but nothing changed materially — nothing to promote.
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
    # Ran a battle, candidate did not clear the bar.
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
        _log.error("decide: registry promote failed for role=%s: %s", role, exc)
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
        _log.error("decide: registry reject failed for role=%s: %s", role, exc)
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

    _log.warning(message)
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
        _log.warning(message)
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


def _persist_run_state(state: EvolveState, *, record_warning: bool = True) -> None:
    """Persist the evolution run state to PostgreSQL for dashboards / recovery."""
    from app.util.json import to_jsonable
    from storage.evolution.state_gateway import EvolutionStateGateway
    from storage.interfaces import EvolutionRunData

    result = state.get("result") or {}
    try:
        finished_at = result.get("finished_at") if isinstance(result, dict) else None
        if not finished_at:
            finished_at = state.get("finished_at")
        started_at = state.get("started_at") or state.get("last_heartbeat_at")
        consolidation = _state_consolidation(state)
        diff = _state_diff(state)
        baseline_config = (
            SkillVersionConfig.from_dict(state.get("baseline_config", {}))
            if isinstance(state.get("baseline_config"), dict)
            else state.get("baseline_config")
        )
        runtime_state = to_jsonable(
            {
                "kind": "role_evolution_run",
                "schema_version": 1,
                "run_id": str(state.get("run_id", "")),
                "role": str(state.get("role", "")),
                "parent_hash": str(state.get("parent_hash", "")),
                "status": str(state.get("status", "")),
                "training_games": list(state.get("training_games", []) or []),
                "battle_games": list(state.get("battle_games", []) or []),
                "training_game_count": len(state.get("training_games", []) or []),
                "battle_game_count": len(state.get("battle_games", []) or []),
                "baseline_config": baseline_config.to_dict() if baseline_config is not None and hasattr(baseline_config, "to_dict") else baseline_config,
                "baseline_skill_dir": state.get("baseline_skill_dir"),
                "candidate_hash": state.get("candidate_hash"),
                "candidate_skill_dir": state.get("candidate_skill_dir"),
                "published_version_id": state.get("published_version_id") or result.get("published_version_id"),
                "published_release_stage": state.get("published_release_stage") or result.get("published_release_stage"),
                "release_stage": state.get("release_stage") or result.get("published_release_stage") or result.get("release_stage"),
                "promoted_version_id": state.get("promoted_version_id") or result.get("promoted_version_id"),
                "battle_result": result.get("battle_result") or state.get("battle_result"),
                "promotion_gate": state.get("promotion_gate") or result.get("promotion_gate"),
                "gate_report": state.get("gate_report") or result.get("gate_report"),
                "release_gate": state.get("release_gate") or result.get("release_gate"),
                "release_decision": state.get("release_decision") or result.get("release_decision"),
                "trust_bundle": state.get("trust_bundle") or result.get("trust_bundle"),
                "scenario_snapshots": list(state.get("scenario_snapshots") or result.get("scenario_snapshots") or []),
                "scenario_replay_report": state.get("scenario_replay_report") or result.get("scenario_replay_report"),
                "scenario_replay_summary": state.get("scenario_replay_summary") or result.get("scenario_replay_summary"),
                "proposal_attribution_report": (
                    state.get("proposal_attribution_report")
                    or result.get("proposal_attribution_report")
                    or (state.get("gate_report") or result.get("gate_report") or {}).get("proposal_attribution")
                ),
                "paired_seed_pairs": list(state.get("paired_seed_pairs") or result.get("paired_seed_pairs") or []),
                "paired_seed_battle_table": list(
                    state.get("paired_seed_battle_table")
                    or result.get("paired_seed_battle_table")
                    or []
                ),
                "paired_seed_summary": state.get("paired_seed_summary") or result.get("paired_seed_summary"),
                "proposals": consolidation.to_dict() if consolidation is not None else None,
                "generated_proposal_ids": list(state.get("generated_proposal_ids") or result.get("generated_proposal_ids") or []),
                "preflight_passed_proposal_ids": list(
                    state.get("preflight_passed_proposal_ids")
                    or result.get("preflight_passed_proposal_ids")
                    or []
                ),
                "preflight_rejected_proposal_ids": list(
                    state.get("preflight_rejected_proposal_ids")
                    or result.get("preflight_rejected_proposal_ids")
                    or []
                ),
                "accepted_proposal_ids": list(state.get("accepted_proposal_ids") or result.get("accepted_proposal_ids") or []),
                "rejected_proposal_ids": list(state.get("rejected_proposal_ids") or result.get("rejected_proposal_ids") or []),
                "preflight_reports": list(state.get("preflight_reports") or result.get("preflight_reports") or []),
                "diff": [item.to_dict() for item in diff] if diff is not None else None,
                "current_stage": str(state.get("current_stage", "")),
                "progress": dict(state.get("progress", {}) or {}),
                "last_heartbeat_at": state.get("last_heartbeat_at"),
                "started_at": started_at,
                "finished_at": finished_at,
                "diagnostics": [dict(item) for item in state.get("diagnostics", []) if isinstance(item, dict)],
                "warnings": list(state.get("warnings", [])),
                "errors": list(state.get("errors", [])),
                "config": dict(state.get("config", {}) or {}),
                "result": dict(result) if isinstance(result, dict) else {},
            }
        )
        EvolutionStateGateway(
            provider=state.get("storage_provider") or None,
            paths=state.get("paths"),
        ).save_runtime_state(
            EvolutionRunData(
                run_id=str(state.get("run_id", "")),
                role=str(state.get("role", "")),
                parent_hash=str(state.get("parent_hash", "")),
                status=str(state.get("status", "")),
                training_games=len(state.get("training_games", []) or []),
                battle_games=len(state.get("battle_games", []) or []),
                baseline_config=baseline_config,
                candidate_hash=state.get("candidate_hash"),
                battle_result=result.get("battle_result") or state.get("battle_result"),
                errors=list(state.get("errors", [])),
                runtime_state=runtime_state,
                started_at=started_at,
                finished_at=finished_at,
            ),
            trust_bundle=runtime_state.get("trust_bundle")
            if isinstance(runtime_state, dict)
            else None,
        )
    except Exception as exc:  # noqa: BLE001 — persistence is best-effort
        message = f"decide: failed to persist run state: {exc}"
        _log.warning(message)
        _record_diagnostic(state, kind="persistence_error", stage="persist.run_state", message=message, exc=exc, level="warning")
        if record_warning:
            state.setdefault("warnings", []).append(message)
            if isinstance(state.get("result"), dict):
                state["result"]["warnings"] = state.get("warnings", [])
                state["result"]["diagnostics"] = state.get("diagnostics", [])


def _state_consolidation(state: EvolveState) -> SkillConsolidation | None:
    data = state.get("consolidation")
    if isinstance(data, dict):
        return SkillConsolidation.from_dict(data)
    proposals = [p for p in state.get("proposals", []) if isinstance(p, dict)]
    if proposals:
        return SkillConsolidation(
            role=str(state.get("role", "")),
            run_id=str(state.get("run_id", "")),
            parent_hash=str(state.get("parent_hash", "")),
            proposals=[SkillProposal.from_dict(p) for p in proposals],
            generated_proposal_ids=[str(item) for item in state.get("generated_proposal_ids", [])],
            preflight_passed_proposal_ids=[str(item) for item in state.get("preflight_passed_proposal_ids", [])],
            preflight_rejected_proposal_ids=[str(item) for item in state.get("preflight_rejected_proposal_ids", [])],
            accepted_proposal_ids=[str(item) for item in state.get("accepted_proposal_ids", [])],
            rejected_proposal_ids=[str(item) for item in state.get("rejected_proposal_ids", [])],
            preflight_reports=[dict(item) for item in state.get("preflight_reports", []) if isinstance(item, dict)],
        )
    return None


def _state_diff(state: EvolveState) -> list[SkillDiff] | None:
    rows = [d for d in state.get("diff", []) if isinstance(d, dict)]
    if not rows:
        return [] if "diff" in state else None
    return [SkillDiff.from_dict(row) for row in rows]


def _safe_id(value: str) -> str:
    """Sanitize an arbitrary string into a registry-safe version id."""
    import re

    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", value).strip("_")
    return cleaned or "candidate"


async def _run_games(
    state: EvolveState,
    *,
    count: int,
    seed_start: int,
    max_days: int,
    label: str,
    skill_dir: Any = None,
    role_skill_dirs: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    from app.graphs.shared.nodes.game_batch import (
        per_game_dir,
        resolve_game_subgraph,
        run_game_batch,
    )

    game_subgraph = resolve_game_subgraph(state)
    run_id = normalize_run_id(state.get("run_id"), default="evolve")
    cfg = state.get("config", {})
    effective_skill_dir = skill_dir if skill_dir is not None else _baseline_skill_dir(state, cfg)
    concurrency = int(cfg.get("game_concurrency", 0) or 0) or None

    # Persist training/battle games under the run's directory for replay.
    paths = state.get("paths")
    from app.config import DEFAULT_GAME_CONCURRENCY, DEFAULT_PATHS

    run_base = Path(getattr(paths, "evolution_dir", DEFAULT_PATHS.evolution_dir)) / str(run_id) / label

    def _build(index: int) -> dict[str, Any]:
        game_id = f"{run_id}_{label}_{index + 1:03d}"
        game_state: dict[str, Any] = {
            "game_id": game_id,
            "seed": seed_start + index,
            "max_days": max_days,
            "model": state.get("model"),
            "skill_dir": effective_skill_dir,
            "paths": paths,
            "storage_provider": state.get("storage_provider"),
            "game_dir": per_game_dir(run_base, label, index),
            "storage_run_type": _storage_run_type_for_game(label),
            "mode": cfg.get("mode", "formal"),
            "source_run_id": run_id,
            "source_game_id": game_id,
            "target_role": state.get("role"),
            "target_version_id": state.get("candidate_hash") if "candidate" in label else state.get("parent_hash"),
            "model_id": cfg.get("model_id"),
            "model_config_hash": cfg.get("model_config_hash"),
            "seed_set_id": cfg.get("seed_set_id"),
            "evaluation_set_id": cfg.get("evaluation_set_id"),
        }
        if role_skill_dirs:
            game_state["role_skill_dirs"] = role_skill_dirs
        _copy_runner_config(cfg, game_state)
        return game_state

    return await run_game_batch(
        game_subgraph,
        count,
        _build,
        concurrency=concurrency or DEFAULT_GAME_CONCURRENCY,
        label=label,
    )


def _storage_run_type_for_game(label: str) -> str:
    if label == "battle_baseline":
        return "evolution_ab_baseline"
    if label == "battle_candidate":
        return "evolution_ab_candidate"
    return "evolution_training"


def _copy_runner_config(source: dict[str, Any], target: dict[str, Any]) -> None:
    for key in (
        "runner_max_retries",
        "runner_retry_delay",
        "runner_action_timeout",
        "runner_game_timeout",
        "game_timeout",
    ) + _AGENT_RUNTIME_CONFIG_KEYS:
        if source.get(key) is not None:
            target[key] = source[key]


async def _attach_training_evidence(
    games: list[dict[str, Any]],
    *,
    role: str,
    model: Any = None,
    enable_judge: bool = False,
    judge_max_decisions: int = 4,
    judge_concurrency: int = 3,
    judge_timeout_seconds: float | None = None,
    judge_fn: Any = None,
    warnings: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Attach compact evidence summaries to successful training-game records."""
    enriched: list[dict[str, Any]] = []
    for game in games:
        if not isinstance(game, dict) or game.get("error"):
            enriched.append(game)
            continue
        row = dict(game)
        try:
            row["evidence"] = _build_training_evidence_summary(row, role=role)
            if enable_judge:
                await _attach_training_decision_judge(
                    row,
                    model=model,
                    max_decisions=judge_max_decisions,
                    concurrency=judge_concurrency,
                    timeout_seconds=judge_timeout_seconds,
                    judge_fn=judge_fn,
                    warnings=warnings,
                )
        except Exception as exc:  # noqa: BLE001 — evidence is advisory, not a training blocker
            message = f"training: evidence extraction failed for game={row.get('game_id')}: {exc}"
            _log.warning(message)
            if warnings is not None:
                warnings.append(message)
            row.setdefault("warnings", []).append(message)
            row["evidence"] = {"error": str(exc), "key_decisions": [], "role_key_decisions": []}
        enriched.append(row)
    return enriched


async def _attach_training_decision_judge(
    row: dict[str, Any],
    *,
    model: Any = None,
    max_decisions: int = 4,
    concurrency: int = 3,
    timeout_seconds: float | None = None,
    judge_fn: Any = None,
    warnings: list[str] | None = None,
) -> None:
    """Attach LLM judge output to one training game's compact evidence."""
    from app.lib.decision_judge import attach_judgments_to_evidence_summary, judge_key_decisions

    try:
        report = await judge_key_decisions(
            model,
            game_id=str(row.get("game_id") or ""),
            winner=row.get("winner"),
            roles=row.get("player_roles") or row.get("roles"),
            events=row.get("events") or row.get("game_events"),
            decisions=row.get("decisions"),
            review=row.get("review"),
            max_decisions=max_decisions,
            concurrency=concurrency,
            timeout_seconds=timeout_seconds,
            judge_fn=judge_fn,
        )
        row["evidence"] = attach_judgments_to_evidence_summary(row.get("evidence") or {}, report)
        report_warnings = [
            str(item) for item in report.get("warnings", [])
            if isinstance(report, dict) and str(item)
        ]
        if report_warnings:
            row.setdefault("warnings", []).extend(report_warnings)
            if warnings is not None:
                warnings.extend(report_warnings)
    except Exception as exc:  # noqa: BLE001 — judge is advisory, not a training blocker
        message = f"training: decision judge failed for game={row.get('game_id')}: {exc}"
        _log.warning(message)
        if warnings is not None:
            warnings.append(message)
        row.setdefault("warnings", []).append(message)
        evidence = row.setdefault("evidence", {})
        evidence["decision_judge"] = {"status": "failed", "error": str(exc), "warnings": [message]}


def _training_judge_enabled(cfg: dict[str, Any]) -> bool:
    for key in (
        "enable_llm_judge",
        "enable_decision_judge",
        "evolve_llm_judge",
        "evolve_decision_judge",
        "training_llm_judge",
        "training_decision_judge",
    ):
        if key in cfg:
            return _as_bool(cfg.get(key))
    return False


def _training_judge_max_decisions(cfg: dict[str, Any]) -> int:
    for key in (
        "training_judge_max_decisions",
        "evolve_judge_max_decisions",
        "judge_max_decisions",
        "decision_judge_max_decisions",
    ):
        if key in cfg:
            value = _as_positive_int(cfg.get(key))
            return value if value is not None else 4
    return 4


def _training_judge_concurrency(cfg: dict[str, Any]) -> int:
    for key in ("training_judge_concurrency", "evolve_judge_concurrency", "judge_concurrency"):
        if key in cfg:
            value = _as_positive_int(cfg.get(key))
            return value if value is not None else 3
    return 3


def _training_judge_timeout_seconds(cfg: dict[str, Any]) -> float | None:
    for key in ("training_judge_timeout_seconds", "evolve_judge_timeout_seconds", "judge_timeout_seconds"):
        if key in cfg:
            return _as_positive_float(cfg.get(key))
    return 20.0


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "enabled"}


def _as_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _as_positive_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _build_training_evidence_summary(game: dict[str, Any], *, role: str) -> dict[str, Any]:
    """Normalize + select key decisions for one training game without LLM calls."""
    from app.lib.evidence import GameEvidenceBundle, normalize_decisions, select_key_decisions

    decisions = [d for d in game.get("decisions", []) if isinstance(d, dict)]
    events = [e for e in game.get("events", []) if isinstance(e, dict)]
    player_roles = dict(game.get("player_roles", {}) or {})
    game_id = str(game.get("game_id") or "")
    bundle = GameEvidenceBundle(
        game_dir=Path(game_id or "."),
        game_id=game_id,
        archive={
            "winner": game.get("winner"),
            "player_roles": player_roles,
            "decisions": decisions,
        },
        agent_decisions=decisions,
        game_events=events,
        meta={
            "winner": game.get("winner"),
            "player_roles": player_roles,
        },
    )
    evidence_inputs = normalize_decisions(bundle)
    key_decisions = select_key_decisions(evidence_inputs, bundle)
    input_by_id = {item.decision_id: item for item in evidence_inputs}
    compact = [_compact_key_decision(item, input_by_id.get(item.decision_id)) for item in key_decisions]
    role_compact = [item for item in compact if not role or item.get("role") == role]
    return {
        "key_decisions": compact[:16],
        "role_key_decisions": role_compact[:12],
        "counts": {
            "decisions": len(evidence_inputs),
            "key_decisions": len(key_decisions),
            "role_key_decisions": len(role_compact),
        },
    }


def _compact_key_decision(key: Any, evidence_input: Any | None) -> dict[str, Any]:
    """Keep only prompt-useful evidence fields; avoid raw prompts/LLM outputs."""
    result = getattr(evidence_input, "decision_result", None)
    reasoning = getattr(getattr(evidence_input, "agent_reasoning", None), "private_reasoning", "") or ""
    public_text = getattr(result, "public_text", "") if result is not None else ""
    return {
        "decision_id": key.decision_id,
        "day": key.day,
        "phase": key.phase,
        "action_type": key.action_type,
        "player_id": key.player_id,
        "role": key.role,
        "impact_level": key.impact_level,
        "key_reason": key.key_reason,
        "turning_point_id": key.turning_point_id,
        "target": getattr(result, "selected_target", None) if result is not None else None,
        "choice": getattr(result, "selected_choice", None) if result is not None else None,
        "reason": reasoning[:180],
        "public_text": public_text[:160],
        "notes": list(key.selection_notes)[:2],
    }
