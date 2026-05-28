"""Integration tests for the role evolution pipeline.

Runs real GameEngine games with a FakeModelAdapter (no external LLM calls)
to verify that skill version configuration flows correctly through the
selfplay system to individual agents.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.evaluation.selfplay import SelfPlayConfig, run_selfplay
from agent.role_evolution.config import (
    build_baseline_config,
    build_role_override_config,
    skill_dir_for_role,
)
from agent.role_evolution.store import VersionStore


# ---------------------------------------------------------------------------
# Minimal game config for fast tests
# ---------------------------------------------------------------------------

from engine.config import GameConfig
from engine.models import Role

MINIMAL_6 = GameConfig(
    name="minimal_6",
    role_counts={
        Role.WEREWOLF: 2,
        Role.VILLAGER: 2,
        Role.SEER: 1,
        Role.WITCH: 1,
    },
    enable_sheriff=False,
)


# ---------------------------------------------------------------------------
# FakeModelAdapter — returns fixed valid JSON, no external LLM calls
# ---------------------------------------------------------------------------


class FakeModelAdapter:
    """Fake model adapter that returns a fixed valid JSON response."""

    async def complete(self, messages: list[dict[str, str]], *, name: str = "") -> str:
        return json.dumps({
            "choice": None,
            "target": None,
            "public_text": "测试发言",
            "private_reasoning": "测试推理",
            "confidence": 0.5,
            "alternatives": [],
            "rejected_reasons": [],
            "memory_refs": [],
            "selected_skills": [],
        })


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestSkillVersionIntegration(unittest.IsolatedAsyncioTestCase):
    """Real engine integration tests for skill version config propagation."""

    # -- 1. skill version config propagation -----------------------------------

    async def test_real_engine_skill_version_config_propagation(self):
        """Verify that SelfPlayConfig.skill_version_config flows through to agents.

        Steps:
        1. Create a VersionStore from the real skills/ directory.
        2. Build a baseline SkillVersionConfig with all role hashes.
        3. Build a composite skill_dir and run 1 real selfplay game.
        4. Verify the game completes and skill_dir paths are valid.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store_dir = tmp_path / "agent_versions"
            store = VersionStore(store_dir)

            # Initialize from real skills/ directory
            skills_root = Path("skills")
            store.initialize_from_skills(skills_root)

            # Build baseline config with all role hashes
            config = build_baseline_config(store)
            self.assertGreater(len(config.role_versions), 0)

            # Verify each role's hash resolves to a valid skill directory
            skill_dirs: dict[str, Path] = {}
            for role in config.role_versions:
                sd = store.get_skill_dir(role, config.role_versions[role])
                self.assertTrue(sd.is_dir(), f"Skill dir for {role} does not exist: {sd}")
                # Verify it contains .md files
                md_files = list(sd.rglob("*.md"))
                self.assertGreater(len(md_files), 0, f"No .md files in {sd}")
                skill_dirs[role] = sd

            # Verify different roles got different skill directories
            dir_values = list(skill_dirs.values())
            for i in range(len(dir_values)):
                for j in range(i + 1, len(dir_values)):
                    self.assertNotEqual(
                        dir_values[i], dir_values[j],
                        f"Different roles share the same skill directory: {dir_values[i]}",
                    )

            # Build composite skill directory from the config
            from agent.role_evolution.pipeline import _build_composite_skill_dir

            composite_dir = _build_composite_skill_dir(store, config)
            try:
                # Verify the composite dir exists and contains role subdirectories
                self.assertTrue(composite_dir.is_dir())
                for role in config.role_versions:
                    role_subdir = composite_dir / role
                    self.assertTrue(
                        role_subdir.is_dir(),
                        f"Composite dir missing subdirectory for role {role}",
                    )

                # Run a real selfplay game with the composite skill_dir
                output_dir = tmp_path / "selfplay_output"
                sp_config = SelfPlayConfig(
                    games=1,
                    output_dir=output_dir,
                    enable_review=False,
                    enable_mid_memory=False,
                    enable_long_term_consolidation=False,
                    game_config=MINIMAL_6,
                    skill_dir=composite_dir,
                    max_days=2,
                    tot_enabled=False,
                    got_enabled=False,
                )

                fake_model = FakeModelAdapter()
                result = await run_selfplay(sp_config, model=fake_model)

                # Verify the game completed
                self.assertEqual(len(result.games), 1)
                game = result.games[0]
                self.assertIsNone(game.error, f"Game failed with error: {game.error}")
                self.assertIn(game.winner, ("werewolves", "villagers"))
                self.assertGreater(game.decision_count, 0)
            finally:
                import shutil

                shutil.rmtree(composite_dir, ignore_errors=True)

    # -- 2. battle with different configs --------------------------------------

    async def test_battle_with_different_configs(self):
        """Run two selfplay games with different SkillVersionConfigs.

        Both games should complete successfully, verifying that different
        configs flow through the selfplay system correctly.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store_dir = tmp_path / "agent_versions"
            store = VersionStore(store_dir)

            # Initialize from real skills/ directory
            skills_root = Path("skills")
            store.initialize_from_skills(skills_root)

            # Build baseline config
            baseline_config = build_baseline_config(store)
            self.assertGreater(len(baseline_config.role_versions), 0)

            # Build a role override config (same hash since there's only one
            # version, but the config name differs)
            target_role = "seer"
            target_hash = baseline_config.role_versions[target_role]
            override_config = build_role_override_config(store, target_role, target_hash)

            # Configs should have different names
            self.assertNotEqual(baseline_config.name, override_config.name)

            # Both configs should cover the same roles
            self.assertEqual(
                set(baseline_config.role_versions.keys()),
                set(override_config.role_versions.keys()),
            )

            # Build composite skill directories for each config
            from agent.role_evolution.pipeline import _build_composite_skill_dir

            composite_baseline = _build_composite_skill_dir(store, baseline_config)
            composite_override = _build_composite_skill_dir(store, override_config)

            try:
                fake_model = FakeModelAdapter()

                # Run game 1: baseline config
                output_1 = tmp_path / "output_baseline"
                sp_config_1 = SelfPlayConfig(
                    games=1,
                    output_dir=output_1,
                    enable_review=False,
                    enable_mid_memory=False,
                    enable_long_term_consolidation=False,
                    game_config=MINIMAL_6,
                    skill_dir=composite_baseline,
                    max_days=2,
                    tot_enabled=False,
                    got_enabled=False,
                )
                result_1 = await run_selfplay(sp_config_1, model=fake_model)

                # Run game 2: override config
                output_2 = tmp_path / "output_override"
                sp_config_2 = SelfPlayConfig(
                    games=1,
                    output_dir=output_2,
                    enable_review=False,
                    enable_mid_memory=False,
                    enable_long_term_consolidation=False,
                    game_config=MINIMAL_6,
                    skill_dir=composite_override,
                    max_days=2,
                    tot_enabled=False,
                    got_enabled=False,
                )
                result_2 = await run_selfplay(sp_config_2, model=fake_model)

                # Both games should complete successfully
                self.assertEqual(len(result_1.games), 1)
                self.assertEqual(len(result_2.games), 1)

                game_1 = result_1.games[0]
                game_2 = result_2.games[0]

                self.assertIsNone(game_1.error, f"Baseline game failed: {game_1.error}")
                self.assertIsNone(game_2.error, f"Override game failed: {game_2.error}")

                self.assertIn(game_1.winner, ("werewolves", "villagers"))
                self.assertIn(game_2.winner, ("werewolves", "villagers"))

                self.assertGreater(game_1.decision_count, 0)
                self.assertGreater(game_2.decision_count, 0)

            finally:
                import shutil

                shutil.rmtree(composite_baseline, ignore_errors=True)
                shutil.rmtree(composite_override, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
