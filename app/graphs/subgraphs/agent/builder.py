"""Agent decision subgraph builder — 7-step pipeline as StateGraph."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from app.graphs.shared.state import AgentState


def build_agent_subgraph() -> Any:
    """Build the agent decision subgraph.

    Nodes:
        remember -> compress -> select_skills -> build_prompt -> call_model -> parse -> enforce_policy

    Conditional edges:
        compress: skip if no old segments
        call_model: retry on error, fallback on repeated failure
    """
    from app.graphs.subgraphs.agent.nodes import (
        AgentMemory,
        _build_prompt_node,
        _call_model_node,
        _compress_node,
        _enforce_policy_node,
        _parse_node,
        _remember_node,
        _select_skills_node,
    )

    workflow = StateGraph(AgentState)

    def _memory(state: AgentState) -> AgentMemory:
        memory = state.get("memory")
        if memory is None:
            from engine import Role

            role = Role(state.get("role", "villager"))
            memory = AgentMemory(player_id=int(state["player_id"]), role=role)
        if state.get("game_id"):
            memory.game_id = state.get("game_id")
        return memory

    async def _remember(state: AgentState) -> dict:
        memory = _memory(state)
        result = _remember_node(dict(state), memory)
        result["memory"] = memory
        return result

    async def _compress(state: AgentState) -> dict:
        model = state.get("model")
        if model is None:
            return dict(state)
        memory = _memory(state)
        result = await _compress_node(dict(state), memory, model)
        result["memory"] = memory
        return result

    async def _select_skills(state: AgentState) -> dict:
        return _select_skills_node(
            dict(state),
            skill_root=state.get("skill_dir"),
        )

    async def _build_prompt(state: AgentState) -> dict:
        return _build_prompt_node(dict(state))

    async def _call_model(state: AgentState) -> dict:
        model = state.get("model")
        if model is None:
            result = dict(state)
            result["errors"] = result.get("errors", []) + ["No model provided for agent graph."]
            result["source"] = "llm_error"
            result["raw_output"] = ""
            return result
        return await _call_model_node(dict(state), model)

    async def _parse(state: AgentState) -> dict:
        return _parse_node(dict(state))

    async def _enforce_policy(state: AgentState) -> dict:
        return _enforce_policy_node(dict(state))

    workflow.add_node("remember", _remember)
    workflow.add_node("compress", _compress)
    workflow.add_node("select_skills", _select_skills)
    workflow.add_node("build_prompt", _build_prompt)
    workflow.add_node("call_model", _call_model)
    workflow.add_node("parse", _parse)
    workflow.add_node("enforce_policy", _enforce_policy)

    workflow.add_edge(START, "remember")
    workflow.add_edge("remember", "compress")
    workflow.add_edge("compress", "select_skills")
    workflow.add_edge("select_skills", "build_prompt")
    workflow.add_edge("build_prompt", "call_model")
    workflow.add_edge("call_model", "parse")
    workflow.add_edge("parse", "enforce_policy")
    workflow.add_edge("enforce_policy", END)

    return workflow.compile()
