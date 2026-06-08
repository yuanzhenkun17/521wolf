"""Evolve subgraph nodes — self-evolution pipeline for one role.

Nodes: init → training → consolidate → apply → battle → decide
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.graphs.shared.nodes.game_batch import BatchAbortedError
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
    "battling": 0.85,
    "decide": 0.95,
    "done": 1.0,
}


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
        "battle_result": result.get("battle_result") or state.get("battle_result"),
        "proposals": list(state.get("proposals", []) or []),
        "diff": list(state.get("diff", []) or []),
        "recommendation": state.get("recommendation") or result.get("recommendation"),
        "diagnostics": list(state.get("diagnostics", []) or []),
        "warnings": list(state.get("warnings", []) or []),
        "errors": list(state.get("errors", []) or []),
        "last_heartbeat_at": state.get("last_heartbeat_at"),
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
    return bool(state.get("run_id") and state.get("paths") is not None)


async def init_evolve_node(state: EvolveState) -> dict:
    """Initialize evolution run: freeze baseline, create run_id.

    Defaults are sourced from EvolutionConfig so there is a single source of
    truth for game counts, seeds, and the promotion gate thresholds.
    """
    import uuid

    from app.lib.evolve import EvolutionConfig

    defaults = EvolutionConfig()
    role = state.get("role") or state.get("config", {}).get("role") or "villager"
    cfg = dict(state.get("config", {}))
    cfg.setdefault("training_games", state.get("training_game_count", defaults.training_games))
    cfg.setdefault("battle_games", state.get("battle_game_count", defaults.battle_games))
    cfg.setdefault("max_days", defaults.max_days)
    cfg.setdefault("seed_start", defaults.seed_start)
    cfg.setdefault("battle_seed_start", defaults.battle_seed_start)
    cfg.setdefault("max_proposals", defaults.max_proposals)
    cfg.setdefault("game_concurrency", defaults.game_concurrency)
    cfg.setdefault("promote_win_rate_margin", defaults.promote_win_rate_margin)
    cfg.setdefault("battle_error_rate_ceiling", defaults.battle_error_rate_ceiling)
    cfg.setdefault("battle_min_completed_games", defaults.battle_min_completed_games)
    cfg.setdefault("battle_confidence_z", defaults.battle_confidence_z)

    run_id = normalize_run_id(state.get("run_id"), default=f"evolve_{uuid.uuid4().hex[:12]}")

    state["role"] = role
    state["config"] = cfg
    state["run_id"] = run_id
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
    role = state.get("role", "villager")
    cfg = state.get("config", {})
    training_games = int(cfg.get("training_games", 20) or 0)
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
        state["training_games"] = _attach_training_evidence(
            games,
            role=role,
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
    games = [g for g in state.get("training_games", []) if not g.get("error")]

    if max_proposals <= 0 or not games:
        state["proposals"] = []
        state["consolidation"] = None
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
            survivors = {
                d["proposal_id"]
                for d in deduplicate_proposals([p.to_dict() for p in consolidation.proposals], rejected)
            }
            dropped = len(consolidation.proposals) - len(survivors)
            if dropped:
                _log.info("consolidate: dropped %d proposal(s) overlapping rejected buffer", dropped)
            consolidation.proposals = [p for p in consolidation.proposals if p.proposal_id in survivors]
        except Exception as exc:  # noqa: BLE001 — dedup should not block consolidation
            message = f"consolidate: rejected proposal dedup failed for role={role}: {exc}"
            _log.warning(message)
            state.setdefault("warnings", []).append(message)
            _record_diagnostic(state, kind="consolidation_error", stage="consolidate.dedup_rejected", message=message, exc=exc, level="warning")

    annotate_proposal_quality(consolidation.proposals, rejected=rejected)
    state["consolidation"] = consolidation.to_dict()
    state["proposals"] = [p.to_dict() for p in consolidation.proposals]
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
    try:
        return _registry(state).load_rejected(role)
    except Exception as exc:  # noqa: BLE001 — dedup is best-effort
        message = f"consolidate: failed to load rejected buffer for role={role}: {exc}"
        _log.warning(message)
        state.setdefault("warnings", []).append(message)
        return []


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
    cfg = state.get("config", {})
    battle_games = int(cfg.get("battle_games", 10) or 0)
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
    state["battle_result"] = {
        "target_team": target_team,
        "candidate_hash": state.get("candidate_hash"),
        "baseline_hash": state.get("parent_hash"),
        "seeds": list(range(seed_start, seed_start + battle_games)),
        "baseline": baseline_agg,
        "candidate": candidate_agg,
        "baseline_games": baseline_games,
        "candidate_win_rate": candidate_agg["target_win_rate"],
        "baseline_win_rate": baseline_agg["target_win_rate"],
        "win_rate_delta": candidate_agg["target_win_rate"] - baseline_agg["target_win_rate"],
        "significant": bool(significance["significant"]),
        "significance": significance,
    }
    _mark_stage(
        state,
        "battling",
        status=state.get("status"),
        progress={"target_games": battle_games * 2, "completed_games": len(state.get("battle_games", []))},
    )
    return state


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

    completed = [g for g in games if not g.get("error")]
    target_wins = sum(1 for g in completed if str(g.get("winner")) == target_team)
    total = len(games)
    return {
        "games": total,
        "completed": len(completed),
        "errors": total - len(completed),
        "error_rate": (total - len(completed)) / total if total else 0.0,
        "winner_counts": winner_counts(completed),
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
      - promote → publish candidate skills + set as baseline (CAS)
      - reject  → persist rejected proposals for future dedup
    The run state is always persisted to disk.
    """
    _log.info("decide: role=%s", state.get("role"))
    _mark_stage(state, "decide", status=state.get("status"))
    role = state.get("role", "")
    battle = state.get("battle_result") or {}
    proposals = state.get("proposals", [])
    cfg = state.get("config", {})

    recommendation = _recommendation(proposals, battle)
    auto_promote = bool(cfg.get("auto_promote"))

    status = EvolutionStatus.REVIEWING.value
    published_version_id: str | None = None
    if auto_promote and recommendation == "promote":
        published_version_id = _registry_promote(state)
        status = EvolutionStatus.PROMOTED.value if published_version_id else EvolutionStatus.REVIEWING.value
    elif auto_promote and recommendation == "reject":
        _registry_reject(state)
        status = EvolutionStatus.REJECTED.value

    state["status"] = status
    state["result"] = {
        "run_id": state.get("run_id"),
        "role": role,
        "parent_hash": state.get("parent_hash"),
        "baseline_skill_dir": state.get("baseline_skill_dir"),
        "candidate_hash": state.get("candidate_hash"),
        "candidate_skill_dir": state.get("candidate_skill_dir"),
        "published_version_id": published_version_id,
        "status": status,
        "recommendation": recommendation,
        "training_games": state.get("training_games", []),
        "battle_games": state.get("battle_games", []),
        "battle_result": battle,
        "proposals": proposals,
        "diff": state.get("diff", []),
        "current_stage": state.get("current_stage"),
        "progress": state.get("progress", {}),
        "last_heartbeat_at": state.get("last_heartbeat_at"),
        "diagnostics": state.get("diagnostics", []),
        "warnings": state.get("warnings", []),
        "errors": state.get("errors", []),
    }
    _mark_stage(state, "done", status=status, progress={"recommendation": recommendation}, persist=False)
    state["result"]["current_stage"] = state.get("current_stage")
    state["result"]["progress"] = state.get("progress", {})
    state["result"]["last_heartbeat_at"] = state.get("last_heartbeat_at")
    state["result"]["diagnostics"] = state.get("diagnostics", [])
    _persist_run_state(state)
    if isinstance(state.get("result"), dict):
        state["result"]["warnings"] = state.get("warnings", [])
        state["result"]["errors"] = state.get("errors", [])
        state["result"]["diagnostics"] = state.get("diagnostics", [])
    return state


def _recommendation(proposals: list[dict[str, Any]], battle: dict[str, Any]) -> str:
    """Map proposals + battle outcome to promote|reject|review."""
    if not proposals:
        return "reject"
    if battle.get("skipped"):
        # Proposals exist but nothing changed materially — nothing to promote.
        return "reject" if battle.get("reason") == "no_candidate_changes" else "review"
    if battle.get("significant"):
        return "promote"
    # Ran a battle, candidate did not clear the bar.
    return "reject"


def _registry_promote(state: EvolveState) -> str | None:
    """Publish candidate skills to the registry and set them as baseline.

    Returns the published version id, or None on failure (degrade to review).
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
    try:
        registry = _registry(state)
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
            set_as_baseline=True,
            expected_current=registry.get_baseline(role),
        )
        _log.info("decide: promoted %s/%s to baseline", role, published)
        return published
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        _log.error("decide: registry promote failed for role=%s: %s", role, exc)
        message = f"promote: {exc}"
        state.setdefault("errors", []).append(message)
        _record_diagnostic(state, kind="registry_error", stage="registry.promote", message=message, exc=exc)
        return None


def _registry_reject(state: EvolveState) -> None:
    """Persist rejected proposals so future consolidation can dedup against them."""
    role = state.get("role", "")
    proposals = [p for p in state.get("proposals", []) if isinstance(p, dict)]
    if not role or not proposals:
        return
    try:
        registry = _registry(state)
        battle = state.get("battle_result") if isinstance(state.get("battle_result"), dict) else None
        registry.save_rejected(role, proposals, battle)
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        _log.error("decide: registry reject failed for role=%s: %s", role, exc)
        message = f"reject: {exc}"
        state.setdefault("errors", []).append(message)
        _record_diagnostic(state, kind="registry_error", stage="registry.reject", message=message, exc=exc)


def _registry(state: EvolveState):
    """Build a VersionRegistry rooted at the configured registry dir."""
    from app.config import DEFAULT_PATHS
    from app.lib.version import VersionRegistry

    paths = state.get("paths")
    registry_dir = getattr(paths, "registry_dir", DEFAULT_PATHS.registry_dir)
    return VersionRegistry(registry_dir)


def _freeze_baseline(
    state: EvolveState,
    role: str,
    cfg: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Freeze the baseline version config used by this evolution run."""
    explicit_parent = state.get("parent_hash") or cfg.get("parent_hash")
    if explicit_parent:
        version_id = str(explicit_parent)
        return version_id, {
            "name": "explicit",
            "role_versions": {role: version_id},
            "notes": ["explicit parent_hash supplied"],
        }

    fallback = f"baseline_{role}"
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
    try:
        from app.lib.version import SkillVersionConfig, build_composite_skill_dir

        config = SkillVersionConfig.from_dict(baseline_config)
        if not config.role_versions:
            return str(fallback) if fallback is not None else None
        if config.name == "fallback" or (config.name == "explicit" and fallback is not None):
            return str(fallback) if fallback is not None else None
        skill_dir = build_composite_skill_dir(_registry(state), config)
        if skill_dir is not None:
            return str(skill_dir)
    except Exception as exc:  # noqa: BLE001 — registry-backed baseline is best-effort
        message = f"init: failed to materialize baseline skills: {exc}"
        _log.warning(message)
        state.setdefault("warnings", []).append(message)
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
    """Persist the evolution run to disk for dashboards / recovery."""
    from app.lib.evolve import EvolutionRun, EvolutionStateManager

    result = state.get("result") or {}
    try:
        consolidation = _state_consolidation(state)
        diff = _state_diff(state)
        manager = EvolutionStateManager(root_dir=getattr(state.get("paths"), "evolution_dir", None))
        run = EvolutionRun(
            run_id=str(state.get("run_id", "")),
            role=str(state.get("role", "")),
            parent_hash=str(state.get("parent_hash", "")),
            status=str(state.get("status", "")),
            training_games=len(state.get("training_games", [])),
            battle_games=len(state.get("battle_games", [])),
            baseline_config=SkillVersionConfig.from_dict(state.get("baseline_config", {}))
            if isinstance(state.get("baseline_config"), dict)
            else state.get("baseline_config"),
            baseline_skill_dir=state.get("baseline_skill_dir"),
            candidate_hash=state.get("candidate_hash"),
            candidate_skill_dir=state.get("candidate_skill_dir"),
            battle_result=result.get("battle_result") or state.get("battle_result"),
            proposals=consolidation,
            diff=diff,
            current_stage=str(state.get("current_stage", "")),
            progress=dict(state.get("progress", {}) or {}),
            last_heartbeat_at=state.get("last_heartbeat_at"),
            diagnostics=[dict(item) for item in state.get("diagnostics", []) if isinstance(item, dict)],
            warnings=list(state.get("warnings", [])),
            errors=list(state.get("errors", [])),
        )
        manager.save_run(run)
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
    from app.config import DEFAULT_PATHS

    run_base = Path(getattr(paths, "evolution_dir", DEFAULT_PATHS.evolution_dir)) / str(run_id) / label

    def _build(index: int) -> dict[str, Any]:
        game_state: dict[str, Any] = {
            "game_id": f"{run_id}_{label}_{index + 1:03d}",
            "seed": seed_start + index,
            "max_days": max_days,
            "model": state.get("model"),
            "skill_dir": effective_skill_dir,
            "paths": paths,
            "game_dir": per_game_dir(run_base, label, index),
        }
        if role_skill_dirs:
            game_state["role_skill_dirs"] = role_skill_dirs
        return game_state

    return await run_game_batch(
        game_subgraph,
        count,
        _build,
        concurrency=concurrency or 3,
        label=label,
    )


def _attach_training_evidence(
    games: list[dict[str, Any]],
    *,
    role: str,
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
        except Exception as exc:  # noqa: BLE001 — evidence is advisory, not a training blocker
            message = f"training: evidence extraction failed for game={row.get('game_id')}: {exc}"
            _log.warning(message)
            if warnings is not None:
                warnings.append(message)
            row.setdefault("warnings", []).append(message)
            row["evidence"] = {"error": str(exc), "key_decisions": [], "role_key_decisions": []}
        enriched.append(row)
    return enriched


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
