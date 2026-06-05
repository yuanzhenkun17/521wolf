from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from agent.learning.pipeline import run_evidence_pipeline


class TestLearningV2Pipeline(unittest.TestCase):
    def test_pipeline_without_llm_writes_base_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            game_dir = Path(tmpdir)
            archive = {
                "game_id": "game_001",
                "winner": "villagers",
                "player_roles": {"1": "seer", "2": "werewolf"},
                "decisions": [
                    {
                        "decision_id": "d1",
                        "index": 1,
                        "player_id": 1,
                        "role": "seer",
                        "day": 1,
                        "phase": "night",
                        "action_type": "seer_check",
                        "candidates": [2],
                        "parsed_decision": {"target": 2},
                        "final_response": {"target": 2},
                    }
                ],
                "final_state": {"winner": "villagers"},
            }
            (game_dir / "archive.json").write_text(
                json.dumps(archive, ensure_ascii=False),
                encoding="utf-8",
            )
            (game_dir / "game_events.jsonl").write_text(
                json.dumps(
                    {
                        "event_type": "game_init",
                        "day": 0,
                        "payload": {"roles": {"1": "seer", "2": "werewolf"}},
                    },
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )

            result = asyncio.run(run_evidence_pipeline(game_dir, use_llm=False))

            self.assertEqual(result.game_id, "game_001")
            self.assertEqual(len(result.evidence_inputs), 1)
            self.assertEqual(result.key_decisions[0].decision_id, "d1")
            self.assertTrue((game_dir / "learning" / "evidence_inputs.jsonl").exists())
            self.assertTrue((game_dir / "learning" / "evidence_report.md").exists())


if __name__ == "__main__":
    unittest.main()
