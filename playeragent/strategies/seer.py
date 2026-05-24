from __future__ import annotations

from werewolf.models import ActionRequest, ActionType

from playeragent.belief import BeliefState
from playeragent.decision import StrategyAdvice
from playeragent.memory import AgentMemory
from playeragent.strategies.base import RoleStrategy


class SeerStrategy(RoleStrategy):
    def advise(self, request: ActionRequest, memory: AgentMemory, belief: BeliefState) -> StrategyAdvice:
        if request.action_type is ActionType.SEER_CHECK:
            targets = belief.most_suspicious(request.candidates)
            return StrategyAdvice(
                goal="查验最需要定性的高风险玩家，帮助白天建立站边。",
                preferred_targets=targets[:3],
                private_notes=["优先查验高狼面、发言带节奏或票型关键的位置。"],
            )
        advice = super().advise(request, memory, belief)
        advice.private_notes.append("预言家要围绕查验结果建立可信度，避免把不可证明的信息说得过满。")
        return advice
