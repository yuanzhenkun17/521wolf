"""Root graph builder — dispatch to play / eval / evolve pipelines."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.graphs.shared.state import RootState
from app.graphs.subgraphs.play.builder import build_play_graph
from app.graphs.subgraphs.eval.builder import build_eval_graph
from app.graphs.subgraphs.evolve.builder import build_evolve_graph
from app.graphs.subgraphs.game.builder import build_game_subgraph
from app.graphs.subgraphs.agent.builder import build_agent_subgraph
from app.graphs.shared.nodes.review import review_node
from app.graphs.main.router import _dispatch


# Graph cache — built once, reused
_cache: dict[str, Any] = {}


def build_root_graph(*, use_checkpointer: bool = False) -> Any:
    """Build the root dispatch graph.

    Returns a compiled StateGraph with nodes: play, eval, evolve.
    Dispatch based on state["run_type"].

    Args:
        use_checkpointer: Enable SQLite checkpointing for state persistence.
    """
    cache_key = f"root:checkpointer={use_checkpointer}"
    if cache_key in _cache:
        return _cache[cache_key]

    workflow = StateGraph(RootState)

    # Build subgraphs lazily
    agent_graph = _build_cached("agent", build_agent_subgraph)
    game_graph = _build_cached("game", lambda: build_game_subgraph(agent_subgraph=agent_graph))

    workflow.add_node("play", build_play_graph(game_subgraph=game_graph, review_node=review_node))
    workflow.add_node("eval", build_eval_graph(game_subgraph=game_graph))
    workflow.add_node("evolve", build_evolve_graph(game_subgraph=game_graph))

    workflow.add_conditional_edges(
        START,
        lambda s: _dispatch(s),
        {"play": "play", "eval": "eval", "evolve": "evolve"},
    )
    workflow.add_edge("play", END)
    workflow.add_edge("eval", END)
    workflow.add_edge("evolve", END)

    checkpointer = None
    if use_checkpointer:
        from langgraph.checkpoint.sqlite import SqliteSaver
        import sqlite3
        from app.config import DEFAULT_PATHS
        db_path = str(DEFAULT_PATHS.wolf_db_path).replace(".db", "_checkpoint.db")
        conn = sqlite3.connect(db_path, check_same_thread=False)
        checkpointer = SqliteSaver(conn)

    graph = workflow.compile(checkpointer=checkpointer)
    _cache[cache_key] = graph
    return graph

def _build_cached(key: str, builder: Any) -> Any:
    """Build and cache a subgraph."""
    if key not in _cache:
        _cache[key] = builder()
    return _cache[key]
