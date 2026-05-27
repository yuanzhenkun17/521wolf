from __future__ import annotations

from engine.models import Role
from engine.role_rules.base import BaseRoleRule


class HunterRule(BaseRoleRule):
    role = Role.HUNTER
