from __future__ import annotations

from engine.models import Role
from engine.role_rules.base import RoleRule
from engine.role_rules.guard import GuardRule
from engine.role_rules.hunter import HunterRule
from engine.role_rules.seer import SeerRule
from engine.role_rules.villager import VillagerRule
from engine.role_rules.werewolf import WerewolfRule
from engine.role_rules.white_wolf_king import WhiteWolfKingRule
from engine.role_rules.witch import WitchRule


ROLE_RULES: dict[Role, RoleRule] = {
    Role.WEREWOLF: WerewolfRule(),
    Role.WHITE_WOLF_KING: WhiteWolfKingRule(),
    Role.VILLAGER: VillagerRule(),
    Role.SEER: SeerRule(),
    Role.WITCH: WitchRule(),
    Role.HUNTER: HunterRule(),
    Role.GUARD: GuardRule(),
}


def rule_for(role: Role) -> RoleRule:
    return ROLE_RULES[role]
