"""Play subgraph — ordinary werewolf game pipeline.

Pipeline: init_run → run_game → review → persist_result
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.graphs.shared.state import PlayState


def build_play_graph(
    game_subgraph: Any = None,
    review_node: Any = None,
) -> Any:
    """Build the ordinary play pipeline.

    Args:
        game_subgraph: Compiled game subgraph (built from app.graphs.subgraphs.game).
        review_node: Review node from app.graphs.shared.nodes.review.
    """
    if game_subgraph is None:
        from app.graphs.subgraphs.agent.builder import build_agent_subgraph
        from app.graphs.subgraphs.game.builder import build_game_subgraph

        game_subgraph = build_game_subgraph(agent_subgraph=build_agent_subgraph())
    if review_node is None:
        from app.graphs.shared.nodes.review import review_node as default_review_node

        review_node = default_review_node

    workflow = StateGraph(PlayState)

    async def _init(state: PlayState) -> dict:
        import uuid
        from app.util.time import beijing_now_iso

        cfg = dict(state.get("config", {}))
        state = dict(state)
        state["config"] = cfg
        state["run_type"] = "play"
        state.setdefault("game_id", cfg.get("game_id") or f"play_{uuid.uuid4().hex[:12]}")
        state.setdefault("seed", int(cfg.get("seed", state.get("seed", 0)) or 0))
        state.setdefault("max_days", int(cfg.get("max_days", state.get("max_days", 20)) or 20))
        state.setdefault("player_count", int(cfg.get("player_count", state.get("player_count", 12)) or 12))
        if "skill_dir" not in state and cfg.get("skill_dir") is not None:
            state["skill_dir"] = cfg["skill_dir"]
        if "game_dir" not in state and cfg.get("game_dir") is not None:
            state["game_dir"] = cfg["game_dir"]
        state.setdefault("started_at", beijing_now_iso())
        return state

    workflow.add_node("init_run", _init)

    async def _run_game(state: PlayState) -> dict:
        cfg = dict(state.get("config", {}))
        game_state = {
            "game_id": state.get("game_id"),
            "seed": state.get("seed", cfg.get("seed", 0)),
            "max_days": state.get("max_days", cfg.get("max_days", 20)),
            "player_count": state.get("player_count", cfg.get("player_count", 12)),
            "enable_sheriff": cfg.get("enable_sheriff", state.get("enable_sheriff", True)),
            "model": state.get("model"),
            "skill_dir": state.get("skill_dir") or cfg.get("skill_dir"),
            "paths": state.get("paths"),
            "game_dir": state.get("game_dir") or cfg.get("game_dir"),
        }
        game_result = await game_subgraph.ainvoke(game_state)
        merged = dict(state)
        for key in (
            "roles",
            "game_events",
            "decisions",
            "winner",
            "finished",
            "error",
            "game_id",
            "seed",
            "max_days",
        ):
            if key in game_result:
                merged[key] = game_result[key]
        merged["game"] = {
            "game_id": merged.get("game_id"),
            "seed": merged.get("seed"),
            "winner": merged.get("winner"),
            "player_roles": dict(merged.get("roles", {})),
            "events": list(merged.get("game_events", [])),
            "decisions": list(merged.get("decisions", [])),
            "finished": merged.get("finished", False),
            "error": merged.get("error"),
        }
        return merged

    workflow.add_node("run_game", _run_game)
    workflow.add_node("review", review_node)

    async def _persist(state: PlayState) -> dict:
        from app.util.time import beijing_now_iso

        state = dict(state)
        state["finished_at"] = beijing_now_iso()
        state["result"] = {
            "status": "completed" if not state.get("error") else "failed",
            "game_id": state.get("game_id"),
            "seed": state.get("seed"),
            "winner": state.get("winner"),
            "player_roles": dict(state.get("roles", {})),
            "events": list(state.get("game_events", [])),
            "decisions": list(state.get("decisions", [])),
            "review": state.get("review"),
            "started_at": state.get("started_at", ""),
            "finished_at": state.get("finished_at", ""),
            "error": state.get("error"),
        }
        return state

    workflow.add_node("persist_result", _persist)

    workflow.add_edge(START, "init_run")
    workflow.add_edge("init_run", "run_game")
    workflow.add_edge("run_game", "review")
    workflow.add_edge("review", "persist_result")
    workflow.add_edge("persist_result", END)

    return workflow.compile()
