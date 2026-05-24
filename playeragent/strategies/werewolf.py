from __future__ import annotations

from werewolf.models import ActionRequest, ActionType

from playeragent.belief import BeliefState
from playeragent.decision import StrategyAdvice
from playeragent.memory import AgentMemory
from playeragent.strategies.base import RoleStrategy


class WerewolfStrategy(RoleStrategy):
    def advise(self, request: ActionRequest, memory: AgentMemory, belief: BeliefState) -> StrategyAdvice:
        advice = super().advise(request, memory, belief)
        teammates = sorted(request.observation.known_roles)
        if request.action_type is ActionType.WEREWOLF_KILL:
            candidates = [candidate for candidate in request.candidates if candidate not in teammates]
            trusted = belief.most_trusted(tuple(candidates))
            return StrategyAdvice(
                goal="夜晚选择对狼人阵营最有价值的击杀目标。",
                preferred_targets=trusted[:3],
                avoid_targets=teammates,
                public_stance="",
                private_notes=["优先刀疑似神职或带队好人，不能选择狼队友。"],
            )
        advice.avoid_targets.extend(teammates)
        advice.private_notes.append("狼人白天要隐藏队友关系，把怀疑引向好人，公开发言不能暴露狼队视角。")
        return advice
