"""Benchmark leaderboard read and comparison service for the UI backend."""

from __future__ import annotations

import json
import logging
import math
from collections import Counter
from typing import Any, Protocol, cast

from fastapi import HTTPException

from storage.benchmark.leaderboard_repo import BenchmarkLeaderboardRepository

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


def _benchmark_results(batch: dict[str, Any]) -> list[dict[str, Any]]:
    results = batch.get("results")
    if isinstance(results, list):
        return [dict(item) for item in results if isinstance(item, dict)]
    result = batch.get("result")
    return [dict(result)] if isinstance(result, dict) else []


def _benchmark_result_batch_id(result: dict[str, Any]) -> str:
    config = result.get("config") if isinstance(result.get("config"), dict) else {}
    return str(result.get("batch_id") or config.get("batch_id") or "")


def _benchmark_result_role(result: dict[str, Any]) -> str | None:
    config = result.get("config") if isinstance(result.get("config"), dict) else {}
    role = result.get("target_role") or config.get("target_role")
    return str(role) if role else None


def _benchmark_result_game_count(result: dict[str, Any]) -> int:
    for key in ("game_count", "completed", "attempted_game_count"):
        try:
            if result.get(key) is not None:
                return max(0, int(result.get(key) or 0))
        except (TypeError, ValueError):
            continue
    games = result.get("games")
    return len([item for item in games if isinstance(item, dict)]) if isinstance(games, list) else 0


def _benchmark_batch_boundary(batch: dict[str, Any]) -> dict[str, Any]:
    benchmark = batch.get("benchmark") if isinstance(batch.get("benchmark"), dict) else {}
    config = batch.get("config") if isinstance(batch.get("config"), dict) else {}
    results = _benchmark_results(batch)

    def first_result_value(*keys: str) -> Any:
        for result in results:
            result_config = result.get("config") if isinstance(result.get("config"), dict) else {}
            for key in keys:
                value = result.get(key)
                if value not in (None, ""):
                    return value
                value = result_config.get(key)
                if value not in (None, ""):
                    return value
        return None

    target_type = str(
        batch.get("target_type")
        or benchmark.get("target_type")
        or config.get("target_type")
        or first_result_value("target_type", "comparison_type")
        or "role_version"
    ).strip().lower()
    roles = batch.get("roles") if isinstance(batch.get("roles"), list) else []
    return {
        "batch_id": str(batch.get("batch_id") or batch.get("run_id") or ""),
        "status": str(batch.get("status") or "").strip().lower(),
        "target_type": "model" if target_type == "model" else "role_version",
        "benchmark_id": str(
            benchmark.get("id")
            or batch.get("benchmark_id")
            or config.get("benchmark_id")
            or first_result_value("benchmark_id")
            or ""
        ),
        "benchmark_version": (
            benchmark.get("version")
            or batch.get("benchmark_version")
            or config.get("benchmark_version")
            or first_result_value("benchmark_version")
        ),
        "evaluation_set_id": str(
            benchmark.get("evaluation_set_id")
            or batch.get("evaluation_set_id")
            or config.get("evaluation_set_id")
            or first_result_value("evaluation_set_id")
            or ""
        ),
        "seed_set_id": str(
            benchmark.get("seed_set_id")
            or batch.get("seed_set_id")
            or config.get("seed_set_id")
            or first_result_value("seed_set_id")
            or ""
        ),
        "model_id": str(batch.get("model_id") or config.get("model_id") or first_result_value("model_id") or ""),
        "model_config_hash": str(
            batch.get("model_config_hash")
            or config.get("model_config_hash")
            or first_result_value("model_config_hash")
            or ""
        ),
        "roles": [str(role).strip().lower() for role in roles if str(role).strip()],
    }


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _decode_json_field(value: Any, *, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return fallback


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _leaderboard_row_payload(row: Any) -> dict[str, Any]:
    payload = _row_to_dict(row)
    by_role = _decode_json_field(payload.get("by_role_category_scores"), fallback={})
    summary = _decode_json_field(payload.get("summary"), fallback={})
    game_count = int(payload.get("games_played") or 0)
    scope = str(payload.get("scope") or "")
    subject_id = str(payload.get("subject_id") or "")
    target_version_id = payload.get("target_version_id")
    model_id = payload.get("model_id")
    model_config_hash = payload.get("model_config_hash")
    score = float(payload.get("avg_role_score") or 0.0)
    strength_score = float(payload.get("strength_score") or score or 0.0)
    source_run_id = _first_text(
        payload.get("source_run_id"),
        payload.get("run_id"),
        payload.get("batch_id"),
        summary.get("source_run_id") if isinstance(summary, dict) else None,
        summary.get("run_id") if isinstance(summary, dict) else None,
        summary.get("batch_id") if isinstance(summary, dict) else None,
        payload.get("comparison_group_id"),
    )
    result_batch_id = _first_text(
        payload.get("result_batch_id"),
        summary.get("result_batch_id") if isinstance(summary, dict) else None,
    )
    report_id = _first_text(
        payload.get("report_id"),
        summary.get("report_id") if isinstance(summary, dict) else None,
        f"benchmark_report:{source_run_id}" if source_run_id else "",
    )
    row_payload = {
        "scope": scope,
        "hash": subject_id or str(target_version_id or model_config_hash or model_id or ""),
        "subject_id": subject_id,
        "model_id": model_id,
        "model_config_hash": model_config_hash,
        "target_role": payload.get("target_role"),
        "target_version_id": target_version_id,
        "comparison_group_id": payload.get("comparison_group_id"),
        "evaluation_set_id": payload.get("evaluation_set_id"),
        "seed_set_id": payload.get("seed_set_id"),
        "benchmark_config_hash": _first_text(
            payload.get("benchmark_config_hash"),
            payload.get("config_hash"),
            summary.get("benchmark_config_hash") if isinstance(summary, dict) else None,
            summary.get("config_hash") if isinstance(summary, dict) else None,
        ) or None,
        "game_count": game_count,
        "games_played": game_count,
        "valid_game_rate": float(payload.get("valid_game_rate") or 0.0),
        "strength_score": strength_score,
        "avg_role_score": score,
        "target_role_role_weighted_score": score,
        "by_role_category_scores": by_role,
        "avg_speech_score": float(payload.get("avg_speech_score") or 0.0),
        "avg_vote_score": float(payload.get("avg_vote_score") or 0.0),
        "avg_skill_score": float(payload.get("avg_skill_score") or 0.0),
        "avg_logic_score": float(payload.get("avg_logic_score") or 0.0),
        "avg_team_score": float(payload.get("avg_team_score") or 0.0),
        "risk_penalty": float(payload.get("risk_penalty") or 0.0),
        "fallback_rate": float(payload.get("fallback_rate") or 0.0),
        "target_role_fallback_rate": float(payload.get("fallback_rate") or 0.0),
        "llm_error_rate": float(payload.get("llm_error_rate") or 0.0),
        "policy_adjusted_rate": float(payload.get("policy_adjusted_rate") or 0.0),
        "target_side_win_rate": float(payload.get("target_side_win_rate") or 0.0),
        "rankable": bool(payload.get("rankable")),
        "data_sufficient": bool(payload.get("data_sufficient")),
        "summary": summary,
        "model_runtime": _json_clone(summary.get("model_runtime") or {}),
        "is_baseline": bool(summary.get("is_baseline", False)) if isinstance(summary, dict) else False,
        "delta_vs_baseline": {},
        "source_run_id": source_run_id,
        "batch_id": source_run_id,
        "result_batch_id": result_batch_id,
        "report_id": report_id,
        "updated_at": payload.get("updated_at"),
    }
    row_payload.update(_leaderboard_row_statistics(row_payload))
    return row_payload


def _leaderboard_subject_key(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    for key in ("subject_id", "hash", "model_config_hash", "target_version_id", "model_id"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _first_int(*values: Any, default: int = 0) -> int:
    for value in values:
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            continue
        return number
    return default


def _first_float(*values: Any, default: float = 0.0) -> float:
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number == number:
            return number
    return default


def _filter_unrankable_evidence_for_compare(
    rows: list[dict[str, Any]],
    *,
    scope: str | None,
    evaluation_set_id: str | None,
    target_role: str | None,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if row.get("rankable") is not False:
            continue
        row_scope = str(row.get("scope") or "").strip().lower()
        if scope and row_scope and row_scope != scope:
            continue
        row_eval = str(row.get("evaluation_set_id") or "").strip()
        if evaluation_set_id and row_eval and row_eval != str(evaluation_set_id):
            continue
        row_role = str(row.get("target_role") or "").strip().lower()
        if target_role and row_role and row_role != str(target_role).strip().lower():
            continue
        evidence.append(_leaderboard_unrankable_evidence_row(row, index=index))
    return evidence


def _benchmark_result_has_unrankable_evidence(result: dict[str, Any]) -> bool:
    if result.get("rankable") is False:
        return True
    gate = result.get("leaderboard_gate") if isinstance(result.get("leaderboard_gate"), dict) else {}
    if gate.get("accepted") is False:
        return True
    return bool(result.get("leaderboard_skipped_reason"))


def _dedupe_unrankable_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        subject = str(row.get("subject_id") or row.get("model_config_hash") or row.get("target_version_id") or "")
        batch_id = str(row.get("batch_id") or "")
        result_batch_id = str(row.get("result_batch_id") or "")
        key = (
            str(row.get("scope") or ""),
            str(row.get("evaluation_set_id") or ""),
            str(row.get("target_role") or ""),
            subject,
            batch_id,
            result_batch_id,
        )
        if not any(key):
            key = (str(row.get("evidence_key") or ""),)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _leaderboard_unrankable_evidence_row(row: dict[str, Any], *, index: int) -> dict[str, Any]:
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    completed_games = _first_int(
        row.get("completed_games"),
        row.get("games_played"),
        row.get("completed"),
        summary.get("completed_games"),
        summary.get("games_played"),
        row.get("game_count"),
    )
    total_games = _first_int(
        row.get("total_games"),
        row.get("game_count"),
        summary.get("total_games"),
        summary.get("game_count"),
        completed_games,
    )
    valid_game_rate = _first_float(row.get("valid_game_rate"), summary.get("valid_game_rate"))
    return {
        "evidence_key": _leaderboard_subject_key(row) or f"unrankable:{index}",
        "scope": row.get("scope"),
        "subject_id": row.get("subject_id") or row.get("hash"),
        "model_id": row.get("model_id"),
        "model_config_hash": row.get("model_config_hash"),
        "target_role": row.get("target_role"),
        "target_version_id": row.get("target_version_id"),
        "evaluation_set_id": row.get("evaluation_set_id"),
        "seed_set_id": row.get("seed_set_id"),
        "batch_id": row.get("batch_id") or summary.get("batch_id") or row.get("comparison_group_id"),
        "result_batch_id": row.get("result_batch_id") or summary.get("result_batch_id"),
        "status": "unrankable",
        "rankable": False,
        "reason": _first_text(
            row.get("rankable_reason"),
            row.get("leaderboard_skipped_reason"),
            row.get("reason"),
            summary.get("rankable_reason"),
            summary.get("leaderboard_skipped_reason"),
            summary.get("reason"),
            "rankable gate failed",
        ),
        "completed_games": completed_games,
        "total_games": total_games,
        "valid_game_rate": valid_game_rate,
        "updated_at": row.get("updated_at"),
        "source": row.get("source") or "leaderboard",
    }


def _select_leaderboard_baseline(
    rows: list[dict[str, Any]],
    *,
    baseline_subject_id: str | None = None,
) -> dict[str, Any] | None:
    wanted = str(baseline_subject_id or "").strip()
    if wanted:
        for row in rows:
            keys = {
                _leaderboard_subject_key(row),
                str(row.get("subject_id") or "").strip(),
                str(row.get("hash") or "").strip(),
                str(row.get("model_config_hash") or "").strip(),
                str(row.get("target_version_id") or "").strip(),
                str(row.get("model_id") or "").strip(),
            }
            if wanted in keys:
                return row
    for row in rows:
        if row.get("is_baseline") is True:
            return row
    for row in rows:
        if row.get("rankable") is not False:
            return row
    return rows[0] if rows else None


def _leaderboard_metric(row: dict[str, Any] | None, *keys: str) -> float:
    if not row:
        return 0.0
    for key in keys:
        try:
            value = float(row.get(key))
        except (TypeError, ValueError):
            continue
        if value == value:
            return value
    return 0.0


_LEADERBOARD_CONFIDENCE_LEVEL = 0.95
_LEADERBOARD_Z_95 = 1.96
_LEADERBOARD_MIN_CONFIDENT_SAMPLE_SIZE = 30
_LEADERBOARD_MIN_PAIRED_OVERLAP = _LEADERBOARD_MIN_CONFIDENT_SAMPLE_SIZE


def _leaderboard_score(row: dict[str, Any] | None, *, scope: str | None) -> float:
    if scope == "model":
        return _leaderboard_metric(row, "strength_score", "avg_role_score", "target_role_role_weighted_score")
    return _leaderboard_metric(row, "avg_role_score", "target_role_role_weighted_score", "strength_score")


def _leaderboard_row_statistics(row: dict[str, Any] | None) -> dict[str, Any]:
    """Return row-level binomial confidence evidence for leaderboard payloads."""
    if not row:
        return _empty_leaderboard_statistics()
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    sample_size = _first_int(
        row.get("sample_size"),
        summary.get("sample_size"),
        row.get("completed_games"),
        row.get("completed"),
        summary.get("completed_games"),
        summary.get("win_rate_denominator"),
        row.get("games_played"),
        row.get("game_count"),
        summary.get("games_played"),
        summary.get("game_count"),
        default=0,
    )
    win_rate = _probability_from_value(
        _first_float(
            row.get("target_side_win_rate"),
            row.get("win_rate"),
            summary.get("target_side_win_rate"),
            summary.get("win_rate"),
            default=0.0,
        )
    )
    standard_error = _binomial_standard_error(win_rate, sample_size)
    ci_low, ci_high = _wilson_confidence_interval(win_rate, sample_size)
    paired_sample_size = _first_int(
        row.get("paired_sample_size"),
        summary.get("paired_sample_size"),
        summary.get("paired_valid_count"),
        default=0,
    )
    paired_delta = _optional_probability_delta(
        row.get("paired_delta"),
        summary.get("paired_delta"),
        summary.get("paired_seed_delta"),
    )
    warnings = _stat_warning_list(row.get("warnings"), summary.get("warnings"))
    if sample_size < _LEADERBOARD_MIN_CONFIDENT_SAMPLE_SIZE:
        warnings.append("low_sample")
    warnings = _dedupe_warning_codes(warnings)
    return {
        "sample_size": sample_size,
        "paired_sample_size": paired_sample_size,
        "win_rate_ci": {
            "low": ci_low,
            "high": ci_high,
            "level": _LEADERBOARD_CONFIDENCE_LEVEL,
        },
        "ci_low": ci_low,
        "ci_high": ci_high,
        "standard_error": standard_error,
        "paired_delta": paired_delta,
        "significant": bool(row.get("significant", False)),
        "significance_label": str(row.get("significance_label") or "待比较"),
        "warnings": warnings,
    }


def _empty_leaderboard_statistics() -> dict[str, Any]:
    return {
        "sample_size": 0,
        "paired_sample_size": 0,
        "win_rate_ci": {"low": 0.0, "high": 0.0, "level": _LEADERBOARD_CONFIDENCE_LEVEL},
        "ci_low": 0.0,
        "ci_high": 0.0,
        "standard_error": 0.0,
        "paired_delta": None,
        "significant": False,
        "significance_label": "待比较",
        "warnings": ["low_sample"],
    }


def _probability_from_value(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    if abs(number) > 1 and abs(number) <= 100:
        number = number / 100.0
    return max(0.0, min(1.0, number))


def _optional_probability_delta(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(number):
            continue
        if abs(number) > 1 and abs(number) <= 100:
            number = number / 100.0
        return number
    return None


def _binomial_standard_error(win_rate: float, sample_size: int) -> float:
    if sample_size <= 0:
        return 0.0
    probability = max(0.0, min(1.0, float(win_rate)))
    return math.sqrt((probability * (1.0 - probability)) / sample_size)


def _wilson_confidence_interval(win_rate: float, sample_size: int) -> tuple[float, float]:
    if sample_size <= 0:
        return 0.0, 0.0
    probability = max(0.0, min(1.0, float(win_rate)))
    z_squared = _LEADERBOARD_Z_95 ** 2
    denominator = 1.0 + (z_squared / sample_size)
    center = (probability + (z_squared / (2 * sample_size))) / denominator
    half_width = (
        _LEADERBOARD_Z_95
        * math.sqrt((probability * (1.0 - probability) / sample_size) + (z_squared / (4 * sample_size ** 2)))
        / denominator
    )
    return (
        max(0.0, min(1.0, center - half_width)),
        max(0.0, min(1.0, center + half_width)),
    )


def _stat_warning_list(*values: Any) -> list[str]:
    warnings: list[str] = []
    for value in values:
        if isinstance(value, str):
            warnings.append(value)
        elif isinstance(value, list):
            warnings.extend(str(item) for item in value)
        elif isinstance(value, dict):
            warnings.extend(str(key) for key, enabled in value.items() if enabled)
    return warnings


def _dedupe_warning_codes(values: list[str]) -> list[str]:
    allowed = {"low_sample", "unpaired_seeds", "insufficient_overlap"}
    warnings: list[str] = []
    for value in values:
        code = str(value or "").strip()
        if code in allowed and code not in warnings:
            warnings.append(code)
    return warnings


def _leaderboard_seed_metrics(row: dict[str, Any] | None) -> dict[str, float]:
    if not row:
        return {}
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    candidates = (
        row.get("seed_metrics"),
        row.get("paired_seed_metrics"),
        row.get("per_seed_metrics"),
        summary.get("seed_metrics"),
        summary.get("paired_seed_metrics"),
        summary.get("per_seed_metrics"),
        summary.get("seed_results"),
        summary.get("per_seed"),
    )
    metrics: dict[str, float] = {}
    for candidate in candidates:
        if isinstance(candidate, dict):
            iterable = [{"seed": seed, "value": value} for seed, value in candidate.items()]
        elif isinstance(candidate, list):
            iterable = candidate
        else:
            continue
        for index, item in enumerate(iterable):
            if not isinstance(item, dict):
                continue
            key = _leaderboard_seed_metric_key(item, index)
            if not key:
                continue
            value = _seed_metric_value(item)
            if value is not None:
                metrics[key] = value
    return metrics


def _leaderboard_seed_metric_key(item: dict[str, Any], index: int) -> str:
    pair_key = _first_text(item.get("pair_key"), item.get("paired_key"), item.get("pair_id"))
    if pair_key:
        return f"pair:{pair_key}"
    seed = _first_text(item.get("seed"), item.get("seed_id"), item.get("id"))
    game_index = _first_text(item.get("game_index"), item.get("game_slot"), item.get("slot_index"), item.get("ordinal"))
    if seed and game_index:
        return f"seed:{seed}:game:{game_index}"
    game_id = _first_text(item.get("source_game_id"), item.get("game_id"))
    if seed and game_id:
        return f"seed:{seed}:source:{game_id}"
    if seed:
        return f"seed:{seed}"
    if game_id:
        return f"game:{game_id}"
    return f"index:{index}"


def _seed_metric_value(item: dict[str, Any]) -> float | None:
    for key in (
        "target_side_win",
        "target_side_won",
        "win",
        "won",
        "value",
        "target_side_win_rate",
        "score",
    ):
        value = item.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        text = str(value).strip().lower()
        if text in {"win", "won", "true", "yes"}:
            return 1.0
        if text in {"loss", "lost", "false", "no"}:
            return 0.0
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return _probability_from_value(number)
    return None


def _leaderboard_paired_evidence(
    row: dict[str, Any],
    baseline: dict[str, Any] | None,
) -> tuple[float | None, int, list[str]]:
    if not baseline:
        return None, 0, []
    row_metrics = _leaderboard_seed_metrics(row)
    baseline_metrics = _leaderboard_seed_metrics(baseline)
    if not row_metrics or not baseline_metrics:
        return None, 0, ["unpaired_seeds"]
    overlap = sorted(set(row_metrics).intersection(baseline_metrics))
    if not overlap:
        return None, 0, ["insufficient_overlap"]
    deltas = [row_metrics[seed] - baseline_metrics[seed] for seed in overlap]
    paired_delta = sum(deltas) / len(deltas)
    warnings: list[str] = []
    if len(overlap) < min(len(row_metrics), len(baseline_metrics)):
        warnings.append("unpaired_seeds")
    if len(overlap) < _LEADERBOARD_MIN_PAIRED_OVERLAP:
        warnings.append("insufficient_overlap")
    return paired_delta, len(overlap), warnings


def _leaderboard_compare_statistics(
    row: dict[str, Any],
    baseline: dict[str, Any] | None,
    *,
    boundary_warnings: list[str],
    is_reference: bool,
    win_rate_delta: float,
) -> dict[str, Any]:
    row_stats = _leaderboard_row_statistics(row)
    baseline_stats = _leaderboard_row_statistics(baseline)
    warnings = list(row_stats["warnings"])
    if baseline and baseline_stats["sample_size"] < _LEADERBOARD_MIN_CONFIDENT_SAMPLE_SIZE:
        warnings.append("low_sample")
    paired_delta, paired_sample_size, paired_warnings = _leaderboard_paired_evidence(row, baseline)
    warnings.extend(paired_warnings)
    paired_delta_error = None
    if paired_sample_size > 0:
        paired_delta_error = math.sqrt(
            (float(row_stats["standard_error"] or 0.0) ** 2)
            + (float(baseline_stats["standard_error"] or 0.0) ** 2)
        )
    combined_standard_error = math.sqrt(
        float(row_stats["standard_error"] or 0.0) ** 2
        + float(baseline_stats["standard_error"] or 0.0) ** 2
    )
    warning_codes = _dedupe_warning_codes(warnings)
    statistically_significant = bool(
        baseline
        and not is_reference
        and not boundary_warnings
        and paired_delta is not None
        and "low_sample" not in warning_codes
        and "unpaired_seeds" not in warning_codes
        and "insufficient_overlap" not in warning_codes
        and paired_delta_error
        and paired_delta_error > 0
        and abs(float(paired_delta or 0.0)) > (_LEADERBOARD_Z_95 * paired_delta_error)
    )
    if is_reference:
        label = "基线参考"
    elif boundary_warnings:
        label = "不可比较"
    elif statistically_significant:
        label = "显著提升" if win_rate_delta > 0 else "显著回退"
    elif baseline:
        label = "差异不显著"
    else:
        label = "等待基线"
    return {
        **row_stats,
        "paired_sample_size": paired_sample_size,
        "paired_delta": paired_delta,
        "standard_error": row_stats["standard_error"],
        "combined_standard_error": combined_standard_error,
        "significant": statistically_significant,
        "significance_label": label,
        "warnings": warning_codes,
    }


def _leaderboard_boundary_warnings(
    row: dict[str, Any],
    baseline: dict[str, Any] | None,
    *,
    scope: str | None,
    target_role: str | None,
) -> list[str]:
    if not baseline:
        return []
    warnings: list[str] = []
    if scope and str(row.get("scope") or "").strip().lower() != scope:
        warnings.append("scope_mismatch")
    row_eval = str(row.get("evaluation_set_id") or "").strip()
    baseline_eval = str(baseline.get("evaluation_set_id") or "").strip()
    if row_eval and baseline_eval and row_eval != baseline_eval:
        warnings.append("evaluation_set_mismatch")
    row_seed = str(row.get("seed_set_id") or "").strip()
    baseline_seed = str(baseline.get("seed_set_id") or "").strip()
    if row_seed and baseline_seed and row_seed != baseline_seed:
        warnings.append("seed_set_mismatch")
    expected_role = str(target_role or baseline.get("target_role") or "").strip()
    row_role = str(row.get("target_role") or "").strip()
    if scope == "role_version" and expected_role and row_role and row_role != expected_role:
        warnings.append("target_role_mismatch")
    return warnings


def _leaderboard_compare_row(
    row: dict[str, Any],
    baseline: dict[str, Any] | None,
    *,
    scope: str | None,
    target_role: str | None,
) -> dict[str, Any]:
    row_key = _leaderboard_subject_key(row)
    baseline_key = _leaderboard_subject_key(baseline)
    score_delta = _leaderboard_score(row, scope=scope) - _leaderboard_score(baseline, scope=scope)
    win_rate_delta = _leaderboard_metric(row, "target_side_win_rate") - _leaderboard_metric(
        baseline,
        "target_side_win_rate",
    )
    fallback_delta = _leaderboard_metric(row, "fallback_rate", "target_role_fallback_rate") - _leaderboard_metric(
        baseline,
        "fallback_rate",
        "target_role_fallback_rate",
    )
    llm_error_delta = _leaderboard_metric(row, "llm_error_rate") - _leaderboard_metric(baseline, "llm_error_rate")
    policy_adjusted_delta = _leaderboard_metric(row, "policy_adjusted_rate") - _leaderboard_metric(
        baseline,
        "policy_adjusted_rate",
    )
    boundary_warnings = _leaderboard_boundary_warnings(row, baseline, scope=scope, target_role=target_role)
    is_reference = bool(baseline_key and row_key == baseline_key)
    comparable = bool(baseline and not boundary_warnings)
    if is_reference:
        change = "reference"
    elif not comparable:
        change = "incomparable"
    elif score_delta > 0:
        change = "improvement"
    elif score_delta < 0:
        change = "regression"
    else:
        change = "stable"
    games = int(_leaderboard_metric(row, "games_played", "game_count", "total_games"))
    baseline_games = int(_leaderboard_metric(baseline, "games_played", "game_count", "total_games"))
    statistics = _leaderboard_compare_statistics(
        row,
        baseline,
        boundary_warnings=boundary_warnings,
        is_reference=is_reference,
        win_rate_delta=win_rate_delta,
    )
    confidence = "low_sample" if "low_sample" in statistics["warnings"] or games < 30 or baseline_games < 30 else (
        "significant" if statistics["significant"] else "not_significant"
    )
    payload = dict(row)
    payload.update(
        {
            "is_reference": is_reference,
            "baseline_subject_id": baseline_key or None,
            "comparable": comparable,
            "boundary_warnings": boundary_warnings,
            "change": change,
            "confidence": confidence,
            **statistics,
            "delta": {
                "score": score_delta,
                "target_side_win_rate": win_rate_delta,
                "paired_delta": statistics["paired_delta"],
                "fallback_rate": fallback_delta,
                "llm_error_rate": llm_error_delta,
                "policy_adjusted_rate": policy_adjusted_delta,
            },
            "delta_vs_baseline": {
                "score": score_delta,
                "target_role_role_weighted_score": score_delta,
                "strength_score": score_delta,
                "target_side_win_rate": win_rate_delta,
                "paired_delta": statistics["paired_delta"],
                "fallback_rate": fallback_delta,
                "llm_error_rate": llm_error_delta,
                "policy_adjusted_rate": policy_adjusted_delta,
            },
        }
    )
    return payload


def _leaderboard_compare_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    changes = Counter(str(row.get("change") or "unknown") for row in rows)
    return {
        "row_count": len(rows),
        "rankable_count": sum(1 for row in rows if row.get("rankable") is not False),
        "unrankable_count": sum(1 for row in rows if row.get("rankable") is False),
        "improvement_count": changes.get("improvement", 0),
        "regression_count": changes.get("regression", 0),
        "stable_count": changes.get("stable", 0),
        "incomparable_count": changes.get("incomparable", 0),
        "reference_count": changes.get("reference", 0),
        "boundary_mismatch_count": sum(1 for row in rows if row.get("boundary_warnings")),
        "significant_count": sum(1 for row in rows if row.get("significant") is True),
        "not_significant_count": sum(
            1
            for row in rows
            if row.get("significant") is False and str(row.get("significance_label") or "") == "差异不显著"
        ),
        "low_sample_count": sum(1 for row in rows if "low_sample" in set(row.get("warnings") or [])),
        "unpaired_seed_count": sum(1 for row in rows if "unpaired_seeds" in set(row.get("warnings") or [])),
        "insufficient_overlap_count": sum(
            1 for row in rows if "insufficient_overlap" in set(row.get("warnings") or [])
        ),
        "by_change": dict(sorted(changes.items())),
    }


def _row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    keys = getattr(row, "keys", None)
    if callable(keys):
        return {key: row[key] for key in keys()}
    return {}


__all__ = [
    "BenchmarkLeaderboardService",
    "BenchmarkLeaderboardServiceContextProtocol",
]
