from __future__ import annotations

from werewolf.models import ActionRequest, ActionType

from playeragent.belief import BeliefState
from playeragent.decision import StrategyAdvice
from playeragent.memory import AgentMemory


class RoleStrategy:
    def advise(self, request: ActionRequest, memory: AgentMemory, belief: BeliefState) -> StrategyAdvice:
        if request.action_type in {ActionType.EXILE_VOTE, ActionType.PK_VOTE, ActionType.HUNTER_SHOOT}:
            targets = belief.most_suspicious(request.candidates)
            return StrategyAdvice(
                goal="根据当前发言、票型和私有信息寻找狼人或高风险目标。",
                preferred_targets=targets[:3],
                public_stance="给出清晰怀疑对象，并说明可公开解释的理由。",
            )
        if request.action_type in {ActionType.SPEAK, ActionType.PK_SPEAK, ActionType.LAST_WORD}:
            targets = belief.most_suspicious(tuple(request.observation.alive_players))
            return StrategyAdvice(
                goal="表达当前站边、怀疑对象和投票倾向。",
                preferred_targets=[target for target in targets if target != request.player_id][:3],
                public_stance="发言要像真实玩家，避免暴露不可公开的私有信息。",
            )
        if request.action_type is ActionType.SHERIFF_RUN:
            return StrategyAdvice(
                goal="判断自己是否适合争取警徽。",
                public_stance="如果竞选，要给出能被其他玩家接受的理由。",
            )
        if request.action_type is ActionType.SHERIFF_WITHDRAW:
            return StrategyAdvice(
                goal="判断是否继续争警长，避免无意义集体退水。",
                public_stance="如果退水，需要说明让位逻辑。",
            )
        return StrategyAdvice(goal="选择当前动作下最合理且合法的行动。")
