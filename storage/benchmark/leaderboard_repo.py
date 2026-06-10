"""Repository for benchmark leaderboard rows."""

from __future__ import annotations

import json
import uuid
from typing import Any

from app.util.time import beijing_now_iso
from storage.shared.database import StorageConnection


class BenchmarkLeaderboardRepository:
    """Persist and query benchmark leaderboard runtime data."""

    def __init__(self, conn: StorageConnection, *, autocommit: bool = False) -> None:
        self._conn = conn
        self._autocommit = autocommit

    def save(self, entry: dict[str, Any]) -> None:
        """Persist a leaderboard entry to benchmark_leaderboard."""
        scope = entry.get("scope") or ("role_version" if entry.get("target_role") else "model")
        subject_id = str(
            entry.get("subject_id")
            or entry.get("target_version_id")
            or entry.get("model_config_hash")
            or entry.get("model_id")
            or entry.get("hash")
            or ""
        )
        group_id = entry.get("comparison_group_id")
        row_id = entry.get("id") or f"{scope}:{subject_id}:{group_id or entry.get('batch_id', '')}" or uuid.uuid4().hex
        by_role = entry.get("by_role_category_scores")
        summary = dict(entry.get("summary") or {})
        for key in ("benchmark_id", "benchmark_version", "benchmark_config_hash", "config_hash", "model_runtime"):
            if entry.get(key) not in (None, ""):
                summary.setdefault(key, entry.get(key))
        source_run_id = (
            entry.get("source_run_id")
            or entry.get("run_id")
            or entry.get("benchmark_batch_id")
            or entry.get("comparison_group_id")
            or entry.get("batch_id")
        )
        result_batch_id = entry.get("result_batch_id") or entry.get("batch_id")
        if source_run_id:
            summary.setdefault("source_run_id", str(source_run_id))
            summary.setdefault("batch_id", str(source_run_id))
            summary.setdefault("report_id", f"benchmark_report:{source_run_id}")
        if result_batch_id:
            summary.setdefault("result_batch_id", str(result_batch_id))
        updated_at = str(entry.get("updated_at") or beijing_now_iso())
        self._conn.execute(
            """INSERT INTO benchmark_leaderboard
            (id, scope, subject_id, model_id, model_config_hash, target_role, target_version_id,
             comparison_group_id, evaluation_set_id, seed_set_id,
             games_played, valid_game_rate, strength_score, avg_role_score, by_role_category_scores,
             avg_speech_score, avg_vote_score, avg_skill_score, avg_logic_score, avg_team_score,
             risk_penalty, fallback_rate, llm_error_rate, policy_adjusted_rate,
             target_side_win_rate, rankable, data_sufficient, summary, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                scope = excluded.scope,
                subject_id = excluded.subject_id,
                model_id = excluded.model_id,
                model_config_hash = excluded.model_config_hash,
                target_role = excluded.target_role,
                target_version_id = excluded.target_version_id,
                comparison_group_id = excluded.comparison_group_id,
                evaluation_set_id = excluded.evaluation_set_id,
                seed_set_id = excluded.seed_set_id,
                games_played = excluded.games_played,
                valid_game_rate = excluded.valid_game_rate,
                strength_score = excluded.strength_score,
                avg_role_score = excluded.avg_role_score,
                by_role_category_scores = excluded.by_role_category_scores,
                avg_speech_score = excluded.avg_speech_score,
                avg_vote_score = excluded.avg_vote_score,
                avg_skill_score = excluded.avg_skill_score,
                avg_logic_score = excluded.avg_logic_score,
                avg_team_score = excluded.avg_team_score,
                risk_penalty = excluded.risk_penalty,
                fallback_rate = excluded.fallback_rate,
                llm_error_rate = excluded.llm_error_rate,
                policy_adjusted_rate = excluded.policy_adjusted_rate,
                target_side_win_rate = excluded.target_side_win_rate,
                rankable = excluded.rankable,
                data_sufficient = excluded.data_sufficient,
                summary = excluded.summary,
                updated_at = excluded.updated_at""",
            (
                row_id,
                scope,
                subject_id,
                entry.get("model_id"),
                entry.get("model_config_hash"),
                entry.get("target_role"),
                entry.get("target_version_id"),
                group_id,
                entry.get("evaluation_set_id"),
                entry.get("seed_set_id"),
                entry.get("game_count", 0),
                entry.get("valid_game_rate", 0.0),
                entry.get("strength_score", 0.0),
                entry.get("avg_role_score", entry.get("target_role_role_weighted_score", 0.0)),
                json.dumps(by_role, ensure_ascii=False) if by_role is not None else None,
                entry.get("avg_speech_score", 0.0),
                entry.get("avg_vote_score", 0.0),
                entry.get("avg_skill_score", 0.0),
                entry.get("avg_logic_score", 0.0),
                entry.get("avg_team_score", 0.0),
                entry.get("risk_penalty", 0.0),
                entry.get("fallback_rate", 0.0),
                entry.get("llm_error_rate", 0.0),
                entry.get("policy_adjusted_rate", 0.0),
                entry.get("target_side_win_rate", 0.0),
                1 if entry.get("rankable") else 0,
                1 if entry.get("rankable") else 0,
                json.dumps(summary, ensure_ascii=False),
                updated_at,
            ),
        )
        if self._autocommit:
            self._conn.commit()

    def list(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        limit: int = 100,
    ) -> list[Any]:
        """Load benchmark leaderboard rows with explicit scope isolation."""
        where = "WHERE 1 = 1 "
        params: list[Any] = []
        if scope:
            where += "AND scope = ? "
            params.append(scope)
        if evaluation_set_id:
            where += "AND evaluation_set_id = ? "
            params.append(evaluation_set_id)
        if target_role:
            where += "AND target_role = ? "
            params.append(target_role)
        capped_limit = max(1, min(int(limit or 100), 500))
        params.append(capped_limit)
        return self._conn.execute(
            _LEADERBOARD_SELECT_COLUMNS
            + "FROM benchmark_leaderboard "
            + where
            + "ORDER BY rankable DESC, strength_score DESC, avg_role_score DESC, updated_at DESC "
            + "LIMIT ?",
            tuple(params),
        ).fetchall()

    def list_role_rows(
        self,
        role: str,
        *,
        evaluation_set_id: str | None = None,
    ) -> list[Any]:
        """Load newest-first leaderboard rows for one role."""
        return self.list_role_rows_for_roles(
            [role],
            evaluation_set_id=evaluation_set_id,
        )

    def list_role_rows_for_roles(
        self,
        roles: list[str],
        *,
        evaluation_set_id: str | None = None,
    ) -> list[Any]:
        """Load newest-first leaderboard rows for multiple roles."""
        role_keys = [str(role) for role in roles if role]
        if not role_keys:
            return []
        placeholders = ", ".join("?" for _ in role_keys)
        where = f"WHERE scope = 'role_version' AND target_role IN ({placeholders}) "
        params: list[Any] = list(role_keys)
        if evaluation_set_id:
            where += "AND evaluation_set_id = ? "
            params.append(evaluation_set_id)
        return self._conn.execute(
            _LEADERBOARD_SELECT_COLUMNS
            + "FROM benchmark_leaderboard "
            + where
            + "ORDER BY updated_at DESC",
            tuple(params),
        ).fetchall()


_LEADERBOARD_SELECT_COLUMNS = (
    "SELECT scope, subject_id, model_id, model_config_hash, target_role, target_version_id, "
    "comparison_group_id, evaluation_set_id, seed_set_id, games_played, valid_game_rate, "
    "strength_score, avg_role_score, by_role_category_scores, avg_speech_score, avg_vote_score, "
    "avg_skill_score, avg_logic_score, avg_team_score, risk_penalty, fallback_rate, llm_error_rate, "
    "policy_adjusted_rate, target_side_win_rate, rankable, data_sufficient, summary, updated_at "
)


__all__ = ["BenchmarkLeaderboardRepository"]
