"""Game subgraph — orchestrates a single werewolf game.

Nodes: init_engine → create_agents → game_loop → record_events → persist
The game_loop node internally invokes the agent_subgraph for each decision.
"""

from __future__ import annotations

import logging
from pathlib import Path
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

    config = replace(STANDARD_12, max_days=max_days, enable_sheriff=enable_sheriff)
    roles = assign_roles(config, seed=seed)
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
    state.setdefault("started_at", beijing_now_iso())
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
    recorder = state.get("recorder") or AgentDecisionRecorder()
    trace_recorder = state.get("trace_recorder")
    agent_subgraph = state.get("agent_subgraph")

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
            )

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

    try:
        winner = await engine.run_until_finished()
        winner_str = winner.value if hasattr(winner, "value") else str(winner)
        state["winner"] = winner_str
    except Exception as exc:
        _log.error("Game loop failed: %s", exc, exc_info=True)
        state["error"] = str(exc)
        state["winner"] = "error"

    state["finished"] = True
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
    """Persist game results to storage."""
    game_id = state.get("game_id", "unknown")
    game_dir = state.get("game_dir")

    if game_dir is not None:
        from app.util.json import write_json, write_jsonl
        from app.util.manifest import atomic_artifact_dir, build_run_manifest, write_manifest
        from app.util.time import beijing_now_iso

        finished_at = state.get("finished_at") or beijing_now_iso()
        state["finished_at"] = finished_at

        events = state.get("game_events", [])
        decisions = state.get("decisions", [])
        error_summary = str(state.get("error") or "")
        status = "failed" if error_summary else "completed"
        config = {
            "max_days": state.get("max_days", 20),
            "player_count": state.get("player_count", 12),
            "enable_sheriff": state.get("enable_sheriff", True),
            "skill_dir": state.get("skill_dir"),
            "role_skill_dirs": state.get("role_skill_dirs") or {},
        }

        with atomic_artifact_dir(game_dir) as out:
            write_jsonl(out / "game_events.jsonl", events)
            write_jsonl(out / "agent_decisions.jsonl", decisions)

            # Write summary
            write_json(out / "meta.json", {
                "game_id": game_id,
                "winner": state.get("winner"),
                "seed": state.get("seed", 0),
                "player_roles": state.get("roles", {}),
                "finished": state.get("finished", False),
            })

            trace_recorder = state.get("trace_recorder")
            if trace_recorder is not None and hasattr(trace_recorder, "flush"):
                trace_recorder.flush(
                    str(game_id),
                    out,
                    seed=state.get("seed", 0),
                    config=config,
                    player_roles=state.get("roles", {}),
                    winner=state.get("winner"),
                    started_at=state.get("started_at"),
                    finished_at=finished_at,
                    public_events=events,
                    final_state={
                        "finished": state.get("finished", False),
                        "error": state.get("error"),
                    },
                )

            manifest = build_run_manifest(
                run_type="game",
                run_id=str(game_id),
                game_id=str(game_id),
                model_config_hash=str(state.get("model_config_hash") or ""),
                seed=int(state.get("seed", 0) or 0),
                config=config,
                started_at=state.get("started_at"),
                finished_at=finished_at,
                status=status,
                error_summary=error_summary,
                paths={
                    "game_dir": str(game_dir),
                    "meta": "meta.json",
                    "events": "game_events.jsonl",
                    "decisions": "agent_decisions.jsonl",
                    "archive": "archive.json",
                },
                metadata={"winner": state.get("winner"), "player_roles": state.get("roles", {})},
            )
            write_manifest(out / "manifest.json", manifest)
            state["manifest"] = manifest

    return state
