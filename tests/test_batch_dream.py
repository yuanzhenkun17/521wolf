from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.evaluation.selfplay import _run_batch_dream


class FakeDreamModel:
    async def complete(self, _messages, *, name: str = "") -> str:
        return json.dumps({
            "insights": [
                {
                    "title": "狼人悍跳需要证据",
                    "evidence_cards": ["card_1", "card_2"],
                    "reasoning_summary": "两张经验卡都指向悍跳准备不足。",
                    "suggested_rule": "悍跳前准备查验链和反打话术。",
                    "confidence": 0.9,
                }
            ],
            "skill_edit_proposals": [
                {
                    "skill": "fake_seer",
                    "operation": "append_rule",
                    "proposal": "悍跳预言家前必须准备至少两轮查验链和被质疑时的反打话术。",
                    "risk": "过度悍跳会暴露狼队。",
                    "evidence_cards": ["card_1", "card_2"],
                    "confidence": 0.9,
                }
            ],
        }, ensure_ascii=False)


class BatchDreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_batch_dream_writes_reports_and_applies_evolvable_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_dir = root / "run"
            game_exp = run_dir / "games" / "game_001" / "experiences"
            role_exp = run_dir / "experiences" / "werewolf"
            skill_dir = root / "skills"
            wolf_skill_dir = skill_dir / "werewolf"
            game_exp.mkdir(parents=True)
            role_exp.mkdir(parents=True)
            wolf_skill_dir.mkdir(parents=True)

            cards = [
                _card("card_1", "lose"),
                _card("card_2", "lose"),
            ]
            for idx, card in enumerate(cards, 1):
                (game_exp / f"player_{idx}_werewolf.json").write_text(
                    json.dumps(card, ensure_ascii=False),
                    encoding="utf-8",
                )
            (role_exp / "cards.jsonl").write_text(
                "\n".join(json.dumps(card, ensure_ascii=False) for card in cards) + "\n",
                encoding="utf-8",
            )
            skill_path = wolf_skill_dir / "fake_seer.md"
            skill_path.write_text(
                "---\nname: fake_seer\nscope: role\nrole: werewolf\nevolvable: true\n---\n\n# 悍跳\n",
                encoding="utf-8",
            )

            await _run_batch_dream(
                run_dir=run_dir,
                model=FakeDreamModel(),
                skill_dir=skill_dir,
                enable_skill_proposals=True,
                auto_apply_skill_proposals=True,
            )

            self.assertTrue((run_dir / "batch_dreams" / "werewolf").exists())
            self.assertTrue((run_dir / "batch_skill_proposals" / "werewolf").exists())
            self.assertTrue((run_dir / "batch_skill_patches" / "werewolf").exists())
            self.assertTrue((run_dir / "memory_candidate" / "werewolf.json").exists())
            self.assertIn("两轮查验链", skill_path.read_text(encoding="utf-8"))


def _card(card_id: str, outcome: str) -> dict:
    return {
        "card_id": card_id,
        "game_id": "game_001",
        "player_id": 1,
        "role": "werewolf",
        "team": "werewolves",
        "outcome": outcome,
        "created_at": "2026-05-27T00:00:00+00:00",
        "summary": "狼人悍跳失败。",
        "situation_tags": ["werewolf", "fake_seer", outcome],
        "key_decisions": [],
        "lessons": ["悍跳预言家前必须准备查验链"],
        "avoid_next_time": ["无准备悍跳"],
        "reusable_strategies": [],
        "related_skills": ["fake_seer"],
        "evidence_decision_ids": [],
        "score": 4.0,
        "confidence": 0.8,
    }


if __name__ == "__main__":
    unittest.main()
