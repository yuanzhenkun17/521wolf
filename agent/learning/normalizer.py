"""Normalize selfplay outputs into decision evidence inputs."""

from __future__ import annotations

from typing import Any

from agent.learning.models import (
    AgentReasoning,
    DecisionEvidenceInput,
    DecisionResult,
    GameEvidenceBundle,
    GodViewAfterGame,
    PlayerView,
)


def normalize_decisions(bundle: GameEvidenceBundle) -> list[DecisionEvidenceInput]:
    agent_by_id = {
        str(row.get("decision_id")): row
        for row in bundle.agent_decisions
        if row.get("decision_id") is not None
    }
    roles = _normalize_roles(bundle.archive.get("player_roles") or _roles_from_events(bundle.game_events))
    winner = str(bundle.archive.get("winner") or "")

    normalized: list[DecisionEvidenceInput] = []
    archive_decisions = bundle.archive.get("decisions") or []
    for fallback_index, archived in enumerate(archive_decisions, start=1):
        decision_id = str(archived.get("decision_id") or f"decision_{fallback_index}")
        agent_row = agent_by_id.get(decision_id, {})
        merged = {**archived, **{key: value for key, value in agent_row.items() if value is not None}}

        player_id = _as_int(merged.get("player_id"))
        selected_target = _first_present(
            merged.get("selected_target"),
            _nested(merged.get("final_response"), "target"),
            _nested(merged.get("parsed_decision"), "target"),
        )
        selected_choice = _first_present(
            merged.get("selected_choice"),
            _nested(merged.get("final_response"), "choice"),
            _nested(merged.get("parsed_decision"), "choice"),
        )

        normalized.append(
            DecisionEvidenceInput(
                decision_id=decision_id,
                decision_index=_as_int(archived.get("index") or fallback_index),
                day=_as_int(merged.get("day")),
                phase=str(merged.get("phase") or ""),
                action_type=str(merged.get("action_type") or ""),
                player_view=PlayerView(
                    player_id=player_id,
                    role=str(merged.get("role") or (roles.get(str(player_id)) if player_id is not None else "") or ""),
                    candidates=list(merged.get("candidates") or []),
                    observation_summary=archived.get("observation_summary"),
                    memory_context=dict(archived.get("memory_context") or {}),
                    belief_context=dict(archived.get("belief_context") or merged.get("belief_snapshot") or {}),
                    prompt_messages=list(archived.get("prompt_messages") or []),
                    selected_skills=_list_str(merged.get("selected_skills")),
                ),
                agent_reasoning=AgentReasoning(
                    private_reasoning=str(merged.get("private_reasoning") or ""),
                    alternatives=list(merged.get("alternatives") or []),
                    rejected_reasons=[str(item) for item in (merged.get("rejected_reasons") or [])],
                    confidence=_as_float(merged.get("confidence")),
                    memory_summary=list(merged.get("memory_summary") or []),
                    raw_output=str(merged.get("raw_output") or ""),
                ),
                decision_result=DecisionResult(
                    selected_target=selected_target,
                    selected_choice=selected_choice,
                    public_text=str(merged.get("public_text") or _nested(merged.get("parsed_decision"), "public_text") or ""),
                    final_response=archived.get("final_response"),
                    source=str(merged.get("source") or ""),
                    errors=list(merged.get("errors") or []),
                    policy_adjustments=list(merged.get("policy_adjustments") or []),
                ),
                god_view_after_game=GodViewAfterGame(
                    player_roles=roles,
                    winner=winner,
                    target_true_role=_target_role(selected_target, roles),
                    eventual_outcome={
                        "final_state": bundle.archive.get("final_state") or {},
                    },
                ),
            )
        )
    return normalized


def _normalize_roles(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {str(key): str(value) for key, value in raw.items()}


def _roles_from_events(events: list[dict[str, Any]]) -> dict[str, str]:
    for event in events:
        payload = event.get("payload") or {}
        roles = payload.get("roles")
        if isinstance(roles, dict):
            return roles
    return {}


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _nested(value: Any, key: str) -> Any:
    return value.get(key) if isinstance(value, dict) else None


def _target_role(target: Any, roles: dict[str, str]) -> str | None:
    if target is None:
        return None
    return roles.get(str(target))


def _list_str(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]
