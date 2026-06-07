"""Evolve subgraph builder — StateGraph for single-role self-evolution."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.graphs.shared.state import EvolveState
from app.graphs.subgraphs.evolve.nodes import (
    apply_node,
    battle_node,
    consolidate_node,
    decide_node,
    init_evolve_node,
    training_node,
)


def build_evolve_graph(game_subgraph: Any = None) -> Any:
    """Build the evolution pipeline graph for a single role.

    Pipeline: init → training → consolidate → apply → battle → decide
    """
    workflow = StateGraph(EvolveState)

    workflow.add_node("init", init_evolve_node)

    async def _training_with_subgraph(state: EvolveState) -> dict:
        if game_subgraph is not None:
            state = {**state, "game_subgraph": game_subgraph}
        return await training_node(state)

    async def _battle_with_subgraph(state: EvolveState) -> dict:
        if game_subgraph is not None:
            state = {**state, "game_subgraph": game_subgraph}
        return await battle_node(state)

    workflow.add_node("training", _training_with_subgraph)
    workflow.add_node("consolidate", consolidate_node)
    workflow.add_node("apply", apply_node)
    workflow.add_node("battle", _battle_with_subgraph)
    workflow.add_node("decide", decide_node)

    workflow.add_edge(START, "init")
    workflow.add_edge("init", "training")
    workflow.add_edge("training", "consolidate")
    workflow.add_edge("consolidate", "apply")
    workflow.add_edge("apply", "battle")
    workflow.add_edge("battle", "decide")
    workflow.add_edge("decide", END)

    return workflow.compile()
