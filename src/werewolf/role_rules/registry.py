from __future__ import annotations

from werewolf.models import Role
from werewolf.role_rules.base import RoleRule
from werewolf.role_rules.guard import GuardRule
from werewolf.role_rules.hunter import HunterRule
from werewolf.role_rules.seer import SeerRule
from werewolf.role_rules.villager import VillagerRule
from werewolf.role_rules.werewolf import WerewolfRule
from werewolf.role_rules.white_wolf_king import WhiteWolfKingRule
from werewolf.role_rules.witch import WitchRule


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
