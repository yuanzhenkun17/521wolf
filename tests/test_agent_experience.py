"""Tests for agent.experience — ExperienceCard, extract_experiences, persistence."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from engine.models import Role, Team

from agent.cognition.experience import (
    ExperienceCard,
    ExperienceDecision,
    extract_experiences,
    load_role_cards,
    write_experience_card,
    write_game_experiences,
)
from agent.evaluation.review import AgentScores
from agent.evaluation.review_enhanced import (
    GameReviewReport,
    PlayerReview,
    DecisionMistake,
    TurningPoint,
    SkillReview,
    MISTAKE_POISONED_GOOD,
)


class ExperienceDecisionTests(unittest.TestCase):
    """Test ExperienceDecision dataclass."""

    def test_construction(self):
        ed = ExperienceDecision(
            day=2, phase="night", action_type="witch_act",
            selected_skills=["witch_poison"],
            context="女巫夜晚行动", action="毒杀P5",
            expected_outcome="毒中狼人", actual_result="毒错",
            lesson="毒人前需要更多信息",
        )
        self.assertEqual(ed.day, 2)
        self.assertEqual(ed.action_type, "witch_act")

    def test_to_dict(self):
        ed = ExperienceDecision(
            day=1, phase="day", action_type="speak",
            selected_skills=["game_rules"], context="", action="",
            expected_outcome="", actual_result="", lesson="",
        )
        d = ed.to_dict()
        self.assertEqual(d["day"], 1)


class ExperienceCardTests(unittest.TestCase):
    """Test ExperienceCard dataclass and serialization."""

    def test_minimal_construction(self):
        card = ExperienceCard(
            card_id="g1_p1_werewolf",
            game_id="g1", player_id=1, role="werewolf",
            team="werewolves", outcome="lose",
            created_at="2026-01-01T00:00:00",
            summary="本局失败", situation_tags=["werewolf"],
            key_decisions=[], lessons=["lesson1"],
            avoid_next_time=[], reusable_strategies=[],
            related_skills=[], evidence_decision_ids=[],
            score=5.0, confidence=0.7,
        )
        self.assertEqual(card.card_id, "g1_p1_werewolf")
        self.assertEqual(card.outcome, "lose")

    def test_to_dict_includes_all_fields(self):
        card = ExperienceCard(
            card_id="g1_p1_wolf", game_id="g1",
            player_id=1, role="werewolf", team="werewolves",
            outcome="lose", created_at="now",
            summary="test", situation_tags=["werewolf"],
            key_decisions=[
                ExperienceDecision(day=1, phase="day", action_type="speak",
                                   selected_skills=[], context="", action="",
                                   expected_outcome="", actual_result="", lesson=""),
            ],
            lessons=["l1"], avoid_next_time=["a1"],
            reusable_strategies=["r1"], related_skills=["s1"],
            evidence_decision_ids=["d1"], score=6.0, confidence=0.8,
        )
        d = card.to_dict()
        self.assertEqual(d["card_id"], "g1_p1_wolf")
        self.assertEqual(len(d["key_decisions"]), 1)
        self.assertEqual(d["score"], 6.0)

    def test_to_dict_json_serializable(self):
        card = ExperienceCard(
            card_id="g1_p1_v", game_id="g1",
            player_id=1, role="villager", team="villagers",
            outcome="win", created_at="now",
            summary="", situation_tags=[],
            key_decisions=[], lessons=[], avoid_next_time=[],
            reusable_strategies=[], related_skills=[],
            evidence_decision_ids=[], score=7.0, confidence=0.9,
        )
        json_str = json.dumps(card.to_dict(), ensure_ascii=False)
        loaded = json.loads(json_str)
        self.assertEqual(loaded["role"], "villager")


class ExtractExperienceTests(unittest.TestCase):
    """Test extract_experiences function."""

    def setUp(self):
        self.roles = {1: Role.VILLAGER, 2: Role.WEREWOLF}
        self.decisions = {
            1: [{"source": "llm", "day": 1, "phase": "day", "action_type": "speak",
                 "selected_skills": ["game_rules"], "selected_target": None}],
            2: [{"source": "fallback", "day": 1, "phase": "night", "action_type": "werewolf_kill",
                 "selected_skills": ["deep_wolf"], "selected_target": 3}],
        }
        self.review = GameReviewReport(
            game_id="test_g1",
            winner="villagers",
            summary="好人获胜",
            team_scores={"villagers": 7.0, "werewolves": 5.0},
            player_scores={
                1: PlayerReview(player_id=1, role="villager", team="villagers",
                                outcome="win", total_score=7.0,
                                speech_score=6.0, vote_score=7.0,
                                skill_score=8.0, information_score=5.0,
                                cooperation_score=6.0),
                2: PlayerReview(player_id=2, role="werewolf", team="werewolves",
                                outcome="lose", total_score=5.0,
                                speech_score=5.0, vote_score=5.0,
                                skill_score=4.0, information_score=4.0,
                                cooperation_score=5.0,
                                mistake_types=[MISTAKE_POISONED_GOOD]),
            },
            key_turning_points=[],
            mistakes=[],
            skill_summary={},
            counterfactuals=[],
            suggestions=[],
        )

    def test_each_player_gets_card(self):
        cards = extract_experiences(
            game_id="test_g1", roles=self.roles,
            agent_decisions=self.decisions,
            review=self.review, winner_team="villagers",
        )
        self.assertEqual(len(cards), 2)

    def test_card_has_correct_role(self):
        cards = extract_experiences(
            game_id="test_g1", roles=self.roles,
            agent_decisions=self.decisions,
            review=self.review, winner_team="villagers",
        )
        card1 = next(c for c in cards if c.player_id == 1)
        card2 = next(c for c in cards if c.player_id == 2)
        self.assertEqual(card1.role, "villager")
        self.assertEqual(card2.role, "werewolf")

    def test_winner_gets_win_outcome(self):
        cards = extract_experiences(
            game_id="test_g1", roles=self.roles,
            agent_decisions=self.decisions,
            review=self.review, winner_team="villagers",
        )
        card1 = next(c for c in cards if c.player_id == 1)
        card2 = next(c for c in cards if c.player_id == 2)
        self.assertEqual(card1.outcome, "win")
        self.assertEqual(card2.outcome, "lose")

    def test_loser_has_lessons(self):
        cards = extract_experiences(
            game_id="test_g1", roles=self.roles,
            agent_decisions=self.decisions,
            review=self.review, winner_team="villagers",
        )
        card2 = next(c for c in cards if c.player_id == 2)
        self.assertGreater(len(card2.lessons), 0)

    def test_card_has_related_skills(self):
        cards = extract_experiences(
            game_id="test_g1", roles=self.roles,
            agent_decisions=self.decisions,
            review=self.review, winner_team="villagers",
        )
        card2 = next(c for c in cards if c.player_id == 2)
        self.assertIn("deep_wolf", card2.related_skills)

    def test_card_has_situation_tags(self):
        cards = extract_experiences(
            game_id="test_g1", roles=self.roles,
            agent_decisions=self.decisions,
            review=self.review, winner_team="villagers",
        )
        card2 = next(c for c in cards if c.player_id == 2)
        self.assertIn("werewolf", card2.situation_tags)
        self.assertIn("lose", card2.situation_tags)


class PersistenceTests(unittest.TestCase):
    """Test writing and reading experience cards."""

    def setUp(self):
        self.card = ExperienceCard(
            card_id="g1_p1_villager", game_id="g1",
            player_id=1, role="villager", team="villagers",
            outcome="win", created_at="now",
            summary="test", situation_tags=["villager", "win"],
            key_decisions=[], lessons=["lesson1"],
            avoid_next_time=[], reusable_strategies=[],
            related_skills=[], evidence_decision_ids=[],
            score=7.0, confidence=0.8,
        )

    def test_write_experience_card_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            path = write_experience_card(self.card, output_dir=base)
            self.assertTrue(path.exists())
            self.assertEqual(path.name, "cards.jsonl")
            self.assertIn("villager", str(path))

    def test_write_game_experiences_creates_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            game_dir = Path(tmp) / "game_001"
            write_game_experiences(
                cards=[self.card],
                game_dir=game_dir,
            )
            exp_dir = game_dir / "experiences"
            self.assertTrue(exp_dir.exists())
            json_files = list(exp_dir.glob("*.json"))
            self.assertEqual(len(json_files), 1)

    def test_load_role_cards_returns_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_experience_card(self.card, output_dir=tmp)
            cards = load_role_cards(Role.VILLAGER, base_dir=tmp)
            self.assertEqual(len(cards), 1)
            self.assertEqual(cards[0]["card_id"], "g1_p1_villager")

    def test_load_role_cards_empty_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            cards = load_role_cards(Role.WEREWOLF, base_dir=tmp)
            self.assertEqual(cards, [])

    def test_append_multiple_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_experience_card(self.card, output_dir=tmp)
            card2 = ExperienceCard(
                card_id="g2_p1_villager", game_id="g2",
                player_id=1, role="villager", team="villagers",
                outcome="lose", created_at="now",
                summary="test2", situation_tags=[],
                key_decisions=[], lessons=[], avoid_next_time=[],
                reusable_strategies=[], related_skills=[],
                evidence_decision_ids=[], score=5.0, confidence=0.6,
            )
            write_experience_card(card2, output_dir=tmp)
            cards = load_role_cards(Role.VILLAGER, base_dir=tmp)
            self.assertEqual(len(cards), 2)
            self.assertEqual(cards[0]["card_id"], "g1_p1_villager")
            self.assertEqual(cards[1]["card_id"], "g2_p1_villager")


if __name__ == "__main__":
    unittest.main()
