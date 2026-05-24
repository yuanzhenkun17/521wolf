from __future__ import annotations

from werewolf.models import ActionRequest, ActionType

from playeragent.belief import BeliefState
from playeragent.decision import StrategyAdvice
from playeragent.memory import AgentMemory
from playeragent.strategies.base import RoleStrategy


class WitchStrategy(RoleStrategy):
    def advise(self, request: ActionRequest, memory: AgentMemory, belief: BeliefState) -> StrategyAdvice:
        if request.action_type is ActionType.WITCH_ACT:
            attacked = request.metadata.get("attacked_player")
            return StrategyAdvice(
                goal="根据被刀对象、药是否可用和局势决定救药或毒药。",
                preferred_targets=belief.most_suspicious(request.candidates)[:3],
                public_stance="",
                private_notes=[
                    f"昨夜被刀对象: {attacked}",
                    "女巫行动属于私有信息，白天不要轻易暴露用药细节。",
                ],
            )
        advice = super().advise(request, memory, belief)
        advice.private_notes.append("女巫白天应谨慎透露身份，除非局势需要带队或自证。")
        return advice
