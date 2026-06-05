import asyncio
from pathlib import Path

from agent.learning.evolution.consolidation import (
    _build_role_messages,
    _load_role_skills_for_str,
    consolidate_for_role,
)
from storage.experience_store import ExperienceCandidateStore
from storage.game_store import GameStore
from storage.ids import artifact_game_id
from storage.schema import get_connection


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


def test_role_consolidator_uses_sqlite_experience_candidates(tmp_path: Path):
    class CapturingModel:
        def __init__(self) -> None:
            self.messages = []

        async def complete(self, messages):
            self.messages = messages
            return '{"trends": ["候选样本显示查验过晚"], "proposals": []}'

    skill_root = tmp_path / "skills"
    skill_root.mkdir()
    (skill_root / "claim.md").write_text(
        """---
name: seer_claim
role: seer
applicable_actions:
  - seer_check
evolution:
  enabled: true
  allowed_actions:
    - append_rule
---
# 查验策略
优先查验警上强势带队位。""",
        encoding="utf-8",
    )

    storage_root = tmp_path / "runs"
    run_dir = storage_root / "evolution" / "evo_test" / "train_0"
    game_dir = run_dir / "games" / "game_001"
    game_dir.mkdir(parents=True)
    game_id = artifact_game_id(game_dir, root=storage_root)

    db_path = tmp_path / "data" / "wolf.db"
    conn = get_connection(db_path)
    GameStore(conn).insert_game(
        game_id,
        seed=1,
        started_at="2026-06-04T00:00:00",
        config={"_storage": {"source_path": str(game_dir)}},
    )
    ExperienceCandidateStore(conn).save_candidates(
        game_id,
        [
            {
                "candidate_id": "cand_001",
                "role": "seer",
                "candidate_type": "anti_pattern",
                "topic": "night_check",
                "evidence_decision_ids": [f"{game_id}::d1"],
                "scenario": "首夜没有查验高影响位",
                "recommendation": "优先查验高影响位",
                "confidence": "medium",
            }
        ],
        created_at="2026-06-04T00:00:00",
    )
    conn.close()

    model = CapturingModel()
    result = asyncio.run(
        consolidate_for_role(
            run_dir,
            "seer",
            model,
            run_id="evo_test",
            parent_hash="parent",
            skill_root=skill_root,
            db_path=db_path,
            storage_root=storage_root,
        )
    )

    prompt = model.messages[1]["content"]
    assert "experience_candidates" in prompt
    assert "优先查验高影响位" in prompt
    assert "cand_001" in prompt
    assert result.source_games == [game_id]
