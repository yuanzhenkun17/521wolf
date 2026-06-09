"""Game subgraph — orchestrates a single werewolf game.

Nodes: init_engine → create_agents → game_loop → record_events → persist
The game_loop node internally invokes the agent_subgraph for each decision.
"""

from __future__ import annotations

import logging
import os
import asyncio
import importlib
import sys
from contextlib import contextmanager, nullcontext
from typing import Any

_log = logging.getLogger(__name__)


async def init_engine_node(state: dict) -> dict:
    """Initialize the game engine with config."""
    from dataclasses import replace

    from engine import STANDARD_12, GameEngine, GameLogger, ScriptedAgent, assign_roles
    from app.util.time import beijing_now_iso

    seed = state.get("seed", 0)
    max_days = state.get("max_days", 20)
    enable_sheriff = bool(state.get("enable_sheriff", True))

    _ensure_game_persistence(state)
    config = replace(
        STANDARD_12,
        max_days=max_days,
        enable_sheriff=enable_sheriff,
        runner_max_retries=_runner_max_retries(state),
        runner_retry_delay=_runner_retry_delay(state),
        runner_action_timeout=_runner_action_timeout(state),
    )
    roles = assign_roles(config, seed=seed)
    persistence = _persistence_handle(state)
    logger = state.get("logger")
    if logger is None and persistence is not None and hasattr(persistence, "create_event_logger"):
        logger = persistence.create_event_logger()
    if logger is None:
        logger = GameLogger()
    bootstrap_agents = {player_id: ScriptedAgent() for player_id in roles}

    engine = GameEngine(
        config=config,
        roles=roles,
        agents=bootstrap_agents,  # replaced by create_agents_node
        logger=logger,
    )

    state["roles"] = {pid: role.value for pid, role in roles.items()}
    state["engine"] = engine
    state["logger"] = logger
    state["day"] = 0
    state["phase"] = "night"
    state["alive_players"] = list(range(1, 13))
    if not state.get("started_at"):
        state["started_at"] = beijing_now_iso()
    return state


async def create_agents_node(state: dict) -> dict:
    """Create AgentRuntime instances for each player."""
    from app.lib.game import create_agent_runtime
    from app.lib.store import AgentDecisionRecorder
    from engine import Role as ERole

    roles_raw = state.get("roles", {})
    roles = {int(pid): ERole(name) for pid, name in roles_raw.items()}
    model = state.get("model")
    if model is None:
        state["error"] = "No model in state; app.run must inject the default LLM client"
        state["finished"] = True
        return state
    game_id = state.get("game_id", "unknown")
    skill_dir = state.get("skill_dir")
    role_skill_dirs = state.get("role_skill_dirs") or {}
    recorder = state.get("recorder")
    if recorder is None:
        persistence = _persistence_handle(state)
        sink = (
            persistence.create_decision_sink()
            if persistence is not None and hasattr(persistence, "create_decision_sink")
            else None
        )
        recorder = AgentDecisionRecorder(sink=sink)
    trace_recorder = state.get("trace_recorder")
    agent_subgraph = state.get("agent_subgraph")
    _ensure_langfuse_trace_id(state)
    agent_runtime_config = _agent_runtime_config(state)

    def _skill_dir_for(role: "ERole"):
        """Per-role override falls back to the shared skill_dir."""
        return role_skill_dirs.get(role.value, skill_dir)

    agents = {}
    for player_id, role in sorted(roles.items()):
        agent_skill_dir = _skill_dir_for(role)
        if agent_subgraph is None:
            agents[player_id] = create_agent_runtime(
                player_id=player_id,
                role=role,
                model=model,
                game_id=game_id,
                skill_dir=agent_skill_dir,
                recorder=recorder,
                trace_recorder=trace_recorder,
                paths=state.get("paths"),
                agent_runtime_config=agent_runtime_config,
            )
        else:
            from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
            from app.services.memory import AgentMemory

            agents[player_id] = AgentRuntimeAdapter(
                graph=agent_subgraph,
                player_id=player_id,
                role=role,
                model=model,
                memory=AgentMemory(player_id=player_id, role=role),
                recorder=recorder,
                trace_recorder=trace_recorder,
                game_id=game_id,
                skill_dir=agent_skill_dir,
                paths=state.get("paths"),
                agent_runtime_config=agent_runtime_config,
            )
        _attach_langfuse_trace_id(agents[player_id], state)

    # Inject agents into engine
    engine = state.get("engine")
    if engine is not None:
        engine.agents = agents

    state["agents"] = agents
    state["recorder"] = recorder
    state["model"] = model
    return state


async def game_loop_node(state: dict) -> dict:
    """Run the game engine until completion.

    The engine internally calls agent.act() for each decision.
    """
    engine = state.get("engine")
    if engine is None:
        state["error"] = "No engine in state"
        state["finished"] = True
        return state

    observability = _observability()
    metadata = _langfuse_game_metadata(state)
    trace_id = _ensure_langfuse_trace_id(state, observability=observability)
    if trace_id:
        state["langfuse_trace_id"] = trace_id
        metadata = _langfuse_game_metadata(state)
    session_id = str(state.get("langfuse_session_id") or metadata.get("source_run_id") or metadata.get("game_id") or "")

    with _langfuse_game_context(
        observability,
        trace_name=f"game.{metadata.get('run_type', 'ordinary_game')}",
        trace_id=trace_id,
        session_id=session_id or None,
        metadata=metadata,
        tags=_langfuse_game_tags(state),
        input={"game_id": metadata.get("game_id"), "seed": metadata.get("seed")},
    ) as observation:
        _link_langfuse_game_dataset_run_item(state, observability, observation)
        _update_langfuse_game_observation_metadata(observability, observation, state)
        try:
            timeout = _game_timeout(state)
            run = engine.run_until_finished()
            winner = await run if timeout is None else await asyncio.wait_for(run, timeout=timeout)
            state["winner"] = winner.value if hasattr(winner, "value") else None
            if winner is None:
                state["terminal_reason"] = "max_days_reached"
                state["outcome"] = "no_winner"
        except asyncio.TimeoutError:
            timeout = _game_timeout(state)
            message = (
                f"游戏运行超过 {timeout:g} 秒，按超时结束"
                if timeout is not None
                else "游戏运行超时，按超时结束"
            )
            engine._record(
                "game_timeout",
                message=message,
                public=False,
                payload={"timeout_s": timeout},
            )
            state["error"] = message
            state["winner"] = "timeout"
            state["outcome"] = "timeout"
            state["terminal_reason"] = "game_timeout"
        except Exception as exc:
            _log.error("Game loop failed: %s", exc, exc_info=True)
            state["error"] = str(exc)
            state["winner"] = "error"

        state["finished"] = True
        _score_langfuse_game_trace(state)
    _flush_langfuse(observability)
    return state


async def record_events_node(state: dict) -> dict:
    """Collect events and decisions from the completed game."""
    engine = state.get("engine")
    recorder = state.get("recorder")

    events = []
    if engine is not None and hasattr(engine, "logger"):
        events = [e.to_dict() if hasattr(e, "to_dict") else e for e in engine.logger.entries]

    decisions = []
    if recorder is not None and hasattr(recorder, "records"):
        decisions = [r.to_dict() for r in recorder.records]

    state["game_events"] = events
    state["decisions"] = decisions
    return state


async def persist_node(state: dict) -> dict:
    """Persist game results to PostgreSQL-backed storage, when available."""
    from app.util.time import beijing_now_iso
    from storage.public_events import public_events_only

    finished_at = state.get("finished_at") or beijing_now_iso()
    started_at = state.get("started_at") or finished_at or beijing_now_iso()
    state["started_at"] = started_at
    state["finished_at"] = finished_at

    persistence = _persistence_handle(state)
    save_game_result = getattr(persistence, "save_game_result", None)
    if save_game_result is None:
        return state

    events = [event for event in state.get("game_events", []) if isinstance(event, dict)]
    player_roles = _normalize_player_roles(state.get("roles", {}))
    final_state = _final_state_payload(state, finished_at=finished_at)

    try:
        save_game_result(
            seed=int(state.get("seed", 0) or 0),
            player_roles=player_roles,
            config=_persistence_config(state),
            winner=state.get("winner"),
            started_at=str(started_at),
            finished_at=finished_at,
            total_rounds=_max_event_day(events),
            public_events=public_events_only(events),
            final_state=final_state,
            deaths=final_state.get("deaths"),
            final_alive=_final_alive(final_state),
        )
    finally:
        if state.get("game_persistence_owner"):
            close = getattr(persistence, "close", None)
            if callable(close):
                close()
            state["game_persistence_owner"] = False
    return state


def _persistence_handle(state: dict) -> Any | None:
    return state.get("persistence") or state.get("game_persistence")


def _observability() -> Any | None:
    try:
        return importlib.import_module("app.services.observability")
    except Exception:  # noqa: BLE001 - observability must not affect game execution
        _log.debug("Langfuse observability import failed", exc_info=True)
        return None


def _ensure_langfuse_trace_id(state: dict, *, observability: Any | None = None) -> str | None:
    existing = state.get("langfuse_trace_id")
    if existing:
        return str(existing)
    try:
        obs = observability or _observability()
        if obs is None:
            return None
        create_trace_id = getattr(obs, "create_trace_id", None)
        if not callable(create_trace_id):
            return None
        trace_id = create_trace_id(seed=str(state.get("game_id") or ""))
    except Exception:  # noqa: BLE001 - tracing must not affect game execution
        _log.debug("Langfuse trace id creation failed", exc_info=True)
        return None
    if trace_id:
        state["langfuse_trace_id"] = str(trace_id)
        return str(trace_id)
    return None


def _attach_langfuse_trace_id(agent: Any, state: dict) -> None:
    trace_id = state.get("langfuse_trace_id")
    if not trace_id:
        return
    try:
        config = getattr(agent, "agent_runtime_config", None)
        if isinstance(config, dict):
            config["langfuse_trace_id"] = str(trace_id)
    except Exception:  # noqa: BLE001 - observability propagation must be advisory
        _log.debug("Langfuse trace id propagation to agent failed", exc_info=True)


def _langfuse_game_metadata(state: dict) -> dict[str, Any]:
    metadata = {
        "game_id": state.get("game_id"),
        "batch_id": state.get("batch_id") or state.get("source_run_id"),
        "seed": state.get("seed"),
        "run_type": _storage_run_type(state),
        "mode": state.get("mode") or "dev",
        "source_run_id": state.get("source_run_id") or state.get("game_id"),
        "source_game_id": state.get("source_game_id") or state.get("game_id"),
        "player_count": state.get("player_count", 12),
        "max_days": state.get("max_days", 20),
    }
    for key in (
        "model_id",
        "model_config_hash",
        "comparison_group_id",
        "comparison_type",
        "target_role",
        "target_version_id",
        "seed_set_id",
        "evaluation_set_id",
        "benchmark_id",
        "benchmark_version",
        "benchmark_config_hash",
        "target_type",
    ):
        if state.get(key) is not None:
            metadata[key] = state[key]
    metadata.update(_langfuse_game_linkage_metadata(state))
    if state.get("paired_seed") is not None:
        metadata["paired_seed"] = bool(state.get("paired_seed"))
    return {key: value for key, value in metadata.items() if value is not None}


def _langfuse_game_tags(state: dict) -> list[str]:
    tags = ["werewolf", _storage_run_type(state)]
    mode = state.get("mode")
    if mode:
        tags.append(str(mode))
    target_role = state.get("target_role")
    if target_role:
        tags.append(f"role:{target_role}")
    return tags


def _score_langfuse_game_trace(state: dict) -> None:
    observability = _observability()
    metadata = _langfuse_game_score_metadata(state)
    winner = state.get("winner")
    if winner is not None:
        _score_langfuse_value(
            observability,
            "winner",
            str(winner),
            data_type="CATEGORICAL",
            metadata=metadata,
        )
    _score_langfuse_value(
        observability,
        "finished",
        bool(state.get("finished")),
        data_type="BOOLEAN",
        metadata=metadata,
    )
    if state.get("error"):
        _score_langfuse_value(
            observability,
            "terminal_status",
            "error",
            data_type="CATEGORICAL",
            comment=str(state.get("error")),
            metadata=metadata,
        )
    else:
        _score_langfuse_value(
            observability,
            "terminal_status",
            "completed",
            data_type="CATEGORICAL",
            metadata=metadata,
        )
    _score_langfuse_decision_quality(observability, state)


def _score_langfuse_decision_quality(observability: Any, state: dict) -> None:
    try:
        from app.lib.score import compute_decision_quality_metrics

        decisions = _langfuse_decision_records(state)
        events = _langfuse_game_events(state)
        metrics = compute_decision_quality_metrics([{"decisions": decisions, "events": events}])
    except Exception:  # noqa: BLE001 - scoring must not affect game execution
        _log.debug("Langfuse decision quality scoring failed", exc_info=True)
        return

    metadata = {
        "metric_family": "decision_quality",
        "decision_count": metrics.get("decision_count", 0),
        "event_count": metrics.get("event_count", 0),
    }
    metadata.update(_langfuse_game_score_metadata(state))
    metadata["metric_family"] = "decision_quality"
    score_names = (
        "decision_count",
        "fallback_rate",
        "llm_error_rate",
        "policy_adjusted_rate",
        "policy_skipped_rate",
        "invalid_response_rate",
        "default_action_rate",
    )
    for name in score_names:
        value = metrics.get(name)
        if value is None:
            continue
        _score_langfuse_value(
            observability,
            f"decision_quality.{name}",
            value,
            data_type="NUMERIC",
            metadata=metadata,
        )


def _score_langfuse_value(
    observability: Any,
    name: str,
    value: Any,
    *,
    data_type: str,
    comment: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    score_current_trace = getattr(observability, "score_current_trace", None)
    if not callable(score_current_trace):
        return
    try:
        score_current_trace(name, value, data_type=data_type, comment=comment, metadata=metadata)
    except TypeError:
        try:
            score_current_trace(name, value, data_type=data_type, metadata=metadata)
        except Exception:  # noqa: BLE001
            _log.debug("Langfuse game score failed for %s", name, exc_info=True)
    except Exception:  # noqa: BLE001
        _log.debug("Langfuse game score failed for %s", name, exc_info=True)


def _langfuse_game_score_metadata(state: dict) -> dict[str, Any]:
    metadata = {
        "metric_family": "game",
        "game_id": state.get("game_id"),
        "batch_id": state.get("batch_id") or state.get("source_run_id"),
        "seed": state.get("seed"),
        "run_type": _storage_run_type(state),
        "winner": state.get("winner"),
        "terminal_reason": state.get("terminal_reason"),
    }
    metadata.update(_langfuse_game_linkage_metadata(state))
    return {key: value for key, value in metadata.items() if value is not None}


def _langfuse_game_linkage_metadata(state: dict) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in (
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
        "langfuse_dataset_run_id",
        "langfuse_dataset_run_item_id",
        "langfuse_trace_id",
        "langfuse_trace_url",
        "langfuse_experiment_url",
    ):
        if state.get(key) is not None:
            metadata[key] = state[key]

    dataset_name = _first_present(state.get("langfuse_dataset_name"), state.get("evaluation_set_id"))
    if dataset_name is not None:
        metadata["langfuse_dataset_name"] = dataset_name

    dataset_item_id = _first_present(state.get("langfuse_dataset_item_id"), _langfuse_game_dataset_item_id(state))
    if dataset_item_id is not None:
        metadata["langfuse_dataset_item_id"] = dataset_item_id

    experiment_name = _first_present(state.get("langfuse_experiment_name"), state.get("experiment_name"))
    if experiment_name is not None:
        metadata["langfuse_experiment_name"] = experiment_name
        metadata["experiment_name"] = experiment_name

    run_name = _first_present(state.get("langfuse_run_name"), state.get("run_name"))
    if run_name is not None:
        metadata["langfuse_run_name"] = run_name
        metadata["run_name"] = run_name

    return {key: value for key, value in metadata.items() if value is not None}


def _link_langfuse_game_dataset_run_item(state: dict, observability: Any | None, observation: Any | None) -> None:
    link_fn = getattr(observability, "link_langfuse_dataset_run_item", None)
    if not callable(link_fn):
        return

    linkage = _langfuse_game_linkage_metadata(state)
    dataset_name = linkage.get("langfuse_dataset_name")
    dataset_item_id = linkage.get("langfuse_dataset_item_id")
    run_name = linkage.get("langfuse_run_name")
    if not dataset_item_id or not run_name:
        return

    try:
        link = link_fn(
            dataset_name=str(dataset_name) if dataset_name is not None else None,
            dataset_item_id=str(dataset_item_id),
            experiment_name=_optional_string(linkage.get("langfuse_experiment_name")),
            run_name=str(run_name),
            trace_id=_optional_string(state.get("langfuse_trace_id")),
            observation_id=_langfuse_observation_id(observation),
            metadata=_langfuse_game_metadata(state),
        )
    except Exception:  # noqa: BLE001 - Langfuse linkage must not affect game execution
        _log.debug("Langfuse game dataset run item link failed", exc_info=True)
        return

    _apply_langfuse_game_link(state, link)


def _apply_langfuse_game_link(state: dict, link: Any) -> None:
    if link is None:
        return
    for source_key, target_key in (
        ("dataset_name", "langfuse_dataset_name"),
        ("dataset_item_id", "langfuse_dataset_item_id"),
        ("experiment_name", "langfuse_experiment_name"),
        ("run_name", "langfuse_run_name"),
        ("dataset_run_id", "langfuse_dataset_run_id"),
        ("dataset_run_item_id", "langfuse_dataset_run_item_id"),
        ("trace_id", "langfuse_trace_id"),
        ("trace_url", "langfuse_trace_url"),
        ("experiment_url", "langfuse_experiment_url"),
    ):
        value = _link_value(link, source_key)
        if value is not None:
            state[target_key] = value


def _link_value(link: Any, key: str) -> Any | None:
    if isinstance(link, dict):
        return link.get(key)
    return getattr(link, key, None)


def _langfuse_observation_id(observation: Any | None) -> str | None:
    for key in ("id", "observation_id", "observationId"):
        value = _link_value(observation, key)
        if value is not None and value != "":
            return str(value)
    return None


def _update_langfuse_game_observation_metadata(
    observability: Any | None,
    observation: Any | None,
    state: dict,
) -> None:
    update_fn = getattr(observability, "update_observation", None)
    if not callable(update_fn):
        return
    try:
        update_fn(observation, metadata=_langfuse_game_metadata(state))
    except Exception:  # noqa: BLE001 - metadata enrichment is advisory
        _log.debug("Langfuse game observation metadata update failed", exc_info=True)


def _langfuse_game_dataset_item_id(state: dict) -> str | None:
    evaluation_set_id = state.get("evaluation_set_id")
    seed_set_id = state.get("seed_set_id")
    seed = state.get("seed")
    if evaluation_set_id is None or seed_set_id is None or seed is None:
        return None
    return f"{evaluation_set_id}:{seed_set_id}:{seed}"


def _first_present(*values: Any) -> Any | None:
    for value in values:
        if value is not None:
            return value
    return None


def _optional_string(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _langfuse_game_context(observability: Any | None, **kwargs: Any) -> Any:
    context_fn = getattr(observability, "langfuse_context", None)
    if not callable(context_fn):
        return nullcontext(None)
    try:
        return _fail_open_langfuse_context(context_fn(**kwargs))
    except Exception:  # noqa: BLE001 - tracing is advisory
        _log.debug("Langfuse game context creation failed", exc_info=True)
        return nullcontext(None)


@contextmanager
def _fail_open_langfuse_context(context: Any) -> Any:
    try:
        value = context.__enter__()
    except Exception:  # noqa: BLE001 - tracing is advisory
        _log.debug("Langfuse game context enter failed", exc_info=True)
        yield None
        return

    try:
        yield value
    except BaseException:
        exc_info = sys.exc_info()
        try:
            suppress = bool(context.__exit__(*exc_info))
        except Exception:  # noqa: BLE001 - tracing cleanup is advisory
            _log.debug("Langfuse game context exception cleanup failed", exc_info=True)
            suppress = False
        if not suppress:
            raise
    else:
        try:
            context.__exit__(None, None, None)
        except Exception:  # noqa: BLE001 - tracing cleanup is advisory
            _log.debug("Langfuse game context cleanup failed", exc_info=True)


def _flush_langfuse(observability: Any) -> None:
    flush = getattr(observability, "flush_langfuse", None)
    if not callable(flush):
        return
    try:
        flush()
    except Exception:  # noqa: BLE001 - observability must not affect game execution
        _log.debug("Langfuse game flush failed", exc_info=True)


def _langfuse_decision_records(state: dict) -> list[Any]:
    decisions = state.get("decisions")
    if isinstance(decisions, list):
        return list(decisions)
    recorder = state.get("recorder")
    records = getattr(recorder, "records", None)
    if isinstance(records, list):
        return [record.to_dict() if hasattr(record, "to_dict") else record for record in records]
    return []


def _langfuse_game_events(state: dict) -> list[Any]:
    events = state.get("game_events")
    if not isinstance(events, list):
        events = state.get("events")
    if isinstance(events, list):
        return list(events)
    engine = state.get("engine")
    logger = getattr(engine, "logger", None) if engine is not None else state.get("logger")
    entries = getattr(logger, "entries", None)
    if isinstance(entries, list):
        return [entry.to_dict() if hasattr(entry, "to_dict") else entry for entry in entries]
    return []


def _game_timeout(state: dict) -> float | None:
    raw_value = _state_or_env_value(
        state,
        "game_timeout",
        env_names=("WEREWOLF_GAME_TIMEOUT", "WEREWOLF_RUNNER_GAME_TIMEOUT"),
    )
    if raw_value is None:
        raw_value = _state_or_env_value(
            state,
            "runner_game_timeout",
            env_names=(),
        )
    if raw_value in {None, ""}:
        return None
    try:
        timeout = float(raw_value)
    except (TypeError, ValueError):
        return None
    return timeout if timeout > 0 else None


def _runner_action_timeout(state: dict) -> float | None:
    return _runner_float_config(
        state,
        "runner_action_timeout",
        env_names=("WEREWOLF_LLM_TIMEOUT",),
        default=None,
        minimum=0.0,
        none_on_non_positive=True,
    )


def _runner_max_retries(state: dict) -> int:
    from engine import STANDARD_12

    raw_value = _state_or_env_value(
        state,
        "runner_max_retries",
        env_names=("WEREWOLF_RUNNER_MAX_RETRIES",),
    )
    if raw_value is None:
        return STANDARD_12.runner_max_retries
    try:
        return max(1, int(raw_value))
    except (TypeError, ValueError):
        return STANDARD_12.runner_max_retries


def _runner_retry_delay(state: dict) -> float:
    from engine import STANDARD_12

    return _runner_float_config(
        state,
        "runner_retry_delay",
        env_names=("WEREWOLF_RUNNER_RETRY_DELAY",),
        default=STANDARD_12.runner_retry_delay,
        minimum=0.0,
        none_on_non_positive=False,
    ) or 0.0


_AGENT_RUNTIME_CONFIG_KEYS: tuple[str, ...] = (
    "langfuse_trace_id",
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


def _agent_runtime_config(state: dict) -> dict[str, Any]:
    cfg = state.get("config")
    result: dict[str, Any] = {}
    for key in _AGENT_RUNTIME_CONFIG_KEYS:
        value = state.get(key)
        if value is None and isinstance(cfg, dict):
            value = cfg.get(key)
        if value is not None:
            result[key] = value
    return result


def _state_or_env_value(state: dict, key: str, *, env_names: tuple[str, ...]) -> Any:
    cfg = state.get("config")
    raw_value = state.get(key)
    if raw_value is None and isinstance(cfg, dict):
        raw_value = cfg.get(key)
    if raw_value is None:
        for env_name in env_names:
            env_value = os.environ.get(env_name)
            if env_value not in {None, ""}:
                return env_value
    return raw_value


def _runner_float_config(
    state: dict,
    key: str,
    *,
    env_names: tuple[str, ...],
    default: float | None,
    minimum: float,
    none_on_non_positive: bool,
) -> float | None:
    raw_value = _state_or_env_value(state, key, env_names=env_names)
    if raw_value is None:
        raw_value = default
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return None
    if none_on_non_positive and value <= minimum:
        return None
    return max(minimum, value)


def _ensure_game_persistence(state: dict) -> Any | None:
    existing = _persistence_handle(state)
    if existing is not None:
        return existing

    from storage.provider import storage_provider_from_env
    from storage.run_policy import RunType, policy_for_run_type
    from storage.runtime import GamePersistence

    game_id = str(state.get("game_id") or "unknown")
    run_type = RunType(_storage_run_type(state))
    run_metadata = _run_metadata(state, game_id=game_id)
    provider = state.get("storage_provider") or storage_provider_from_env(paths=state.get("paths"))
    persistence = GamePersistence(
        game_id=game_id,
        game_dir=state.get("game_dir"),
        provider=provider,
        source_game_id=str(state.get("source_game_id") or game_id),
        run_policy=policy_for_run_type(run_type),
        run_metadata=run_metadata,
    )
    state["game_persistence"] = persistence
    state["game_persistence_owner"] = True
    return persistence


def _storage_run_type(state: dict) -> str:
    explicit = state.get("storage_run_type")
    if explicit:
        return str(explicit)
    run_type = str(state.get("run_type") or "").lower()
    if run_type in {"eval", "evaluation", "evaluation_batch"}:
        return "evaluation_batch"
    if run_type in {"evolve", "evolution"}:
        return "evolution_training"
    return "ordinary_game"


def _run_metadata(state: dict, *, game_id: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "mode": state.get("mode") or "dev",
        "source_run_id": state.get("source_run_id") or game_id,
        "ruleset_version": state.get("ruleset_version") or "werewolf_12p_v1",
    }
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
        if state.get(key) is not None:
            metadata[key] = state[key]
    if state.get("paired_seed") is not None:
        metadata["paired_seed"] = bool(state.get("paired_seed"))
    return metadata


def _persistence_config(state: dict) -> dict[str, Any]:
    config = {
        "max_days": state.get("max_days", 20),
        "player_count": state.get("player_count", 12),
        "enable_sheriff": state.get("enable_sheriff", True),
        "skill_dir": state.get("skill_dir"),
        "role_skill_dirs": state.get("role_skill_dirs") or {},
        "run_type": _storage_run_type(state),
        "mode": state.get("mode") or "dev",
        "source_run_id": state.get("source_run_id") or state.get("game_id"),
        "source_game_id": state.get("source_game_id") or state.get("game_id"),
    }
    for key in (
        "model_id",
        "model_config_hash",
        "comparison_group_id",
        "comparison_type",
        "target_role",
        "target_version_id",
        "seed_set_id",
        "evaluation_set_id",
        "paired_seed",
    ):
        if state.get(key) is not None:
            config[key] = state[key]
    return config


def _normalize_player_roles(raw_roles: Any) -> dict[int, str]:
    roles: dict[int, str] = {}
    if not isinstance(raw_roles, dict):
        return roles
    for player_id, role in raw_roles.items():
        try:
            seat = int(player_id)
        except (TypeError, ValueError):
            continue
        roles[seat] = str(role.value if hasattr(role, "value") else role)
    return roles


def _final_state_payload(state: dict, *, finished_at: str) -> dict[str, Any]:
    error = str(state.get("error") or "")
    payload: dict[str, Any] = {
        "finished": bool(state.get("finished", False)),
        "status": "failed" if error else "completed",
        "winner": state.get("winner"),
        "outcome": state.get("outcome"),
        "terminal_reason": state.get("terminal_reason"),
        "error": error or None,
        "started_at": state.get("started_at"),
        "finished_at": finished_at,
    }
    engine = state.get("engine")
    if engine is not None and hasattr(engine, "snapshot"):
        snapshot = engine.snapshot()
        if isinstance(snapshot, dict):
            payload["snapshot"] = snapshot
            payload["deaths"] = list(snapshot.get("deaths") or [])
            payload["players"] = dict(snapshot.get("players") or {})
    return payload


def _final_alive(final_state: dict[str, Any]) -> dict[int, bool] | None:
    players = final_state.get("players")
    if not isinstance(players, dict):
        return None
    alive: dict[int, bool] = {}
    for player_id, player in players.items():
        if not isinstance(player, dict):
            continue
        try:
            seat = int(player_id)
        except (TypeError, ValueError):
            continue
        alive[seat] = bool(player.get("alive", True))
    return alive


def _max_event_day(events: list[dict[str, Any]]) -> int:
    days: list[int] = []
    for event in events:
        try:
            days.append(int(event.get("day", 0) or 0))
        except (TypeError, ValueError):
            continue
    return max(days) if days else 0
