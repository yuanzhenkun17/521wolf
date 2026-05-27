"""Tests for agent.long_memory — consolidation and prompt hints."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.models import Role

from agent.cognition.long_memory import (
    consolidate_all_roles,
    consolidate_role_memory,
    load_role_memory,
    long_memory_prompt_hints,
    write_role_memory,
)


def _write_card(base: Path, role: str, card: dict) -> None:
    role_dir = base / role
    role_dir.mkdir(parents=True, exist_ok=True)
    with open(role_dir / "cards.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(card, ensure_ascii=False) + "\n")


class LongMemoryConsolidationTests(unittest.TestCase):
    def test_consolidate_empty_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = consolidate_role_memory(Role.WITCH, experience_dir=Path(tmp))

        self.assertEqual(memory.role, "witch")
        self.assertEqual(memory.source_card_count, 0)
        self.assertEqual(memory.effective_strategies, [])

    def test_consolidate_role_memory_from_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_card(base, "witch", {
                "card_id": "g1_p4_witch",
                "outcome": "lose",
                "score": 4.0,
                "lessons": ["毒人前必须确认目标身份，避免毒杀神职"],
                "avoid_next_time": ["无充分证据时毒杀疑似神职目标"],
                "reusable_strategies": ["第二天结合票型再毒人更稳定"],
                "related_skills": ["witch_poison"],
            })
            _write_card(base, "witch", {
                "card_id": "g2_p4_witch",
                "outcome": "win",
                "score": 8.0,
                "lessons": ["毒人前必须确认目标身份，避免毒杀神职"],
                "avoid_next_time": ["无充分证据时毒杀疑似神职目标"],
                "reusable_strategies": ["第二天结合票型再毒人更稳定"],
                "related_skills": ["witch_poison"],
            })

            memory = consolidate_role_memory(Role.WITCH, experience_dir=base)

        self.assertEqual(memory.source_card_count, 2)
        self.assertEqual(memory.win_rate, 0.5)
        self.assertAlmostEqual(memory.avg_score, 6.0)
        self.assertEqual(memory.recurring_mistakes[0].evidence_count, 2)
        self.assertIn("witch_poison", memory.skill_update_suggestions)

    def test_write_and_load_role_memory(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "experiences"
            out = Path(tmp) / "long_memory"
            _write_card(base, "seer", {
                "card_id": "g1_p3_seer",
                "outcome": "win",
                "score": 8.0,
                "lessons": ["查验后要及时公开信息链"],
                "avoid_next_time": [],
                "reusable_strategies": ["查验目标优先选择发言矛盾者"],
                "related_skills": ["seer_check"],
            })
            memory = consolidate_role_memory(Role.SEER, experience_dir=base)
            json_path, md_path = write_role_memory(memory, output_dir=out)
            loaded = load_role_memory(Role.SEER, memory_dir=out)

            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.role, "seer")

    def test_long_memory_prompt_hints(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "experiences"
            out = Path(tmp) / "long_memory"
            _write_card(base, "hunter", {
                "card_id": "g1_p6_hunter",
                "outcome": "lose",
                "score": 3.0,
                "lessons": ["开枪前必须确认目标身份，避免带走队友"],
                "avoid_next_time": ["未确认身份时开枪"],
                "reusable_strategies": ["猎人应结合票型选择最大狼坑"],
                "related_skills": ["hunter_shoot"],
            })
            memory = consolidate_role_memory(Role.HUNTER, experience_dir=base)
            write_role_memory(memory, output_dir=out)

            hints = long_memory_prompt_hints(
                Role.HUNTER,
                action_type="hunter_shoot",
                memory_dir=out,
            )

        self.assertTrue(hints)
        self.assertTrue(any("开枪" in hint or "枪" in hint for hint in hints))

    def test_consolidate_all_roles_writes_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "experiences"
            out = Path(tmp) / "long_memory"
            _write_card(base, "villager", {
                "card_id": "g1_p2_villager",
                "outcome": "win",
                "score": 7.0,
                "lessons": ["投票前需要更多票型分析和站边推理"],
                "avoid_next_time": ["仅凭发言印象投票，忽略票型分析"],
                "reusable_strategies": ["村民应围绕票型建立狼坑"],
                "related_skills": ["villager_vote"],
            })

            memories = consolidate_all_roles(experience_dir=base, output_dir=out)

            self.assertIn("villager", memories)
            self.assertTrue((out / "villager.json").exists())
            self.assertTrue((out / "villager.md").exists())


if __name__ == "__main__":
    unittest.main()
