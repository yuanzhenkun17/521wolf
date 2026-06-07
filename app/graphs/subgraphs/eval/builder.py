"""Eval subgraph builder — StateGraph for batch evaluation."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.graphs.shared.state import EvalBatchState
from app.graphs.subgraphs.eval.nodes import (
    aggregate_node,
    fairness_node,
    init_batch_node,
    persist_batch_node,
    run_games_node,
)


def build_eval_graph(
    game_subgraph: Any = None,
    score_lib: Any = None,
) -> Any:
    """Build the evaluation batch graph.

    Pipeline: init_batch → run_games → aggregate → fairness → persist_batch
    """
    workflow = StateGraph(EvalBatchState)

    workflow.add_node("init_batch", init_batch_node)

    async def _run_games_with_subgraph(state: EvalBatchState) -> dict:
        if game_subgraph is not None:
            state = {**state, "game_subgraph": game_subgraph}
        return await run_games_node(state)

    workflow.add_node("run_games", _run_games_with_subgraph)
    workflow.add_node("aggregate", aggregate_node)
    workflow.add_node("fairness", fairness_node)
    workflow.add_node("persist_batch", persist_batch_node)

    workflow.add_edge(START, "init_batch")
    workflow.add_edge("init_batch", "run_games")
    workflow.add_edge("run_games", "aggregate")
    workflow.add_edge("aggregate", "fairness")
    workflow.add_edge("fairness", "persist_batch")
    workflow.add_edge("persist_batch", END)

    return workflow.compile()
