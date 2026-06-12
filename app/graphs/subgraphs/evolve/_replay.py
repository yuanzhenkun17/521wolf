"""Scenario replay node and helpers for the evolution pipeline."""

from __future__ import annotations

import logging
from typing import Any

from app.graphs.shared.state import EvolveState
from app.lib.evolve import EvolutionStatus, normalize_run_id

from ._shared import _mark_stage

_log = logging.getLogger(__name__)


async def scenario_replay_node(state: EvolveState) -> dict:
    """Freeze scenario snapshots and replay baseline vs candidate decisions.

    When the state carries a model, runs real LLM-based decision replay for
    each scenario snapshot. Falls back to contract-only mode when no model
    is available.
    """
    _log.info("scenario_replay: role=%s", state.get("role"))
    _mark_stage(state, "scenario_replay", status=EvolutionStatus.SCENARIO_REPLAY.value)
    cfg = state.get("config", {})
    limit = int(cfg.get("scenario_replay_max_snapshots", cfg.get("scenario_max_snapshots", 3)) or 0)
    snapshots = _build_scenario_snapshots(state, limit=max(0, limit))
    model = state.get("model")
    report = await _build_scenario_replay_report(state, snapshots, model=model)
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


async def _build_scenario_replay_report(
    state: EvolveState,
    snapshots: list[dict[str, Any]],
    *,
    model: Any = None,
) -> dict[str, Any]:
    use_real_replay = model is not None
    rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        if use_real_replay:
            try:
                row = await _replay_scenario_result(state, snapshot, model=model)
            except Exception as exc:  # noqa: BLE001 — degrade to contract-only on failure
                _log.warning("scenario_replay: real replay failed for %s: %s", snapshot.get("scenario_id"), exc, exc_info=True)
                row = _contract_only_scenario_result(snapshot)
                row["replay_error"] = str(exc)
        else:
            row = _contract_only_scenario_result(snapshot)
        rows.append(row)
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
    elif use_real_replay:
        verdict = "replayed"
    else:
        verdict = "contract_ready"
    return {
        "schema_version": "scenario_replay_report_v1",
        "execution_mode": "llm_replay" if use_real_replay else "contract_only",
        "status": "replayed" if use_real_replay and rows else ("contract_ready" if rows else "skipped"),
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


async def _replay_scenario_result(
    state: EvolveState,
    snapshot: dict[str, Any],
    *,
    model: Any,
) -> dict[str, Any]:
    """Run real LLM replay for a single scenario snapshot."""
    from app.services.chain import run_decision_chain

    messages = _build_replay_messages(snapshot)
    baseline_decision_raw = snapshot.get("actor_observation", {})
    baseline_choice = baseline_decision_raw.get("choice") or baseline_decision_raw.get("target")
    try:
        candidate_raw = await run_decision_chain(model, messages=messages)
    except Exception as exc:  # noqa: BLE001
        _log.warning("scenario_replay: LLM call failed for %s: %s", snapshot.get("scenario_id"), exc)
        return {
            "scenario_id": snapshot.get("scenario_id"),
            "source_game_id": snapshot.get("source_game_id"),
            "role": snapshot.get("role"),
            "phase": snapshot.get("phase"),
            "baseline_decision": {"choice": baseline_choice, "source": "training_record"},
            "candidate_decision": None,
            "rubric_score_delta": None,
            "policy_violations": [],
            "private_info_leaks": [],
            "decision_issue_delta": None,
            "verdict": "replay_error",
            "contract_missing": [],
            "replay_error": str(exc),
        }
    candidate_parsed = _parse_replay_decision(candidate_raw)
    candidate_choice = candidate_parsed.get("choice") or candidate_parsed.get("target")
    matches = _choices_match(baseline_choice, candidate_choice)
    score_delta = 0.0 if matches else -1.0
    role = str(snapshot.get("role") or "")
    return {
        "scenario_id": snapshot.get("scenario_id"),
        "source_game_id": snapshot.get("source_game_id"),
        "role": role,
        "phase": snapshot.get("phase"),
        "baseline_decision": {"choice": baseline_choice, "source": "training_record"},
        "candidate_decision": {"choice": candidate_choice, "raw_output": candidate_raw[:500], "source": "llm_replay"},
        "rubric_score_delta": score_delta,
        "policy_violations": [],
        "private_info_leaks": [],
        "decision_issue_delta": None,
        "verdict": "replayed",
        "contract_missing": [],
    }


def _build_replay_messages(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    """Build decision-chain messages from a frozen scenario snapshot."""
    role = str(snapshot.get("role") or "unknown")
    phase = str(snapshot.get("phase") or "unknown")
    day = snapshot.get("day", "?")
    action_type = str(snapshot.get("action_type") or "speak")
    actor_id = snapshot.get("actor_id", "?")
    event_prefix = snapshot.get("public_event_prefix") or []
    observation = snapshot.get("actor_observation") or {}
    legal_actions = snapshot.get("legal_actions") or []
    players_state = snapshot.get("players_public_state") or []
    skill_inventory = snapshot.get("skill_inventory") or {}

    system_parts = [
        f"你是一个狼人杀玩家，角色是{role}，坐在{actor_id}号位。",
        f"当前是第{day}天，阶段：{phase}。",
        f"你需要做出的决策类型：{action_type}。",
    ]
    if skill_inventory.get("active_skills"):
        system_parts.append(f"可用技能：{', '.join(str(s) for s in skill_inventory['active_skills'][:5])}")
    system_msg = "\n".join(system_parts)

    context_parts = []
    if event_prefix:
        context_parts.append("## 最近事件")
        for event in event_prefix[:8]:
            text = event.get("text") or event.get("summary") or str(event)
            context_parts.append(f"- {text}")
    if players_state:
        context_parts.append("\n## 玩家状态")
        for p in players_state[:12]:
            seat = p.get("seat") or p.get("id") or "?"
            status = "存活" if p.get("alive") else "死亡"
            context_parts.append(f"- {seat}号: {status}")
    if observation.get("reason"):
        context_parts.append(f"\n## 你的判断\n{observation['reason']}")
    if legal_actions:
        context_parts.append(f"\n## 合法动作\n{', '.join(str(a) for a in legal_actions[:6])}")
    context_msg = "\n".join(context_parts) if context_parts else "无上下文信息"

    user_msg = f"{context_msg}\n\n请输出你的决策（JSON格式，包含 choice/target 和 reason 字段）。"
    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def _parse_replay_decision(raw: str) -> dict[str, Any]:
    """Extract a structured decision from LLM raw output."""
    from app.util.text import extract_json

    try:
        parsed = extract_json(raw)
        if isinstance(parsed, dict):
            return parsed
    except (ValueError, TypeError):
        pass
    return {"choice": raw.strip()[:100], "raw": raw[:200]}


def _choices_match(baseline: Any, candidate: Any) -> bool:
    """Check if baseline and candidate decisions match."""
    if baseline is None or candidate is None:
        return False
    b = str(baseline).strip().lower()
    c = str(candidate).strip().lower()
    return b == c
