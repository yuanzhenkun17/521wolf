from __future__ import annotations

from engine.models import Role
from engine.role_rules.base import BaseRoleRule


class VillagerRule(BaseRoleRule):
    role = Role.VILLAGER
