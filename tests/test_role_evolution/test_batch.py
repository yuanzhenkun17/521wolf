from __future__ import annotations

import json
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent.learning.evolution.games import SelfPlayGameResult
from agent.learning.evolution.batch import run_batch_evolution
from agent.learning.evolution.models import SkillConsolidation, SkillDiff, SkillProposal
from agent.learning.evolution.registry import VersionRegistry


def _proposal(role: str) -> SkillProposal:
    return SkillProposal(
        proposal_id=f"{role}_p1",
        target_file="skill.md",
        action_type="rewrite_section",
        content=f"# improved {role}",
        rationale="test",
        confidence=0.9,
        risk="low",
        expected_metric="role_weighted_score",
        expected_direction="up",
    )


async def _fake_consolidator(run_dir, role_arg, model_adapter, **kwargs):
    return SkillConsolidation(
        role=role_arg,
        run_id=kwargs.get("run_id", "evo_test"),
        parent_hash=kwargs.get("parent_hash", ""),
        generated_at="2025-01-01T00:00:00Z",
        source_window=5,
        prompt_version="v1",
        proposals=[_proposal(role_arg)],
    )


async def _fake_applier(current_skills, proposals, model_adapter):
    role = proposals.role
    return (
        {"skill.md": f"# {role} candidate\n"},
        [SkillDiff(filename="skill.md", action="rewrite", proposal_ref=f"{role}_p1")],
    )


async def _passing_battle(
    store,
    role,
    candidate_hash,
    games,
    model_adapter,
    selfplay_runner,
    on_progress=None,
    **kwargs,
):
    return {
        "role": role,
        "candidate_hash": candidate_hash,
        "battle_games": games,
        "baseline": {
            "avg_role_weighted_score": 0.7,
            "fallback_rate": 0.05,
        },
        "candidate": {
            "avg_role_weighted_score": 0.8,
            "fallback_rate": 0.04,
        },
    }


@dataclass
class _FakeSelfplayResult:
    config: Any


async def _fake_selfplay(config, **kwargs):
    on_game_complete = kwargs.get("on_game_complete")
    for i in range(config.games):
        if on_game_complete is not None:
            on_game_complete(
                i,
                SelfPlayGameResult(
                    game_id=f"game_{i + 1:03d}",
                    seed=config.seed_start + i,
                    winner="villagers",
                    days=3,
                    player_roles={},
                    decision_count=10,
                    fallback_count=0,
                    policy_adjusted_count=0,
                    avg_confidence=0.5,
                    review_score=8.0,
                    output_dir=Path("."),
                    role_weighted_score=0.8,
                ),
            )
    return _FakeSelfplayResult(config=config)


class TestBatchEvolution(unittest.IsolatedAsyncioTestCase):
    async def test_batch_evolution_uses_one_snapshot_and_promotes_pack(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = VersionRegistry(Path(tmp) / "role_versions")
            seer_base = await store.publish_skills(
                "seer",
                {"skill.md": "# seer base\n"},
                source="test",
            )
            await store.set_baseline("seer", seer_base, expected_current=None)
            wolf_base = await store.publish_skills(
                "werewolf",
                {"skill.md": "# werewolf base\n"},
                source="test",
            )
            await store.set_baseline("werewolf", wolf_base, expected_current=None)

            result = await run_batch_evolution(
                store=store,
                roles=["seer", "werewolf"],
                training_games=1,
                battle_games=1,
                role_concurrency=2,
                game_concurrency=2,
                llm_concurrency=2,
                auto_promote=True,
                selfplay_runner=_fake_selfplay,
                consolidator=_fake_consolidator,
                applier=_fake_applier,
                battle_runner=_passing_battle,
            )

            self.assertEqual(
                result.baseline_config.role_versions,
                {"seer": seer_base, "werewolf": wolf_base},
            )
            self.assertEqual(set(result.accepted_roles), {"seer", "werewolf"})
            self.assertTrue(result.combined_passed)
            self.assertEqual(set(result.promoted_roles), {"seer", "werewolf"})
            self.assertNotEqual(store.get_baseline("seer"), seer_base)
            self.assertNotEqual(store.get_baseline("werewolf"), wolf_base)
            json.dumps(result.to_dict())


if __name__ == "__main__":
    unittest.main()
