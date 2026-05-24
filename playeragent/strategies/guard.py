from __future__ import annotations

from werewolf.models import ActionRequest, ActionType

from playeragent.belief import BeliefState
from playeragent.decision import StrategyAdvice
from playeragent.memory import AgentMemory
from playeragent.strategies.base import RoleStrategy


class GuardStrategy(RoleStrategy):
    def advise(self, request: ActionRequest, memory: AgentMemory, belief: BeliefState) -> StrategyAdvice:
        if request.action_type is ActionType.GUARD_PROTECT:
            trusted = belief.most_trusted(request.candidates)
            return StrategyAdvice(
                goal="守护最可能被狼人击杀的好人或关键神职。",
                preferred_targets=trusted[:3],
                private_notes=["避免连续守护同一目标，候选列表已经由规则层过滤。"],
            )
        advice = super().advise(request, memory, belief)
        advice.private_notes.append("守卫白天应隐藏身份，避免成为狼刀目标。")
        return advice
