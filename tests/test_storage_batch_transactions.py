from __future__ import annotations

import pytest


def _seed_game(conn, game_id: str = "g1") -> None:
    conn.execute(
        "INSERT INTO games (id, seed, started_at) VALUES (?, ?, ?)",
        (game_id, 1, "2026-01-01T00:00:00+08:00"),
    )
    conn.commit()


def test_evaluation_save_batch_rolls_back_whole_batch_on_failure(tmp_path):
    from storage.battle.evaluation_repo import EvaluationStore
    from storage.schema import get_connection

    conn = get_connection(tmp_path / "wolf.db")
    try:
        _seed_game(conn)
        store = EvaluationStore(conn, timestamp_provider=lambda: "2026-01-01T00:00:00+08:00")

        with pytest.raises(ValueError, match="invalid literal"):
            store.save_batch(
                [
                    {
                        "id": "ev1",
                        "game_id": "g1",
                        "player_seat": 1,
                        "role": "seer",
                        "overall_score": 0.8,
                    },
                    {
                        "id": "ev_bad",
                        "game_id": "g1",
                        "player_seat": "not-an-int",
                        "role": "werewolf",
                    },
                ]
            )

        count = conn.execute("SELECT COUNT(*) AS n FROM evaluations").fetchone()["n"]
        assert count == 0
    finally:
        conn.close()


def test_battle_review_batch_success_paths_commit(tmp_path):
    from storage.battle.review_repo import CounterfactualStore, DecisionReviewStore
    from storage.schema import get_connection

    conn = get_connection(tmp_path / "wolf.db")
    try:
        _seed_game(conn)
        reviews = DecisionReviewStore(conn, timestamp_provider=lambda: "2026-01-01T00:00:00+08:00")
        counterfactuals = CounterfactualStore(conn, timestamp_provider=lambda: "2026-01-01T00:00:00+08:00")

        review_ids = reviews.save_batch(
            [
                {
                    "id": "r1",
                    "game_id": "g1",
                    "decision_id": "d1",
                    "player_seat": 1,
                    "day": 1,
                    "phase": "day",
                    "action_type": "vote",
                    "quality": "good",
                },
                {
                    "id": "r2",
                    "game_id": "g1",
                    "decision_id": "d2",
                    "player_seat": 2,
                    "day": 1,
                    "phase": "day",
                    "action_type": "vote",
                    "quality": "bad",
                },
            ]
        )
        counterfactual_ids = counterfactuals.save_batch(
            [
                {
                    "id": "cf1",
                    "game_id": "g1",
                    "decision_id": "d1",
                    "what_if": "vote 2",
                    "confidence": 0.7,
                },
                {
                    "id": "cf2",
                    "game_id": "g1",
                    "decision_id": "d2",
                    "what_if": "vote 3",
                    "confidence": 0.4,
                },
            ]
        )

        assert review_ids == ["r1", "r2"]
        assert counterfactual_ids == ["cf1", "cf2"]
        assert len(reviews.get_for_game("g1")) == 2
        assert len(counterfactuals.get_for_game("g1")) == 2
    finally:
        conn.close()


def test_experience_save_candidates_success_path_commits(tmp_path):
    from storage.evolution.experience_repo import ExperienceCandidateStore
    from storage.shared.connection import get_evolution_connection

    conn = get_evolution_connection(tmp_path / "evolution.db")
    try:
        store = ExperienceCandidateStore(conn, timestamp_provider=lambda: "2026-01-01T00:00:00+08:00")

        saved = store.save_candidates(
            "g1",
            [
                {
                    "role": "seer",
                    "candidate_type": "decision",
                    "topic": "night check",
                    "recommendation": "check contested players",
                },
                {
                    "candidate_id": "custom_candidate",
                    "role": "witch",
                    "candidate_type": "risk",
                    "topic": "save timing",
                    "recommendation": "avoid early save without signal",
                },
            ],
            run_type="evolution_training",
            learning_eligible=True,
        )

        assert saved == ["g1_candidate_001", "custom_candidate"]
        assert len(store.list_candidates(game_id="g1")) == 2
    finally:
        conn.close()


class _Evidence:
    def __init__(self, game_id: str) -> None:
        self.game_id = game_id

    def to_dict(self) -> dict[str, str]:
        return {"game_id": self.game_id}


def test_evolution_save_proposals_success_path_commits(tmp_path):
    from storage.evolution.run_repo import EvolutionStore
    from storage.interfaces import SkillProposalData
    from storage.shared.connection import get_evolution_connection

    conn = get_evolution_connection(tmp_path / "evolution.db")
    try:
        store = EvolutionStore(conn)
        store.save_proposals(
            [
                SkillProposalData(
                    proposal_id="p1",
                    target_file="seer/vote.md",
                    action_type="append_rule",
                    content="Wait for evidence.",
                    rationale="two games",
                    confidence=0.8,
                    risk="low",
                    expected_metric="role_score",
                    expected_direction="improve",
                    evidence=[_Evidence("g1"), _Evidence("g2")],
                ),
                SkillProposalData(
                    proposal_id="p2",
                    target_file="witch/save.md",
                    action_type="append_rule",
                    content="Track poison risk.",
                    rationale="one game",
                    confidence=0.5,
                    risk="medium",
                    expected_metric="win_rate",
                    expected_direction="improve",
                ),
            ],
            source_version_id="baseline_v1",
        )

        proposals = store.list_proposals(source_version_id="baseline_v1")
        assert {proposal["id"] for proposal in proposals} == {"p1", "p2"}
    finally:
        conn.close()
