from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from ui.backend.evolution_runner import EvolutionManager


class EvolutionRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_manager_keeps_ui_run_id_and_records_artifact_id(self):
        async def fake_runner(config):
            return SimpleNamespace(
                run_id="evolution_real",
                config=config,
                promoted=True,
                reasons=["score improved"],
                metrics={"score_delta": 0.2},
                to_dict=lambda: {
                    "run_id": "evolution_real",
                    "promoted": True,
                    "reasons": ["score improved"],
                    "metrics": {"score_delta": 0.2},
                },
            )

        manager = EvolutionManager(output_dir=Path("runs/evolution_test"), runner=fake_runner)
        run = await manager.start_run(
            base_version="baseline",
            candidate_version="dream_v1",
            training_games=1,
            battle_games=1,
        )

        self.assertIsNotNone(run.task)
        await run.task

        snapshot = manager.get_run(run.run_id).snapshot()
        self.assertEqual(snapshot["status"], "completed")
        self.assertEqual(snapshot["artifact_run_id"], "evolution_real")
        self.assertEqual(snapshot["candidate_version"], "dream_v1")
        self.assertTrue(snapshot["promoted"])
        self.assertEqual(snapshot["metrics"]["score_delta"], 0.2)

    async def test_manager_reports_failures(self):
        async def failing_runner(_config):
            raise RuntimeError("boom")

        manager = EvolutionManager(output_dir=Path("runs/evolution_test"), runner=failing_runner)
        run = await manager.start_run(
            base_version="baseline",
            candidate_version="dream_v1",
        )

        await run.task

        snapshot = run.snapshot()
        self.assertEqual(snapshot["status"], "failed")
        self.assertEqual(snapshot["stage"], "failed")
        self.assertEqual(snapshot["error"], "boom")


if __name__ == "__main__":
    unittest.main()
