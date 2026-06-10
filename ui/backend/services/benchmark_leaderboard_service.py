"""Benchmark leaderboard read and comparison service for the UI backend."""

from __future__ import annotations

import logging
from typing import Any, Protocol, cast

from fastapi import HTTPException

from storage.benchmark.leaderboard_repo import BenchmarkLeaderboardRepository
from ui.backend.services.benchmark_leaderboard_payloads import (
    _benchmark_batch_boundary,
    _benchmark_result_batch_id,
    _benchmark_result_game_count,
    _benchmark_result_has_unrankable_evidence,
    _benchmark_result_role,
    _benchmark_results,
    _dedupe_unrankable_evidence,
    _filter_unrankable_evidence_for_compare,
    _first_float,
    _first_int,
    _first_text,
    _leaderboard_compare_row,
    _leaderboard_compare_summary,
    _leaderboard_row_payload,
    _leaderboard_subject_key,
    _leaderboard_unrankable_evidence_row,
    _row_to_dict,
    _select_leaderboard_baseline,
)
_log = logging.getLogger(__name__)


class BenchmarkLeaderboardServiceContextProtocol(Protocol):
    """Context capabilities required by ``BenchmarkLeaderboardService``."""

    paths: object
    evolution_batches: dict[str, dict[str, Any]]


class BenchmarkLeaderboardService:
    """Read benchmark leaderboard rows and produce comparison payloads."""

    def __init__(self, context: BenchmarkLeaderboardServiceContextProtocol) -> None:
        self._context = context

    def _open_connection(self) -> Any:
        from app.lib.score import open_eval_connection

        return open_eval_connection(getattr(self._context, "paths", None))

    def load_role_leaderboard_rows(
        self,
        role: str,
        *,
        evaluation_set_id: str | None = None,
    ) -> list[Any]:
        conn = None
        try:
            conn = self._open_connection()
            return BenchmarkLeaderboardRepository(conn).list_role_rows(
                role,
                evaluation_set_id=evaluation_set_id,
            )
        finally:
            if conn is not None:
                conn.close()

    def load_leaderboard_rows(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        limit: int = 100,
    ) -> list[Any]:
        conn = None
        try:
            conn = self._open_connection()
            return BenchmarkLeaderboardRepository(conn).list(
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                target_role=target_role,
                limit=limit,
            )
        finally:
            if conn is not None:
                conn.close()

    def load_role_leaderboard_rows_for_roles(
        self,
        roles: list[str],
        *,
        evaluation_set_id: str | None = None,
    ) -> list[Any]:
        conn = None
        try:
            conn = self._open_connection()
            return BenchmarkLeaderboardRepository(conn).list_role_rows_for_roles(
                roles,
                evaluation_set_id=evaluation_set_id,
            )
        finally:
            if conn is not None:
                conn.close()

    def leaderboard_scores_for_role(
        self,
        role: str,
        *,
        evaluation_set_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Load persisted benchmark scores for a role, keyed by version id."""
        scores: dict[str, dict[str, Any]] = {}
        try:
            rows = self.load_role_leaderboard_rows(
                role,
                evaluation_set_id=evaluation_set_id,
            )
            for row in rows:
                payload = _row_to_dict(row)
                vid = payload.get("target_version_id")
                if vid and vid not in scores:  # newest row per version wins
                    scores[str(vid)] = _leaderboard_row_payload(row)
        except Exception:  # noqa: BLE001 - leaderboard read is best-effort
            _log.warning("leaderboard_scores_for_role failed for %s", role, exc_info=True)
        return scores

    def leaderboard_entries(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Load benchmark leaderboard rows with explicit scope isolation."""
        normalized_scope = str(scope or "").strip().lower()
        if normalized_scope not in {"", "role_version", "model"}:
            raise HTTPException(status_code=422, detail="unsupported leaderboard scope")
        rows_out: list[dict[str, Any]] = []
        try:
            rows = self.load_leaderboard_rows(
                scope=normalized_scope or None,
                evaluation_set_id=evaluation_set_id,
                target_role=target_role,
                limit=limit,
            )
            rows_out = [_leaderboard_row_payload(row) for row in rows]
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001 - leaderboard read is best-effort
            _log.warning("leaderboard_entries failed", exc_info=True)
        return rows_out

    def model_leaderboard_entries(
        self,
        *,
        evaluation_set_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Load model-scope benchmark leaderboard rows."""
        return self.leaderboard_entries(scope="model", evaluation_set_id=evaluation_set_id, limit=limit)

    def leaderboard_unrankable_evidence(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        limit: int = 100,
        rows: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """Return non-ranking evidence rows for subjects excluded by leaderboard gates."""
        normalized_scope = str(scope or "").strip().lower() or None
        target_role_filter = target_role if normalized_scope != "model" else None
        source_rows = rows if rows is not None else self._public_leaderboard_entries(
            scope=normalized_scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role_filter,
            limit=limit,
        )
        evidence = _filter_unrankable_evidence_for_compare(
            source_rows,
            scope=normalized_scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role_filter,
        )
        evidence.extend(
            self._benchmark_batch_unrankable_evidence(
                scope=normalized_scope,
                evaluation_set_id=evaluation_set_id,
                target_role=target_role_filter,
                limit=limit,
            )
        )
        return _dedupe_unrankable_evidence(evidence)[: max(1, min(int(limit or 100), 500))]

    def leaderboard_compare(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        baseline_subject_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return canonical leaderboard deltas against a pinned baseline row."""
        normalized_scope = str(scope or "").strip().lower() or None
        target_role_filter = target_role if normalized_scope != "model" else None
        rows = self._public_leaderboard_entries(
            scope=normalized_scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role_filter,
            limit=limit,
        )
        rankable_rows = [row for row in rows if row.get("rankable") is not False]
        unrankable_evidence = self.leaderboard_unrankable_evidence(
            scope=normalized_scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role_filter,
            limit=limit,
            rows=rows,
        )
        baseline = _select_leaderboard_baseline(rankable_rows, baseline_subject_id=baseline_subject_id)
        compare_rows = [
            _leaderboard_compare_row(row, baseline, scope=normalized_scope, target_role=target_role)
            for row in rankable_rows
        ]
        summary = _leaderboard_compare_summary(compare_rows)
        summary["unrankable_count"] = len(unrankable_evidence)
        summary["unrankable_evidence_count"] = len(unrankable_evidence)
        return {
            "kind": "benchmark_leaderboard_compare",
            "schema_version": 1,
            "scope": normalized_scope,
            "evaluation_set_id": evaluation_set_id,
            "target_role": target_role,
            "baseline_subject_id": _leaderboard_subject_key(baseline) if baseline else None,
            "baseline": baseline,
            "rows": compare_rows,
            "unrankable_evidence": unrankable_evidence,
            "summary": summary,
        }

    def leaderboard_scores_for_roles(
        self,
        roles: list[str],
        *,
        evaluation_set_id: str | None = None,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        """Load persisted benchmark scores for multiple roles with one DB round trip."""
        role_keys = [str(role) for role in roles if role]
        if not role_keys:
            return {}
        scores: dict[str, dict[str, dict[str, Any]]] = {role: {} for role in role_keys}
        try:
            rows = self.load_role_leaderboard_rows_for_roles(
                role_keys,
                evaluation_set_id=evaluation_set_id,
            )
            for row in rows:
                payload = _row_to_dict(row)
                role = payload.get("target_role")
                vid = payload.get("target_version_id")
                if role in scores and vid and vid not in scores[role]:
                    scores[role][str(vid)] = _leaderboard_row_payload(row)
        except Exception:  # noqa: BLE001 - leaderboard read is best-effort
            _log.warning("leaderboard_scores_for_roles failed", exc_info=True)
        return scores

    def _public_leaderboard_entries(
        self,
        *,
        scope: str | None,
        evaluation_set_id: str | None,
        target_role: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        loader = getattr(self._context, "leaderboard_entries", None)
        if callable(loader):
            return cast(
                list[dict[str, Any]],
                loader(
                    scope=scope,
                    evaluation_set_id=evaluation_set_id,
                    target_role=target_role,
                    limit=limit,
                ),
            )
        return self.leaderboard_entries(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role,
            limit=limit,
        )

    def _benchmark_batch_unrankable_evidence(
        self,
        *,
        scope: str | None,
        evaluation_set_id: str | None,
        target_role: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Recover gate-failed benchmark results that never reached leaderboard rows."""
        normalized_scope = str(scope or "").strip().lower() or None
        requested_eval = str(evaluation_set_id or "").strip()
        requested_role = str(target_role or "").strip().lower()
        evidence: list[dict[str, Any]] = []
        capped_limit = max(1, min(int(limit or 100), 500))
        evolution_batches = getattr(self._context, "evolution_batches", {})
        for batch in evolution_batches.values():
            if not isinstance(batch, dict):
                continue
            meta = _benchmark_batch_boundary(batch)
            batch_scope = str(meta.get("target_type") or "").strip().lower()
            if normalized_scope and batch_scope and batch_scope != normalized_scope:
                continue
            batch_eval = str(meta.get("evaluation_set_id") or "").strip()
            if requested_eval and batch_eval != requested_eval:
                continue
            for index, result in enumerate(_benchmark_results(batch), start=1):
                if not _benchmark_result_has_unrankable_evidence(result):
                    continue
                result_role = _benchmark_result_role(result)
                if requested_role and str(result_role or "").strip().lower() != requested_role:
                    continue
                result_config = result.get("config") if isinstance(result.get("config"), dict) else {}
                summary = result.get("score_summary") if isinstance(result.get("score_summary"), dict) else {}
                gate = result.get("leaderboard_gate") if isinstance(result.get("leaderboard_gate"), dict) else {}
                gate_metrics = gate.get("metrics") if isinstance(gate.get("metrics"), dict) else {}
                result_batch_id = _benchmark_result_batch_id(result)
                model_id = _first_text(result.get("model_id"), result_config.get("model_id"), meta.get("model_id"))
                model_config_hash = _first_text(
                    result.get("model_config_hash"),
                    result_config.get("model_config_hash"),
                    meta.get("model_config_hash"),
                )
                target_version_id = _first_text(result.get("target_version_id"), result_config.get("target_version_id"))
                subject_id = (
                    model_config_hash or model_id or result_batch_id
                    if batch_scope == "model"
                    else target_version_id or result_batch_id
                )
                total_games = _first_int(
                    result.get("total_games"),
                    result.get("game_count"),
                    result.get("attempted_game_count"),
                    result_config.get("game_count"),
                    summary.get("total_games"),
                    summary.get("game_count"),
                    default=_benchmark_result_game_count(result),
                )
                completed_games = _first_int(
                    result.get("completed_games"),
                    result.get("completed"),
                    result.get("games_played"),
                    summary.get("completed_games"),
                    summary.get("games_played"),
                    gate_metrics.get("completed_games"),
                    default=_benchmark_result_game_count(result),
                )
                reason = _first_text(
                    result.get("rankable_reason"),
                    result.get("leaderboard_skipped_reason"),
                    gate.get("reason"),
                    summary.get("rankable_reason"),
                    "rankable gate failed",
                )
                row_summary = dict(summary)
                row_summary.update(
                    {
                        "batch_id": meta.get("batch_id"),
                        "result_batch_id": result_batch_id,
                        "rankable_reason": reason,
                        "leaderboard_skipped_reason": result.get("leaderboard_skipped_reason") or gate.get("reason"),
                        "completed_games": completed_games,
                        "total_games": total_games,
                    }
                )
                row = {
                    "scope": batch_scope or normalized_scope,
                    "hash": subject_id,
                    "subject_id": subject_id,
                    "model_id": model_id or None,
                    "model_config_hash": model_config_hash or None,
                    "target_role": result_role,
                    "target_version_id": target_version_id or None,
                    "comparison_group_id": meta.get("batch_id"),
                    "evaluation_set_id": batch_eval or requested_eval,
                    "seed_set_id": meta.get("seed_set_id"),
                    "game_count": total_games,
                    "games_played": completed_games,
                    "completed_games": completed_games,
                    "total_games": total_games,
                    "valid_game_rate": _first_float(
                        result.get("valid_game_rate"),
                        summary.get("valid_game_rate"),
                        gate_metrics.get("valid_game_rate"),
                    ),
                    "rankable": False,
                    "rankable_reason": reason,
                    "leaderboard_skipped_reason": result.get("leaderboard_skipped_reason") or gate.get("reason"),
                    "summary": row_summary,
                    "batch_id": meta.get("batch_id"),
                    "result_batch_id": result_batch_id,
                    "updated_at": batch.get("finished_at") or batch.get("updated_at") or batch.get("started_at"),
                    "source": "benchmark_batch",
                }
                evidence.append(_leaderboard_unrankable_evidence_row(row, index=index))
                if len(evidence) >= capped_limit:
                    return evidence
        return evidence


__all__ = [
    "BenchmarkLeaderboardService",
    "BenchmarkLeaderboardServiceContextProtocol",
]
