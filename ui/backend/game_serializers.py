"""Game response shaping helpers for the UI backend."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.util.json import to_jsonable
from engine import Role
from storage.public_events import is_public_event, public_events_only, sanitize_public_payload


_WOLF_ROLES = {"werewolf", "white_wolf_king", "狼人", "白狼王"}
_HIDDEN_ACTION_EVENT_TYPES = {
    "action_request",
    "action_response",
    "default_action",
    "guard_protect",
    "guard_result",
    "hunter_shoot",
    "hunter_no_shot",
    "seer_check",
    "seer_result",
    "werewolf_kill",
    "werewolf_result",
    "witch_act",
    "witch_result",
}
_REDACTED_TERMINAL_GAME_STATUSES = {"failed", "cancelled", "interrupted"}
_PUBLIC_DECISION_ACTIONS = {
    "exile_vote",
    "last_word",
    "pk_speak",
    "pk_vote",
    "sheriff_badge",
    "sheriff_run",
    "sheriff_speak",
    "sheriff_vote",
    "sheriff_withdraw",
    "speak",
    "speech_order",
}


def _int_or_none(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _is_completed_game(snapshot: dict[str, Any]) -> bool:
    status = str(snapshot.get("status") or "").lower()
    if status in _REDACTED_TERMINAL_GAME_STATUSES:
        return False
    return bool(snapshot.get("winner")) or status == "completed"


def _is_player_view_snapshot(snapshot: dict[str, Any]) -> bool:
    return (
        str(snapshot.get("mode") or "") == "play"
        and _int_or_none(snapshot.get("human_player_id")) is not None
        and not _is_completed_game(snapshot)
    )


def _role_value(player: dict[str, Any] | None) -> str:
    if not isinstance(player, dict):
        return ""
    return str(player.get("role") or player.get("role_hint") or "")


def _is_wolf_role(role: str) -> bool:
    return role in _WOLF_ROLES


def _visible_role_ids(snapshot: dict[str, Any]) -> set[int]:
    human_id = _int_or_none(snapshot.get("human_player_id"))
    if human_id is None:
        return set()
    players = [p for p in snapshot.get("players") or [] if isinstance(p, dict)]
    by_id = {_int_or_none(player.get("id")): player for player in players}
    visible = {human_id}
    human = by_id.get(human_id)
    if human and _is_wolf_role(_role_value(human)):
        visible.update(
            player_id
            for player_id, player in by_id.items()
            if player_id is not None and _is_wolf_role(_role_value(player))
        )

    pending = snapshot.get("pending_human_action") if isinstance(snapshot.get("pending_human_action"), dict) else {}
    observation = pending.get("observation") if isinstance(pending.get("observation"), dict) else {}
    known_roles = observation.get("known_roles") if isinstance(observation.get("known_roles"), dict) else {}
    for raw_id in known_roles:
        player_id = _int_or_none(raw_id)
        if player_id is not None:
            visible.add(player_id)
    return visible


def _sanitize_player_for_view(player: dict[str, Any], *, visible_role_ids: set[int]) -> dict[str, Any]:
    player_id = _int_or_none(player.get("id"))
    if player_id in visible_role_ids:
        return dict(player)
    redacted = dict(player)
    redacted["role"] = "unknown"
    redacted["role_hint"] = "未知"
    redacted["team"] = "unknown"
    redacted["role_state"] = {}
    return redacted


def _visibility(event: dict[str, Any]) -> str:
    visibility = event.get("visibility")
    if visibility:
        return str(visibility).lower()
    return "public" if is_public_event(event) else "private"


def _event_type(event: dict[str, Any]) -> str:
    return str(event.get("event_type") or event.get("type") or event.get("action") or event.get("action_type") or "")


def _event_actor(event: dict[str, Any]) -> int | None:
    return _int_or_none(event.get("actor_id", event.get("actor")))


def _event_target(event: dict[str, Any]) -> int | None:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return _int_or_none(
        event.get("target_id")
        or event.get("target")
        or payload.get("target_id")
        or payload.get("target")
    )


def _event_visible_to_player(event: dict[str, Any], *, human_player_id: int) -> bool:
    visibility = _visibility(event)
    actor_id = _event_actor(event)
    event_type = _event_type(event)
    if visibility == "god":
        return False
    if visibility == "private":
        return actor_id == human_player_id
    if event_type in _HIDDEN_ACTION_EVENT_TYPES and actor_id != human_player_id:
        return False
    return True


def _sanitize_public_payload(event: dict[str, Any], *, keep_private: bool) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    if keep_private:
        return dict(payload)
    return sanitize_public_payload(event)


def _sanitize_event_for_player_view(event: dict[str, Any], *, human_player_id: int) -> dict[str, Any] | None:
    normalized = _normalize_event(event)
    if not _event_visible_to_player(normalized, human_player_id=human_player_id):
        return None
    keep_private = _visibility(normalized) == "private" and _event_actor(normalized) == human_player_id
    sanitized = dict(normalized)
    sanitized["payload"] = _sanitize_public_payload(normalized, keep_private=keep_private)
    sanitized["public"] = _visibility(normalized) != "private"
    return sanitized


def _decision_action(decision: dict[str, Any]) -> str:
    return str(decision.get("action") or decision.get("action_type") or "")


def _decision_actor(decision: dict[str, Any]) -> int | None:
    return _int_or_none(decision.get("actor_id", decision.get("player_id")))


def _sanitize_decision_for_player_view(
    decision: dict[str, Any],
    *,
    human_player_id: int,
    visible_role_ids: set[int],
    index: int,
) -> dict[str, Any] | None:
    normalized = _normalize_decision(decision, index)
    actor_id = _decision_actor(normalized)
    action = _decision_action(normalized)
    if actor_id != human_player_id and action not in _PUBLIC_DECISION_ACTIONS:
        return None

    public_summary = normalized.get("public_summary") or normalized.get("public_text") or normalized.get("text") or ""
    role = normalized.get("role") if actor_id in visible_role_ids else "unknown"
    return {
        "index": normalized.get("index", index),
        "id": normalized.get("id") or normalized.get("decision_id") or f"decision_{index}",
        "decision_id": normalized.get("decision_id") or normalized.get("id") or f"decision_{index}",
        "day": normalized.get("day", 0),
        "phase": normalized.get("phase", ""),
        "actor_id": actor_id,
        "player_id": normalized.get("player_id", actor_id),
        "target_id": normalized.get("target_id"),
        "action": action,
        "action_type": action,
        "role": role,
        "public_summary": public_summary,
        "reason": public_summary,
        "source": normalized.get("source", "llm"),
        "confidence": normalized.get("confidence", 0.0),
    }


def _sanitize_pending_for_player_view(pending: Any, *, human_player_id: int) -> dict[str, Any] | None:
    if not isinstance(pending, dict):
        return None
    player_id = _int_or_none(pending.get("player_id"))
    if player_id is not None and player_id != human_player_id:
        return None
    return dict(pending)


def _sanitize_vote_tally_for_player_view(
    snapshot: dict[str, Any],
    decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return _vote_tally(
        decisions,
        current_day=snapshot.get("day"),
        current_phase=snapshot.get("phase"),
        pending_action=snapshot.get("pending_human_action") or snapshot.get("pending_action"),
    )


def _player_view_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return the browser-safe view for an in-progress human player game."""
    if not _is_player_view_snapshot(snapshot):
        return snapshot

    human_player_id = _int_or_none(snapshot.get("human_player_id"))
    if human_player_id is None:
        return snapshot

    visible_role_ids = _visible_role_ids(snapshot)
    players = [
        _sanitize_player_for_view(player, visible_role_ids=visible_role_ids)
        for player in snapshot.get("players") or []
        if isinstance(player, dict)
    ]
    events = [
        sanitized
        for event in snapshot.get("events") or snapshot.get("logs") or []
        if isinstance(event, dict)
        for sanitized in [_sanitize_event_for_player_view(event, human_player_id=human_player_id)]
        if sanitized is not None
    ]
    decisions = [
        sanitized
        for index, decision in enumerate(snapshot.get("decisions") or [], start=1)
        if isinstance(decision, dict)
        for sanitized in [
            _sanitize_decision_for_player_view(
                decision,
                human_player_id=human_player_id,
                visible_role_ids=visible_role_ids,
                index=index,
            )
        ]
        if sanitized is not None
    ]
    pending = _sanitize_pending_for_player_view(snapshot.get("pending_human_action"), human_player_id=human_player_id)

    safe = dict(snapshot)
    safe["players"] = players
    safe["logs"] = events
    safe["events"] = events
    safe["decisions"] = decisions
    safe["pending_human_action"] = pending
    safe["pending_action"] = _ui_pending_action(pending)
    safe["waiting_for"] = _waiting_for_pending(pending)
    safe["current_speaker_id"] = pending.get("player_id") if pending and safe["waiting_for"] == "speech" else None
    safe["vote_tally"] = _sanitize_vote_tally_for_player_view(snapshot, decisions)
    safe["review"] = None
    return safe


def _player_view_sse_payload(event_name: str, payload: Any, snapshot: dict[str, Any]) -> Any | None:
    if not _is_player_view_snapshot(snapshot):
        return payload
    human_player_id = _int_or_none(snapshot.get("human_player_id"))
    if human_player_id is None:
        return payload
    if event_name == "log" and isinstance(payload, dict):
        return _sanitize_event_for_player_view(payload, human_player_id=human_player_id)
    if event_name == "decision" and isinstance(payload, dict):
        index = _int_or_none(payload.get("index") or payload.get("sequence")) or 1
        return _sanitize_decision_for_player_view(
            payload,
            human_player_id=human_player_id,
            visible_role_ids=_visible_role_ids(snapshot),
            index=index,
        )
    if event_name == "done" and isinstance(payload, dict):
        return _player_view_snapshot(payload)
    if event_name == "decision_needed":
        return _sanitize_pending_for_player_view(payload, human_player_id=human_player_id)
    return payload

def _engine_events(engine: Any) -> list[dict[str, Any]]:
    logger = getattr(engine, "logger", None)
    entries = getattr(logger, "entries", []) if logger is not None else []
    return [to_jsonable(entry.to_dict() if hasattr(entry, "to_dict") else entry) for entry in entries]

def _recorder_decisions(recorder: Any) -> list[dict[str, Any]]:
    records = getattr(recorder, "records", [])
    return [to_jsonable(record.to_dict() if hasattr(record, "to_dict") else record) for record in records]

def _review_live_result(session: Any) -> dict[str, Any]:
    try:
        from app.lib.review import analyze_game

        decisions_by_player: dict[int, list[dict[str, Any]]] = {}
        for decision in _recorder_decisions(session.recorder):
            player_id = decision.get("player_id")
            if player_id is None:
                continue
            try:
                decisions_by_player.setdefault(int(player_id), []).append(decision)
            except (TypeError, ValueError):
                continue

        roles = {pid: player.role for pid, player in session.engine.state.players.items()}
        review = analyze_game(
            game_log=_engine_events(session.engine),
            agent_decisions=decisions_by_player,
            roles=roles,
            winner_team=session.winner,
            game_id=session.game_id,
        )
        return _frontend_review(review.to_dict(), events=_engine_events(session.engine))
    except Exception as exc:  # pragma: no cover - review should not break game completion
        return {
            "game_id": session.game_id,
            "review_status": "failed",
            "error": str(exc),
            "diagnostics": [
                {
                    "kind": "review_error",
                    "stage": "live_review.analyze_game",
                    "message": str(exc),
                    "exception_type": type(exc).__name__,
                }
            ],
        }

def _pending_action_payload(request: Any) -> dict[str, Any]:
    observation = request.observation
    metadata = to_jsonable(dict(getattr(request, "metadata", {}) or {}))
    action_type = request.action_type.value if hasattr(request.action_type, "value") else str(request.action_type)
    phase = request.phase.value if hasattr(request.phase, "value") else str(request.phase)
    role_state = to_jsonable(getattr(observation, "role_state", {}) or {})
    target_required = _target_required(action_type)
    return {
        "player_id": request.player_id,
        "action_type": action_type,
        "phase": phase,
        "day": getattr(observation, "day", 0),
        "candidates": list(getattr(request, "candidates", ()) or ()),
        "candidate_ids": list(getattr(request, "candidates", ()) or ()),
        "retry_count": getattr(request, "retry_count", 0),
        "target_required": target_required,
        "allow_no_target": not target_required,
        "metadata": metadata,
        "prompt": _action_prompt(action_type),
        "observation": {
            "player_id": getattr(observation, "player_id", request.player_id),
            "self_role": _enum_value(getattr(observation, "self_role", "")),
            "phase": _enum_value(getattr(observation, "phase", phase)),
            "day": getattr(observation, "day", 0),
            "alive_players": list(getattr(observation, "alive_players", ()) or ()),
            "dead_players": list(getattr(observation, "dead_players", ()) or ()),
            "sheriff_id": getattr(observation, "sheriff_id", None),
            "known_roles": {str(pid): _enum_value(role) for pid, role in getattr(observation, "known_roles", {}).items()},
            "seer_checks": {str(pid): _enum_value(team) for pid, team in getattr(observation, "seer_checks", {}).items()},
            "role_state": role_state,
            "metadata": to_jsonable(getattr(observation, "metadata", {}) or {}),
        },
    }

def _waiting_for_pending(pending: dict[str, Any] | None) -> str:
    if not pending:
        return "none"
    action_type = str(pending.get("action_type") or pending.get("type") or "")
    if action_type in {"speak", "sheriff_speak", "pk_speak", "last_word"}:
        return "speech"
    if action_type in {"exile_vote", "pk_vote", "sheriff_vote"}:
        return "vote"
    return "action"

def _ui_pending_action(pending: dict[str, Any] | None) -> dict[str, Any] | None:
    if not pending or _waiting_for_pending(pending) == "speech":
        return None
    action_type = str(pending.get("action_type") or pending.get("type") or "")
    metadata = pending.get("metadata") if isinstance(pending.get("metadata"), dict) else {}
    candidate_ids = list(pending.get("candidate_ids") or pending.get("candidates") or [])
    raw_target_required = pending.get("target_required")
    target_required = _target_required(action_type) if raw_target_required is None else bool(raw_target_required)
    return {
        "type": action_type,
        "prompt": pending.get("prompt") or _action_prompt(action_type),
        "candidate_ids": candidate_ids,
        "target_required": target_required,
        "allow_no_target": not target_required,
        "options": {
            **metadata,
            "target_required": target_required,
            "allow_no_target": not target_required,
            "choices": _choice_options(action_type, metadata),
        },
    }

def _normalize_roles(raw: Any) -> dict[int, str]:
    if not isinstance(raw, dict):
        return {}
    roles: dict[int, str] = {}
    for player_id, role in raw.items():
        try:
            roles[int(player_id)] = role.value if hasattr(role, "value") else str(role)
        except (TypeError, ValueError):
            continue
    return roles

def _normalize_event(event: dict[str, Any]) -> dict[str, Any]:
    event = to_jsonable(event)
    event_type = event.get("event_type") or event.get("type") or ""
    actor = event.get("actor_id", event.get("actor"))
    target = event.get("target_id", event.get("target"))
    return {
        **event,
        "event_type": event_type,
        "type": event_type,
        "sequence": event.get("sequence", event.get("index", 0)),
        "actor_id": actor,
        "target_id": target,
        "speaker": event.get("speaker") or (f"{actor}号" if actor else "法官"),
        "visibility": _visibility(event),
        "message": event.get("message", ""),
    }

def _normalize_decision(decision: dict[str, Any], index: int) -> dict[str, Any]:
    decision = to_jsonable(decision)
    action = decision.get("action") or decision.get("action_type") or ""
    actor_id = decision.get("actor_id", decision.get("player_id"))
    target_id = decision.get("target_id", decision.get("selected_target"))
    public_summary = decision.get("public_summary") or decision.get("public_text") or decision.get("text") or ""
    reason = decision.get("reason") or decision.get("private_reasoning") or public_summary
    selected_skills = decision.get("selected_skills") or []
    return {
        **decision,
        "index": decision.get("index", index),
        "id": decision.get("id") or decision.get("decision_id") or f"decision_{index}",
        "actor_id": actor_id,
        "player_id": decision.get("player_id", actor_id),
        "target_id": target_id,
        "action": action,
        "action_type": action,
        "public_summary": public_summary,
        "reason": reason,
        "selected_skill": decision.get("selected_skill") or (selected_skills[0] if selected_skills else None),
        "memory_refs": decision.get("memory_refs") or decision.get("memory_summary") or [],
        "belief_snapshot": decision.get("belief_snapshot") or {},
        "source": decision.get("source", "llm"),
        "confidence": decision.get("confidence", 0.0),
    }

def _frontend_review(raw: Any, *, events: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not raw:
        return None
    if not isinstance(raw, dict):
        return {"data": raw}
    review = to_jsonable(dict(raw))
    agent_scores = review.get("agent_scores") if isinstance(review.get("agent_scores"), dict) else {}
    player_evaluations: list[dict[str, Any]] = []
    for pid, score in sorted(agent_scores.items(), key=lambda item: int(item[0]) if str(item[0]).isdigit() else 999):
        if not isinstance(score, dict):
            continue
        scores = score.get("scores") if isinstance(score.get("scores"), dict) else {}
        player_evaluations.append(
            {
                "player_seat": int(pid) if str(pid).isdigit() else pid,
                "role": score.get("role", ""),
                "speech_score": _score_ratio(scores.get("speech_quality")),
                "vote_score": _score_ratio(scores.get("vote_accuracy")),
                "skill_score": _score_ratio(scores.get("skill_accuracy")),
                "logic_score": None,
                "information_score": None,
                "team_score": _score_ratio(scores.get("team_contribution")),
                "cooperation_score": _score_ratio(scores.get("team_contribution")),
                "role_score": _score_ratio(scores.get("overall")),
                "overall_score": _score_ratio(scores.get("overall")),
                "risk_penalty": 0,
                "highlights": list(score.get("highlights", []) or []),
                "mistakes": list(score.get("mistakes", []) or []),
            }
        )
    turning_points = [
        {
            "day": None,
            "phase": "",
            "impact": "medium",
            "description": str(item),
        }
        for item in review.get("key_turning_points", []) or []
    ]
    review.setdefault(
        "game_summary",
        {
            "winner": review.get("winner"),
            "total_days": review.get("total_days", 0),
            "event_count": len(events),
        },
    )
    review.setdefault("player_evaluations", player_evaluations)
    review.setdefault("player_scores", player_evaluations)
    review.setdefault("turning_points", turning_points)
    review.setdefault("counterfactuals", [])
    review.setdefault("timeline", [_review_timeline_event(event) for event in events[-12:]])
    return review

def _archive_payload(
    game_id: str,
    snapshot: dict[str, Any],
    *,
    stored: dict[str, Any] | None = None,
) -> dict[str, Any]:
    events = public_events_only(list(snapshot.get("events") or snapshot.get("logs") or []))
    decisions = list(snapshot.get("decisions") or [])
    review = snapshot.get("review")
    has_snapshot_review = "review" in snapshot
    base = dict(stored or {})
    highlights = list(base.get("highlights") or [])
    if not highlights and isinstance(review, dict):
        highlights.extend(str(item) for item in review.get("key_turning_points", [])[:3])
        highlights.extend(str(item) for item in review.get("recommendations", [])[:3])
    if not highlights:
        highlights = [
            event.get("message", "")
            for event in events
            if isinstance(event, dict) and event.get("message")
        ][:3]
    base.update(
        {
            "kind": "game_trace_archive",
            "schema_version": 1,
            "game_id": game_id,
            "title": base.get("title") or "对局档案",
            "summary": base.get("summary") or _archive_summary(snapshot, events, decisions),
            "highlights": highlights,
            "seed": snapshot.get("seed", base.get("seed")),
            "config": snapshot.get("config", base.get("config", {})),
            "winner": snapshot.get("winner", base.get("winner")),
            "events": events,
            "decisions": decisions,
            "decision_count": len(decisions),
            "error_count": len([d for d in decisions if d.get("errors")]),
            "fallback_count": len([d for d in decisions if d.get("source") == "fallback"]),
            "decision_sources": dict(Counter(d.get("source", "unknown") for d in decisions)),
            "review": review if has_snapshot_review else base.get("review"),
        }
    )
    return base

def _archive_summary(
    snapshot: dict[str, Any],
    events: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
) -> str:
    winner = snapshot.get("winner") or "未结束"
    day = snapshot.get("day", 0)
    return f"胜利方：{winner}；当前/结束天数：{day}；事件 {len(events)} 条，决策 {len(decisions)} 条。"

def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value

def _score_ratio(value: Any) -> float:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if number > 1:
        number = number / 10.0
    return max(0.0, min(1.0, number))

def _review_timeline_event(event: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_event(event)
    return {
        "day": normalized.get("day"),
        "phase": normalized.get("phase"),
        "event_type": normalized.get("event_type") or normalized.get("type"),
        "description": normalized.get("message", ""),
        "actor_id": normalized.get("actor_id"),
        "target_id": normalized.get("target_id"),
    }

def _action_prompt(action_type: str) -> str:
    return {
        "sheriff_run": "请选择是否竞选警长。",
        "sheriff_withdraw": "请选择是否退水。",
        "sheriff_vote": "请选择警长票目标。",
        "sheriff_badge": "请选择警徽处理方式。",
        "speech_order": "请选择发言顺序。",
        "guard_protect": "请选择守护目标。",
        "werewolf_kill": "请选择夜刀目标。",
        "seer_check": "请选择查验目标。",
        "witch_act": "女巫请选择是否发动技能。",
        "white_wolf_explode": "请选择是否发动白狼王自爆。",
        "exile_vote": "请选择放逐票目标。",
        "pk_vote": "请选择 PK 票目标。",
        "hunter_shoot": "请选择开枪目标。",
    }.get(action_type, "请选择本轮行动。")

def _target_required(action_type: str) -> bool:
    return action_type in {"guard_protect", "werewolf_kill", "seer_check"}

def _choice_options(action_type: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    if action_type == "speech_order":
        values = metadata.get("choices") if isinstance(metadata.get("choices"), list) else ["forward", "reverse"]
        return [
            {"value": value, "label": "逆序发言" if value == "reverse" else "顺序发言"}
            for value in values
        ]
    options = {
        "sheriff_run": [
            {"value": "run", "label": "竞选"},
            {"value": "pass", "label": "不上警"},
        ],
        "sheriff_withdraw": [
            {"value": "stay", "label": "留警上"},
            {"value": "withdraw", "label": "退水"},
        ],
        "sheriff_badge": [
            {"value": "transfer", "label": "移交警徽", "requiresTarget": True},
            {"value": "destroy", "label": "撕毁警徽"},
        ],
        "white_wolf_explode": [
            {"value": "explode", "label": "自爆带人", "requiresTarget": True},
            {"value": "pass", "label": "暂不自爆"},
        ],
        "witch_act": [
            {"value": "save", "label": "使用解药"},
            {"value": "poison", "label": "使用毒药", "requiresTarget": True},
            {"value": "none", "label": "跳过"},
        ],
    }
    return options.get(action_type, [])

_VOTE_ACTIONS = {"exile_vote", "pk_vote", "sheriff_vote", "vote"}
_EXACT_VOTE_ACTIONS = {"exile_vote", "pk_vote", "sheriff_vote"}
_VOTE_PHASE_ALIASES = {
    "exile_vote": "exile_vote",
    "pk_vote": "pk_vote",
    "vote": "vote",
    "sheriff_vote": "sheriff_vote",
    "sheriff_election": "sheriff_vote",
}


def _vote_bucket_for_action(action: Any) -> str | None:
    value = str(action or "")
    if value == "sheriff_vote":
        return "sheriff_vote"
    if value in {"exile_vote", "pk_vote"}:
        return value
    if value == "vote":
        return "exile_vote"
    return None


def _canonical_vote_action(action: Any) -> str:
    value = str(action or "")
    return "exile_vote" if value == "vote" else value


def _vote_bucket_for_phase(phase: Any) -> str | None:
    return _VOTE_PHASE_ALIASES.get(str(phase or ""))


def _vote_phase_compatible(decision_phase: Any, expected_action: str) -> bool:
    phase_bucket = _vote_bucket_for_phase(decision_phase)
    if phase_bucket is None or phase_bucket == "vote":
        return True
    if expected_action in {"exile_vote", "pk_vote"} and phase_bucket in {"exile_vote", "pk_vote"}:
        return True
    return phase_bucket == expected_action


def _pending_vote_action(pending_action: Any) -> str | None:
    if not isinstance(pending_action, dict):
        return None
    action = str(pending_action.get("action_type") or pending_action.get("type") or "")
    return _canonical_vote_action(action) if action in _VOTE_ACTIONS else None


def _scoped_vote_decisions(
    decisions: list[dict[str, Any]],
    *,
    current_day: Any = None,
    current_phase: Any = None,
    pending_action: Any = None,
) -> list[dict[str, Any]]:
    has_scope = current_day is not None or current_phase is not None or pending_action is not None
    current_day_id = _int_or_none(current_day)
    active_action = _pending_vote_action(pending_action)
    phase_bucket = _vote_bucket_for_phase(current_phase)
    exact_action = active_action if active_action in _EXACT_VOTE_ACTIONS else None
    if exact_action is None and phase_bucket in _EXACT_VOTE_ACTIONS:
        exact_action = phase_bucket
    if has_scope and exact_action is None and phase_bucket is None:
        return []

    scoped: list[dict[str, Any]] = []
    for decision in decisions:
        action = str(decision.get("action") or decision.get("action_type") or "")
        if action not in _VOTE_ACTIONS:
            continue
        canonical_action = _canonical_vote_action(action)
        if exact_action is not None and canonical_action != exact_action:
            continue
        if current_day_id is not None and _int_or_none(decision.get("day")) != current_day_id:
            continue
        if exact_action is not None:
            if not _vote_phase_compatible(decision.get("phase"), exact_action):
                continue
        elif phase_bucket == "vote":
            if canonical_action == "sheriff_vote":
                continue
            decision_bucket = _vote_bucket_for_phase(decision.get("phase"))
            if decision_bucket not in {None, "vote", "exile_vote", "pk_vote"}:
                continue
        elif phase_bucket == "sheriff_vote" and canonical_action != "sheriff_vote":
            continue
        scoped.append(decision)

    if not has_scope or exact_action is not None:
        return scoped
    latest_action = next(
        (
            _canonical_vote_action(decision.get("action") or decision.get("action_type"))
            for decision in reversed(scoped)
        ),
        None,
    )
    if latest_action in _EXACT_VOTE_ACTIONS:
        return [
            decision
            for decision in scoped
            if _canonical_vote_action(decision.get("action") or decision.get("action_type")) == latest_action
        ]
    return scoped


def _vote_tally(
    decisions: list[dict[str, Any]],
    *,
    current_day: Any = None,
    current_phase: Any = None,
    pending_action: Any = None,
) -> list[dict[str, Any]]:
    votes: dict[int, list[dict[str, Any]]] = {}
    for decision in _scoped_vote_decisions(
        decisions,
        current_day=current_day,
        current_phase=current_phase,
        pending_action=pending_action,
    ):
        target = decision.get("target_id") or decision.get("selected_target")
        target_id = _int_or_none(target)
        if target_id is None:
            continue
        votes.setdefault(target_id, []).append(decision)
    return [
        {
            "target_id": target_id,
            "targetName": f"{target_id}号",
            "count": len(items),
            "voter_ids": [
                int(actor_id)
                for item in items
                for actor_id in [item.get("actor_id") or item.get("player_id")]
                if actor_id is not None and str(actor_id).isdigit()
            ],
            "votes": items,
        }
        for target_id, items in sorted(votes.items(), key=lambda item: (-len(item[1]), item[0]))
    ]

def _dead_players(events: list[dict[str, Any]]) -> set[int]:
    dead: set[int] = set()
    for event in events:
        if (event.get("event_type") or event.get("type")) == "death":
            target_id = _event_target(event)
            if target_id is not None:
                dead.add(target_id)
    return dead

def _sheriff_from_events(events: list[dict[str, Any]]) -> int | None:
    sheriff_id: int | None = None
    for event in events:
        event_type = event.get("event_type") or event.get("type")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        if event_type in {"sheriff_election_end", "sheriff_result"}:
            next_sheriff = _int_or_none(payload.get("winner")) or _event_target(event)
            if next_sheriff is not None:
                sheriff_id = next_sheriff
        elif event_type in {"sheriff_badge_destroy", "sheriff_destroy"}:
            sheriff_id = None
        elif event_type in {"sheriff_badge_transfer", "sheriff_transfer"}:
            next_sheriff = _int_or_none(
                event.get("target_id")
                or event.get("target")
                or payload.get("to")
                or payload.get("target_id")
                or payload.get("target")
            )
            if next_sheriff is not None:
                sheriff_id = next_sheriff
    return sheriff_id

def _team_for_role(role: str) -> str:
    try:
        return Role(role).team.value
    except ValueError:
        return "villagers"

def _role_label(role: str) -> str:
    return {
        "white_wolf_king": "白狼王",
        "werewolf": "狼人",
        "villager": "平民",
        "seer": "预言家",
        "witch": "女巫",
        "hunter": "猎人",
        "guard": "守卫",
    }.get(role, role)

