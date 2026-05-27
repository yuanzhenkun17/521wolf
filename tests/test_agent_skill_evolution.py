from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.cognition.dream import DreamReport, SkillEditProposal
from agent.cognition.skill_evolution import (
    apply_skill_proposals,
    find_skill_path,
    proposals_from_dream,
    write_skill_proposals,
)


def _report() -> DreamReport:
    return DreamReport(
        role="witch",
        generated_at="2026-01-01T00:00:00Z",
        source_card_count=3,
        rule_memory_summary={},
        skill_edit_proposals=[
            SkillEditProposal(
                skill="witch_poison",
                operation="append_rule",
                proposal="毒人前至少确认两个独立证据来源。",
                risk="可能导致女巫过于保守",
                evidence_cards=["c1", "c2", "c3"],
                confidence=0.82,
            ),
            SkillEditProposal(
                skill="witch_poison",
                operation="append_rule",
                proposal="低置信建议",
                evidence_cards=["c1"],
                confidence=0.2,
            ),
        ],
    )


def _write_skill(root: Path) -> Path:
    path = root / "witch" / "poison.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        """---
name: witch_poison
scope: role
role: witch
applicable_actions:
  - witch_act
---

# 女巫毒人

## 策略原则

- 确认目标大概率是狼人再毒。
""",
        encoding="utf-8",
    )
    return path


class SkillEvolutionTests(unittest.TestCase):
    def test_proposals_from_dream_filters_by_confidence_and_evidence(self):
        proposals = proposals_from_dream(_report())

        self.assertEqual(len(proposals), 2)
        self.assertEqual(proposals[0].status, "pending")
        self.assertEqual(proposals[1].status, "rejected")
        self.assertIn("confidence", proposals[1].reason)

    def test_write_skill_proposals_outputs_json_and_markdown(self):
        proposals = proposals_from_dream(_report())
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_skill_proposals(proposals, output_dir=Path(tmp))

            self.assertIsNotNone(paths)
            json_path, md_path = paths
            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            self.assertIn("witch_poison", md_path.read_text(encoding="utf-8"))

    def test_find_skill_path_by_front_matter_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = _write_skill(root)

            found = find_skill_path("witch", "witch_poison", skill_root=root)

            self.assertEqual(found, path)

    def test_apply_skill_proposals_appends_rule_and_patch_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills"
            patch_dir = Path(tmp) / "patches"
            skill_path = _write_skill(root)
            proposals = proposals_from_dream(_report())

            records = apply_skill_proposals(
                proposals,
                skill_root=root,
                patch_dir=patch_dir,
                min_confidence=0.75,
                min_evidence_cards=3,
            )

            self.assertEqual(len(records), 1)
            text = skill_path.read_text(encoding="utf-8")
            self.assertIn("经验沉淀规则", text)
            self.assertIn("两个独立证据来源", text)
            self.assertTrue(list(patch_dir.glob("*.json")))

    def test_apply_skill_proposals_does_not_duplicate_existing_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "skills"
            skill_path = _write_skill(root)
            proposals = proposals_from_dream(_report())

            first = apply_skill_proposals(proposals, skill_root=root)
            second = apply_skill_proposals(proposals, skill_root=root)

            self.assertEqual(len(first), 1)
            self.assertEqual(len(second), 0)
            text = skill_path.read_text(encoding="utf-8")
            self.assertEqual(text.count("经验沉淀规则"), 1)


if __name__ == "__main__":
    unittest.main()
