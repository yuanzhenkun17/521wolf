from pathlib import Path

from agent.learning.evolution.consolidation import (
    _build_role_messages,
    _load_role_skills_for_str,
)


def test_role_consolidator_prompt_lists_real_target_files(tmp_path: Path):
    (tmp_path / "claim.md").write_text(
        """---
name: seer_claim
role: seer
applicable_actions:
  - seer_check
evolution:
  enabled: true
  allowed_actions:
    - append_rule
    - rewrite_section
---
# 查验策略
优先查验警上强势带队位。""",
        encoding="utf-8",
    )
    (tmp_path / "readonly.md").write_text(
        """---
name: seer_readonly
role: seer
---
只读背景。""",
        encoding="utf-8",
    )
    (tmp_path / "wolf.md").write_text(
        """---
name: wolf_fake_claim
role: werewolf
evolution:
  enabled: true
  allowed_actions:
    - append_rule
---
狼人悍跳。""",
        encoding="utf-8",
    )

    skills = _load_role_skills_for_str("seer", skill_root=tmp_path)
    messages = _build_role_messages(
        filtered_analyses=[
            {
                "game_id": "game_001",
                "winner": "villagers",
                "decision_reviews": [{"action_type": "seer_check", "verdict": "bad"}],
                "strategic_insights": [{"text": "查验过晚", "relevance": "direct"}],
                "error_patterns": [],
                "turning_points": [],
                "counterfactuals": [],
            },
            {
                "game_id": "game_002",
                "winner": "werewolves",
                "decision_reviews": [{"action_type": "seer_check", "verdict": "bad"}],
                "strategic_insights": [{"text": "重复迟查强势位", "relevance": "direct"}],
                "error_patterns": [],
                "turning_points": [],
                "counterfactuals": [],
            },
        ],
        skills=skills,
        role="seer",
    )

    prompt = messages[1]["content"]

    assert {skill.name for skill in skills} == {"seer_claim", "seer_readonly"}
    assert "## Skill file: claim.md" in prompt
    assert "## Skill file: readonly.md" in prompt
    assert "wolf.md" not in prompt
    assert '"target_file": "claim.md"' in prompt
    assert '"target_file": "readonly.md"' not in prompt
    assert '"append_rule"' in prompt
    assert "action_type 是技能修改动作，不是游戏动作" in prompt
    assert "applicable_actions 只是 skill 适用的游戏动作" in prompt
    assert "至少引用 2 个不同 source_games" in prompt
