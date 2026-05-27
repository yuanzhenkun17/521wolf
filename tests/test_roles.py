import unittest

from engine.config import STANDARD_12
from engine.roles import assign_roles, random_standard_roles, roles_from_config, standard_roles


class RolesTests(unittest.TestCase):
    def test_standard_config_counts_players_and_roles(self):
        self.assertEqual(STANDARD_12.player_count, 12)
        self.assertEqual(sorted(role.value for role in roles_from_config(STANDARD_12)), sorted(role.value for role in standard_roles().values()))

    def test_random_standard_roles_keeps_role_counts_and_changes_seats_by_seed(self):
        roles_a = random_standard_roles(seed=1)
        roles_b = random_standard_roles(seed=2)

        self.assertEqual(set(roles_a), set(range(1, 13)))
        self.assertEqual(sorted(role.value for role in roles_a.values()), sorted(role.value for role in standard_roles().values()))
        self.assertEqual(roles_a, random_standard_roles(seed=1))
        self.assertNotEqual(roles_a, roles_b)

    def test_assign_roles_uses_config_player_count(self):
        roles = assign_roles(STANDARD_12, seed=1)

        self.assertEqual(set(roles), set(range(1, STANDARD_12.player_count + 1)))
        self.assertEqual(sorted(role.value for role in roles.values()), sorted(role.value for role in standard_roles().values()))


if __name__ == "__main__":
    unittest.main()
