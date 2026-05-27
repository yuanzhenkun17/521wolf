from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent.cognition.dream import (
    DreamAgent,
    DreamInsight,
    DreamReport,
    SkillEditProposal,
    build_dream_prompt,
    fallback_dream_report,
    parse_dream_report,
    write_dream_report,
)
from agent.cognition.long_memory import RoleLongTermMemory, StrategyPrinciple
from engine.models import Role


class StubModel:
    def __init__(self, response: str) -> None:
        self.response = response
        self.messages: list[dict[str, str]] = []
        self.name = ""

    async def complete(self, messages: list[dict[str, str]], *, name: str = "") -> str:
        self.messages = messages
        self.name = name
        return self.response


def _rule_memory() -> RoleLongTermMemory:
    return RoleLongTermMemory(
        role="witch",
        generated_at="2026-01-01T00:00:00Z",
        source_card_count=2,
        win_rate=0.5,
        avg_score=6.0,
        recurring_mistakes=[
            StrategyPrinciple(
                title="高频教训 1",
                description="毒人前必须确认目标身份",
                evidence_count=2,
                confidence=0.8,
                source_cards=["g1_p4_witch", "g2_p4_witch"],
            )
        ],
        skill_update_suggestions={
            "witch_poison": ["考虑加入经验规则：毒人前必须确认目标身份"]
        },
    )


def _cards() -> list[dict]:
    return [
        {
            "card_id": "g1_p4_witch",
            "role": "witch",
            "outcome": "lose",
            "lessons": ["毒人前必须确认目标身份"],
            "related_skills": ["witch_poison"],
        }
    ]


class DreamReportTests(unittest.TestCase):
    def test_parse_dream_report_from_json(self):
        raw = json.dumps({
            "insights": [
                {
                    "title": "女巫毒人过早",
                    "evidence_cards": ["g1_p4_witch"],
                    "reasoning_summary": "证据不足时使用毒药",
                    "suggested_rule": "至少两个独立证据再毒人",
                    "confidence": 0.82,
                }
            ],
            "skill_edit_proposals": [
                {
                    "skill": "witch_poison",
                    "operation": "append_rule",
                    "proposal": "毒人前检查独立证据数量",
                    "risk": "可能过于保守",
                    "evidence_cards": ["g1_p4_witch"],
                    "confidence": 0.7,
                }
            ],
        }, ensure_ascii=False)

        report = parse_dream_report(
            role=Role.WITCH,
            raw_output=raw,
            source_card_count=1,
            rule_memory=_rule_memory(),
        )

        self.assertEqual(report.role, "witch")
        self.assertEqual(len(report.insights), 1)
        self.assertEqual(report.insights[0].title, "女巫毒人过早")
        self.assertEqual(report.skill_edit_proposals[0].skill, "witch_poison")

    def test_fallback_uses_rule_memory_mistakes(self):
        report = fallback_dream_report(
            role=Role.WITCH,
            cards=_cards(),
            rule_memory=_rule_memory(),
            error="model failed",
        )

        self.assertEqual(report.role, "witch")
        self.assertEqual(len(report.insights), 1)
        self.assertIn("毒人前", report.insights[0].suggested_rule)
        self.assertEqual(report.errors, ["model failed"])

    def test_write_dream_report_outputs_json_and_markdown(self):
        report = DreamReport(
            role="witch",
            generated_at="2026-01-01T00:00:00Z",
            source_card_count=1,
            rule_memory_summary={},
            insights=[
                DreamInsight(
                    title="测试洞察",
                    evidence_cards=["c1"],
                    reasoning_summary="理由",
                    suggested_rule="规则",
                    confidence=0.5,
                )
            ],
            skill_edit_proposals=[
                SkillEditProposal(
                    skill="witch_poison",
                    operation="append_rule",
                    proposal="建议",
                )
            ],
        )

        with tempfile.TemporaryDirectory() as tmp:
            json_path, md_path = write_dream_report(report, output_dir=Path(tmp))

            self.assertTrue(json_path.exists())
            self.assertTrue(md_path.exists())
            self.assertIn("测试洞察", md_path.read_text(encoding="utf-8"))

    def test_build_prompt_contains_cards_rule_memory_and_schema(self):
        prompt = build_dream_prompt(
            role=Role.WITCH,
            cards=_cards(),
            rule_memory=_rule_memory(),
            memory_snapshot={"self_history": ["witch_act"]},
            belief_snapshot={"top_suspicions": []},
            skills=[],
        )

        self.assertIn("反思角色: witch", prompt)
        self.assertIn("g1_p4_witch", prompt)
        self.assertIn("skill_edit_proposals", prompt)


class DreamAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_reflect_calls_model_and_returns_report(self):
        model = StubModel(json.dumps({
            "insights": [
                {
                    "title": "保毒策略",
                    "evidence_cards": ["g1_p4_witch"],
                    "reasoning_summary": "过早毒人",
                    "suggested_rule": "证据不足时保毒",
                    "confidence": 0.75,
                }
            ],
            "skill_edit_proposals": [],
        }, ensure_ascii=False))
        agent = DreamAgent(
            role=Role.WITCH,
            model=model,
            experience_cards=_cards(),
            rule_memory=_rule_memory(),
        )

        report = await agent.reflect()

        self.assertEqual(model.name, "dream/witch")
        self.assertEqual(report.insights[0].title, "保毒策略")


if __name__ == "__main__":
    unittest.main()
