from __future__ import annotations

from werewolf.models import Role
from werewolf.role_rules.base import BaseRoleRule


class HunterRule(BaseRoleRule):
    role = Role.HUNTER
