from __future__ import annotations

from werewolf.models import ActionRequest, ActionType

from playeragent.belief import BeliefState
from playeragent.decision import StrategyAdvice
from playeragent.memory import AgentMemory
from playeragent.strategies.base import RoleStrategy


class HunterStrategy(RoleStrategy):
    def advise(self, request: ActionRequest, memory: AgentMemory, belief: BeliefState) -> StrategyAdvice:
        if request.action_type is ActionType.HUNTER_SHOOT:
            targets = belief.most_suspicious(request.candidates)
            return StrategyAdvice(
                goal="死亡后只在有较高把握时开枪带走疑似狼人。",
                preferred_targets=targets[:3],
                private_notes=["避免被狼人诱导带走高可信好人。"],
            )
        advice = super().advise(request, memory, belief)
        advice.private_notes.append("猎人可以适度强势，但不宜过早暴露身份。")
        return advice
