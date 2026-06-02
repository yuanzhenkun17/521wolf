"""Tests for enhanced review report structures."""

from __future__ import annotations

import json
import unittest

from engine.models import Role, Team

from agent.learning.review import (
    DecisionMistake,
    GameReviewReport,
    MISTAKE_FALLBACK_USED,
    MISTAKE_ILLEGAL_ACTION,
    MISTAKE_POLICY_ADJUSTED,
    MISTAKE_POISONED_GOOD,
    MISTAKE_SHOT_GOOD,
    MISTAKE_WRONG_VOTE,
    PlayerReview,
    SkillReview,
    TurningPoint,
    Counterfactual,
    generate_enhanced_review,
    _classify_mistakes,
    _collect_mistakes,
    _enhanced_turning_points,
    _player_outcome,
)


class PlayerReviewTests(unittest.TestCase):
    """Test PlayerReview dataclass and serialization."""

    def test_default_construction(self):
        pr = PlayerReview(player_id=1, role="villager", team="villagers", outcome="win")
        self.assertEqual(pr.total_score, 0.0)
        self.assertEqual(pr.highlights, [])
        self.assertEqual(pr.suggestions, [])
        self.assertEqual(pr.mistake_types, [])

    def test_to_dict(self):
        pr = PlayerReview(
            player_id=1, role="werewolf", team="werewolves",
            outcome="win", total_score=7.5,
            speech_score=6.0, vote_score=8.0, skill_score=7.0,
            information_score=5.0, cooperation_score=6.0,
            highlights=["成功悍跳"], mistakes=["投票失误"],
            mistake_types=["wrong_vote"],
            suggestions=["加强票型分析"],
        )
        d = pr.to_dict()
        self.assertEqual(d["player_id"], 1)
        self.assertEqual(d["role"], "werewolf")
        self.assertAlmostEqual(d["total_score"], 7.5)
        self.assertIn("scores", d)
        self.assertIn("highlights", d)

    def test_to_dict_json_serializable(self):
        pr = PlayerReview(player_id=3, role="witch", team="villagers", outcome="lose")
        json_str = json.dumps(pr.to_dict(), ensure_ascii=False)
        loaded = json.loads(json_str)
        self.assertEqual(loaded["player_id"], 3)


class TurningPointTests(unittest.TestCase):
    """Test TurningPoint dataclass."""

    def test_construction(self):
        tp = TurningPoint(
            day=2, phase="night", description="女巫毒杀预言家",
            impact="negative", affected_team="villagers",
        )
        self.assertEqual(tp.day, 2)
        self.assertEqual(tp.impact, "negative")

    def test_to_dict(self):
        tp = TurningPoint(
            day=1, phase="day", description="狼人自爆",
            impact="positive", affected_team="werewolves",
        )
        d = tp.to_dict()
        self.assertEqual(d["day"], 1)
        self.assertIn("description", d)


class DecisionMistakeTests(unittest.TestCase):
    """Test DecisionMistake dataclass."""

    def test_default_severity(self):
        m = DecisionMistake(
            player_id=1, role="witch", day=2, phase="night",
            action_type="witch_act", mistake_type=MISTAKE_POISONED_GOOD,
            description="毒错好人",
        )
        self.assertEqual(m.severity, "medium")

    def test_to_dict(self):
        m = DecisionMistake(
            player_id=1, role="witch", day=2, phase="night",
            action_type="witch_act", mistake_type=MISTAKE_POISONED_GOOD,
            description="毒杀预言家", severity="high",
        )
        d = m.to_dict()
        self.assertEqual(d["mistake_type"], MISTAKE_POISONED_GOOD)


class SkillReviewTests(unittest.TestCase):
    """Test SkillReview aggregation."""

    def test_construction(self):
        sr = SkillReview(skill_name="witch_poison")
        self.assertEqual(sr.use_count, 0)

    def test_aggregation(self):
        sr = SkillReview(skill_name="game_rules")
        sr.use_count = 5
        sr.avg_confidence = 0.8
        sr.success_count = 4
        sr.fail_count = 1
        d = sr.to_dict()
        self.assertEqual(d["use_count"], 5)
        self.assertAlmostEqual(d["avg_confidence"], 0.8)


class GameReviewReportTests(unittest.TestCase):
    """Test GameReviewReport markdown generation."""

    def test_empty_report(self):
        report = GameReviewReport(
            game_id="game_001",
            winner="villagers",
            summary="好人获胜",
            team_scores={"villagers": 7.0, "werewolves": 5.0},
            player_scores={},
            key_turning_points=[],
            mistakes=[],
            skill_summary={},
            counterfactuals=[],
            suggestions=[],
        )
        md = report.to_markdown()
        self.assertIn("game_001", md)
        self.assertIn("villagers", md)

    def test_report_with_mistakes(self):
        report = GameReviewReport(
            game_id="g1", winner="werewolves", summary="狼人获胜",
            team_scores={"villagers": 5.0, "werewolves": 7.0},
            player_scores={
                1: PlayerReview(player_id=1, role="witch", team="villagers", outcome="lose"),
            },
            key_turning_points=[
                TurningPoint(day=2, phase="night", description="女巫毒错",
                             impact="negative", affected_team="villagers"),
            ],
            mistakes=[
                DecisionMistake(player_id=1, role="witch", day=2, phase="night",
                               action_type="witch_act", mistake_type=MISTAKE_POISONED_GOOD,
                               description="毒杀预言家", severity="high"),
            ],
            skill_summary={"witch_poison": SkillReview(skill_name="witch_poison", use_count=1)},
            counterfactuals=[],
            suggestions=["毒人前确认身份"],
        )
        md = report.to_markdown()
        self.assertIn("关键错误", md)
        self.assertIn("女巫毒错", md)
        self.assertIn("毒人前确认身份", md)

    def test_to_dict(self):
        report = GameReviewReport(
            game_id="g1", winner="villagers", summary="test",
            team_scores={}, player_scores={},
            key_turning_points=[], mistakes=[],
            skill_summary={}, counterfactuals=[], suggestions=[],
        )
        d = report.to_dict()
        self.assertEqual(d["game_id"], "g1")


class MistakeClassificationTests(unittest.TestCase):
    """Test _classify_mistakes helper."""

    def test_classify_poison(self):
        types = _classify_mistakes(["毒杀了 P3"], 1, Role.WITCH, {})
        self.assertIn(MISTAKE_POISONED_GOOD, types)

    def test_classify_fallback(self):
        types = _classify_mistakes(["投票 使用了回退动作"], 1, Role.VILLAGER, {})
        self.assertIn(MISTAKE_FALLBACK_USED, types)

    def test_classify_adjusted(self):
        types = _classify_mistakes(["投票 被策略修正"], 1, Role.VILLAGER, {})
        self.assertIn(MISTAKE_POLICY_ADJUSTED, types)

    def test_classify_shot(self):
        types = _classify_mistakes(["开枪带走了 P3"], 1, Role.HUNTER, {})
        self.assertIn(MISTAKE_SHOT_GOOD, types)

    def test_classify_vote(self):
        types = _classify_mistakes(["投票错误"], 1, Role.VILLAGER, {})
        self.assertIn(MISTAKE_WRONG_VOTE, types)

    def test_classify_illegal_default(self):
        types = _classify_mistakes(["未知错误"], 1, Role.VILLAGER, {})
        self.assertIn(MISTAKE_ILLEGAL_ACTION, types)


class PlayerOutcomeTests(unittest.TestCase):
    """Test _player_outcome helper."""

    def test_wolf_wins_when_wolves_win(self):
        self.assertEqual(_player_outcome(1, Role.WEREWOLF, "werewolves"), "win")

    def test_villager_loses_when_wolves_win(self):
        self.assertEqual(_player_outcome(1, Role.VILLAGER, "werewolves"), "lose")

    def test_villager_wins_when_villagers_win(self):
        self.assertEqual(_player_outcome(1, Role.VILLAGER, "villagers"), "win")

    def test_wolf_loses_when_villagers_win(self):
        self.assertEqual(_player_outcome(1, Role.WEREWOLF, "villagers"), "lose")


class EnhancedTurningPointTests(unittest.TestCase):
    """Test _enhanced_turning_points detection."""

    def test_detects_death_event(self):
        game_log = {"entries": [{"event_type": "death", "target": 2, "day": 1, "phase": "night"}]}
        roles = {2: Role.SEER, 5: Role.WEREWOLF}
        points = _enhanced_turning_points(game_log, {}, roles, "werewolves")
        self.assertGreater(len(points), 0)
        self.assertIn("死亡", points[0].description)

    def test_detects_witch_poison(self):
        decisions = {
            3: [{"action_type": "witch_act", "selected_choice": "poison",
                 "selected_target": 5, "day": 2, "phase": "night"}],
        }
        roles = {5: Role.VILLAGER}
        points = _enhanced_turning_points({}, decisions, roles, "werewolves")
        self.assertGreater(len(points), 0)
        self.assertIn("毒杀", points[0].description)

    def test_detects_hunter_shoot(self):
        decisions = {
            6: [{"action_type": "hunter_shoot", "selected_target": 3,
                 "day": 3, "phase": "day"}],
        }
        roles = {3: Role.WEREWOLF}
        points = _enhanced_turning_points({}, decisions, roles, "villagers")
        self.assertGreater(len(points), 0)
        self.assertIn("开枪", points[0].description)

    def test_detects_werewolf_kill_god(self):
        decisions = {
            1: [{"action_type": "werewolf_kill", "selected_target": 4,
                 "day": 1, "phase": "night"}],
        }
        roles = {4: Role.SEER}
        points = _enhanced_turning_points({}, decisions, roles, "werewolves")
        self.assertGreater(len(points), 0)
        self.assertIn("刀杀", points[0].description)


class CollectMistakesTests(unittest.TestCase):
    """Test _collect_mistakes from decision records."""

    def test_detects_fallback(self):
        decisions = {
            1: [{"source": "fallback", "day": 1, "phase": "day", "action_type": "speak"}],
        }
        roles = {1: Role.VILLAGER}
        mistakes = _collect_mistakes(decisions, roles)
        self.assertEqual(len(mistakes), 1)
        self.assertEqual(mistakes[0].mistake_type, MISTAKE_FALLBACK_USED)

    def test_detects_policy_adjusted(self):
        decisions = {
            1: [{"source": "policy_adjusted", "day": 1, "phase": "day",
                 "action_type": "vote", "policy_adjustments": ["target修正"]}],
        }
        roles = {1: Role.VILLAGER}
        mistakes = _collect_mistakes(decisions, roles)
        self.assertEqual(len(mistakes), 1)
        self.assertEqual(mistakes[0].mistake_type, MISTAKE_POLICY_ADJUSTED)

    def test_detects_poisoned_good(self):
        decisions = {
            3: [{"action_type": "witch_act", "selected_choice": "poison",
                 "selected_target": 5, "day": 2, "phase": "night", "source": "llm"}],
        }
        roles = {3: Role.WITCH, 5: Role.VILLAGER}
        mistakes = _collect_mistakes(decisions, roles)
        self.assertEqual(len(mistakes), 1)
        self.assertEqual(mistakes[0].mistake_type, MISTAKE_POISONED_GOOD)

    def test_detects_hunter_shot_good(self):
        decisions = {
            6: [{"action_type": "hunter_shoot", "selected_target": 3,
                 "day": 3, "phase": "day", "source": "llm"}],
        }
        roles = {6: Role.HUNTER, 3: Role.VILLAGER}
        mistakes = _collect_mistakes(decisions, roles)
        self.assertEqual(len(mistakes), 1)
        self.assertEqual(mistakes[0].mistake_type, MISTAKE_SHOT_GOOD)

    def test_no_false_positive_when_correct(self):
        decisions = {
            3: [{"action_type": "witch_act", "selected_choice": "poison",
                 "selected_target": 1, "day": 2, "phase": "night", "source": "llm"}],
        }
        roles = {3: Role.WITCH, 1: Role.WEREWOLF}
        mistakes = _collect_mistakes(decisions, roles)
        poisoned = [m for m in mistakes if m.mistake_type == MISTAKE_POISONED_GOOD]
        self.assertEqual(len(poisoned), 0)


class GenerateEnhancedReviewTests(unittest.TestCase):
    """Test generate_enhanced_review integration."""

    def test_minimal_input(self):
        game_log = {"entries": []}
        roles = {1: Role.VILLAGER, 2: Role.WEREWOLF}
        report = generate_enhanced_review(
            game_log=game_log,
            agent_decisions={},
            roles=roles,
            winner_team="villagers",
            game_id="test_001",
        )
        self.assertIsInstance(report, GameReviewReport)
        self.assertEqual(report.game_id, "test_001")
        self.assertEqual(report.winner, "villagers")
        self.assertIn(1, report.player_scores)
        self.assertIn(2, report.player_scores)

    def test_team_scores_present(self):
        game_log = {"entries": []}
        roles = {1: Role.VILLAGER, 2: Role.WEREWOLF}
        report = generate_enhanced_review(
            game_log=game_log, agent_decisions={},
            roles=roles, winner_team="villagers",
        )
        self.assertIn("villagers", report.team_scores)
        self.assertIn("werewolves", report.team_scores)


if __name__ == "__main__":
    unittest.main()
