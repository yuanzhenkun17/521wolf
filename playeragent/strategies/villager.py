from __future__ import annotations

from werewolf.models import ActionRequest

from playeragent.belief import BeliefState
from playeragent.decision import StrategyAdvice
from playeragent.memory import AgentMemory
from playeragent.strategies.base import RoleStrategy


class VillagerStrategy(RoleStrategy):
    def advise(self, request: ActionRequest, memory: AgentMemory, belief: BeliefState) -> StrategyAdvice:
        advice = super().advise(request, memory, belief)
        advice.private_notes.append("村民没有私有验人信息，应更多依赖公开发言、投票和死亡信息。")
        return advice
