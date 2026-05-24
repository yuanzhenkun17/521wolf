from __future__ import annotations

from playeragent.adapters import ModelAdapter
from playeragent.belief import BeliefState
from playeragent.decision import DecisionRecord
from playeragent.memory import AgentMemory
from playeragent.parsing import parse_action_response, parse_decision_record
from playeragent.policies import apply_response_policy, fallback_response
from playeragent.prompts import build_messages, default_persona
from playeragent.strategies import strategy_for
from werewolf.models import ActionRequest, ActionResponse, Role


class AgentRuntime:
    def __init__(
        self,
        *,
        player_id: int,
        role: Role,
        model: ModelAdapter,
        persona: str | None = None,
        memory: AgentMemory | None = None,
        belief: BeliefState | None = None,
    ) -> None:
        self.player_id = player_id
        self.role = role
        self.model = model
        self.persona = persona or default_persona(player_id, role)
        self.memory = memory or AgentMemory(player_id=player_id, role=role)
        self.belief = belief or BeliefState(player_id=player_id, role=role)
        self.strategy = strategy_for(role)

    async def act(self, request: ActionRequest) -> ActionResponse:
        memory_context = self.memory.build_context(request)
        belief_context = self.belief.build_context(request, self.memory)
        strategy_advice = self.strategy.advise(request, self.memory, self.belief)
        messages = build_messages(
            request,
            player_id=self.player_id,
            role=self.role,
            persona=self.persona,
            memory_context=memory_context,
            belief_context=belief_context,
            strategy_advice=strategy_advice,
        )
        content = ""
        try:
            content = await self.model.complete(messages)
            response = parse_action_response(request, content)
            original_response = response
            response = apply_response_policy(request, response)
            decision = parse_decision_record(request, content, response)
            if response != original_response:
                decision.source = "policy_adjusted"
        except Exception as exc:
            self.memory.remember_error(f"模型调用或解析失败，使用回退动作: {exc}")
            response = fallback_response(request)
            decision = fallback_decision(request, response, str(exc), belief_context, memory_context)
        enrich_decision(decision, belief_context, memory_context)
        self.memory.remember_action(request, response, decision)
        return response


def fallback_decision(
    request: ActionRequest,
    response: ActionResponse,
    error: str,
    belief_context: dict,
    memory_context: dict,
) -> DecisionRecord:
    return DecisionRecord(
        action_type=request.action_type,
        day=request.observation.day,
        phase=request.phase.value,
        player_id=request.player_id,
        role=request.observation.self_role.value,
        candidates=list(request.candidates),
        selected_target=response.target,
        selected_choice=response.choice,
        public_text=response.text,
        private_reasoning=f"模型调用或解析失败，使用合法回退动作。错误：{error}",
        alternatives=list(request.candidates[:3]),
        rejected_reasons=["优先保证返回规则层可接受的合法动作"],
        belief_snapshot=belief_context,
        memory_summary=memory_context.get("memory_events", [])[-6:],
        source="fallback",
    )


def enrich_decision(decision: DecisionRecord, belief_context: dict, memory_context: dict) -> None:
    if not decision.private_reasoning:
        decision.private_reasoning = "模型未提供 reasoning；记录最终动作作为决策依据。"
    if not decision.alternatives:
        decision.alternatives = []
    if not decision.rejected_reasons:
        decision.rejected_reasons = ["模型未提供 rejected_reasons。"]
    decision.belief_snapshot = belief_context
    decision.memory_summary = memory_context.get("memory_events", [])[-6:]
