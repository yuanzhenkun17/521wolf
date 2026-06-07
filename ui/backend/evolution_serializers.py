"""Evolution and benchmark response shaping helpers for the UI backend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ui.backend.game_serializers import _archive_payload, _normalize_decision, _normalize_event
from ui.backend.task_state import _background_source

def _sample_game_history_id(
    run_id: str | None,
    game: dict[str, Any],
    *,
    phase: str,
    side: str | None,
) -> str | None:
    if game.get("history_game_id"):
        return str(game["history_game_id"])
    game_id = game.get("game_id") or game.get("id")
    game_dir = game.get("game_dir")
    if not run_id:
        return None
    path = Path(str(game_dir)) if game_dir else None
    game_dir_name = path.name if path is not None else str(game_id or "")
    phase_dir_name = path.parent.name if path is not None else ""
    if not phase_dir_name:
        if phase == "training":
            phase_dir_name = "training"
        elif side in {"baseline", "candidate"}:
            phase_dir_name = f"battle_{side}"
        else:
            phase_dir_name = phase
    if not game_dir_name:
        return None
    return f"evolution:{run_id}:{phase_dir_name}:{game_dir_name}"


def _sample_game_summary(game: dict[str, Any], *, run_id: str | None, phase: str, side: str | None) -> dict[str, Any]:
    history_game_id = _sample_game_history_id(run_id, game, phase=phase, side=side)
    return {
        "game_id": game.get("game_id") or game.get("id"),
        "id": game.get("id") or game.get("game_id"),
        "history_game_id": history_game_id,
        "replay_available": bool(history_game_id),
        "replay_unavailable_reason": None if history_game_id else "缺少可定位的样本局 ID",
        "status": game.get("status", "completed"),
        "seed": game.get("seed"),
        "winner": game.get("winner"),
        "phase": game.get("phase") or phase,
        "side": game.get("side") or side,
        "event_count": game.get("event_count", len(game.get("events", []) or [])),
        "decision_count": game.get("decision_count", len(game.get("decisions", []) or [])),
        "day": game.get("day", game.get("days", 0)),
        "days": game.get("days", game.get("day", 0)),
        "in_progress": game.get("in_progress", False),
    }

def _count_games(value: Any) -> int:
    if isinstance(value, list):
        return len([item for item in value if isinstance(item, dict)])
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0

def _overall_progress(
    entity: dict[str, Any],
    *,
    training_games: list[dict[str, Any]] | None = None,
    battle_games: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    progress = entity.get("progress") if isinstance(entity.get("progress"), dict) else {}
    training_total = _count_games(entity.get("training_game_count") or entity.get("training_requested") or entity.get("config", {}).get("training_games"))
    battle_total = _count_games(entity.get("battle_game_count") or entity.get("battle_requested") or entity.get("config", {}).get("battle_games"))
    training_completed = _count_games(entity.get("training_completed"))
    battle_completed = _count_games(entity.get("battle_completed"))
    if training_games is not None and not training_completed:
        training_completed = len(training_games)
    if battle_games is not None and not battle_completed:
        battle_completed = len(battle_games)
    if not training_total and training_games is not None:
        training_total = len(training_games)
    if not battle_total and battle_games is not None:
        battle_total = len(battle_games)
    stage = str(entity.get("current_stage") or progress.get("stage") or entity.get("status") or "")
    terminal = str(entity.get("status") or "").lower() in {"reviewing", "promoted", "rejected", "failed", "completed", "cancelled", "interrupted"}
    weighted_total = training_total + (battle_total * 2)
    weighted_completed = training_completed + battle_completed
    if weighted_total > 0:
        percent = weighted_completed / weighted_total
    elif terminal:
        percent = 1.0
    else:
        percent = _safe_float(progress.get("percent"), 0.0)
    if terminal and str(entity.get("status") or "").lower() not in {"failed", "cancelled", "interrupted"}:
        percent = max(percent, 1.0)
    return {
        "stage": stage,
        "percent": max(0.0, min(1.0, float(percent))),
        "training_completed": training_completed,
        "training_total": training_total,
        "battle_completed": battle_completed,
        "battle_total": battle_total * 2,
        "battle_requested_per_side": battle_total,
        "updated_at": entity.get("last_heartbeat_at") or progress.get("updated_at"),
    }

def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

def _evolution_battle_result_summary(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    keys = (
        "target_team",
        "candidate_hash",
        "baseline_hash",
        "candidate_win_rate",
        "baseline_win_rate",
        "win_rate_delta",
        "significant",
        "significance",
        "skipped",
        "reason",
        "error",
        "baseline",
        "candidate",
        "seeds",
        "completed",
        "errored",
        "game_count",
    )
    return {key: result.get(key) for key in keys if key in result}

def _evolution_run_summary(run: dict[str, Any]) -> dict[str, Any]:
    training_games = [game for game in run.get("training_games", []) or [] if isinstance(game, dict)]
    battle_games = [game for game in run.get("battle_games", []) or [] if isinstance(game, dict)]
    summary = {
        key: run.get(key)
        for key in (
            "kind",
            "schema_version",
            "run_id",
            "batch_id",
            "source",
            "role",
            "roles",
            "status",
            "stop_requested",
            "cancelled",
            "cancelled_at",
            "interrupted",
            "failed",
            "started_at",
            "finished_at",
            "last_heartbeat_at",
            "interrupted_at",
            "parent_hash",
            "candidate_hash",
            "current_stage",
            "progress",
            "overall_progress",
            "stage_progress",
            "diagnostics",
            "recommendation",
            "error",
        )
        if key in run
    }
    summary.update(
        {
            "source": "evolution",
            "config": run.get("config", {}),
            "training_game_count": int(run.get("training_game_count") or len(training_games)),
            "training_completed": int(run.get("training_completed") or len(training_games)),
            "battle_game_count": int(run.get("battle_game_count") or len(battle_games)),
            "battle_completed": int(run.get("battle_completed") or len(battle_games)),
            "proposal_count": len(run.get("proposals", []) or []),
            "diff_count": len(run.get("diff", []) or []),
            "error_count": len(run.get("errors", []) or []),
            "overall_progress": run.get("overall_progress") if isinstance(run.get("overall_progress"), dict) else _overall_progress(run, training_games=training_games, battle_games=battle_games),
            "stage_progress": run.get("stage_progress") if isinstance(run.get("stage_progress"), dict) else run.get("progress", {}),
            "battle_result": _evolution_battle_result_summary(run.get("battle_result")),
        }
    )
    return summary

def _benchmark_result_summary(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    return {
        key: result.get(key)
        for key in (
            "batch_id",
            "config",
            "game_count",
            "completed",
            "errored",
            "score_summary",
            "fairness",
            "rankable",
            "rankable_reason",
            "started_at",
            "finished_at",
            "candidate_hash",
            "baseline_hash",
            "candidate_win_rate",
        )
        if key in result
    }

def _evolution_batch_summary(batch: dict[str, Any]) -> dict[str, Any]:
    summary = {
        key: batch.get(key)
        for key in (
            "kind",
            "schema_version",
            "batch_id",
            "source",
            "roles",
            "status",
            "cancelled",
            "cancelled_at",
            "interrupted",
            "failed",
            "started_at",
            "finished_at",
            "last_heartbeat_at",
            "interrupted_at",
            "current_stage",
            "progress",
            "overall_progress",
            "stage_progress",
            "diagnostics",
            "runs",
            "run_summaries",
            "config",
            "error",
            "stop_requested",
        )
        if key in batch
    }
    summary["source"] = _background_source(batch)
    summary["result"] = _benchmark_result_summary(batch.get("result"))
    summary["overall_progress"] = batch.get("overall_progress") if isinstance(batch.get("overall_progress"), dict) else _overall_progress(batch)
    summary["stage_progress"] = batch.get("stage_progress") if isinstance(batch.get("stage_progress"), dict) else batch.get("progress", {})
    return summary

def _evolution_games_for_query(
    run: dict[str, Any],
    *,
    phase: str,
    side: str | None,
    include_details: bool = False,
) -> list[dict[str, Any]]:
    run_id = str(run.get("run_id") or "")
    games = run.get("training_games", []) if phase == "training" else run.get("battle_games", [])
    if phase != "training" and side and any(isinstance(game, dict) and game.get("side") for game in games or []):
        games = [game for game in games or [] if isinstance(game, dict) and game.get("side") == side]
    normalized: list[dict[str, Any]] = []
    for game in games or []:
        if not isinstance(game, dict):
            continue
        if not include_details:
            normalized.append(_sample_game_summary(game, run_id=run_id, phase=phase, side=side))
            continue
        history_game_id = _sample_game_history_id(run_id, game, phase=phase, side=side)
        normalized.append(
            {
                **game,
                "history_game_id": history_game_id,
                "replay_available": bool(history_game_id),
                "replay_unavailable_reason": None if history_game_id else "缺少可定位的样本局 ID",
                "phase": game.get("phase") or phase,
                "side": game.get("side") or side,
                "event_count": game.get("event_count", len(game.get("events", []) or [])),
                "decision_count": game.get("decision_count", len(game.get("decisions", []) or [])),
                "day": game.get("day", game.get("days", 0)),
            }
        )
    return normalized

def _sample_game_archive_payload(
    run_id: str,
    game_id: str,
    game: dict[str, Any],
    *,
    phase: str,
    side: str | None,
) -> dict[str, Any]:
    events = [_normalize_event(event) for event in game.get("events", []) or []]
    decisions = [
        _normalize_decision(decision, index)
        for index, decision in enumerate(game.get("decisions", []) or [], start=1)
    ]
    snapshot = {
        **game,
        "game_id": game.get("game_id") or game_id,
        "winner": game.get("winner"),
        "day": game.get("day", game.get("days", 0)),
        "events": events,
        "decisions": decisions,
        "review": game.get("review"),
        "config": {
            **(game.get("config") if isinstance(game.get("config"), dict) else {}),
            "run_id": run_id,
            "phase": phase,
            "side": side,
            "seed": game.get("seed"),
        },
    }
    archive = _archive_payload(str(snapshot["game_id"]), snapshot)
    archive.update(
        {
            "kind": "role_evolution_game_archive",
            "run_id": run_id,
            "phase": phase,
            "side": side,
            "history_game_id": _sample_game_history_id(run_id, game, phase=phase, side=side),
        }
    )
    archive["replay_available"] = bool(archive["history_game_id"])
    archive["replay_unavailable_reason"] = None if archive["history_game_id"] else "缺少可定位的样本局 ID"
    return archive

def _evolution_sse_event(status: Any) -> str:
    status_text = str(status or "").lower()
    if status_text in {"reviewing", "promoted", "rejected", "failed", "completed", "interrupted"}:
        return status_text
    return "progress"
