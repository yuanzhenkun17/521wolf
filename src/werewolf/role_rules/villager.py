from __future__ import annotations

from werewolf.models import Role
from werewolf.role_rules.base import BaseRoleRule


class VillagerRule(BaseRoleRule):
    role = Role.VILLAGER
