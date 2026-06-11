"""Evaluation store: CRUD for player performance evaluations."""

from __future__ import annotations

from typing import Any

from storage.shared.interfaces import TimestampProvider, storage_timestamp
from storage.shared.database import StorageConnection


class EvaluationStore:
    """Store and query per-player evaluation scores for completed games."""

    def __init__(
        self,
        conn: StorageConnection,
        timestamp_provider: TimestampProvider | None = None,
    ) -> None:
        self._conn = conn
        self._timestamp = timestamp_provider or storage_timestamp

    def save_evaluation(
        self,
        evaluation_id: str,
        game_id: str,
        player_seat: int,
        role: str,
        *,
        speech_score: float | None = None,
        vote_score: float | None = None,
        skill_score: float | None = None,
        logic_score: float | None = None,
        team_score: float | None = None,
        risk_penalty: float | None = None,
        role_score: float | None = None,
        score_completeness: float | None = None,
        # Legacy fields
        information_score: float | None = None,
        cooperation_score: float | None = None,
        overall_score: float | None = None,
        # Metadata
        scoring_version: str | None = None,
        evaluator_config_hash: str | None = None,
        ruleset_version: str | None = None,
        created_at: str | None = None,
    ) -> str:
        now = created_at or self._timestamp()
        self._conn.execute(
            "INSERT INTO evaluations "
            "(id, game_id, player_seat, role, "
            "speech_score, vote_score, skill_score, "
            "logic_score, team_score, risk_penalty, role_score, score_completeness, "
            "information_score, cooperation_score, overall_score, "
            "scoring_version, evaluator_config_hash, ruleset_version, "
            "created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "game_id = excluded.game_id, "
            "player_seat = excluded.player_seat, "
            "role = excluded.role, "
            "speech_score = excluded.speech_score, "
            "vote_score = excluded.vote_score, "
            "skill_score = excluded.skill_score, "
            "logic_score = excluded.logic_score, "
            "team_score = excluded.team_score, "
            "risk_penalty = excluded.risk_penalty, "
            "role_score = excluded.role_score, "
            "score_completeness = excluded.score_completeness, "
            "information_score = excluded.information_score, "
            "cooperation_score = excluded.cooperation_score, "
            "overall_score = excluded.overall_score, "
            "scoring_version = excluded.scoring_version, "
            "evaluator_config_hash = excluded.evaluator_config_hash, "
            "ruleset_version = excluded.ruleset_version, "
            "created_at = excluded.created_at",
            (
                evaluation_id,
                game_id,
                player_seat,
                role,
                speech_score,
                vote_score,
                skill_score,
                logic_score,
                team_score,
                risk_penalty if risk_penalty is not None else 0.0,
                role_score,
                score_completeness if score_completeness is not None else 1.0,
                information_score,
                cooperation_score,
                overall_score,
                scoring_version or "scoring_v1",
                evaluator_config_hash or "rule_heuristic_v1",
                ruleset_version or "werewolf_12p_v1",
                now,
            ),
        )
        self._conn.commit()
        return evaluation_id

    def save_batch(
        self,
        evaluations: list[dict[str, Any]],
    ) -> list[str]:
        """Save multiple evaluations in a single transaction."""
        saved: list[str] = []
        now = self._timestamp()
        with self._conn:
            for ev in evaluations:
                eid = str(ev["id"])
                self._conn.execute(
                    "INSERT INTO evaluations "
                    "(id, game_id, player_seat, role, speech_score, vote_score, "
                    "skill_score, logic_score, team_score, risk_penalty, role_score, "
                    "score_completeness, information_score, cooperation_score, "
                    "overall_score, scoring_version, evaluator_config_hash, "
                    "ruleset_version, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "game_id = excluded.game_id, "
                    "player_seat = excluded.player_seat, "
                    "role = excluded.role, "
                    "speech_score = excluded.speech_score, "
                    "vote_score = excluded.vote_score, "
                    "skill_score = excluded.skill_score, "
                    "logic_score = excluded.logic_score, "
                    "team_score = excluded.team_score, "
                    "risk_penalty = excluded.risk_penalty, "
                    "role_score = excluded.role_score, "
                    "score_completeness = excluded.score_completeness, "
                    "information_score = excluded.information_score, "
                    "cooperation_score = excluded.cooperation_score, "
                    "overall_score = excluded.overall_score, "
                    "scoring_version = excluded.scoring_version, "
                    "evaluator_config_hash = excluded.evaluator_config_hash, "
                    "ruleset_version = excluded.ruleset_version, "
                    "created_at = excluded.created_at",
                    (
                        eid,
                        str(ev["game_id"]),
                        int(ev["player_seat"]),
                        str(ev["role"]),
                        ev.get("speech_score"),
                        ev.get("vote_score"),
                        ev.get("skill_score"),
                        ev.get("logic_score"),
                        ev.get("team_score"),
                        ev.get("risk_penalty", 0.0),
                        ev.get("role_score"),
                        ev.get("score_completeness", 1.0),
                        ev.get("information_score"),
                        ev.get("cooperation_score"),
                        ev.get("overall_score"),
                        ev.get("scoring_version") or "scoring_v1",
                        ev.get("evaluator_config_hash") or "rule_heuristic_v1",
                        ev.get("ruleset_version") or "werewolf_12p_v1",
                        str(ev.get("created_at") or now),
                    ),
                )
                saved.append(eid)
        return saved

    def get_evaluation(self, evaluation_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM evaluations WHERE id = ?", (evaluation_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def get_for_game(self, game_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM evaluations WHERE game_id = ? ORDER BY player_seat",
            (game_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def query(
        self,
        *,
        game_id: str | None = None,
        role: str | None = None,
        player_seat: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []

        if game_id:
            conditions.append("game_id = ?")
            params.append(game_id)
        if role:
            conditions.append("role = ?")
            params.append(role)
        if player_seat is not None:
            conditions.append("player_seat = ?")
            params.append(player_seat)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM evaluations{where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def avg_scores_by_role(self, role: str) -> dict[str, float]:
        """Return average scores for a given role across all evaluations."""
        row = self._conn.execute(
            "SELECT "
            "AVG(speech_score) AS avg_speech, "
            "AVG(vote_score) AS avg_vote, "
            "AVG(skill_score) AS avg_skill, "
            "AVG(information_score) AS avg_information, "
            "AVG(cooperation_score) AS avg_cooperation, "
            "AVG(overall_score) AS avg_overall, "
            "COUNT(*) AS cnt "
            "FROM evaluations WHERE role = ?",
            (role,),
        ).fetchone()
        if row is None or row["cnt"] == 0:
            return {
                "avg_speech": 0.0,
                "avg_vote": 0.0,
                "avg_skill": 0.0,
                "avg_information": 0.0,
                "avg_cooperation": 0.0,
                "avg_overall": 0.0,
                "count": 0,
            }
        return {
            "avg_speech": float(row["avg_speech"] or 0.0),
            "avg_vote": float(row["avg_vote"] or 0.0),
            "avg_skill": float(row["avg_skill"] or 0.0),
            "avg_information": float(row["avg_information"] or 0.0),
            "avg_cooperation": float(row["avg_cooperation"] or 0.0),
            "avg_overall": float(row["avg_overall"] or 0.0),
            "count": int(row["cnt"]),
        }

    def delete_for_game(self, game_id: str) -> int:
        cursor = self._conn.execute(
            "DELETE FROM evaluations WHERE game_id = ?", (game_id,)
        )
        self._conn.commit()
        return cursor.rowcount
