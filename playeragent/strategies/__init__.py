from playeragent.strategies.base import RoleStrategy
from playeragent.strategies.guard import GuardStrategy
from playeragent.strategies.hunter import HunterStrategy
from playeragent.strategies.seer import SeerStrategy
from playeragent.strategies.villager import VillagerStrategy
from playeragent.strategies.werewolf import WerewolfStrategy
from playeragent.strategies.white_wolf_king import WhiteWolfKingStrategy
from playeragent.strategies.witch import WitchStrategy
from werewolf.models import Role


_STRATEGIES: dict[Role, RoleStrategy] = {
    Role.VILLAGER: VillagerStrategy(),
    Role.WEREWOLF: WerewolfStrategy(),
    Role.WHITE_WOLF_KING: WhiteWolfKingStrategy(),
    Role.SEER: SeerStrategy(),
    Role.WITCH: WitchStrategy(),
    Role.GUARD: GuardStrategy(),
    Role.HUNTER: HunterStrategy(),
}


def strategy_for(role: Role) -> RoleStrategy:
    return _STRATEGIES[role]


__all__ = ["RoleStrategy", "strategy_for"]
