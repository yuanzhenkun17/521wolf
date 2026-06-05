import json

from agent.learning.game_analysis import _build_messages, _parse_analysis, filter_mid_memory_for_role
from agent.learning.review import GameReviewReport, PlayerReview
from agent.infrastructure.decision_log import DecisionRecord
from engine.models import ActionType


def _minimal_review() -> GameReviewReport:
    return GameReviewReport(
        game_id="game_001",
        winner="villagers",
        summary="test",
        team_scores={"villagers": 7.0, "werewolves": 4.0},
        player_scores={
            1: PlayerReview(player_id=1, role="seer", team="gods", outcome="win"),
        },
        key_turning_points=[],
        mistakes=[],
        skill_summary={},
        counterfactuals=[],
    )


def test_mid_memory_prompt_exposes_decision_ids_and_relevance_rules():
    review = _minimal_review()
    messages = _build_messages(
        review=review,
        agent_decisions={
            1: [
                {
                    "decision_id": "dec_seer_1",
                    "player_id": 1,
                    "role": "seer",
                    "day": 1,
                    "phase": "night",
                    "action_type": "seer_check",
                    "selected_target": 3,
                    "selected_choice": "werewolf",
                    "public_text": "",
                    "private_reasoning": "3号警上发言强硬且票型异常",
                    "selected_skills": ["seer_claim"],
                    "confidence": 0.8,
                    "source": "llm",
                }
            ]
        },
        roles={1: "seer", 3: "werewolf"},
        winner_team="villagers",
    )

    prompt = messages[1]["content"]

    assert '"decision_id": "dec_seer_1"' in prompt
    assert "source_decision_ids 只能从玩家决策记录中的 decision_id 逐字复制" in prompt
    assert "relevance 只能是 direct|contextual" in prompt
    assert "direct 洞察必须至少有 1 个 source_player_ids 和 1 个 source_decision_ids" in prompt
    assert "不要提出 skill 文件修改方案" in prompt


def test_mid_memory_parser_preserves_evidence_fields_and_downgrades_weak_direct():
    raw = json.dumps({
        "turning_points": [
            {
                "day": 1,
                "phase": "night",
                "description": "预言家首夜查中狼人",
                "impact": "positive",
                "affected_team": "villagers",
                "root_cause": "目标选择基于警上强势位",
                "involved_roles": ["seer"],
            }
        ],
        "decision_reviews": [
            {
                "decision_id": "dec_seer_1",
                "player_id": 1,
                "role": "seer",
                "day": 1,
                "phase": "night",
                "action_type": "seer_check",
                "quality_score": 8.5,
                "verdict": "good",
                "reasoning": "命中狼人",
                "improvement": "继续优先查验强势带队位",
            }
        ],
        "counterfactuals": [],
        "strategic_insights": [
            {
                "text": "预言家首夜应优先查验强势带队位",
                "source_roles": ["seer"],
                "source_player_ids": [1],
                "source_decision_ids": ["dec_seer_1"],
                "confidence": 1.2,
                "relevance": "direct",
            },
            {
                "text": "没有具体决策来源的全局判断",
                "source_roles": ["seer"],
                "source_player_ids": [],
                "source_decision_ids": [],
                "confidence": 0.9,
                "relevance": "direct",
            },
        ],
        "error_patterns": [],
    })

    analysis = _parse_analysis(
        game_id="game_001",
        raw_output=raw,
        roles={1: "seer"},
        winner_team="villagers",
        player_scores={},
        team_scores={},
    )

    assert analysis.turning_points[0].involved_roles == ["seer"]
    assert analysis.decision_reviews[0].decision_id == "dec_seer_1"
    assert analysis.strategic_insights[0].confidence == 1.0
    assert analysis.strategic_insights[0].source_decision_ids == ["dec_seer_1"]
    assert analysis.strategic_insights[1].relevance == "contextual"

    filtered = filter_mid_memory_for_role(analysis, "seer")
    assert filtered["turning_points"][0]["role_involved"] is True
    assert filtered["decision_reviews"][0]["decision_id"] == "dec_seer_1"


def test_decision_record_serializes_decision_id():
    record = DecisionRecord(action_type=ActionType.SEER_CHECK)
    data = record.to_dict()

    assert data["decision_id"] == record.decision_id
    assert data["decision_id"]
