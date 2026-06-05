"""Unified ReviewService – the single entry point for post-game evaluation.

All routes (ordinary, evaluation, evolution) must use this service for
review so that scoring, counterfactuals, and reports are consistent.

ReviewService is the ONLY upstream for:
- report facts (evaluations, decision_reviews, counterfactuals, reports)
- leaderboard metrics
- EvidencePipeline structured input
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.common import beijing_now_iso
from agent.learning.review.evaluator import GameEvaluator, PlayerEvaluation
from agent.learning.review.reviewer import GameReviewer
from agent.learning.review.report import generate_enhanced_review, GameReviewReport

_log = logging.getLogger(__name__)


@dataclass
class StructuredReviewResult:
    """Complete structured review output for a single game."""

    game_id: str
    player_evaluations: list[PlayerEvaluation] = field(default_factory=list)
    review_report: GameReviewReport | None = None
    scoring_version: str = "scoring_v1"
    evaluator_config_hash: str = "rule_heuristic_v1"
    ruleset_version: str = "werewolf_12p_v1"
    review_status: str = "completed"
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.review_status == "completed" and not self.errors

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "scoring_version": self.scoring_version,
            "evaluator_config_hash": self.evaluator_config_hash,
            "ruleset_version": self.ruleset_version,
            "review_status": self.review_status,
            "player_count": len(self.player_evaluations),
            "errors": self.errors,
        }


class ReviewService:
    """Unified facade for game review and evaluation.

    Orchestrates:
    1. GameEvaluator – multi-dimensional rule-based scoring
    2. GameReviewer – turning-point detection, counterfactual analysis
    3. ReportGenerator – structured report with suggestions

    Does NOT call LLM – all scoring is deterministic/heuristic.
    LLM structured judgments are a future extension point.
    """

    def __init__(self, *, scoring_version: str = "scoring_v1") -> None:
        self._scoring_version = scoring_version

    def review_game(
        self,
        *,
        game_id: str,
        events: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
        player_roles: dict[int, str],
        winner: str,
        ruleset_version: str = "werewolf_12p_v1",
    ) -> StructuredReviewResult:
        """Run full structured review on a completed game.

        Returns StructuredReviewResult with per-player evaluations,
        decision reviews, counterfactuals, and report.
        """
        errors: list[str] = []

        # Step 1: Multi-dimensional evaluation
        evaluator = GameEvaluator()
        evaluation = None
        player_evaluations = []
        try:
            evaluation = evaluator.evaluate_game(
                game_id=game_id,
                events=events,
                decisions=decisions,
                player_roles=player_roles,
                winner=winner,
            )
            player_evaluations = evaluation.players
        except Exception as exc:
            _log.warning("GameEvaluator failed for %s: %s", game_id, exc, exc_info=True)
            errors.append(f"evaluator_error: {exc}")

        # Step 2: Enhanced review report (turning points, counterfactuals, etc.)
        review_report = None
        if evaluation is not None:
            try:
                from agent.learning.review.reviewer import GameReviewer
                from agent.learning.review.report import ReportGenerator

                reviewer = GameReviewer()
                reviews, counterfactuals = reviewer.review_game(
                    game_id,
                    events=events,
                    decisions=decisions,
                    evaluation=evaluation,
                    player_roles=player_roles,
                    winner=winner,
                )
                generator = ReportGenerator()
                total_days = max((e.get("day", 0) for e in events), default=0)
                review_report = generator.generate(
                    game_id,
                    evaluation=evaluation,
                    reviews=reviews,
                    counterfactuals=counterfactuals,
                    events=events,
                    player_roles=player_roles,
                    winner=winner,
                    total_days=total_days,
                )
            except Exception as exc:
                _log.warning("Review report failed for %s: %s", game_id, exc, exc_info=True)
                errors.append(f"report_error: {exc}")

        review_status = "completed" if not errors else "partial"
        return StructuredReviewResult(
            game_id=game_id,
            player_evaluations=player_evaluations,
            review_report=review_report,
            scoring_version=self._scoring_version,
            ruleset_version=ruleset_version,
            review_status=review_status,
            errors=errors,
        )

    @staticmethod
    def persist_to_db(
        conn: Any,
        result: StructuredReviewResult,
    ) -> None:
        """Persist structured review results to SQLite.

        Writes evaluations, decision_reviews, counterfactuals, and reports.
        """
        from storage.battle.evaluation_repo import EvaluationStore
        from storage.battle.review_repo import ReviewStore

        try:
            eval_store = EvaluationStore(conn)
            for pe in result.player_evaluations:
                eval_store.save_evaluation(
                    evaluation_id=pe.id,
                    game_id=result.game_id,
                    player_seat=pe.player_seat,
                    role=pe.role,
                    speech_score=pe.speech_score,
                    vote_score=pe.vote_score,
                    skill_score=pe.skill_score,
                    logic_score=pe.logic_score,
                    team_score=pe.team_score,
                    risk_penalty=pe.risk_penalty,
                    role_score=pe.role_score,
                    score_completeness=pe.score_completeness,
                    information_score=pe.information_score,
                    cooperation_score=pe.cooperation_score,
                    overall_score=pe.overall_score,
                    scoring_version=result.scoring_version,
                    evaluator_config_hash=result.evaluator_config_hash,
                    ruleset_version=result.ruleset_version,
                    created_at=pe.created_at,
                )
        except Exception as exc:
            _log.warning("Failed to persist evaluations: %s", exc, exc_info=True)

        if result.review_report is not None:
            try:
                review_store = ReviewStore(conn)
                review_store.save_report(
                    game_id=result.game_id,
                    report=result.review_report,
                )
            except Exception as exc:
                _log.warning("Failed to persist review report: %s", exc, exc_info=True)
