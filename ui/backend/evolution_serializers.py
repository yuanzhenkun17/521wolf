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

def _clean_id_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]

def _first_id_list(*values: Any) -> list[str] | None:
    for value in values:
        if isinstance(value, list):
            return _clean_id_list(value)
    return None

def _proposal_status(proposal: dict[str, Any]) -> str:
    status = str(proposal.get("status") or proposal.get("review_status") or "proposed").strip().lower()
    if status in {"accept", "approved", "approve"}:
        return "accepted"
    if status in {"reject", "declined", "deny", "denied"}:
        return "rejected"
    if status in {"", "pending", "reviewing"}:
        return "proposed"
    return status

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
    status = str(proposal.get("preflight_status") or "").strip().lower()
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
    accepted_ids = [
        str(proposal.get("proposal_id"))
        for proposal in proposals
        if _proposal_status(proposal) == "accepted" and proposal.get("proposal_id")
    ]
    rejected_ids = [
        str(proposal.get("proposal_id"))
        for proposal in proposals
        if _proposal_status(proposal) == "rejected" and proposal.get("proposal_id")
    ]
    applied_ids = _first_id_list(run.get("applied_proposal_ids"), stored.get("applied_proposal_ids")) or []
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

def _proposal_review_summary(run: dict[str, Any]) -> dict[str, Any]:
    stored = run.get("proposal_review") if isinstance(run.get("proposal_review"), dict) else {}
    proposals = [item for item in run.get("proposals", []) or [] if isinstance(item, dict)]
    counts: dict[str, int] = {}
    for proposal in proposals:
        status = _proposal_status(proposal)
        counts[status] = counts.get(status, 0) + 1
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
    if stored:
        summary = dict(stored)
        summary.setdefault("schema_version", 1)
        summary.setdefault("total", len(proposals))
        summary.setdefault("generated_count", len(generated_ids))
        summary.setdefault("preflight_passed_count", len(preflight_ids))
        summary.setdefault("accepted_count", len(accepted_ids))
        summary.setdefault("rejected_count", len(rejected_ids))
        summary.setdefault("pending_count", len(pending_ids))
        summary.setdefault("applied_count", len(applied_ids))
        summary.setdefault("generated_proposal_ids", generated_ids)
        summary.setdefault("preflight_passed_proposal_ids", preflight_ids)
        summary.setdefault("accepted_proposal_ids", accepted_ids)
        summary.setdefault("rejected_proposal_ids", rejected_ids)
        summary.setdefault("pending_proposal_ids", pending_ids)
        summary.setdefault("applied_proposal_ids", applied_ids)
        summary.setdefault("counts", counts)
        return summary
    if not proposals:
        status = "empty"
    elif pending_ids:
        status = "partial" if accepted_ids or rejected_ids else "unreviewed"
    elif accepted_ids and rejected_ids:
        status = "mixed"
    elif accepted_ids:
        status = "accepted"
    else:
        status = "rejected"
    if applied_ids:
        status = "applied"
    return {
        "schema_version": 1,
        "status": status,
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
        "counts": counts,
        "updated_at": run.get("last_heartbeat_at") or run.get("finished_at"),
    }

def _proposal_attribution_report(run: dict[str, Any], gate: dict[str, Any] | None = None) -> dict[str, Any]:
    battle = run.get("battle_result") if isinstance(run.get("battle_result"), dict) else {}
    candidates = (
        run.get("proposal_attribution_report"),
        run.get("proposal_attribution"),
        gate.get("proposal_attribution_report") if isinstance(gate, dict) else None,
        gate.get("proposal_attribution") if isinstance(gate, dict) else None,
        battle.get("proposal_attribution_report"),
        battle.get("proposal_attribution"),
    )
    for candidate in candidates:
        if isinstance(candidate, dict):
            return candidate
    return {}

def _evolution_gate_report(run: dict[str, Any]) -> dict[str, Any]:
    battle = run.get("battle_result") if isinstance(run.get("battle_result"), dict) else {}
    gate = run.get("gate_report")
    if not isinstance(gate, dict):
        gate = run.get("promotion_gate")
    if not isinstance(gate, dict):
        gate = battle.get("promotion_gate")
    if not isinstance(gate, dict):
        gate = {}
    decision = str(gate.get("decision") or gate.get("recommendation") or run.get("recommendation") or "").strip()
    if not decision:
        if gate.get("promote_allowed") is True:
            decision = "promote"
        elif gate:
            decision = "review_required"
        else:
            decision = "unknown"
    blocked = gate.get("blocked_reasons")
    if blocked is None:
        blocked = gate.get("reasons")
    metrics = gate.get("metrics") if isinstance(gate.get("metrics"), dict) else {}
    release_gate = gate.get("release_gate") if isinstance(gate.get("release_gate"), dict) else run.get("release_gate")
    proposal_attribution = _proposal_attribution_report(run, gate)
    return {
        "schema_version": 1,
        "decision": decision,
        "promote_allowed": bool(gate.get("promote_allowed", decision == "promote")),
        "release_decision": gate.get("release_decision") or (release_gate or {}).get("decision"),
        "release_gate": release_gate if isinstance(release_gate, dict) else {},
        "policy_versions": gate.get("policy_versions") if isinstance(gate.get("policy_versions"), dict) else {},
        "thresholds": gate.get("thresholds") if isinstance(gate.get("thresholds"), dict) else {},
        "recommendation": gate.get("recommendation") or run.get("recommendation"),
        "blocked_reasons": [str(item) for item in blocked or []],
        "metrics": metrics,
        "scenario_replay": gate.get("scenario_replay") if isinstance(gate.get("scenario_replay"), dict) else {},
        "proposal_attribution": proposal_attribution,
        "trust_bundle_completeness": gate.get("trust_bundle_completeness") if isinstance(gate.get("trust_bundle_completeness"), dict) else {},
        "risk_tags": [str(item) for item in gate.get("risk_tags", []) or []],
        "raw": gate,
    }

def _paired_seed_summary(run: dict[str, Any]) -> dict[str, Any]:
    explicit = run.get("paired_seed_summary")
    if isinstance(explicit, dict):
        return explicit
    pairs = run.get("paired_seed_pairs")
    if not isinstance(pairs, list):
        pairs = run.get("battle_pairs")
    if not isinstance(pairs, list):
        pairs = []
    valid = [
        item for item in pairs
        if isinstance(item, dict)
        and item.get("baseline_rankable", True)
        and item.get("candidate_rankable", True)
    ]
    candidate_wins = len([item for item in valid if isinstance(item, dict) and item.get("winner_side") == "candidate"])
    baseline_wins = len([item for item in valid if isinstance(item, dict) and item.get("winner_side") == "baseline"])
    ties = len([item for item in valid if isinstance(item, dict) and item.get("winner_side") in {"tie", "draw", None, ""}])
    deltas = []
    for item in valid:
        try:
            deltas.append(float(item.get("score_delta")))
        except (TypeError, ValueError):
            continue
    return {
        "schema_version": 1,
        "paired": bool(pairs),
        "pair_count": len([item for item in pairs if isinstance(item, dict)]),
        "valid_pair_count": len(valid),
        "candidate_wins": candidate_wins,
        "baseline_wins": baseline_wins,
        "ties": ties,
        "avg_score_delta": sum(deltas) / len(deltas) if deltas else None,
    }

def _evolution_run_summary(run: dict[str, Any]) -> dict[str, Any]:
    training_games = [game for game in run.get("training_games", []) or [] if isinstance(game, dict)]
    battle_games = [game for game in run.get("battle_games", []) or [] if isinstance(game, dict)]
    gate_report = _evolution_gate_report(run)
    paired_summary = _paired_seed_summary(run)
    result = run.get("result") if isinstance(run.get("result"), dict) else {}
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
            "published_version_id",
            "published_release_stage",
            "release_stage",
            "promoted_version_id",
            "promotion_gate",
            "gate_report",
            "release_gate",
            "release_decision",
            "trust_bundle",
            "scenario_replay_report",
            "scenario_replay_summary",
            "proposal_attribution_report",
            "paired_seed_summary",
            "proposal_review",
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
            "published_version_id": run.get("published_version_id") or result.get("published_version_id"),
            "published_release_stage": run.get("published_release_stage") or result.get("published_release_stage"),
            "release_stage": run.get("release_stage") or result.get("published_release_stage") or result.get("release_stage"),
            "promoted_version_id": run.get("promoted_version_id") or result.get("promoted_version_id"),
            "promotion_gate": run.get("promotion_gate") if isinstance(run.get("promotion_gate"), dict) else gate_report["raw"],
            "gate_report": gate_report,
            "release_gate": run.get("release_gate") if isinstance(run.get("release_gate"), dict) else gate_report.get("release_gate", {}),
            "release_decision": run.get("release_decision") or gate_report.get("release_decision"),
            "trust_bundle": run.get("trust_bundle") if isinstance(run.get("trust_bundle"), dict) else {},
            "scenario_replay_report": run.get("scenario_replay_report") if isinstance(run.get("scenario_replay_report"), dict) else {},
            "scenario_replay_summary": run.get("scenario_replay_summary") if isinstance(run.get("scenario_replay_summary"), dict) else {},
            "proposal_attribution_report": _proposal_attribution_report(run, gate_report["raw"]),
            "paired_seed_summary": paired_summary,
            "proposal_review": _proposal_review_summary(run),
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
            "benchmark",
            "target_type",
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
            "run_plan",
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
