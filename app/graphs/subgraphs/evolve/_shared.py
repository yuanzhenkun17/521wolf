"""Shared utilities for evolve subgraph nodes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.graphs.shared.state import EvolveState

_log = logging.getLogger(__name__)

_STAGE_PROGRESS = {
    "init": 0.0,
    "training": 0.0,
    "consolidating": 0.45,
    "applying": 0.60,
    "scenario_replay": 0.70,
    "battling": 0.70,
    "decide": 0.95,
    "done": 1.0,
}

_STAGE_ORDER = {
    "init": 0,
    "training": 1,
    "consolidating": 2,
    "applying": 3,
    "scenario_replay": 4,
    "battling": 5,
    "decide": 6,
    "done": 7,
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
        _log.warning("evolution cancel check raised: %s", exc)
        return False


def _should_persist_stage_state(state: EvolveState) -> bool:
    storage = state.get("storage_provider") or state.get("paths")
    return storage is not None


def _persist_run_state(state: EvolveState, *, record_warning: bool = True) -> None:
    """Persist the current run state to the evolution storage backend."""
    from app.util.json import to_jsonable
    from app.util.time import beijing_now_iso

    gateway = state.get("_evolution_state_gateway")
    if gateway is None:
        return
    run_id = str(state.get("run_id") or "")
    if not run_id:
        return
    try:
        runtime_state = to_jsonable(_progress_snapshot(state))
        gateway.save_runtime_state(
            {
                "run_id": run_id,
                "role": str(state.get("role") or ""),
                "parent_hash": str(state.get("parent_hash") or ""),
                "status": str(state.get("status") or ""),
                "training_games": len(state.get("training_games") or []),
                "battle_games": len(state.get("battle_games") or []),
                "runtime_state": runtime_state,
            },
            trust_bundle=state.get("trust_bundle"),
        )
    except Exception as exc:  # noqa: BLE001 — persistence is best-effort
        message = f"persist_run_state: {exc}"
        if record_warning:
            _log.warning(message, exc_info=True)
            state.setdefault("warnings", []).append(message)
        else:
            _log.debug(message)


def _resumed_past_stage(state: EvolveState, stage: str) -> bool:
    current = str(state.get("current_stage") or "")
    return bool(current) and _STAGE_ORDER.get(current, -1) > _STAGE_ORDER.get(stage, -1)


def _unique_str(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "on"}


def _as_positive_int(value: Any, default: int = 0) -> int:
    try:
        number = int(value or 0)
        return max(0, number)
    except (TypeError, ValueError):
        return default


def _as_positive_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value or 0.0)
        return max(0.0, number)
    except (TypeError, ValueError):
        return default


def _registry(state: EvolveState) -> Any:
    from app.lib.version import version_registry_from_env

    provider = state.get("storage_provider")
    paths = state.get("paths")
    return version_registry_from_env(provider=provider, paths=paths)


def _baseline_skill_dir(state: EvolveState, cfg: dict[str, Any]) -> str:
    explicit = state.get("baseline_skill_dir") or state.get("skill_dir")
    if explicit:
        return str(explicit)
    return str(cfg.get("baseline_skill_dir") or cfg.get("skill_dir") or "")


def _read_skill_contents(skill_dir: Any) -> dict[str, str]:
    """Read all skill files under a directory into {relative_path: content}."""
    if not skill_dir:
        return {}
    root = Path(skill_dir)
    if not root.is_dir():
        return {}
    contents: dict[str, str] = {}
    for path in sorted(root.rglob("*.md")):
        try:
            contents[str(path.relative_to(root))] = path.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            _log.warning("failed to read skill %s: %s", path, exc)
    return contents


def _write_candidate_skills(state: EvolveState, skills: dict[str, str]) -> Path | None:
    """Write candidate skill files to a temporary directory."""
    import tempfile

    if not skills:
        return None
    run_id = str(state.get("run_id") or "evolve")
    role = str(state.get("role") or "role")
    root = Path(tempfile.mkdtemp(prefix=f"evolve_{role}_{run_id}_candidate_"))
    for relative, content in skills.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def _storage_run_type_for_game(state: EvolveState) -> str:
    return "evolution_training" if str(state.get("run_type") or "") == "evolve" else "benchmark"


def _copy_runner_config(cfg: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in cfg.items() if key not in _AGENT_RUNTIME_CONFIG_KEYS}


def _safe_id(value: str) -> str:
    """Sanitize an arbitrary string into a registry-safe version id."""
    import re

    cleaned = re.sub(r"[^A-Za-z0-9_-]", "_", value).strip("_")
    return cleaned or "candidate"
