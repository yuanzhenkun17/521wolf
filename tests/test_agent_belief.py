from __future__ import annotations

import unittest

from agent.core.belief import BeliefState
from agent.core.belief import PlayerBelief
from agent.core.memory import AgentMemory
from engine.models import ActionRequest, ActionType, Observation, Phase, Role


def _request(public_log: list[str], *, dead_players: tuple[int, ...] = ()) -> ActionRequest:
    return ActionRequest(
        player_id=5,
        action_type=ActionType.EXILE_VOTE,
        phase=Phase.EXILE_VOTE,
        observation=Observation(
            player_id=5,
            self_role=Role.VILLAGER,
            phase=Phase.EXILE_VOTE,
            day=2,
            alive_players=(1, 2, 3, 5, 6, 8, 9, 10),
            dead_players=dead_players,
            sheriff_id=None,
            public_log=tuple(public_log),
            known_roles={},
            seer_checks={},
            metadata={},
        ),
        candidates=(1, 2, 3, 6, 8, 9, 10),
    )


class BeliefWeightedEvidenceTests(unittest.TestCase):
    def test_trusted_source_suspicion_increases_target_wolf_probability(self):
        memory = AgentMemory(player_id=5, role=Role.VILLAGER)
        belief = BeliefState(player_id=5, role=Role.VILLAGER)
        request = _request(["1号发言怀疑3号"])

        memory.build_context(request)
        belief.update_from_request(request, memory)

        target = belief.players[3]
        self.assertGreater(target.wolf_prob, 0.33)
        self.assertTrue(
            any(e.direction == "wolf" and e.source == 1 for e in target.evidence),
            target.evidence,
        )

    def test_high_wolf_source_attack_is_good_evidence_for_target(self):
        memory = AgentMemory(player_id=5, role=Role.VILLAGER)
        belief = BeliefState(player_id=5, role=Role.VILLAGER)

        # Seed P1 as a high-wolf source before processing their accusation.
        belief.players[1] = PlayerBelief(player_id=1)
        belief.players[1].set_certainty(wolf=10.0, villager=0.2, god=0.2)

        request = _request(["1号发言怀疑3号"])
        memory.build_context(request)
        belief.update_from_request(request, memory)

        target = belief.players[3]
        self.assertLess(target.wolf_prob, 0.33)
        self.assertTrue(
            any(e.direction == "good" and e.source == 1 for e in target.evidence),
            target.evidence,
        )

    def test_werewolf_night_death_does_not_increase_wolf_probability(self):
        memory = AgentMemory(player_id=5, role=Role.VILLAGER)
        belief = BeliefState(player_id=5, role=Role.VILLAGER)
        request = _request(["Player 4 died by werewolf"], dead_players=(4,))

        memory.build_context(request)
        belief.update_from_request(request, memory)

        dead = belief.players[4]
        self.assertLess(dead.wolf_prob, 0.33)
        self.assertTrue(
            any(e.type == "death" and e.direction == "good" for e in dead.evidence),
            dead.evidence,
        )


if __name__ == "__main__":
    unittest.main()
