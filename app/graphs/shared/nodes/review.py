"""Shared graph nodes — reusable across subgraphs.

review.py — post-game review (scoring, turning points, counterfactuals)
evidence.py — evidence extraction pipeline (training → experience candidates)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


async def review_node(state: dict) -> dict:
    """Run post-game review: analyze decisions, detect mistakes, generate report.

    Uses app.lib.review (pure heuristics, no LLM needed).
    """
    from app.lib.review import analyze_game
    from engine import Role as ERole

    game_events = state.get("game_events") or state.get("events", [])
    decisions_raw = state.get("decisions", [])
    if "roles" in state:
        roles_raw = state.get("roles")
        roles_source = "roles"
    elif "player_roles" in state:
        roles_raw = state.get("player_roles")
        roles_source = "player_roles"
    else:
        roles_raw = {}
        roles_source = "roles"
    winner = state.get("winner", "unknown")
    game_id = state.get("game_id", "")

    # Normalize decisions: list → dict by player_id
    agent_decisions: dict[int, list[dict]] = {}
    warnings: list[str] = []
    for d in decisions_raw:
        if not isinstance(d, dict):
            continue
        pid = _as_positive_int(d.get("player_id"))
        if pid is None:
            warnings.append(f"skipped decision without valid player_id: {d.get('decision_id', '?')}")
            continue
        agent_decisions.setdefault(pid, []).append(d)

    # Normalize roles: str → Role enum
    roles: dict[int, ERole] = {}
    if not isinstance(roles_raw, dict):
        warnings.append(
            f"ignored {roles_source} because expected dict, got {type(roles_raw).__name__}"
        )
        roles_raw = {}
    for pid, rname in roles_raw.items():
        player_id = _as_positive_int(pid)
        if player_id is None:
            warnings.append(f"skipped role entry with invalid player_id: {pid!r}={rname!r}")
            continue
        try:
            roles[player_id] = ERole(str(rname))
        except ValueError:
            warnings.append(f"skipped role entry with invalid role: player_id={player_id}, role={rname!r}")

    try:
        review = analyze_game(
            game_log=game_events,
            agent_decisions=agent_decisions,
            roles=roles,
            winner_team=winner,
            game_id=game_id,
        )
        state["review"] = review.to_dict()
        state["review"]["status"] = "ok"
        if warnings:
            state["review"]["warnings"] = warnings
            _append_warnings(state, warnings)
    except Exception as exc:
        _log.warning("review_node failed: %s", exc, exc_info=True)
        state["review"] = {"status": "failed", "error": str(exc)}
        if warnings:
            state["review"]["warnings"] = warnings
            _append_warnings(state, warnings)
        _append_warnings(state, [f"review failed: {type(exc).__name__}: {exc}"])

    return state


async def evidence_node(state: dict) -> dict:
    """Extract evidence from completed games for evolution training.

    Uses app.lib.evidence for normalization and selection.
    LLM judging goes through app.services.chain.py:run_evidence_chain().
    """
    from app.lib.evidence import (
        GameEvidenceBundle,
        normalize_decisions,
        select_key_decisions,
    )

    game_dir = _resolve_game_dir(state)
    if not game_dir:
        _log.debug("evidence_node: no game_dir, skipping")
        state["evidence"] = {"status": "skipped", "reason": "no_game_dir"}
        return state

    try:
        warnings: list[str] = []
        replay_diagnostics: dict[str, Any] = {}
        replay_config: dict[str, Any] = {}
        replay_game_id: str | None = None
        agent_decisions = _list_value(state.get("decisions"))
        game_events = _list_value(state.get("game_events") or state.get("events"))
        used_state_decisions = bool(agent_decisions)
        used_state_events = bool(game_events)
        used_replay_decisions = False
        used_replay_events = False

        if not agent_decisions or not game_events:
            replay = _load_replay_inputs(
                state,
                game_dir,
                need_decisions=not agent_decisions,
                need_events=not game_events,
            )
            replay_diagnostics = replay["diagnostics"]
            replay_config = replay["config"]
            replay_game_id = replay["game_id"]
            warnings.extend(replay["warnings"])

            if not agent_decisions and replay["decisions"]:
                agent_decisions = replay["decisions"]
                state["decisions"] = agent_decisions
                used_replay_decisions = True
            if not game_events and replay["events"]:
                game_events = replay["events"]
                state["game_events"] = game_events
                used_replay_events = True

        input_source = _evidence_input_source(
            used_state_decisions=used_state_decisions,
            used_state_events=used_state_events,
            used_replay_decisions=used_replay_decisions,
            used_replay_events=used_replay_events,
        )
        metadata = _evidence_metadata(
            used_state_decisions=used_state_decisions,
            used_state_events=used_state_events,
            used_replay_decisions=used_replay_decisions,
            used_replay_events=used_replay_events,
            evidence_source=input_source,
            replay_diagnostics=replay_diagnostics,
            has_decisions=bool(agent_decisions),
            has_events=bool(game_events),
            warnings=warnings,
        )

        if not agent_decisions:
            warnings.append("evidence skipped: no decisions available from state or replay")
            metadata = _evidence_metadata(
                used_state_decisions=used_state_decisions,
                used_state_events=used_state_events,
                used_replay_decisions=used_replay_decisions,
                used_replay_events=used_replay_events,
                evidence_source=input_source,
                replay_diagnostics=replay_diagnostics,
                has_decisions=False,
                has_events=bool(game_events),
                warnings=warnings,
            )
            state["evidence_inputs"] = []
            state["key_decisions"] = []
            state["evidence"] = {
                "status": "skipped",
                "reason": "no_decisions",
                "evidence_inputs": 0,
                "key_decisions": 0,
                "metadata": metadata,
                "warnings": warnings,
            }
            if replay_diagnostics:
                state["evidence"]["replay"] = replay_diagnostics
            _append_warnings(state, warnings)
            return state

        if not game_events:
            warnings.append("evidence running without game events; key decision selection may be incomplete")
            metadata = _evidence_metadata(
                used_state_decisions=used_state_decisions,
                used_state_events=used_state_events,
                used_replay_decisions=used_replay_decisions,
                used_replay_events=used_replay_events,
                evidence_source=input_source,
                replay_diagnostics=replay_diagnostics,
                has_decisions=True,
                has_events=False,
                warnings=warnings,
            )

        meta = _dict_value(state.get("review"))
        if replay_config:
            meta = {**replay_config, **meta}
        archive = {"config": replay_config} if replay_config else {}
        bundle = GameEvidenceBundle(
            game_dir=Path(game_dir),
            game_id=str(state.get("game_id") or replay_game_id or ""),
            archive={},
            agent_decisions=agent_decisions,
            game_events=game_events,
            meta=meta,
        )
        bundle.archive.update(archive)
        evidence_inputs = normalize_decisions(bundle)
        if not evidence_inputs:
            warnings.append("evidence skipped: decision normalization produced no evidence inputs")
            metadata = _evidence_metadata(
                used_state_decisions=used_state_decisions,
                used_state_events=used_state_events,
                used_replay_decisions=used_replay_decisions,
                used_replay_events=used_replay_events,
                evidence_source=input_source,
                replay_diagnostics=replay_diagnostics,
                has_decisions=bool(agent_decisions),
                has_events=bool(game_events),
                warnings=warnings,
            )
            state["evidence_inputs"] = []
            state["key_decisions"] = []
            state["evidence"] = {
                "status": "skipped",
                "reason": "no_evidence_inputs",
                "evidence_inputs": 0,
                "key_decisions": 0,
                "metadata": metadata,
                "warnings": warnings,
            }
            if replay_diagnostics:
                state["evidence"]["replay"] = replay_diagnostics
            _append_warnings(state, warnings)
            return state

        key_decisions = select_key_decisions(evidence_inputs, bundle)

        state["evidence_inputs"] = evidence_inputs
        state["key_decisions"] = key_decisions
        state["evidence"] = {
            "status": "ok",
            "input_source": input_source,
            "evidence_inputs": len(evidence_inputs),
            "key_decisions": len(key_decisions),
            "metadata": metadata,
        }
        if warnings:
            state["evidence"]["warnings"] = warnings
            _append_warnings(state, warnings)
        if replay_diagnostics:
            state["evidence"]["replay"] = replay_diagnostics
    except Exception as exc:
        _log.warning("evidence_node failed: %s", exc, exc_info=True)
        message = f"evidence failed: {type(exc).__name__}: {exc}"
        state["evidence"] = {"status": "failed", "error": str(exc), "warnings": [message]}
        _append_warnings(state, [message])

    return state


def _append_warnings(state: dict, messages: list[str]) -> None:
    warnings = state.setdefault("warnings", [])
    for message in messages:
        text = str(message)
        if text and text not in warnings:
            warnings.append(text)


def _load_replay_inputs(
    state: dict,
    game_dir: Path | str,
    *,
    need_decisions: bool,
    need_events: bool,
) -> dict[str, Any]:
    db_path = _resolve_db_path(state)
    if not db_path:
        diagnostics: dict[str, Any] = {}
        if need_decisions:
            diagnostics["decisions"] = _missing_replay_diagnostic("decisions", game_dir, "no db_path available")
        if need_events:
            diagnostics["events"] = _missing_replay_diagnostic("events", game_dir, "no db_path available")
        if need_decisions or need_events:
            diagnostics["config"] = _missing_replay_diagnostic("config", game_dir, "no db_path available")
        return {
            "decisions": [],
            "events": [],
            "config": {},
            "game_id": None,
            "diagnostics": diagnostics,
            "warnings": ["evidence replay skipped: no db_path available"],
        }

    from storage.replay import explain_replay_lookup

    root = _resolve_replay_root(state)
    diagnostics: dict[str, Any] = {}
    warnings: list[str] = []
    decisions: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    config: dict[str, Any] = {}
    game_id: str | None = None

    if need_decisions:
        result = explain_replay_lookup(db_path, game_dir, root=root, replay_type="decisions")
        diagnostics["decisions"] = _lookup_diagnostic(result)
        if result.ok and isinstance(result.data, list):
            decisions = result.data
            game_id = game_id or result.game_id
        else:
            warnings.append(_replay_warning("decisions", result))

    if need_events:
        result = explain_replay_lookup(db_path, game_dir, root=root, replay_type="events")
        diagnostics["events"] = _lookup_diagnostic(result)
        if result.ok and isinstance(result.data, list):
            events = result.data
            game_id = game_id or result.game_id
        else:
            warnings.append(_replay_warning("events", result))

    result = explain_replay_lookup(db_path, game_dir, root=root, replay_type="config")
    diagnostics["config"] = _lookup_diagnostic(result)
    if result.ok and isinstance(result.data, dict):
        config = result.data
        game_id = game_id or result.game_id
    elif need_decisions or need_events:
        warnings.append(_replay_warning("config", result))

    return {
        "decisions": decisions,
        "events": events,
        "config": config,
        "game_id": game_id,
        "diagnostics": diagnostics,
        "warnings": warnings,
    }


def _lookup_diagnostic(result: Any) -> dict[str, Any]:
    diagnostic = {
        "status": result.status,
        "game_id": result.game_id,
        "table": result.table,
        "message": result.message,
        "candidates": list(result.candidates),
    }
    if result.error:
        diagnostic["error"] = result.error
    return diagnostic


def _missing_replay_diagnostic(replay_type: str, game_dir: Path | str, message: str) -> dict[str, Any]:
    table = {"decisions": "decisions", "events": "game_events", "config": "games"}.get(replay_type)
    return {
        "status": "missing_db_path",
        "game_id": None,
        "table": table,
        "message": message,
        "candidates": [Path(game_dir).name],
    }


def _replay_warning(replay_type: str, result: Any) -> str:
    detail = result.error or result.message or "no diagnostic message"
    return f"evidence replay {replay_type} unavailable: {result.status}: {detail}"


def _evidence_input_source(
    *,
    used_state_decisions: bool,
    used_state_events: bool,
    used_replay_decisions: bool,
    used_replay_events: bool,
) -> str:
    used_state = used_state_decisions or used_state_events
    used_replay = used_replay_decisions or used_replay_events
    if used_replay_decisions and used_replay_events and not used_state:
        return "replay"
    if used_state and used_replay:
        return "mixed"
    if used_replay:
        return "replay_partial"
    if used_state:
        return "state"
    return "unavailable"


def _evidence_metadata(
    *,
    used_state_decisions: bool,
    used_state_events: bool,
    used_replay_decisions: bool,
    used_replay_events: bool,
    evidence_source: str,
    replay_diagnostics: dict[str, Any],
    has_decisions: bool,
    has_events: bool,
    warnings: list[str],
) -> dict[str, Any]:
    replay_missing = _replay_has_status(
        replay_diagnostics,
        {"missing_db_path", "missing_db", "missing_table", "missing_rows", "not_found"},
    )
    replay_error = _replay_has_status(replay_diagnostics, {"sqlite_error", "unsupported_type"})
    statuses = {
        key: str(value.get("status"))
        for key, value in replay_diagnostics.items()
        if isinstance(value, dict) and value.get("status")
    }
    return {
        "used_state_decisions": used_state_decisions,
        "used_state_events": used_state_events,
        "used_replay_decisions": used_replay_decisions,
        "used_replay_events": used_replay_events,
        "replay_missing": replay_missing,
        "replay_error": replay_error,
        "replay_statuses": statuses,
        "evidence_source": evidence_source,
        "reliability": _evidence_reliability(
            has_decisions=has_decisions,
            has_events=has_events,
            replay_missing=replay_missing,
            replay_error=replay_error,
            warnings=warnings,
        ),
    }


def _replay_has_status(replay_diagnostics: dict[str, Any], statuses: set[str]) -> bool:
    for diagnostic in replay_diagnostics.values():
        if not isinstance(diagnostic, dict):
            continue
        if str(diagnostic.get("status") or "") in statuses:
            return True
        if "error" in diagnostic and "sqlite_error" in statuses:
            return True
    return False


def _evidence_reliability(
    *,
    has_decisions: bool,
    has_events: bool,
    replay_missing: bool,
    replay_error: bool,
    warnings: list[str],
) -> str:
    if not has_decisions:
        return "none"
    if replay_error:
        return "low"
    if replay_missing or not has_events or warnings:
        return "degraded"
    return "high"


def _resolve_game_dir(state: dict) -> Any:
    return state.get("game_dir") or state.get("path")


def _resolve_db_path(state: dict) -> Any:
    for key in ("db_path", "wolf_db_path"):
        value = state.get(key)
        if value:
            return value

    paths = state.get("paths")
    value = _mapping_or_attr(paths, "wolf_db_path") or _mapping_or_attr(paths, "db_path")
    if value:
        return value

    for container_key in ("config", "batch_config"):
        container = state.get(container_key)
        value = _mapping_or_attr(container, "db_path") or _mapping_or_attr(container, "wolf_db_path")
        if value:
            return value
    return None


def _resolve_replay_root(state: dict) -> Any:
    for key in ("root", "runs_root", "artifact_root", "artifacts_root"):
        value = state.get(key)
        if value:
            return value

    paths = state.get("paths")
    value = (
        _mapping_or_attr(paths, "root")
        or _mapping_or_attr(paths, "runs_root")
        or _mapping_or_attr(paths, "artifacts_root")
    )
    if value:
        return value

    for container_key in ("config", "batch_config"):
        container = state.get(container_key)
        value = (
            _mapping_or_attr(container, "root")
            or _mapping_or_attr(container, "runs_root")
            or _mapping_or_attr(container, "artifact_root")
            or _mapping_or_attr(container, "artifacts_root")
        )
        if value:
            return value
    return None


def _mapping_or_attr(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _list_value(value: Any) -> list[dict[str, Any]]:
    return value if isinstance(value, list) else []


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None
