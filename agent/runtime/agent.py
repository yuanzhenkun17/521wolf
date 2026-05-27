"""Agent — ``AgentRuntime`` (decision pipeline) and ``LLMPlayerAgent`` (rule-layer adapter).

Receives ``ActionRequest`` from the game engine, chains nodes
(observe -> memory -> belief -> skill_router -> prompt -> llm -> parse -> policy -> log),
and returns ``ActionResponse``.

Key responsibilities:
- Node orchestration: each node reads from / writes to ``AgentContext``.
- ToT integration: for key actions, the reasoning node generates multiple
  candidates and a judge selects the best one, bypassing the normal LLM call.
- GoT integration: for high-conflict key actions, the reasoning node builds
  an evidence/hypothesis graph before selecting the final action.
- Decision recording: writes ``DecisionRecord`` entries to the shared recorder.
- Trace recording: if a ``trace_recorder`` is attached, every decision context
  is archived for post-game analysis.

``LLMPlayerAgent`` wraps the runtime as a rule-layer ``PlayerAgent`` so it
drops into any existing game without rule-layer changes.
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator

from langfuse import observe, propagate_attributes
from engine.models import ActionRequest, ActionResponse, Role

from agent.cognition.belief import BeliefState
from agent.cognition.memory import AgentMemory
from agent.observability.archive import AgentTraceRecorder
from agent.observability.decision_log import AgentDecisionRecorder
from agent.prompts.instructions import default_persona
from agent.runtime.context import AgentContext
from agent.runtime.model import ModelAdapter
from agent.nodes.observe import observe_node
from agent.nodes.memory import memory_node
from agent.nodes.belief import belief_node
from agent.nodes.skill_router import skill_router_node
from agent.nodes.prompt import prompt_node
from agent.nodes.llm import llm_node
from agent.nodes.parse import parse_node
from agent.nodes.policy import policy_node
from agent.nodes.log import log_node
from agent.nodes.got import got_node
from agent.nodes.tot import tot_node
from agent.observability.stream import get_broadcaster, stream_decision


@contextmanager
def _noop() -> Iterator[None]:
    yield


class AgentRuntime:
    """Graph-like runtime that chains decision nodes.

    Pipeline::

        ActionRequest
        -> observe_node
        -> memory_node
        -> belief_node
        -> skill_router_node
        -> prompt_node
        -> llm_node        (async)
        -> parse_node
        -> policy_node
        -> log_node
        -> ActionResponse
    """

    def __init__(
        self,
        *,
        player_id: int,
        role: Role,
        model: ModelAdapter,
        persona: str | None = None,
        memory: AgentMemory | None = None,
        belief: BeliefState | None = None,
        recorder: AgentDecisionRecorder | None = None,
        trace_recorder: AgentTraceRecorder | None = None,
        game_id: str | None = None,
        skill_dir: Path | str | None = None,
    ) -> None:
        self.player_id = player_id
        self.role = role
        self.model = model
        self.game_id = game_id
        self.persona = persona or default_persona(player_id, role)
        self.memory = memory or AgentMemory(player_id=player_id, role=role)
        self.belief = belief or BeliefState(player_id=player_id, role=role)
        self.recorder = recorder
        self.trace_recorder = trace_recorder
        self.skill_dir = Path(skill_dir) if skill_dir else None

    @observe(name="act")
    async def act(self, request: ActionRequest) -> ActionResponse:
        ctx = AgentContext(
            request=request,
            player_id=self.player_id,
            role=self.role.value,
        )

        with propagate_attributes(session_id=self.game_id) if self.game_id else _noop():
            # -- synchronous nodes -------------------------------------------------
            ctx = observe_node(ctx)
            ctx = memory_node(ctx, self.memory)
            ctx = belief_node(ctx, self.belief, self.memory)
            ctx = skill_router_node(ctx, skill_root=self.skill_dir)
            ctx = prompt_node(ctx, persona=self.persona)

            # -- GoT/ToT reasoning for key actions --------------------------------
            ctx = await got_node(ctx, self.model)
            if ctx.source != "got":
                ctx = await tot_node(ctx, self.model)

            # -- async LLM call (skipped when GoT/ToT succeeded) ------------------
            if ctx.source in {"got", "tot"}:
                ctx = parse_node(ctx)
            else:
                ctx = await llm_node(ctx, self.model)
                ctx = parse_node(ctx)
            ctx = policy_node(ctx)
            ctx = log_node(ctx, self.recorder)

            # -- optional trace recording for archive ------------------------------
            if self.trace_recorder:
                self.trace_recorder.record(ctx)

            # -- debug WebSocket stream (if a broadcaster is active) ---------------
            bc = get_broadcaster()
            if bc is not None:
                bc.broadcast(stream_decision(ctx))

            # -- write decision record back to memory ------------------------------
            self.memory.remember_action(request, ctx.response, ctx.decision_record)

        return ctx.response  # type: ignore[return-value]


class LLMPlayerAgent:
    """Werewolf player agent backed by the node-based runtime.

    Implements the rule-layer ``PlayerAgent`` protocol.
    """

    def __init__(
        self,
        *,
        player_id: int,
        role: Role,
        client: ModelAdapter,
        persona: str | None = None,
        decision_recorder: AgentDecisionRecorder | None = None,
        trace_recorder: AgentTraceRecorder | None = None,
        game_id: str | None = None,
        skill_dir: Path | str | None = None,
    ) -> None:
        self.player_id = player_id
        self.role = role
        self.runtime = AgentRuntime(
            player_id=player_id,
            role=role,
            model=client,
            persona=persona,
            recorder=decision_recorder,
            trace_recorder=trace_recorder,
            game_id=game_id,
            skill_dir=skill_dir,
        )

    @property
    def persona(self) -> str:
        return self.runtime.persona

    @property
    def memory(self):
        return self.runtime.memory

    @property
    def belief(self):
        return self.runtime.belief

    async def act(self, request: ActionRequest) -> ActionResponse:
        return await self.runtime.act(request)
