from __future__ import annotations

from werewolf.models import ActionRequest, ActionType

from playeragent.belief import BeliefState
from playeragent.decision import StrategyAdvice
from playeragent.memory import AgentMemory
from playeragent.strategies.werewolf import WerewolfStrategy


class WhiteWolfKingStrategy(WerewolfStrategy):
    def advise(self, request: ActionRequest, memory: AgentMemory, belief: BeliefState) -> StrategyAdvice:
        if request.action_type is ActionType.WHITE_WOLF_EXPLODE:
            trusted = belief.most_trusted(request.candidates)
            return StrategyAdvice(
                goal="判断是否自爆并带走关键好人或神职。",
                preferred_targets=trusted[:3],
                private_notes=["只有在能显著扩大狼队优势时才自爆，公开遗言仍要伪装视角。"],
            )
        advice = super().advise(request, memory, belief)
        advice.private_notes.append("白狼王要寻找能带走关键神职的自爆时机。")
        return advice
