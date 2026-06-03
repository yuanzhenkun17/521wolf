"""Tests for the evolution pipeline: run_evolution, promote, reject, recovery."""

from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass, field
from pathlib import Path

from agent.learning.evolution.models import (
    EvolutionRun,
    EvolutionStatus,
    SkillConsolidation,
    SkillDiff,
    SkillProposal,
)
from agent.learning.evolution.pipeline import (
    BaselineChangedError,
    InvalidRunStateError,
    promote,
    recover_interrupted_runs,
    reject,
    run_evolution,
    scan_active_runs,
)
from agent.learning.evolution.state import save_run_state
from agent.learning.evolution.store import VersionStore
from agent.common.paths import PathConfig, DEFAULT as DEFAULT_PATHS


# ---------------------------------------------------------------------------
# Fake SelfPlayConfig (lightweight stand-in to avoid importing evaluation.selfplay)
# ---------------------------------------------------------------------------


@dataclass
class _FakeSelfPlayConfig:
    games: int
    output_dir: Path
    enable_mid_memory: bool = True
    enable_long_term_consolidation: bool = False
    skill_dir: Path | None = None
    game_concurrency: int = 1


# ---------------------------------------------------------------------------
# Build a fake ``agent.learning.evolution.games`` module with SelfPlayConfig
# so that ``from agent.learning.evolution.games import SelfPlayConfig`` works
# inside _stage_training without pulling in the real (heavy) module.
# ---------------------------------------------------------------------------

_original_games_module = sys.modules.get("agent.learning.evolution.games")


def _install_fake_selfplay_module():
    """Install a minimal fake ``agent.learning.evolution.games`` module into sys.modules."""
    fake_mod = types.ModuleType("agent.learning.evolution.games")
    fake_mod.SelfPlayConfig = _FakeSelfPlayConfig  # type: ignore[attr-defined]
    sys.modules["agent.learning.evolution.games"] = fake_mod
    return fake_mod


def _restore_selfplay_module():
    """Restore the original ``agent.learning.evolution.games`` entry in sys.modules."""
    if _original_games_module is None:
        sys.modules.pop("agent.learning.evolution.games", None)
    else:
        sys.modules["agent.learning.evolution.games"] = _original_games_module


# ---------------------------------------------------------------------------
# Fake pipeline stage callables
# ---------------------------------------------------------------------------


def _make_fake_selfplay():
    """Return a fake async selfplay runner with call tracking."""
    calls: list = []

    async def _runner(config, **kwargs):
        calls.append(config)

        @dataclass
        class _FakeResult:
            config: object
            games: list = field(default_factory=list)
            run_id: str = "train_0"

        return _FakeResult(config=config)

    _runner.calls = calls  # type: ignore[attr-defined]
    return _runner


def _make_fake_consolidator(role: str = "seer", parent_hash: str = ""):
    """Return a fake async consolidator that produces one proposal."""
    proposal = SkillProposal(
        proposal_id="p1",
        target_file="claim.md",
        action_type="rewrite_section",
        content="# New content\n",
        rationale="improvement",
        confidence=0.9,
        risk="low",
        expected_metric="review_score",
        expected_direction="up",
    )
    consolidation = SkillConsolidation(
        role=role,
        run_id="evo_test",
        parent_hash=parent_hash,
        generated_at="2025-01-01T00:00:00Z",
        source_window=5,
        prompt_version="v1",
        proposals=[proposal],
    )

    async def _consolidator(run_dir, role_arg, model_adapter, **kwargs):
        return consolidation

    return _consolidator


def _make_fake_applier():
    """Return a fake async applier that rewrites skills with new content."""
    new_skills = {"claim.md": "# Evolved seer claim\n"}
    diffs = [SkillDiff(filename="claim.md", action="rewrite", proposal_ref="p1")]

    async def _applier(current_skills, proposals, model_adapter):
        return new_skills, diffs

    return _applier


def _make_fake_battle_runner():
    """Return a fake async battle runner returning a win summary."""
    summary = {"wins": 8, "losses": 2, "draws": 0}

    async def _battle_runner(
        store, role, candidate_hash, games, model_adapter, selfplay_runner,
        on_progress=None, **kwargs,
    ):
        return summary

    return _battle_runner


# ---------------------------------------------------------------------------
# Store + pipeline helpers
# ---------------------------------------------------------------------------


async def _setup_store(tmp_path: Path, role: str = "seer") -> tuple[VersionStore, str]:
    """Create a VersionStore with a baseline version for *role*.

    Returns ``(store, parent_hash)``.
    """
    store = VersionStore(tmp_path / "role_versions")
    baseline_skills = {"claim.md": "# Seer claim v1\n"}
    parent_hash = await store.save_version(
        role, baseline_skills, parent_hash=None, source="test_setup",
    )
    return store, parent_hash


async def _run_pipeline(tmp_path: Path, role: str = "seer"):
    """Run a full evolution pipeline with fakes.

    Returns ``(run, store, parent_hash)``.
    """
    store, parent_hash = await _setup_store(tmp_path, role)

    fake_selfplay = _make_fake_selfplay()
    fake_consolidator = _make_fake_consolidator(role=role, parent_hash=parent_hash)
    fake_applier = _make_fake_applier()
    fake_battle = _make_fake_battle_runner()

    # Install fake module so ``from agent.learning.evolution.games import SelfPlayConfig``
    # resolves without pulling in the real heavy evaluation module.
    _install_fake_selfplay_module()
    try:
        run = await run_evolution(
            store=store,
            role=role,
            training_games=5,
            battle_games=3,
            selfplay_runner=fake_selfplay,
            consolidator=fake_consolidator,
            applier=fake_applier,
            battle_runner=fake_battle,
        )
    finally:
        _restore_selfplay_module()

    return run, store, parent_hash


async def _make_reviewing_run(
    tmp_path: Path, role: str = "seer", evolve: bool = True,
):
    """Create an EvolutionRun in *reviewing* status.

    If *evolve* is True the full pipeline is executed (candidate differs from
    parent).  Otherwise a minimal run with ``candidate_hash == parent_hash``
    is returned.

    Returns ``(run, store, parent_hash)``.
    """
    if evolve:
        return await _run_pipeline(tmp_path, role)

    store, parent_hash = await _setup_store(tmp_path, role)
    run_id = "evo_review_test"
    run = EvolutionRun(
        run_id=run_id,
        role=role,
        parent_hash=parent_hash,
        status=EvolutionStatus.REVIEWING,
        candidate_hash=parent_hash,
    )
    # Ensure the run directory exists so save_run_state can write state.json
    rd = PathConfig(root=tmp_path).evolution_dir / run_id
    rd.mkdir(parents=True, exist_ok=True)
    save_run_state(run, paths=PathConfig(root=tmp_path))
    return run, store, parent_hash


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPipeline(unittest.IsolatedAsyncioTestCase):

    # -- 1. full mock pipeline -----------------------------------------------
    async def test_full_mock_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run, store, parent_hash = await _run_pipeline(tmp_path)

            self.assertEqual(run.role, "seer")
            self.assertEqual(run.parent_hash, parent_hash)
            self.assertIsNotNone(run.candidate_hash)
            self.assertNotEqual(run.candidate_hash, parent_hash)
            self.assertEqual(run.status, EvolutionStatus.REVIEWING)
            self.assertEqual(run.training_games, 5)
            self.assertEqual(run.battle_games, 3)
            self.assertEqual(run.training_run_id, "train_0")
            self.assertIsNotNone(run.baseline_config)

    async def test_training_uses_composite_baseline_skill_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store = VersionStore(tmp_path / "role_versions")
            seer_hash = await store.save_version(
                "seer", {"claim.md": "# Seer\n"}, parent_hash=None, source="test_setup",
            )
            await store.save_version(
                "werewolf", {"attack.md": "# Wolf\n"}, parent_hash=None, source="test_setup",
            )

            async def fake_selfplay(config, **kwargs):
                self.assertEqual(config.game_concurrency, 3)
                self.assertTrue((config.skill_dir / "seer").is_dir())
                self.assertTrue((config.skill_dir / "werewolf").is_dir())

                @dataclass
                class _FakeResult:
                    config: object
                    games: list = field(default_factory=list)
                    run_id: str = "train_0"

                return _FakeResult(config=config)

            async def no_proposals(run_dir, role_arg, model_adapter, **kwargs):
                return SkillConsolidation(
                    role=role_arg,
                    run_id="evo_test",
                    parent_hash=seer_hash,
                    generated_at="2025-01-01T00:00:00Z",
                    source_window=5,
                    prompt_version="v1",
                    proposals=[],
                )

            _install_fake_selfplay_module()
            try:
                run = await run_evolution(
                    store=store,
                    role="seer",
                    training_games=1,
                    battle_games=1,
                    game_concurrency=3,
                    selfplay_runner=fake_selfplay,
                    consolidator=no_proposals,
                    applier=_make_fake_applier(),
                    battle_runner=_make_fake_battle_runner(),
                )
            finally:
                _restore_selfplay_module()

            self.assertEqual(run.parent_hash, seer_hash)

    # -- 2. promote updates baseline if CAS matches --------------------------
    async def test_promote_updates_baseline_if_cas_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run, store, parent_hash = await _make_reviewing_run(tmp_path)

            await promote(run, store)

            self.assertEqual(run.status, EvolutionStatus.PROMOTED)
            history = store.get_history("seer")
            self.assertEqual(history.baseline, run.candidate_hash)

    # -- 3. promote fails if CAS mismatch ------------------------------------
    async def test_promote_fails_if_cas_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run, store, parent_hash = await _make_reviewing_run(tmp_path)

            # Externally change the baseline before promote
            new_skills = {"claim.md": "# Externally changed\n"}
            external_hash = await store.save_version(
                "seer", new_skills, parent_hash=parent_hash, source="external",
            )
            await store.set_baseline("seer", external_hash, expected_current=parent_hash)

            with self.assertRaises(BaselineChangedError):
                await promote(run, store)

    # -- 4. reject leaves baseline unchanged ----------------------------------
    async def test_reject_leaves_baseline_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run, store, parent_hash = await _make_reviewing_run(tmp_path)

            await reject(run, store)

            self.assertEqual(run.status, EvolutionStatus.REJECTED)
            history = store.get_history("seer")
            self.assertEqual(history.baseline, parent_hash)

    # -- 5. promote is idempotent --------------------------------------------
    async def test_promote_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run, store, parent_hash = await _make_reviewing_run(tmp_path)

            await promote(run, store)
            self.assertEqual(run.status, EvolutionStatus.PROMOTED)
            # Second call should be a no-op
            await promote(run, store)
            self.assertEqual(run.status, EvolutionStatus.PROMOTED)

    # -- 6. reject is idempotent ---------------------------------------------
    async def test_reject_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run, store, parent_hash = await _make_reviewing_run(tmp_path)

            await reject(run, store)
            self.assertEqual(run.status, EvolutionStatus.REJECTED)
            await reject(run, store)
            self.assertEqual(run.status, EvolutionStatus.REJECTED)

    # -- 7. terminal conflict: promote a rejected run -------------------------
    async def test_terminal_conflict_promote_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run, store, parent_hash = await _make_reviewing_run(tmp_path)

            await reject(run, store)
            with self.assertRaises(InvalidRunStateError):
                await promote(run, store)

    # -- 8. terminal conflict: reject a promoted run --------------------------
    async def test_terminal_conflict_reject_promoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run, store, parent_hash = await _make_reviewing_run(tmp_path)

            await promote(run, store)
            with self.assertRaises(InvalidRunStateError):
                await reject(run, store)

    # -- 9. promote only from reviewing ---------------------------------------
    async def test_promote_only_from_reviewing(self):
        non_reviewing = [
            EvolutionStatus.QUEUED,
            EvolutionStatus.TRAINING,
            EvolutionStatus.CONSOLIDATING,
            EvolutionStatus.APPLYING,
            EvolutionStatus.BATTLING,
        ]
        for status in non_reviewing:
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    store, parent_hash = await _setup_store(tmp_path)
                    run = EvolutionRun(
                        run_id=f"evo_{status}",
                        role="seer",
                        parent_hash=parent_hash,
                        status=status,
                    )
                    with self.assertRaises(InvalidRunStateError):
                        await promote(run, store)

    # -- 10. reject only from reviewing ---------------------------------------
    async def test_reject_only_from_reviewing(self):
        non_reviewing = [
            EvolutionStatus.QUEUED,
            EvolutionStatus.TRAINING,
            EvolutionStatus.CONSOLIDATING,
            EvolutionStatus.APPLYING,
            EvolutionStatus.BATTLING,
        ]
        for status in non_reviewing:
            with self.subTest(status=status):
                with tempfile.TemporaryDirectory() as tmp:
                    tmp_path = Path(tmp)
                    store, parent_hash = await _setup_store(tmp_path)
                    run = EvolutionRun(
                        run_id=f"evo_{status}",
                        role="seer",
                        parent_hash=parent_hash,
                        status=status,
                    )
                    with self.assertRaises(InvalidRunStateError):
                        await reject(run, store)

    # -- 11. state.json written at each stage ---------------------------------
    async def test_state_json_written_at_each_stage(self):
        progress_log: list[tuple[str, dict]] = []

        def on_progress(stage, data):
            progress_log.append((stage, data))

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store, parent_hash = await _setup_store(tmp_path)

            fake_selfplay = _make_fake_selfplay()
            fake_consolidator = _make_fake_consolidator(
                role="seer", parent_hash=parent_hash,
            )
            fake_applier = _make_fake_applier()
            fake_battle = _make_fake_battle_runner()

            _install_fake_selfplay_module()
            try:
                run = await run_evolution(
                    store=store,
                    role="seer",
                    training_games=5,
                    battle_games=3,
                    on_progress=on_progress,
                    selfplay_runner=fake_selfplay,
                    consolidator=fake_consolidator,
                    applier=fake_applier,
                    battle_runner=fake_battle,
                )
            finally:
                _restore_selfplay_module()

            # Final state.json should be reviewing
            state_path = DEFAULT_PATHS.evolution_dir / run.run_id / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(state["status"], "reviewing")

            # Verify progress callbacks confirm all stages were hit
            stage_names = [s for s, _ in progress_log]
            self.assertIn("training", stage_names)
            self.assertIn("consolidating", stage_names)
            self.assertIn("battling", stage_names)
            self.assertIn("reviewing", stage_names)

    # -- 12. state.json recoverable -------------------------------------------
    async def test_state_json_recoverable(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store = VersionStore(tmp_path / "role_versions")
            run_id = "evo_interrupted"

            # Manually write a state.json with non-terminal status
            evo_root = DEFAULT_PATHS.evolution_dir / run_id
            evo_root.mkdir(parents=True, exist_ok=True)
            state_path = evo_root / "state.json"
            state = {
                "run_id": run_id,
                "role": "seer",
                "parent_hash": "abc123",
                "candidate_hash": None,
                "status": "training",
                "training_games": 20,
                "battle_games": 10,
            }
            state_path.write_text(json.dumps(state), encoding="utf-8")

            interrupted = recover_interrupted_runs(store)

            self.assertEqual(len(interrupted), 1)
            self.assertEqual(interrupted[0]["run_id"], run_id)
            self.assertEqual(interrupted[0]["status"], EvolutionStatus.FAILED)
            self.assertEqual(interrupted[0]["error"], "interrupted")

            # Cleanup
            import shutil
            shutil.rmtree(evo_root, ignore_errors=True)

    # -- 13. active run blocks same role --------------------------------------
    async def test_active_run_blocks_same_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # First evolution — reaches reviewing (non-terminal)
            run1, store, parent_hash = await _run_pipeline(tmp_path, "seer")
            self.assertEqual(run1.status, EvolutionStatus.REVIEWING)

            # Role should appear in active runs
            active = scan_active_runs()
            active_run_ids = [r["run_id"] for r in active]
            self.assertIn(run1.run_id, active_run_ids)

            # Start a second evolution for the same role while first is active
            run2, store, _ = await _run_pipeline(tmp_path, "seer")
            self.assertEqual(run2.status, EvolutionStatus.REVIEWING)

            # Both should be active (non-terminal)
            active = scan_active_runs()
            active_run_ids = [r["run_id"] for r in active]
            self.assertIn(run1.run_id, active_run_ids)
            self.assertIn(run2.run_id, active_run_ids)

            # Promote the first run -> terminal
            await promote(run1, store)
            self.assertEqual(run1.status, EvolutionStatus.PROMOTED)

            # Now only the second run should be active
            active = scan_active_runs()
            active_run_ids = [r["run_id"] for r in active]
            self.assertNotIn(run1.run_id, active_run_ids)
            self.assertIn(run2.run_id, active_run_ids)


if __name__ == "__main__":
    unittest.main()
