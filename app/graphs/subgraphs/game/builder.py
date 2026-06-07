"""Game subgraph builder — StateGraph for a single game."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.graphs.shared.state import GameState
from app.graphs.subgraphs.game.nodes import (
    create_agents_node,
    game_loop_node,
    init_engine_node,
    persist_node,
    record_events_node,
)


def build_game_subgraph(
    agent_subgraph: Any = None,
    *,
    checkpointer: Any = None,
) -> Any:
    """Build the game subgraph.

    Pipeline: init_engine → create_agents → game_loop → record → persist

    Args:
        agent_subgraph: Optional compiled agent decision subgraph.
                        If provided, agents use it. Otherwise sequential fallback.
        checkpointer: Optional LangGraph checkpointer for state persistence.
    """
    workflow = StateGraph(GameState)

    workflow.add_node("init_engine", init_engine_node)

    async def _create_agents_with_subgraph(state: GameState) -> dict:
        if agent_subgraph is not None:
            state["agent_subgraph"] = agent_subgraph
        return await create_agents_node(state)

    workflow.add_node("create_agents", _create_agents_with_subgraph)
    workflow.add_node("game_loop", game_loop_node)
    workflow.add_node("record", record_events_node)
    workflow.add_node("persist", persist_node)

    workflow.add_edge(START, "init_engine")
    workflow.add_edge("init_engine", "create_agents")
    workflow.add_edge("create_agents", "game_loop")

    # After game loop: always record
    workflow.add_edge("game_loop", "record")

    # After recording: persist if game_dir is set, else end
    def _should_persist(state: GameState) -> str:
        if state.get("game_dir"):
            return "persist"
        return END

    workflow.add_conditional_edges("record", _should_persist, {"persist": "persist", END: END})
    workflow.add_edge("persist", END)

    if checkpointer is not None:
        return workflow.compile(checkpointer=checkpointer)
    return workflow.compile()
