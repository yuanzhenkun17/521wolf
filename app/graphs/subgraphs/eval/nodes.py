"""Eval subgraph nodes — batch evaluation pipeline.

Nodes: init_batch → run_games → aggregate → fairness → persist_batch
"""

from __future__ import annotations

import importlib
import logging
import sys
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any

from app.graphs.shared.nodes.game_batch import BatchAbortedError, DEFAULT_CONCURRENCY, valid_completed_games
from app.graphs.shared.state import EvalBatchState
from app.util.winner import has_valid_winner, normalize_winner

_log = logging.getLogger(__name__)

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
    explicit_seeds = _explicit_batch_seeds(cfg.get("seeds"))
    if cfg.get("seeds") is not None and len(explicit_seeds) < game_count:
        message = (
            f"explicit benchmark seeds {len(explicit_seeds)} < game_count {game_count}; "
            "falling back to seed_start"
        )
        state.setdefault("warnings", []).append(message)
        _record_diagnostic(
            state,
            kind="benchmark_seed_error",
            stage="run_games.seed",
            level="warning",
            message=message,
        )
        explicit_seeds = []
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
        seed = explicit_seeds[index] if explicit_seeds else seed_start + index
        game_state: dict[str, Any] = {
            "game_id": f"{batch_id}_game_{index + 1:03d}",
            "batch_id": batch_id,
            "seed": seed,
            "max_days": max_days,
            "model": state.get("model"),
            "skill_dir": base_skill_dir,
            "paths": paths,
            "storage_provider": state.get("storage_provider"),
            "game_dir": per_game_dir(batch_base, "game", index),
            "storage_run_type": "evaluation_batch",
            "mode": cfg.get("mode", "dev"),
            "source_run_id": batch_id,
            "source_game_id": f"{batch_id}_game_{index + 1:03d}",
            "model_id": cfg.get("model_id"),
            "model_config_hash": cfg.get("model_config_hash"),
            "comparison_group_id": cfg.get("comparison_group_id"),
            "comparison_type": cfg.get("comparison_type"),
            "target_role": cfg.get("target_role"),
            "target_version_id": cfg.get("target_version_id"),
            "seed_set_id": cfg.get("seed_set_id"),
            "evaluation_set_id": cfg.get("evaluation_set_id"),
            "paired_seed": cfg.get("paired_seed"),
        }
        game_state.update(_langfuse_game_metadata_from_eval_config(cfg, state, seed=seed, index=index))
        if role_skill_dirs:
            game_state["role_skill_dirs"] = role_skill_dirs
        _copy_runner_config(cfg, game_state)
        return game_state

    with _langfuse_eval_context(
        state,
        stage="run_games",
        input={
            "batch_id": batch_id,
            "game_count": game_count,
            "max_days": max_days,
            "seed_start": seed_start,
            "seed_count": len(explicit_seeds) if explicit_seeds else game_count,
            "seed_preview": explicit_seeds[:5],
        },
    ):
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
    for game in valid_completed_games(games):
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


def _explicit_batch_seeds(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    seeds: list[int] = []
    for item in value:
        try:
            seed = int(item)
        except (TypeError, ValueError):
            continue
        if seed >= 0:
            seeds.append(seed)
    return seeds


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
        from app.lib.version import registry_version_release_stage, version_registry_from_env

        registry = version_registry_from_env(paths=paths)
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
    try:
        for role, version_id in role_versions.items():
            try:
                release_stage = registry_version_release_stage(registry, role, version_id)
                if str(release_stage or "").strip().lower() == "shadow":
                    raise ValueError(
                        f"role version {role}/{version_id} is release_stage=shadow; "
                        "promote to canary before explicit evaluation"
                    )
                resolved[role] = str(registry.get_skill_dir(role, version_id))
            except ValueError:
                raise
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
    finally:
        registry.close()
    return resolved


async def aggregate_node(state: EvalBatchState) -> dict:
    """Aggregate scores across all games."""
    from app.lib.score import aggregate_batch_scores, compute_decision_quality_metrics, PlayerScore

    scores = state.get("player_scores", [])
    player_scores = [PlayerScore(**s) if isinstance(s, dict) else s for s in scores]
    judge_aggregate = await _attach_eval_decision_judge_reports(state)
    decision_quality = compute_decision_quality_metrics(state.get("games", []))
    terminal_stats = _terminal_stats(state.get("games", []))
    completed_games = len(valid_completed_games(state.get("games", [])))
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
        "decision_quality": decision_quality,
        "terminal_stats": terminal_stats,
        "fallback_rate": decision_quality["fallback_rate"],
        "llm_error_rate": decision_quality["llm_error_rate"],
        "policy_adjusted_rate": decision_quality["policy_adjusted_rate"],
    }
    if judge_aggregate is not None:
        state["score_summary"]["decision_judge_aggregate"] = judge_aggregate
        state["decision_judge_aggregate"] = judge_aggregate
    return state


async def _attach_eval_decision_judge_reports(state: EvalBatchState) -> dict[str, Any] | None:
    """Attach lightweight judge reports to completed eval games and aggregate them."""
    cfg = state.get("batch_config", {})
    if not _eval_judge_configured(state, cfg):
        return None

    from app.lib.decision_judge import judge_key_decisions
    from app.lib.judge_policy import resolve_judge_policy

    policy = resolve_judge_policy("eval", cfg, state)
    games = valid_completed_games(state.get("games", []))
    if not policy.enabled:
        return _aggregate_decision_judge_reports([], game_count=len(games), skipped_reason="disabled")

    reports: list[dict[str, Any]] = []
    warnings: list[str] = []
    judge_model = state.get("decision_judge_model")
    if judge_model is None:
        judge_model = state.get("model")
    for game in games:
        try:
            report = await judge_key_decisions(
                judge_model,
                game_id=str(game.get("game_id") or ""),
                winner=game.get("winner"),
                roles=game.get("player_roles") or game.get("roles"),
                events=game.get("events") or game.get("game_events"),
                decisions=game.get("decisions"),
                review=game.get("review"),
                max_decisions=policy.max_decisions,
                concurrency=policy.concurrency,
                timeout_seconds=policy.timeout_seconds,
                judge_fn=state.get("decision_judge_fn"),
            )
            for judgment in report.get("judgments", []) if isinstance(report, dict) else []:
                if isinstance(judgment, dict):
                    judgment.setdefault("game_id", game.get("game_id"))
            game.setdefault("review", {})["decision_judge"] = report
            reports.append(report)
            for warning in report.get("warnings", []) if isinstance(report, dict) else []:
                text = str(warning)
                if text:
                    warnings.append(text)
        except Exception as exc:  # noqa: BLE001 - eval judge is advisory
            message = f"eval decision judge failed for game={game.get('game_id')}: {type(exc).__name__}: {exc}"
            warnings.append(message)
            game.setdefault("review", {})["decision_judge"] = {
                "status": "failed",
                "error": str(exc),
                "warnings": [message],
            }

    aggregate = _aggregate_decision_judge_reports(reports, game_count=len(games), warnings=warnings)
    if warnings:
        state.setdefault("warnings", []).extend(warning for warning in warnings if warning not in state.get("warnings", []))
        for warning in warnings:
            _append_warning_diagnostic(
                state,
                warning,
                kind="decision_judge_warning",
                stage="aggregate.decision_judge",
            )
    return aggregate


def _aggregate_decision_judge_reports(
    reports: list[dict[str, Any]],
    *,
    game_count: int,
    warnings: list[str] | None = None,
    skipped_reason: str | None = None,
) -> dict[str, Any]:
    warnings = [str(item) for item in (warnings or []) if str(item)]
    judgments = [
        item
        for report in reports
        if isinstance(report, dict)
        for item in report.get("judgments", []) or []
        if isinstance(item, dict)
    ]
    scores = [_safe_float(item.get("score")) for item in judgments]
    scores = [score for score in scores if score is not None]
    report_reasons = _unique_text(
        report.get("reason")
        for report in reports
        if isinstance(report, dict) and report.get("reason")
    )
    degraded_reasons = _unique_text(
        reason
        for report in reports
        if isinstance(report, dict)
        for reason in report.get("degraded_reasons", []) or []
    )
    diagnostics = [
        dict(diagnostic)
        for report in reports
        if isinstance(report, dict)
        for diagnostic in report.get("diagnostics", []) or []
        if isinstance(diagnostic, dict)
    ]
    quality_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    recommended_skill_counts: dict[str, int] = {}
    by_role: dict[str, dict[str, Any]] = {}
    by_action_type: dict[str, dict[str, Any]] = {}

    for item in judgments:
        quality = str(item.get("quality") or "unknown")
        quality_counts[quality] = quality_counts.get(quality, 0) + 1
        for tag in item.get("mistake_tags", []) or []:
            text = str(tag)
            if text:
                tag_counts[text] = tag_counts.get(text, 0) + 1
        for path in item.get("recommended_skill_files", []) or item.get("related_skills", []) or []:
            text = str(path)
            if text:
                recommended_skill_counts[text] = recommended_skill_counts.get(text, 0) + 1
        _add_judge_group(by_role, str(item.get("role") or "unknown"), item)
        _add_judge_group(by_action_type, str(item.get("action_type") or "unknown"), item)

    judged = len(judgments)
    failed = sum(int((report.get("metrics") or {}).get("failed") or 0) for report in reports if isinstance(report, dict))
    skipped_games = sum(1 for report in reports if isinstance(report, dict) and report.get("status") == "skipped")
    if judged and not failed and not warnings:
        status = "ok"
    elif judged:
        status = "degraded"
    elif skipped_reason or skipped_games:
        status = "skipped"
    else:
        status = "failed" if warnings else "skipped"

    lowest = sorted(
        judgments,
        key=lambda item: (_safe_float(item.get("score")) if _safe_float(item.get("score")) is not None else 99, str(item.get("decision_id") or "")),
    )[:5]
    average = round(sum(scores) / len(scores), 4) if scores else None
    reason = skipped_reason
    if reason is None and report_reasons:
        reason = report_reasons[0] if len(report_reasons) == 1 else "mixed"
    return {
        "status": status,
        "reason": reason,
        "report_reasons": report_reasons,
        "degraded_reasons": degraded_reasons,
        "diagnostics": diagnostics,
        "game_count": game_count,
        "reported_games": len(reports),
        "skipped_games": skipped_games,
        "judged_decisions": judged,
        "failed_decisions": failed,
        "avg_score": average,
        "bad_rate": round(quality_counts.get("bad", 0) / judged, 4) if judged else None,
        "unknown_rate": round(quality_counts.get("unknown", 0) / judged, 4) if judged else None,
        "quality_counts": quality_counts,
        "top_mistake_tags": [
            {"tag": tag, "count": count}
            for tag, count in sorted(tag_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
        ],
        "recommended_skill_files": [
            {"path": path, "count": count}
            for path, count in sorted(recommended_skill_counts.items(), key=lambda item: (-item[1], item[0]))[:8]
        ],
        "by_role": _finalize_judge_groups(by_role),
        "by_action_type": _finalize_judge_groups(by_action_type),
        "lowest_decisions": [
            {
                "game_id": item.get("game_id"),
                "decision_id": item.get("decision_id"),
                "player_id": item.get("player_id"),
                "role": item.get("role"),
                "action_type": item.get("action_type"),
                "score": item.get("score"),
                "quality": item.get("quality"),
                "reason": item.get("reason"),
                "evidence": item.get("evidence") or item.get("evidence_refs") or [],
                "counterfactual": item.get("counterfactual", ""),
                "related_skills": item.get("related_skills", []),
                "recommended_skill_files": item.get("recommended_skill_files", []),
                "suggestion": item.get("suggestion"),
            }
            for item in lowest
        ],
        "warnings": warnings,
    }


def _eval_judge_configured(state: dict[str, Any], cfg: dict[str, Any]) -> bool:
    keys = {
        "enable_llm_judge",
        "enable_decision_judge",
        "eval_llm_judge",
        "eval_decision_judge",
        "review_llm_judge",
        "review_decision_judge",
        "judge_max_decisions",
        "eval_judge_max_decisions",
        "review_judge_max_decisions",
        "decision_judge_max_decisions",
        "judge_timeout_seconds",
        "eval_judge_timeout_seconds",
        "review_judge_timeout_seconds",
    }
    return any(key in cfg for key in keys) or any(key in state for key in keys)


def _unique_text(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _add_judge_group(groups: dict[str, dict[str, Any]], key: str, item: dict[str, Any]) -> None:
    score = _safe_float(item.get("score"))
    row = groups.setdefault(key or "unknown", {"count": 0, "score_sum": 0.0, "bad": 0, "unknown": 0})
    row["count"] += 1
    if score is not None:
        row["score_sum"] += score
    quality = str(item.get("quality") or "")
    if quality == "bad":
        row["bad"] += 1
    if quality == "unknown":
        row["unknown"] += 1


def _finalize_judge_groups(groups: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for key, row in groups.items():
        count = int(row.get("count") or 0)
        result[key] = {
            "count": count,
            "avg_score": round(float(row.get("score_sum") or 0.0) / count, 4) if count else None,
            "bad_rate": round(float(row.get("bad") or 0) / count, 4) if count else None,
            "unknown_rate": round(float(row.get("unknown") or 0) / count, 4) if count else None,
        }
    return result


def _safe_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _terminal_stats(games: list[dict[str, Any]]) -> dict[str, Any]:
    stats: dict[str, Any] = {
        "attempted": len(games),
        "completed": 0,
        "invalid": 0,
        "timeout": 0,
        "abnormal": 0,
        "errored": 0,
        "winner_counts": {"villagers": 0, "werewolves": 0},
        "terminal_reason_counts": {},
        "excluded_from_win_rate": 0,
    }
    for game in games:
        if not isinstance(game, dict):
            stats["invalid"] += 1
            continue
        reason = str(game.get("terminal_reason") or game.get("outcome") or "").strip()
        if reason:
            counts = stats["terminal_reason_counts"]
            counts[reason] = counts.get(reason, 0) + 1

        winner = normalize_winner(game.get("winner"))
        if has_valid_winner(game):
            stats["completed"] += 1
            stats["winner_counts"][winner] += 1
        elif _is_timeout_game(game):
            stats["timeout"] += 1
        elif game.get("error"):
            stats["errored"] += 1
        elif _is_abnormal_terminal(game):
            stats["abnormal"] += 1
        else:
            stats["invalid"] += 1

    stats["excluded_from_win_rate"] = (
        stats["attempted"]
        - stats["completed"]
    )
    completed = int(stats["completed"])
    stats["win_rate_denominator"] = completed
    stats["villagers_win_rate"] = round(stats["winner_counts"]["villagers"] / completed, 6) if completed else None
    stats["werewolves_win_rate"] = round(stats["winner_counts"]["werewolves"] / completed, 6) if completed else None
    return stats


def _leaderboard_target_team(cfg: dict[str, Any], target_role: Any) -> str | None:
    explicit = normalize_winner(cfg.get("target_team") or cfg.get("target_side"))
    if explicit:
        return explicit
    role = str(target_role or "").strip().lower()
    if not role:
        return None
    aliases = {
        "wolf": "werewolf",
        "wolves": "werewolf",
        "white_wolf": "white_wolf_king",
        "white_wolf_king": "white_wolf_king",
    }
    role = aliases.get(role, role)
    try:
        from engine import Role, Team

        team = Role(role).team
        return "werewolves" if team is Team.WEREWOLVES else "villagers"
    except (ValueError, KeyError):
        if "wolf" in role:
            return "werewolves"
        return "villagers"


def _target_side_win_evidence(games: list[dict[str, Any]], *, target_team: str | None) -> dict[str, Any]:
    if not target_team:
        return {}
    completed = valid_completed_games(games)
    seed_metrics: list[dict[str, Any]] = []
    target_wins = 0
    for index, game in enumerate(completed, start=1):
        winner = normalize_winner(game.get("winner"))
        target_side_win = winner == target_team
        if target_side_win:
            target_wins += 1
        seed = game.get("seed")
        source_game_id = game.get("source_game_id") or game.get("game_id")
        seed_metrics.append(
            {
                "seed": seed,
                "game_index": index,
                "game_id": game.get("game_id"),
                "source_game_id": source_game_id,
                "pair_key": f"{seed}:{index}" if seed is not None else source_game_id,
                "winner": winner,
                "target_team": target_team,
                "target_side_win": target_side_win,
            }
        )
    sample_size = len(completed)
    return {
        "sample_size": sample_size,
        "target_team": target_team,
        "target_wins": target_wins,
        "target_side_win_rate": round(target_wins / sample_size, 6) if sample_size else 0.0,
        "seed_metrics": seed_metrics,
    }


def _is_timeout_game(game: dict[str, Any]) -> bool:
    values = (
        game.get("winner"),
        game.get("outcome"),
        game.get("terminal_reason"),
        game.get("error"),
    )
    text = " ".join(str(value or "").lower() for value in values)
    return "timeout" in text


def _is_abnormal_terminal(game: dict[str, Any]) -> bool:
    status = str(game.get("status") or "").strip().lower()
    reason = str(game.get("terminal_reason") or game.get("outcome") or "").strip().lower()
    winner = str(game.get("winner") or "").strip().lower()
    return status in {"failed", "cancelled", "interrupted"} or reason in {
        "cancelled",
        "interrupted",
        "aborted",
        "failed",
        "max_days_reached",
    } or winner in {"error", "timeout", "cancelled", "aborted", "unknown"}


def _compute_data_sufficient(
    cfg: dict[str, Any],
    *,
    completed: int,
    requested: int,
    valid_game_rate: float,
) -> tuple[bool, str]:
    min_games = int(
        cfg.get("leaderboard_min_games")
        or cfg.get("data_sufficient_min_games")
        or cfg.get("min_completed_games")
        or cfg.get("min_rankable_games")
        or 1
    )
    min_valid_rate = _safe_float(
        cfg.get("leaderboard_min_valid_game_rate")
        or cfg.get("data_sufficient_min_valid_game_rate")
        or cfg.get("min_valid_game_rate")
    )
    if min_valid_rate is None:
        min_valid_rate = 0.8 if str(cfg.get("mode", "dev")) == "prod" else 0.0
    if completed < min_games:
        return False, f"completed_games {completed} < required {min_games}"
    if requested and valid_game_rate < min_valid_rate:
        return False, f"valid_game_rate {valid_game_rate:.1%} < required {min_valid_rate:.1%}"
    return True, "ok"


def _low_error_rates_ok(cfg: dict[str, Any], summary: dict[str, Any]) -> tuple[bool, str]:
    default_ceiling = _safe_float(
        cfg.get("leaderboard_error_rate_ceiling")
        or cfg.get("rankable_error_rate_ceiling")
    )
    if default_ceiling is None:
        default_ceiling = 0.30
    rate_fields = (
        (
            "llm_error_rate",
            summary.get("llm_error_rate"),
            _safe_float(cfg.get("leaderboard_llm_error_rate_ceiling") or cfg.get("max_llm_error_rate")),
        ),
        (
            "fallback_rate",
            summary.get("fallback_rate"),
            _safe_float(cfg.get("leaderboard_fallback_rate_ceiling") or cfg.get("max_fallback_rate")),
        ),
        (
            "policy_adjusted_rate",
            summary.get("policy_adjusted_rate"),
            _safe_float(
                cfg.get("leaderboard_policy_adjusted_rate_ceiling")
                or cfg.get("max_policy_adjusted_rate")
            ),
        ),
    )
    decision_quality = summary.get("decision_quality") if isinstance(summary.get("decision_quality"), dict) else {}
    for name, value, field_ceiling in (
        *rate_fields,
        ("invalid_response_rate", decision_quality.get("invalid_response_rate"), None),
        ("default_action_rate", decision_quality.get("default_action_rate"), None),
    ):
        ceiling = field_ceiling if field_ceiling is not None else default_ceiling
        rate = _safe_float(value)
        if rate is not None and rate > ceiling:
            return False, f"{name} {rate:.1%} > ceiling {ceiling:.1%}"
    return True, "ok"


def _leaderboard_acceptance_gate(
    state: EvalBatchState,
    result: dict[str, Any],
    entry: dict[str, Any],
) -> dict[str, Any]:
    del entry
    rankable = bool(result.get("rankable"))
    data_sufficient = bool(result.get("data_sufficient"))
    low_error_rate = bool(result.get("low_error_rate"))
    reasons = []
    if not rankable:
        reasons.append(str(result.get("rankable_reason") or "not_rankable"))
    if not data_sufficient:
        reasons.append(str(result.get("data_sufficient_reason") or "data_insufficient"))
    if not low_error_rate:
        reasons.append(str(result.get("low_error_rate_reason") or "error_rate_too_high"))
    unique_reasons = _unique_text(reasons)
    terminal_stats = result.get("terminal_stats") if isinstance(result.get("terminal_stats"), dict) else {}
    accepted = not unique_reasons
    return {
        "accepted": accepted,
        "reason": "ok" if accepted else "; ".join(unique_reasons),
        "rankable": rankable,
        "data_sufficient": data_sufficient,
        "low_error_rate": low_error_rate,
        "completed_games": result.get("game_count", 0),
        "attempted_games": result.get("attempted_game_count", 0),
        "excluded_from_win_rate": terminal_stats.get("excluded_from_win_rate", 0),
        "valid_game_rate": state.get("valid_game_rate", 0.0),
    }


def _observability() -> Any | None:
    try:
        return importlib.import_module("app.services.observability")
    except Exception:  # noqa: BLE001 - observability must not affect eval
        _log.debug("Langfuse observability import failed", exc_info=True)
        return None


def _ensure_langfuse_eval_trace_id(state: EvalBatchState, observability: Any | None) -> str | None:
    trace_id = state.get("langfuse_trace_id")
    if trace_id:
        return str(trace_id)
    if observability is None:
        return None
    create_trace_id = getattr(observability, "create_trace_id", None)
    if not callable(create_trace_id):
        return None
    try:
        batch_id = str(state.get("batch_id") or "")
        trace_id = create_trace_id(seed=batch_id) if batch_id else create_trace_id()
    except Exception:  # noqa: BLE001 - tracing is advisory
        _log.debug("Langfuse eval trace id creation failed", exc_info=True)
        return None
    if trace_id:
        state["langfuse_trace_id"] = str(trace_id)
        return str(trace_id)
    return None


def _langfuse_eval_context(
    state: EvalBatchState,
    *,
    stage: str,
    result: dict[str, Any] | None = None,
    input: Any | None = None,
    observability: Any | None = None,
) -> Any:
    observability = observability or _observability()
    if observability is None:
        return nullcontext(None)
    context_fn = getattr(observability, "langfuse_context", None)
    if not callable(context_fn):
        return nullcontext(None)

    trace_id = _ensure_langfuse_eval_trace_id(state, observability)
    metadata = _langfuse_eval_metadata(state, result=result)
    metadata["stage"] = stage
    try:
        return _fail_open_langfuse_context(context_fn(
            trace_name="eval.batch",
            trace_id=trace_id,
            session_id=str(state.get("batch_id") or "") or None,
            metadata={key: value for key, value in metadata.items() if value is not None},
            tags=_langfuse_eval_tags(state, result=result),
            input=input,
        ))
    except Exception:  # noqa: BLE001 - tracing is advisory
        _log.debug("Langfuse eval context creation failed", exc_info=True)
        return nullcontext(None)


def _langfuse_eval_metadata(
    state: EvalBatchState,
    *,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = dict(state.get("batch_config", {}) or {})
    games = state.get("games", [])
    result = result if isinstance(result, dict) else {}
    metadata: dict[str, Any] = {
        "run_type": "eval",
        "batch_id": state.get("batch_id") or result.get("batch_id"),
        "mode": cfg.get("mode", "dev"),
        "configured_game_count": cfg.get("game_count"),
        "attempted_game_count": result.get("attempted_game_count") if result else len(games),
        "completed_game_count": result.get("game_count"),
        "rankable": result.get("rankable", state.get("rankable")),
        "valid_game_rate": _first_present(result.get("valid_game_rate"), state.get("valid_game_rate")),
        "data_sufficient": result.get("data_sufficient", state.get("data_sufficient")),
        "low_error_rate": result.get("low_error_rate", state.get("low_error_rate")),
    }
    metadata.update(_langfuse_eval_linkage_metadata(state, result=result))
    for key in (
        "model_id",
        "model_config_hash",
        "comparison_group_id",
        "comparison_type",
        "target_role",
        "target_version_id",
        "seed_set_id",
        "evaluation_set_id",
    ):
        value = _first_present(cfg.get(key), state.get(key))
        if value is not None:
            metadata[key] = value
    if cfg.get("paired_seed") is not None:
        metadata["paired_seed"] = bool(cfg.get("paired_seed"))
    gate = result.get("leaderboard_gate")
    if isinstance(gate, dict):
        metadata["leaderboard_accepted"] = gate.get("accepted")
        metadata["leaderboard_gate_reason"] = gate.get("reason")
    return {key: value for key, value in metadata.items() if value is not None}


def _langfuse_eval_tags(
    state: EvalBatchState,
    *,
    result: dict[str, Any] | None = None,
) -> list[str]:
    cfg = dict(state.get("batch_config", {}) or {})
    tags = ["werewolf", "eval"]
    mode = cfg.get("mode")
    if mode:
        tags.append(str(mode))
    comparison_type = cfg.get("comparison_type")
    if comparison_type:
        tags.append(f"comparison:{comparison_type}")
    target_role = cfg.get("target_role")
    if target_role:
        tags.append(f"role:{target_role}")
    result = result if isinstance(result, dict) else {}
    if result.get("rankable") is True:
        tags.append("rankable")
    return tags


def _benchmark_metadata_from_config(cfg: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in (
        "benchmark_id",
        "benchmark_version",
        "benchmark_config_hash",
        "evaluation_set_id",
        "seed_set_id",
        "target_type",
    ):
        value = cfg.get(key)
        if value is not None:
            metadata[key] = value
    return metadata


def _score_langfuse_eval_batch_trace(state: EvalBatchState, result: dict[str, Any]) -> None:
    observability = _observability()
    if observability is None:
        return
    try:
        with _langfuse_eval_context(
            state,
            stage="persist_batch",
            result=result,
            input={
                "batch_id": result.get("batch_id"),
                "game_count": result.get("game_count"),
                "attempted_game_count": result.get("attempted_game_count"),
            },
            observability=observability,
        ):
            _write_langfuse_eval_scores(observability, state, result)
    except Exception:  # noqa: BLE001 - observability must not affect eval
        _log.debug("Langfuse eval scoring failed", exc_info=True)
    finally:
        _flush_langfuse(observability)


def _write_langfuse_eval_scores(
    observability: Any,
    state: EvalBatchState,
    result: dict[str, Any],
) -> None:
    summary = result.get("score_summary") if isinstance(result.get("score_summary"), dict) else {}
    terminal_stats = result.get("terminal_stats") if isinstance(result.get("terminal_stats"), dict) else {}
    decision_quality = summary.get("decision_quality") if isinstance(summary.get("decision_quality"), dict) else {}
    metadata = _langfuse_eval_score_metadata(state, result)
    dataset_run_ids = _langfuse_dataset_run_ids(result.get("games") or state.get("games"))

    numeric_scores = {
        "eval.avg_role_score": summary.get("avg_role_score"),
        "eval.strength_score": summary.get("strength_score"),
        "eval.valid_game_rate": _first_present(result.get("valid_game_rate"), state.get("valid_game_rate")),
        "eval.fallback_rate": _first_present(summary.get("fallback_rate"), decision_quality.get("fallback_rate")),
        "eval.llm_error_rate": _first_present(summary.get("llm_error_rate"), decision_quality.get("llm_error_rate")),
        "eval.policy_adjusted_rate": _first_present(
            summary.get("policy_adjusted_rate"),
            decision_quality.get("policy_adjusted_rate"),
        ),
        "eval.villagers_win_rate": terminal_stats.get("villagers_win_rate"),
        "eval.werewolves_win_rate": terminal_stats.get("werewolves_win_rate"),
    }
    for name, value in numeric_scores.items():
        number = _safe_float(value)
        if number is not None:
            _score_langfuse_metric(
                observability,
                name,
                number,
                data_type="NUMERIC",
                metadata=metadata,
                dataset_run_ids=dataset_run_ids,
            )

    if "rankable" in result or "rankable" in state:
        _score_langfuse_metric(
            observability,
            "eval.rankable",
            bool(_first_present(result.get("rankable"), state.get("rankable"))),
            data_type="BOOLEAN",
            metadata=metadata,
            dataset_run_ids=dataset_run_ids,
        )

    boolean_scores = {
        "eval.data_sufficient": _first_present(result.get("data_sufficient"), state.get("data_sufficient")),
        "eval.low_error_rate": _first_present(result.get("low_error_rate"), state.get("low_error_rate")),
        "eval.leaderboard_accepted": _leaderboard_accepted(result),
    }
    for name, value in boolean_scores.items():
        if value is not None:
            _score_langfuse_metric(
                observability,
                name,
                bool(value),
                data_type="BOOLEAN",
                metadata=metadata,
                dataset_run_ids=dataset_run_ids,
            )

    judge = summary.get("decision_judge_aggregate")
    if not isinstance(judge, dict):
        judge = state.get("decision_judge_aggregate") if isinstance(state.get("decision_judge_aggregate"), dict) else {}
    if isinstance(judge, dict):
        for name, value in (
            ("eval.decision_judge_avg_score", judge.get("avg_score")),
            ("eval.decision_judge_bad_rate", judge.get("bad_rate")),
        ):
            number = _safe_float(value)
            if number is not None:
                _score_langfuse_metric(
                    observability,
                    name,
                    number,
                    data_type="NUMERIC",
                    metadata=metadata,
                    dataset_run_ids=dataset_run_ids,
                )


def _langfuse_eval_score_metadata(state: EvalBatchState, result: dict[str, Any]) -> dict[str, Any]:
    gate = result.get("leaderboard_gate") if isinstance(result.get("leaderboard_gate"), dict) else {}
    cfg = dict(state.get("batch_config", {}) or {})
    metadata = {
        "metric_family": "eval",
        "batch_id": result.get("batch_id") or state.get("batch_id"),
        "game_count": result.get("game_count"),
        "attempted_game_count": result.get("attempted_game_count"),
        "rankable": result.get("rankable"),
        "rankable_reason": result.get("rankable_reason") or state.get("rankable_reason"),
        "data_sufficient": result.get("data_sufficient", state.get("data_sufficient")),
        "data_sufficient_reason": result.get("data_sufficient_reason") or state.get("data_sufficient_reason"),
        "low_error_rate": result.get("low_error_rate", state.get("low_error_rate")),
        "low_error_rate_reason": result.get("low_error_rate_reason") or state.get("low_error_rate_reason"),
        "leaderboard_accepted": gate.get("accepted"),
        "leaderboard_gate_reason": gate.get("reason"),
    }
    metadata.update(_langfuse_eval_linkage_metadata(state, result=result))
    return {key: value for key, value in metadata.items() if value is not None}


def _langfuse_eval_linkage_metadata(
    state: EvalBatchState,
    *,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = dict(state.get("batch_config", {}) or {})
    result = result if isinstance(result, dict) else {}
    result_cfg = result.get("config") if isinstance(result.get("config"), dict) else {}
    summary = result.get("score_summary") if isinstance(result.get("score_summary"), dict) else {}
    metadata: dict[str, Any] = {}

    for key in (
        "batch_id",
        "evaluation_set_id",
        "seed_set_id",
        "benchmark_id",
        "benchmark_version",
        "benchmark_config_hash",
        "model_id",
        "model_config_hash",
        "comparison_group_id",
        "comparison_type",
        "target_role",
        "target_version_id",
        "target_type",
    ):
        value = _first_present(
            result.get(key),
            cfg.get(key),
            result_cfg.get(key),
            summary.get(key),
            state.get(key),
        )
        if value is not None:
            metadata[key] = value

    dataset_name = _first_present(
        cfg.get("langfuse_dataset_name"),
        result_cfg.get("langfuse_dataset_name"),
        state.get("langfuse_dataset_name"),
        metadata.get("evaluation_set_id"),
    )
    if dataset_name is not None:
        metadata["langfuse_dataset_name"] = dataset_name

    dataset_item_id = _first_present(
        cfg.get("langfuse_dataset_item_id"),
        result_cfg.get("langfuse_dataset_item_id"),
        state.get("langfuse_dataset_item_id"),
        _langfuse_dataset_item_id_from_config(cfg),
    )
    if dataset_item_id is not None:
        metadata["langfuse_dataset_item_id"] = dataset_item_id

    experiment_name = _first_present(
        cfg.get("langfuse_experiment_name"),
        result_cfg.get("langfuse_experiment_name"),
        state.get("langfuse_experiment_name"),
        cfg.get("experiment_name"),
        result_cfg.get("experiment_name"),
        state.get("experiment_name"),
    )
    if experiment_name is not None:
        metadata["langfuse_experiment_name"] = experiment_name
        metadata["experiment_name"] = experiment_name

    run_name = _first_present(
        cfg.get("langfuse_run_name"),
        result_cfg.get("langfuse_run_name"),
        state.get("langfuse_run_name"),
        cfg.get("run_name"),
        result_cfg.get("run_name"),
        state.get("run_name"),
    )
    if run_name is not None:
        metadata["langfuse_run_name"] = run_name
        metadata["run_name"] = run_name

    return {key: value for key, value in metadata.items() if value is not None}


def _langfuse_game_metadata_from_eval_config(
    cfg: dict[str, Any],
    state: EvalBatchState,
    *,
    seed: int,
    index: int,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    dataset_name = _first_present(
        cfg.get("langfuse_dataset_name"),
        state.get("langfuse_dataset_name"),
        cfg.get("evaluation_set_id"),
    )
    if dataset_name is not None:
        metadata["langfuse_dataset_name"] = dataset_name

    dataset_item_id = _langfuse_dataset_item_id_from_config(cfg, seed=seed, index=index)
    if dataset_item_id is None:
        dataset_item_id = state.get("langfuse_dataset_item_id")
    if dataset_item_id is not None:
        metadata["langfuse_dataset_item_id"] = dataset_item_id

    experiment_name = _first_present(
        cfg.get("langfuse_experiment_name"),
        state.get("langfuse_experiment_name"),
        cfg.get("experiment_name"),
        state.get("experiment_name"),
    )
    if experiment_name is not None:
        metadata["langfuse_experiment_name"] = experiment_name
        metadata["experiment_name"] = experiment_name

    run_name = _first_present(
        cfg.get("langfuse_run_name"),
        state.get("langfuse_run_name"),
        cfg.get("run_name"),
        state.get("run_name"),
    )
    if run_name is not None:
        metadata["langfuse_run_name"] = run_name
        metadata["run_name"] = run_name
    return metadata


def _langfuse_dataset_item_id_from_config(
    cfg: dict[str, Any],
    *,
    seed: int | None = None,
    index: int | None = None,
) -> str | None:
    configured = cfg.get("langfuse_dataset_item_id")
    if isinstance(configured, str) and configured.strip():
        return configured
    if isinstance(configured, list) and index is not None and 0 <= index < len(configured):
        item = configured[index]
        if item is not None:
            return str(item)
    if isinstance(configured, dict):
        for key in (seed, str(seed) if seed is not None else None, index, str(index) if index is not None else None):
            if key is not None and key in configured and configured[key] is not None:
                return str(configured[key])

    if seed is None:
        game_count = cfg.get("game_count")
        try:
            if int(game_count or 0) != 1:
                return None
            seeds = _explicit_batch_seeds(cfg.get("seeds"))
            seed = seeds[0] if seeds else int(cfg.get("seed_start", 0) or 0)
        except (TypeError, ValueError):
            return None

    evaluation_set_id = cfg.get("evaluation_set_id")
    seed_set_id = cfg.get("seed_set_id")
    if evaluation_set_id is None or seed_set_id is None:
        return None
    return f"{evaluation_set_id}:{seed_set_id}:{seed}"


def _leaderboard_accepted(result: dict[str, Any]) -> bool | None:
    gate = result.get("leaderboard_gate") if isinstance(result.get("leaderboard_gate"), dict) else {}
    if "accepted" in gate:
        return bool(gate.get("accepted"))
    if "leaderboard_skipped_reason" in result:
        return False
    return None


def _score_langfuse_metric(
    observability: Any,
    name: str,
    value: float | bool | str,
    *,
    data_type: str,
    metadata: dict[str, Any],
    dataset_run_ids: tuple[str, ...] = (),
) -> None:
    score_current_trace = getattr(observability, "score_current_trace", None)
    if callable(score_current_trace):
        try:
            score_current_trace(name, value, data_type=data_type, metadata=metadata)
        except Exception:  # noqa: BLE001 - scoring is advisory
            _log.debug("Langfuse eval score failed for %s", name, exc_info=True)
    _score_langfuse_dataset_runs(
        observability,
        dataset_run_ids,
        name,
        value,
        data_type=data_type,
        metadata=metadata,
    )


def _score_langfuse_dataset_runs(
    observability: Any,
    dataset_run_ids: tuple[str, ...],
    name: str,
    value: float | bool | str,
    *,
    data_type: str,
    metadata: dict[str, Any],
) -> None:
    if not dataset_run_ids:
        return
    score_dataset_run = getattr(observability, "score_dataset_run", None)
    if not callable(score_dataset_run):
        return
    for dataset_run_id in dataset_run_ids:
        try:
            score_dataset_run(
                dataset_run_id,
                name,
                value,
                data_type=data_type,
                metadata={**metadata, "langfuse_dataset_run_id": dataset_run_id},
            )
        except Exception:  # noqa: BLE001 - dataset-run scoring is advisory
            _log.debug("Langfuse eval dataset run score failed for %s on %s", name, dataset_run_id, exc_info=True)


def _langfuse_dataset_run_ids(games: Any) -> tuple[str, ...]:
    if not isinstance(games, list):
        return ()
    seen: set[str] = set()
    dataset_run_ids: list[str] = []
    for game in games:
        if not isinstance(game, dict):
            continue
        value = game.get("langfuse_dataset_run_id")
        if value is None or value == "":
            continue
        dataset_run_id = str(value)
        if dataset_run_id in seen:
            continue
        seen.add(dataset_run_id)
        dataset_run_ids.append(dataset_run_id)
    return tuple(dataset_run_ids)


def _flush_langfuse(observability: Any) -> None:
    flush = getattr(observability, "flush_langfuse", None)
    if not callable(flush):
        return
    try:
        flush()
    except Exception:  # noqa: BLE001 - flushing is advisory
        _log.debug("Langfuse eval flush failed", exc_info=True)


@contextmanager
def _fail_open_langfuse_context(context: Any) -> Any:
    try:
        value = context.__enter__()
    except Exception:  # noqa: BLE001 - tracing is advisory
        _log.debug("Langfuse eval context enter failed", exc_info=True)
        yield None
        return

    try:
        yield value
    except BaseException:
        exc_info = sys.exc_info()
        try:
            suppress = bool(context.__exit__(*exc_info))
        except Exception:  # noqa: BLE001 - tracing cleanup is advisory
            _log.debug("Langfuse eval context exception cleanup failed", exc_info=True)
            suppress = False
        if not suppress:
            raise
    else:
        try:
            context.__exit__(None, None, None)
        except Exception:  # noqa: BLE001 - tracing cleanup is advisory
            _log.debug("Langfuse eval context cleanup failed", exc_info=True)


def _first_present(*values: Any) -> Any | None:
    for value in values:
        if value is not None:
            return value
    return None


async def fairness_node(state: EvalBatchState) -> dict:
    """Compute fairness validation, including cross-batch comparison groups."""
    from app.lib.score import compute_group_fairness, compute_rankable, open_eval_connection

    cfg = state.get("batch_config", {})
    games = state.get("games", [])
    requested_game_count = int(cfg.get("game_count", len(games)) or 0)
    completed = len(valid_completed_games(games))
    valid_rate = completed / requested_game_count if requested_game_count else 0.0

    comparison_group_id = cfg.get("comparison_group_id")
    comparison_type = cfg.get("comparison_type")
    target_role = cfg.get("target_role")

    # Standalone batch (no group) is trivially fair; grouped batches load siblings.
    if not comparison_group_id:
        is_fair = completed > 0
        reason = "standalone batch" if is_fair else "No games in batch"
    else:
        current_batch = {
            "comparison_type": comparison_type,
            "model_id": cfg.get("model_id"),
            "model_config_hash": cfg.get("model_config_hash"),
            "target_role": target_role,
            "target_version_id": cfg.get("target_version_id"),
            "seed_set_id": cfg.get("seed_set_id"),
            "evaluation_set_id": cfg.get("evaluation_set_id"),
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
        game_count=completed,
        valid_game_rate=valid_rate,
        is_fair=is_fair,
    )
    data_sufficient, data_sufficient_reason = _compute_data_sufficient(
        cfg,
        completed=completed,
        requested=requested_game_count,
        valid_game_rate=valid_rate,
    )
    low_error_rate, low_error_rate_reason = _low_error_rates_ok(cfg, state.get("score_summary") or {})
    if state.get("role_version_resolution_failed"):
        rankable = False
        rankable_reason = "role version resolution failed"
    elif rankable and not data_sufficient:
        rankable = False
        rankable_reason = data_sufficient_reason
    elif rankable and not low_error_rate:
        rankable = False
        rankable_reason = low_error_rate_reason
    state["fairness"] = {"is_fair": is_fair, "reason": reason}
    state["valid_game_rate"] = valid_rate
    state["data_sufficient"] = data_sufficient
    state["data_sufficient_reason"] = data_sufficient_reason
    state["low_error_rate"] = low_error_rate
    state["low_error_rate_reason"] = low_error_rate_reason
    state["rankable"] = rankable
    state["rankable_reason"] = rankable_reason
    return state


async def persist_batch_node(state: EvalBatchState) -> dict:
    """Finalize the batch result and persist the batch row + leaderboard entry.

    Writes to PostgreSQL: an evaluation_batches row and a benchmark_leaderboard
    entry in the wolf schema (scope = role_version when a target role/version is
    set, else model).
    Persistence is best-effort and never fails the pipeline.
    """
    from app.util.time import beijing_now_iso

    state["finished_at"] = beijing_now_iso()
    batch_id = state.get("batch_id", "unknown")
    _log.info("persist_batch_node: batch %s complete", batch_id)
    games = state.get("games", [])
    cfg = dict(state.get("batch_config", {}))
    summary = state.get("score_summary")
    terminal_stats = _terminal_stats(games)
    completed = terminal_stats["completed"]
    requested_game_count = int(cfg.get("game_count", len(games)) or 0)
    valid_game_rate = state.get("valid_game_rate")
    if valid_game_rate is None:
        valid_game_rate = completed / requested_game_count if requested_game_count else 0.0
    data_sufficient, data_sufficient_reason = (
        (state["data_sufficient"], state.get("data_sufficient_reason", "ok"))
        if "data_sufficient" in state
        else _compute_data_sufficient(
            cfg,
            completed=completed,
            requested=requested_game_count,
            valid_game_rate=float(valid_game_rate or 0.0),
        )
    )
    low_error_rate, low_error_rate_reason = (
        (state["low_error_rate"], state.get("low_error_rate_reason", "ok"))
        if "low_error_rate" in state
        else _low_error_rates_ok(cfg, summary or {})
    )
    rankable = bool(state.get("rankable", False))
    rankable_reason = str(state.get("rankable_reason", ""))
    if rankable and not data_sufficient:
        rankable = False
        rankable_reason = data_sufficient_reason
    elif rankable and not low_error_rate:
        rankable = False
        rankable_reason = low_error_rate_reason
    state["data_sufficient"] = data_sufficient
    state["data_sufficient_reason"] = data_sufficient_reason
    state["low_error_rate"] = low_error_rate
    state["low_error_rate_reason"] = low_error_rate_reason
    state["valid_game_rate"] = float(valid_game_rate or 0.0)
    state["rankable"] = rankable
    state["rankable_reason"] = rankable_reason

    result = {
        "batch_id": batch_id,
        "config": cfg,
        "game_count": completed,
        "attempted_game_count": len(games),
        "completed": completed,
        "invalid": terminal_stats["invalid"],
        "timeout": terminal_stats["timeout"],
        "abnormal": terminal_stats["abnormal"],
        "errored": terminal_stats["errored"],
        "terminal_stats": terminal_stats,
        "games": games,
        "score_summary": summary,
        "fairness": state.get("fairness"),
        "valid_game_rate": float(valid_game_rate or 0.0),
        "data_sufficient": data_sufficient,
        "data_sufficient_reason": data_sufficient_reason,
        "low_error_rate": low_error_rate,
        "low_error_rate_reason": low_error_rate_reason,
        "rankable": rankable,
        "rankable_reason": rankable_reason,
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
    result["metadata"] = {"storage": "postgresql"}
    _score_langfuse_eval_batch_trace(state, result)
    return state


def _persist_batch(state: EvalBatchState, result: dict[str, Any]) -> list[str]:
    """Save the batch row and a leaderboard entry to PostgreSQL (best-effort)."""
    from app.lib.score import open_eval_connection, persist_leaderboard_entry, save_evaluation_batch

    warnings: list[str] = []
    cfg = dict(state.get("batch_config", {}))
    summary = dict(result.get("score_summary") or {})
    for key, value in _benchmark_metadata_from_config(cfg).items():
        summary.setdefault(key, value)
    result["score_summary"] = summary
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
        leaderboard_summary = dict(summary)
        for key in (
            "benchmark_id",
            "benchmark_version",
            "benchmark_config_hash",
            "evaluation_set_id",
            "seed_set_id",
            "target_type",
            "model_runtime",
        ):
            if cfg.get(key) is not None:
                leaderboard_summary.setdefault(key, cfg.get(key))
        target_side_evidence = _target_side_win_evidence(
            result.get("games", []),
            target_team=_leaderboard_target_team(cfg, target_role),
        )
        for key, value in target_side_evidence.items():
            leaderboard_summary.setdefault(key, value)
        entry = {
            "batch_id": result["batch_id"],
            "comparison_group_id": cfg.get("comparison_group_id"),
            "model_id": cfg.get("model_id"),
            "model_config_hash": cfg.get("model_config_hash"),
            "model_runtime": cfg.get("model_runtime"),
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
            "fallback_rate": summary.get("fallback_rate", 0.0),
            "llm_error_rate": summary.get("llm_error_rate", 0.0),
            "policy_adjusted_rate": summary.get("policy_adjusted_rate", 0.0),
            "target_side_win_rate": summary.get(
                "target_side_win_rate",
                target_side_evidence.get("target_side_win_rate", 0.0),
            ),
            "summary": leaderboard_summary,
        }
        gate = _leaderboard_acceptance_gate(state, result, entry)
        result["leaderboard_gate"] = gate
        if not gate["accepted"]:
            result["leaderboard_skipped_reason"] = gate["reason"]
            return warnings
        entry["data_sufficient"] = gate["data_sufficient"]
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
