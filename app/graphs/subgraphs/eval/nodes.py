"""Eval subgraph nodes — batch evaluation pipeline.

Nodes: init_batch → run_games → aggregate → fairness → persist_batch
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.graphs.shared.nodes.game_batch import BatchAbortedError, DEFAULT_CONCURRENCY
from app.graphs.shared.state import EvalBatchState

_log = logging.getLogger(__name__)


def _exception_message(prefix: str, exc: BaseException) -> str:
    return f"{prefix}: {type(exc).__name__}: {exc}"


def _record_diagnostic(
    state: EvalBatchState,
    *,
    kind: str,
    stage: str,
    level: str,
    message: str,
    exc: BaseException | None = None,
) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {
        "kind": kind,
        "stage": stage,
        "level": level,
        "message": message,
    }
    if exc is not None:
        diagnostic["exception_type"] = type(exc).__name__
        diagnostic["exception_message"] = str(exc)
    state.setdefault("diagnostics", []).append(diagnostic)
    return diagnostic


def _diagnostic_from_warning(
    warning: str,
    *,
    kind: str,
    stage: str,
    level: str = "warning",
) -> dict[str, Any]:
    diagnostic = getattr(warning, "diagnostic", None)
    if isinstance(diagnostic, dict):
        return dict(diagnostic)

    record: dict[str, Any] = {
        "kind": kind,
        "stage": stage,
        "level": level,
        "message": str(warning),
    }
    parts = str(warning).split(": ", 2)
    if len(parts) == 3 and parts[0].endswith(" failed"):
        record["exception_type"] = parts[1]
        record["exception_message"] = parts[2]
    return record


def _append_warning_diagnostic(
    state: EvalBatchState,
    warning: str,
    *,
    kind: str,
    stage: str,
    level: str = "warning",
) -> None:
    state.setdefault("diagnostics", []).append(
        _diagnostic_from_warning(warning, kind=kind, stage=stage, level=level)
    )


async def init_batch_node(state: EvalBatchState) -> dict:
    """Initialize batch run: set up paths, generate batch_id."""
    import uuid
    from app.util.time import beijing_now_iso

    cfg = state.get("batch_config", {})
    state.setdefault("batch_id", cfg.get("batch_id") or f"batch_{uuid.uuid4().hex[:8]}")
    state["started_at"] = beijing_now_iso()
    state["games"] = []
    state["player_scores"] = []
    state["warnings"] = []
    state["errors"] = []
    state["diagnostics"] = []
    return state


async def run_games_node(state: EvalBatchState) -> dict:
    """Run all evaluation games through the reusable game subgraph, concurrently.

    When the batch targets specific role versions (role_version_config, or a
    target_role + target_version_id pair), the evaluated roles are mounted from
    the registry via role_skill_dirs so only those roles use the versioned
    skills; every other role keeps the batch's baseline skill_dir. Each game is
    persisted under the batch directory for later replay.
    """
    from app.config import DEFAULT_PATHS
    from app.graphs.shared.nodes.game_batch import (
        per_game_dir,
        resolve_game_subgraph,
        run_game_batch,
    )

    cfg = state.get("batch_config", {})
    game_count = int(cfg.get("game_count", 10) or 0)
    max_days = int(cfg.get("max_days", 20) or 20)
    seed_start = int(cfg.get("seed_start", 0) or 0)
    batch_id = state.get("batch_id", "unknown")
    concurrency = int(cfg.get("game_concurrency", 0) or 0) or DEFAULT_CONCURRENCY
    game_subgraph = resolve_game_subgraph(state)

    base_skill_dir = cfg.get("skill_dir") or state.get("skill_dir")
    state["role_version_resolution_failed"] = False
    state["role_version_resolution_missing"] = {}
    requested_role_versions = _role_version_specs(cfg)
    role_skill_dirs = _resolve_role_version_dirs(
        cfg,
        state.get("paths"),
        warnings=state.setdefault("warnings", []),
        diagnostics=state.setdefault("diagnostics", []),
    )
    missing_role_versions = {
        role: version_id
        for role, version_id in requested_role_versions.items()
        if role not in role_skill_dirs
    }
    if missing_role_versions:
        state["role_version_resolution_failed"] = True
        state["role_version_resolution_missing"] = missing_role_versions

    paths = state.get("paths")
    batch_base = (
        Path(getattr(paths, "runs_dir", DEFAULT_PATHS.runs_dir)) / "evaluation_batches" / batch_id / "games"
    )

    def _build(index: int) -> dict[str, Any]:
        game_state: dict[str, Any] = {
            "game_id": f"{batch_id}_game_{index + 1:03d}",
            "seed": seed_start + index,
            "max_days": max_days,
            "model": state.get("model"),
            "skill_dir": base_skill_dir,
            "paths": paths,
            "game_dir": per_game_dir(batch_base, "game", index),
        }
        if role_skill_dirs:
            game_state["role_skill_dirs"] = role_skill_dirs
        return game_state

    try:
        games = await run_game_batch(
            game_subgraph, game_count, _build, concurrency=concurrency, label="eval",
        )
    except BatchAbortedError as exc:
        # Systemic failure — record cleanly and let downstream nodes mark the
        # batch unrankable instead of crashing the graph.
        _log.error("run_games_node: batch %s aborted: %s", batch_id, exc)
        state["games"] = []
        state["player_scores"] = []
        state.setdefault("errors", []).append(str(exc))
        return state

    scores: list[dict[str, Any]] = []
    for game in games:
        if not game.get("error"):
            scores.extend(_score_game(game))

    _log.info("run_games_node: completed %d/%d games", len(games), game_count)
    state["games"] = games
    state["player_scores"] = scores
    return state


def _role_version_specs(cfg: dict[str, Any]) -> dict[str, str]:
    role_versions: dict[str, str] = {}
    rv_config = cfg.get("role_version_config")
    if isinstance(rv_config, dict):
        role_versions.update({str(r): str(v) for r, v in rv_config.items() if v})
    target_role = cfg.get("target_role")
    target_version = cfg.get("target_version_id")
    if target_role and target_version:
        role_versions[str(target_role)] = str(target_version)
    return role_versions


def _resolve_role_version_dirs(
    cfg: dict[str, Any],
    paths: Any,
    *,
    warnings: list[str] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Build {role: skill_dir} from a batch's role-version spec via the registry.

    Accepts either an explicit role_version_config ({role: version_id}) or a
    single target_role + target_version_id pair. Failed roles degrade to the
    baseline skill dir and record warnings when provided.
    """
    role_versions = _role_version_specs(cfg)
    if not role_versions:
        return {}

    try:
        from app.config import DEFAULT_PATHS
        from app.lib.version import VersionRegistry

        registry_dir = getattr(paths, "registry_dir", DEFAULT_PATHS.registry_dir)
        registry = VersionRegistry(registry_dir)
    except Exception as exc:  # noqa: BLE001 — degrade to baseline skills
        message = _exception_message("failed to initialize role version registry", exc)
        _log.warning(message, exc_info=True)
        if warnings is not None:
            warnings.append(message)
        if diagnostics is not None:
            diagnostics.append({
                "kind": "role_version_error",
                "stage": "role_version.registry_init",
                "level": "warning",
                "message": message,
                "exception_type": type(exc).__name__,
                "exception_message": str(exc),
            })
        return {}

    resolved: dict[str, str] = {}
    for role, version_id in role_versions.items():
        try:
            resolved[role] = str(registry.get_skill_dir(role, version_id))
        except Exception as exc:  # noqa: BLE001 — degrade this role to baseline skills
            message = _exception_message(f"failed to resolve role version {role}/{version_id}", exc)
            _log.warning(message, exc_info=True)
            if warnings is not None:
                warnings.append(message)
            if diagnostics is not None:
                diagnostics.append({
                    "kind": "role_version_error",
                    "stage": "role_version.resolve",
                    "level": "warning",
                    "message": message,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                })
    return resolved


async def aggregate_node(state: EvalBatchState) -> dict:
    """Aggregate scores across all games."""
    from app.lib.score import aggregate_batch_scores, PlayerScore

    scores = state.get("player_scores", [])
    player_scores = [PlayerScore(**s) if isinstance(s, dict) else s for s in scores]
    completed_games = sum(1 for game in state.get("games", []) if not game.get("error"))
    summary = aggregate_batch_scores(
        player_scores,
        batch_id=state.get("batch_id", ""),
        game_count=completed_games,
    )

    state["score_summary"] = {
        "batch_id": summary.batch_id,
        "game_count": summary.game_count,
        "avg_role_score": round(summary.avg_role_score, 4),
        "by_role_category": {k: round(v, 4) for k, v in summary.by_role_category.items()},
        "avg_speech_score": round(summary.avg_speech_score, 4),
        "avg_vote_score": round(summary.avg_vote_score, 4),
        "avg_skill_score": round(summary.avg_skill_score, 4),
        "avg_logic_score": round(summary.avg_logic_score, 4),
        "avg_team_score": round(summary.avg_team_score, 4),
        "avg_risk_penalty": round(summary.avg_risk_penalty, 4),
        "strength_score": round(summary.strength_score, 4),
    }
    return state


async def fairness_node(state: EvalBatchState) -> dict:
    """Compute fairness validation, including cross-batch comparison groups."""
    from app.lib.score import compute_group_fairness, compute_rankable, open_eval_connection

    cfg = state.get("batch_config", {})
    games = state.get("games", [])
    completed = sum(1 for g in games if not g.get("error"))
    game_count = int(cfg.get("game_count", len(games)) or 0)
    valid_rate = completed / game_count if game_count else 0.0

    comparison_group_id = cfg.get("comparison_group_id")
    comparison_type = cfg.get("comparison_type")
    target_role = cfg.get("target_role")

    # Standalone batch (no group) is trivially fair; grouped batches load siblings.
    if not comparison_group_id:
        is_fair = game_count > 0
        reason = "standalone batch" if is_fair else "No games in batch"
    else:
        current_batch = {
            "comparison_type": comparison_type,
            "model_id": cfg.get("model_id"),
            "target_role": target_role,
            "target_version_id": cfg.get("target_version_id"),
            "seed_set_id": cfg.get("seed_set_id"),
        }
        conn = None
        try:
            conn = open_eval_connection(state.get("paths"))
            fairness = compute_group_fairness(
                conn,
                comparison_group_id=comparison_group_id,
                comparison_type=comparison_type,
                target_role=target_role,
                batch_id=state.get("batch_id", ""),
                current_batch=current_batch,
            )
            is_fair, reason = fairness.is_fair, fairness.reason
        except Exception as exc:  # noqa: BLE001 — fairness storage is advisory, not a graph crash
            _log.warning("fairness check failed for batch %s", state.get("batch_id", ""), exc_info=True)
            reason = _exception_message("fairness check failed", exc)
            state.setdefault("warnings", []).append(reason)
            _record_diagnostic(
                state,
                kind="fairness_error",
                stage="fairness.compute",
                level="warning",
                message=reason,
                exc=exc,
            )
            is_fair = False
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception as exc:  # noqa: BLE001 — cleanup should not fail the batch
                    _log.warning("fairness connection close failed for batch %s", state.get("batch_id", ""), exc_info=True)
                    warning = _exception_message("fairness connection close failed", exc)
                    state.setdefault("warnings", []).append(warning)
                    _record_diagnostic(
                        state,
                        kind="cleanup_error",
                        stage="fairness.close",
                        level="warning",
                        message=warning,
                        exc=exc,
                    )

    if not is_fair and not any(
        item.get("stage") == "fairness.compute" and item.get("message") == reason
        for item in state.get("diagnostics", [])
        if isinstance(item, dict)
    ):
        _record_diagnostic(
            state,
            kind="fairness_failed",
            stage="fairness.validate",
            level="warning",
            message=str(reason),
        )

    rankable, rankable_reason = compute_rankable(
        mode=str(cfg.get("mode", "dev")),
        paired_seed=bool(cfg.get("paired_seed", False)),
        game_count=game_count,
        valid_game_rate=valid_rate,
        is_fair=is_fair,
    )
    if state.get("role_version_resolution_failed"):
        rankable = False
        rankable_reason = "role version resolution failed"
    state["fairness"] = {"is_fair": is_fair, "reason": reason}
    state["valid_game_rate"] = valid_rate
    state["rankable"] = rankable
    state["rankable_reason"] = rankable_reason
    return state


async def persist_batch_node(state: EvalBatchState) -> dict:
    """Finalize the batch result and persist the batch row + leaderboard entry.

    Writes to wolf.db: an evaluation_batches row and a benchmark_leaderboard
    entry (scope = role_version when a target role/version is set, else model).
    Persistence is best-effort and never fails the pipeline.
    """
    from app.config import DEFAULT_PATHS
    from app.util.manifest import build_run_manifest, write_manifest
    from app.util.time import beijing_now_iso

    state["finished_at"] = beijing_now_iso()
    batch_id = state.get("batch_id", "unknown")
    _log.info("persist_batch_node: batch %s complete", batch_id)
    games = state.get("games", [])
    cfg = dict(state.get("batch_config", {}))
    summary = state.get("score_summary")
    completed = sum(1 for g in games if not g.get("error"))

    result = {
        "batch_id": batch_id,
        "config": cfg,
        "game_count": len(games),
        "completed": completed,
        "errored": sum(1 for g in games if g.get("error")),
        "games": games,
        "score_summary": summary,
        "fairness": state.get("fairness"),
        "rankable": state.get("rankable", False),
        "rankable_reason": state.get("rankable_reason", ""),
        "started_at": state.get("started_at", ""),
        "finished_at": state.get("finished_at", ""),
        "warnings": list(state.get("warnings", [])),
        "diagnostics": [dict(item) for item in state.get("diagnostics", []) if isinstance(item, dict)],
    }
    state["result"] = result
    warnings = _persist_batch(state, result)
    if warnings:
        state.setdefault("warnings", []).extend(warnings)
        result["warnings"] = list(state.get("warnings", []))
    result["diagnostics"] = [dict(item) for item in state.get("diagnostics", []) if isinstance(item, dict)]
    paths = state.get("paths")
    batch_dir = Path(getattr(paths, "runs_dir", DEFAULT_PATHS.runs_dir)) / "evaluation_batches" / str(batch_id)
    manifest_path = batch_dir / "manifest.json"
    result["metadata"] = {
        "artifact_dir": str(batch_dir),
        "manifest_path": str(manifest_path),
    }
    manifest = build_run_manifest(
        run_type="eval",
        run_id=str(batch_id),
        batch_id=str(batch_id),
        model_config_hash=str(cfg.get("model_config_hash") or ""),
        seed=cfg.get("seed_start"),
        config=cfg,
        started_at=result.get("started_at"),
        finished_at=result.get("finished_at"),
        status="failed" if state.get("errors") else "completed",
        error_summary="; ".join(str(item) for item in state.get("errors", [])),
        paths={
            "batch_dir": str(batch_dir),
            "games_dir": str(batch_dir / "games"),
            "manifest": "manifest.json",
        },
        metadata={
            "completed": completed,
            "errored": result["errored"],
            "rankable": result.get("rankable", False),
            "rankable_reason": result.get("rankable_reason", ""),
            "warnings": result.get("warnings", []),
            "diagnostics": result.get("diagnostics", []),
        },
    )
    result["manifest"] = manifest
    try:
        write_manifest(manifest_path, manifest)
    except Exception as exc:  # noqa: BLE001 — artifact manifest should not crash evaluation
        warning = _exception_message("persist_batch manifest write failed", exc)
        state.setdefault("warnings", []).append(warning)
        result["warnings"] = list(state.get("warnings", []))
        _record_diagnostic(
            state,
            kind="persistence_error",
            stage="persist_batch.manifest",
            level="warning",
            message=warning,
            exc=exc,
        )
        result["diagnostics"] = [dict(item) for item in state.get("diagnostics", []) if isinstance(item, dict)]
    return state


def _persist_batch(state: EvalBatchState, result: dict[str, Any]) -> list[str]:
    """Save the batch row and a leaderboard entry to wolf.db (best-effort)."""
    from app.lib.score import open_eval_connection, persist_leaderboard_entry, save_evaluation_batch

    warnings: list[str] = []
    cfg = dict(state.get("batch_config", {}))
    summary = result.get("score_summary") or {}
    target_role = cfg.get("target_role")
    target_version = cfg.get("target_version_id")
    comparison_type = cfg.get("comparison_type") or ("role_version" if target_role else "model")

    conn = None
    try:
        conn = open_eval_connection(state.get("paths"))
        warning = save_evaluation_batch(conn, {
            "batch_id": result["batch_id"],
            "comparison_group_id": cfg.get("comparison_group_id"),
            "comparison_type": comparison_type,
            "mode": cfg.get("mode", "dev"),
            "model_id": cfg.get("model_id"),
            "model_config_hash": cfg.get("model_config_hash"),
            "target_role": target_role,
            "target_version_id": target_version,
            "role_version_config": cfg.get("role_version_config"),
            "game_count": result["game_count"],
            "evaluation_set_id": cfg.get("evaluation_set_id"),
            "seed_set_id": cfg.get("seed_set_id"),
            "max_days": cfg.get("max_days", 20),
            "rankable": result.get("rankable"),
            "rankable_reason": result.get("rankable_reason"),
            "score_summary": summary,
            "started_at": result.get("started_at"),
            "finished_at": result.get("finished_at"),
        })
        if warning:
            warnings.append(warning)
            _append_warning_diagnostic(
                state,
                warning,
                kind="persistence_error",
                stage="persist_batch.save_evaluation_batch",
            )
        entry = {
            "batch_id": result["batch_id"],
            "comparison_group_id": cfg.get("comparison_group_id"),
            "model_id": cfg.get("model_id"),
            "model_config_hash": cfg.get("model_config_hash"),
            "evaluation_set_id": cfg.get("evaluation_set_id"),
            "seed_set_id": cfg.get("seed_set_id"),
            "rankable": result.get("rankable"),
            "game_count": result["game_count"],
            "valid_game_rate": state.get("valid_game_rate", 0.0),
            "avg_role_score": summary.get("avg_role_score", 0.0),
            "by_role_category_scores": summary.get("by_role_category"),
            "avg_speech_score": summary.get("avg_speech_score", 0.0),
            "avg_vote_score": summary.get("avg_vote_score", 0.0),
            "avg_skill_score": summary.get("avg_skill_score", 0.0),
            "avg_logic_score": summary.get("avg_logic_score", 0.0),
            "avg_team_score": summary.get("avg_team_score", 0.0),
            "strength_score": summary.get("strength_score", 0.0),
            "risk_penalty": summary.get("avg_risk_penalty", 0.0),
            "summary": summary,
        }
        if target_role and target_version:
            entry["scope"] = "role_version"
            entry["target_role"] = target_role
            entry["target_version_id"] = target_version
            entry["subject_id"] = target_version
        else:
            entry["scope"] = "model"
            entry["subject_id"] = cfg.get("model_config_hash") or cfg.get("model_id") or result["batch_id"]
        warning = persist_leaderboard_entry(conn, entry)
        if warning:
            warnings.append(warning)
            _append_warning_diagnostic(
                state,
                warning,
                kind="persistence_error",
                stage="persist_batch.persist_leaderboard_entry",
            )
    except Exception as exc:  # noqa: BLE001 — persistence is best-effort
        _log.warning("persist_batch failed for %s", result.get("batch_id"), exc_info=True)
        warning = _exception_message("persist_batch failed", exc)
        warnings.append(warning)
        _record_diagnostic(
            state,
            kind="persistence_error",
            stage="persist_batch",
            level="warning",
            message=warning,
            exc=exc,
        )
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception as exc:  # noqa: BLE001 — persistence cleanup is best-effort
                _log.warning("persist_batch close failed for %s", result.get("batch_id"), exc_info=True)
                warning = _exception_message("persist_batch close failed", exc)
                warnings.append(warning)
                _record_diagnostic(
                    state,
                    kind="cleanup_error",
                    stage="persist_batch.close",
                    level="warning",
                    message=warning,
                    exc=exc,
                )
    return warnings


def _game_result_dict(*, game_id: str, seed: int, result: dict[str, Any]) -> dict[str, Any]:
    # Backward-compatible shim — delegates to the shared normalizer.
    from app.graphs.shared.nodes.game_batch import normalize_game_result

    return normalize_game_result(game_id=game_id, seed=seed, result=result)


def _score_game(game: dict[str, Any]) -> list[dict[str, Any]]:
    from app.lib.review import analyze_game
    from app.lib.score import PlayerScore
    from engine import Role

    decisions_by_player: dict[int, list[dict[str, Any]]] = {}
    for decision in game.get("decisions", []):
        pid = decision.get("player_id")
        if pid is None:
            continue
        decisions_by_player.setdefault(int(pid), []).append(decision)

    roles: dict[int, Role] = {}
    for pid, role_name in game.get("player_roles", {}).items():
        try:
            roles[int(pid)] = Role(str(role_name))
        except (ValueError, KeyError):
            continue

    review = analyze_game(
        game_log=game.get("events", []),
        agent_decisions=decisions_by_player,
        roles=roles,
        winner_team=game.get("winner"),
        game_id=game.get("game_id", ""),
    )

    scores: list[dict[str, Any]] = []
    for score in review.agent_scores.values():
        scores.append(
            PlayerScore(
                player_id=score.player_id,
                role=score.role,
                speech_score=score.speech_quality,
                vote_score=score.vote_accuracy,
                skill_score=score.skill_accuracy,
                logic_score=score.overall,
                team_score=score.team_contribution,
                role_score=score.overall,
            ).to_dict()
        )
    return scores
