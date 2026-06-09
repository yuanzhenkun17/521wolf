"""Score computation — evaluation metrics, stats, fairness, leaderboard."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from app.util.time import beijing_now_iso

_log = logging.getLogger(__name__)


class PersistenceWarning(str):
    """Backward-compatible warning string carrying structured diagnostics."""

    diagnostic: dict[str, Any]

    def __new__(cls, operation: str, exc: Exception) -> "PersistenceWarning":
        message = f"{operation} failed: {type(exc).__name__}: {exc}"
        value = str.__new__(cls, message)
        value.diagnostic = _persistence_diagnostic(operation, exc, message)
        return value


def _persistence_diagnostic(operation: str, exc: Exception, message: str) -> dict[str, Any]:
    return {
        "kind": "persistence_error",
        "stage": f"persist_batch.{operation}",
        "level": "warning",
        "message": message,
        "exception_type": type(exc).__name__,
        "exception_message": str(exc),
    }


def _persistence_warning(operation: str, exc: Exception) -> PersistenceWarning:
    return PersistenceWarning(operation, exc)


@dataclass(slots=True)
class PlayerScore:
    """Per-player per-game score."""
    player_id: int
    role: str
    speech_score: float = 0.0
    vote_score: float = 0.0
    skill_score: float = 0.0
    logic_score: float = 0.0
    team_score: float = 0.0
    risk_penalty: float = 0.0
    role_score: float = 0.0

    @property
    def skill_applicable(self) -> bool:
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "role": self.role,
            "speech_score": round(self.speech_score, 4),
            "vote_score": round(self.vote_score, 4),
            "skill_score": round(self.skill_score, 4),
            "logic_score": round(self.logic_score, 4),
            "team_score": round(self.team_score, 4),
            "risk_penalty": round(self.risk_penalty, 4),
            "role_score": round(self.role_score, 4),
        }


@dataclass(slots=True)
class BatchScoreSummary:
    """Aggregated scores across an evaluation batch."""
    batch_id: str = ""
    game_count: int = 0
    avg_role_score: float = 0.0
    by_role_category: dict[str, float] = field(default_factory=dict)
    avg_speech_score: float = 0.0
    avg_vote_score: float = 0.0
    avg_skill_score: float = 0.0
    avg_logic_score: float = 0.0
    avg_team_score: float = 0.0
    avg_risk_penalty: float = 0.0
    strength_score: float = 0.0


@dataclass(slots=True)
class FairnessResult:
    """Result of fairness validation for an evaluation comparison group."""
    is_fair: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"is_fair": self.is_fair, "reason": self.reason}


# ---------------------------------------------------------------------------
# Score aggregation
# ---------------------------------------------------------------------------

def aggregate_batch_scores(
    scores: list[PlayerScore],
    *,
    batch_id: str = "",
    game_count: int | None = None,
) -> BatchScoreSummary:
    """Aggregate a list of PlayerScore into a BatchScoreSummary."""
    resolved_game_count = int(game_count or 0)
    if not scores:
        return BatchScoreSummary(batch_id=batch_id, game_count=resolved_game_count)

    summary = BatchScoreSummary(batch_id=batch_id, game_count=resolved_game_count)
    n = len(scores)
    summary.avg_speech_score = sum(s.speech_score for s in scores) / n
    summary.avg_vote_score = sum(s.vote_score for s in scores) / n
    summary.avg_skill_score = sum(s.skill_score for s in scores) / n
    summary.avg_logic_score = sum(s.logic_score for s in scores) / n
    summary.avg_team_score = sum(s.team_score for s in scores) / n
    summary.avg_risk_penalty = sum(s.risk_penalty for s in scores) / n
    summary.avg_role_score = sum(s.role_score for s in scores) / n

    by_role: dict[str, list[float]] = {}
    for s in scores:
        by_role.setdefault(s.role, []).append(s.role_score)
    summary.by_role_category = {role: sum(vals)/len(vals) for role, vals in by_role.items()}

    summary.strength_score = summary.avg_role_score
    return summary


def compute_decision_quality_metrics(games: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute batch-level decision quality counters and rates from game records."""
    decision_count = 0
    fallback_count = 0
    llm_error_count = 0
    policy_adjusted_count = 0
    policy_skipped_count = 0
    event_count = 0
    invalid_response_count = 0
    default_action_count = 0

    for game in games:
        if not isinstance(game, dict):
            continue
        for decision in _iter_mapping_items(game.get("decisions")):
            decision_count += 1
            source = str(_item_value(decision, "source") or "").strip().lower()
            if source == "fallback":
                fallback_count += 1
            elif source == "llm_error":
                llm_error_count += 1
            elif source == "policy_skipped":
                policy_skipped_count += 1
            if source == "policy_adjusted" or _has_policy_adjustments(
                _item_value(decision, "policy_adjustments")
            ):
                policy_adjusted_count += 1

        for event in _iter_mapping_items(game.get("events")):
            event_count += 1
            event_type = str(_item_value(event, "event_type", "type") or "").strip()
            if event_type == "invalid_response":
                invalid_response_count += 1
            elif event_type == "default_action":
                default_action_count += 1

    return {
        "decision_count": decision_count,
        "fallback_count": fallback_count,
        "llm_error_count": llm_error_count,
        "policy_adjusted_count": policy_adjusted_count,
        "policy_skipped_count": policy_skipped_count,
        "fallback_rate": _safe_rate(fallback_count, decision_count),
        "llm_error_rate": _safe_rate(llm_error_count, decision_count),
        "policy_adjusted_rate": _safe_rate(policy_adjusted_count, decision_count),
        "policy_skipped_rate": _safe_rate(policy_skipped_count, decision_count),
        "event_count": event_count,
        "invalid_response_count": invalid_response_count,
        "default_action_count": default_action_count,
        "invalid_response_rate": _safe_rate(invalid_response_count, event_count),
        "default_action_rate": _safe_rate(default_action_count, event_count),
    }


def _iter_mapping_items(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [item for item in value if item is not None]


def _item_value(item: Any, *keys: str) -> Any:
    for key in keys:
        if isinstance(item, dict) and key in item:
            return item.get(key)
        if hasattr(item, key):
            return getattr(item, key)
    return None


def _has_policy_adjustments(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return False
        try:
            decoded = json.loads(text)
        except json.JSONDecodeError:
            return True
        return bool(decoded)
    if isinstance(value, (list, tuple, set, dict)):
        return bool(value)
    return bool(value)


def _safe_rate(count: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(count / denominator, 6)


# ---------------------------------------------------------------------------
# Role score computation
# ---------------------------------------------------------------------------

def compute_role_score(
    *,
    speech_score: float = 0.0,
    vote_score: float = 0.0,
    skill_score: float = 0.0,
    logic_score: float = 0.0,
    team_score: float = 0.0,
    risk_penalty: float = 0.0,
    skill_applicable: bool = True,
) -> float:
    """Compute a single role-weighted score.

    Generic weights; specific role weights are handled by the evaluator.
    """
    base = (
        speech_score * 0.20
        + vote_score * 0.25
        + skill_score * 0.25
        + logic_score * 0.15
        + team_score * 0.15
    )
    if not skill_applicable:
        base = (
            speech_score * 0.30
            + vote_score * 0.30
            + logic_score * 0.25
            + team_score * 0.15
        )
    return max(0.0, min(10.0, base - risk_penalty))


# ---------------------------------------------------------------------------
# Fairness validation
# ---------------------------------------------------------------------------

def validate_role_version_comparison(batches: list[dict[str, Any]], target_role: str) -> FairnessResult:
    """Validate that role-version comparison batches are fair."""
    if len(batches) < 2:
        return FairnessResult(False, f"Need at least 2 batches with role={target_role} for comparison")
    model_seeds = set()
    for b in batches:
        if b.get("target_role") != target_role:
            return FairnessResult(False, f"Batch {b.get('batch_id')} target_role mismatch: {b.get('target_role')} != {target_role}")
        model_seeds.add((b.get("model_id"), b.get("seed_set_id")))
    if len(model_seeds) < 2:
        return FairnessResult(False, "All batches share the same (model, seed_set); no comparison baseline")
    return FairnessResult(True, f"Fair comparison of {len(batches)} batches for role={target_role}")


def validate_model_comparison(batches: list[dict[str, Any]]) -> FairnessResult:
    """Validate that model comparison batches are fair."""
    if len(batches) < 2:
        return FairnessResult(False, "Need at least 2 batches for model comparison")
    seed_sets = {b.get("seed_set_id") for b in batches}
    if len(seed_sets) > 1:
        return FairnessResult(False, "Model comparison batches must share the same seed_set_id")
    model_subjects = {
        b.get("model_config_hash") or b.get("model_id")
        for b in batches
        if b.get("model_config_hash") or b.get("model_id")
    }
    if len(model_subjects) < 2:
        return FairnessResult(False, "Need at least 2 model subjects for comparison")
    return FairnessResult(True, f"Fair comparison of {len(batches)} model batches on seed_set={next(iter(seed_sets), None)}")


# ---------------------------------------------------------------------------
# Rankable computation
# ---------------------------------------------------------------------------

def compute_rankable(
    *,
    mode: str = "dev",
    paired_seed: bool = False,
    game_count: int = 0,
    valid_game_rate: float = 0.0,
    is_fair: bool = False,
) -> tuple[bool, str]:
    """Determine if an evaluation batch result is rankable."""
    if game_count < 1:
        return False, "No games in batch"
    if not is_fair:
        return False, "Fairness check failed"
    if mode == "dev" and paired_seed and valid_game_rate < 0.5:
        return False, f"valid_game_rate {valid_game_rate:.1%} < 50% for dev/paired"
    if mode == "prod" and valid_game_rate < 0.8:
        return False, f"valid_game_rate {valid_game_rate:.1%} < 80% for prod"
    return True, "ok"


# ---------------------------------------------------------------------------
# Leaderboard entry computation
# ---------------------------------------------------------------------------

def compute_role_version_leaderboard_entry(
    *,
    batch_id: str,
    target_role: str,
    target_version_id: str,
    model_id: str | None = None,
    evaluation_set_id: str | None = None,
    seed_set_id: str | None = None,
    score_summary: BatchScoreSummary | None = None,
    rankable: bool = False,
    game_count: int = 0,
) -> dict[str, Any]:
    """Compute a leaderboard entry for a role_version evaluation."""
    avg = score_summary.by_role_category.get(target_role, 0.0) if score_summary else 0.0
    return {
        "batch_id": batch_id,
        "hash": target_version_id,
        "target_role": target_role,
        "target_version_id": target_version_id,
        "model_id": model_id,
        "evaluation_set_id": evaluation_set_id,
        "seed_set_id": seed_set_id,
        "target_role_role_weighted_score": round(avg, 6),
        "target_role_fallback_rate": 0.0,
        "target_side_win_rate": 0.0,
        "delta_vs_baseline": {},
        "is_baseline": False,
        "rankable": rankable,
        "game_count": game_count,
    }


def compute_model_leaderboard_entry(
    *,
    batch_id: str,
    model_id: str | None = None,
    model_config_hash: str | None = None,
    evaluation_set_id: str | None = None,
    seed_set_id: str | None = None,
    score_summary: BatchScoreSummary | None = None,
    rankable: bool = False,
    game_count: int = 0,
) -> dict[str, Any]:
    """Compute a leaderboard entry for a model evaluation."""
    return {
        "batch_id": batch_id,
        "hash": model_config_hash or model_id or "",
        "model_id": model_id,
        "model_config_hash": model_config_hash,
        "evaluation_set_id": evaluation_set_id,
        "seed_set_id": seed_set_id,
        "rankable": rankable,
        "game_count": game_count,
        "avg_role_score": round(score_summary.avg_role_score, 6) if score_summary else 0.0,
        "is_baseline": False,
    }


def persist_leaderboard_entry(conn: Any, entry: dict[str, Any]) -> str | None:
    """Persist a leaderboard entry to the benchmark_leaderboard table.

    Idempotent per (scope, subject_id, comparison_group_id) — re-running a
    batch overwrites its row rather than accumulating duplicates. Returns a
    warning string when the best-effort write fails.
    """
    import uuid

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
    # Stable id so re-runs replace rather than duplicate.
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
    try:
        conn.execute(
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
        conn.commit()
        return None
    except Exception as exc:  # noqa: BLE001 — leaderboard write is best-effort
        _log.warning("persist_leaderboard_entry failed", exc_info=True)
        return _persistence_warning("persist_leaderboard_entry", exc)


# ---------------------------------------------------------------------------
# Evaluation batch persistence + comparison-group fairness
# ---------------------------------------------------------------------------

def open_eval_connection(paths: Any = None) -> Any:
    """Open the wolf-domain storage connection used by evaluation persistence."""
    from storage.provider import storage_provider_from_env

    return storage_provider_from_env(paths=paths).open_wolf_connection()


def save_evaluation_batch(conn: Any, batch: dict[str, Any]) -> str | None:
    """Persist an evaluation batch row to evaluation_batches (idempotent by id).

    Returns a warning string when the best-effort write fails.
    """
    summary = batch.get("score_summary")
    created_at = str(batch.get("created_at") or beijing_now_iso())
    started_at = _nullable_timestamp(batch.get("started_at"))
    finished_at = _nullable_timestamp(batch.get("finished_at"))
    try:
        conn.execute(
            """INSERT INTO evaluation_batches
            (id, comparison_group_id, comparison_type, mode, model_id, model_config_hash,
             target_role, target_version_id, role_version_config, game_count,
             evaluation_set_id, seed_set_id, max_days, rankable, rankable_reason,
             summary, started_at, finished_at, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                comparison_group_id = excluded.comparison_group_id,
                comparison_type = excluded.comparison_type,
                mode = excluded.mode,
                model_id = excluded.model_id,
                model_config_hash = excluded.model_config_hash,
                target_role = excluded.target_role,
                target_version_id = excluded.target_version_id,
                role_version_config = excluded.role_version_config,
                game_count = excluded.game_count,
                evaluation_set_id = excluded.evaluation_set_id,
                seed_set_id = excluded.seed_set_id,
                max_days = excluded.max_days,
                rankable = excluded.rankable,
                rankable_reason = excluded.rankable_reason,
                summary = excluded.summary,
                started_at = excluded.started_at,
                finished_at = excluded.finished_at,
                created_at = excluded.created_at""",
            (
                str(batch.get("batch_id", "")),
                batch.get("comparison_group_id"),
                batch.get("comparison_type"),
                str(batch.get("mode", "dev")),
                batch.get("model_id"),
                batch.get("model_config_hash"),
                batch.get("target_role"),
                batch.get("target_version_id"),
                json.dumps(batch.get("role_version_config"), ensure_ascii=False)
                if batch.get("role_version_config") is not None else None,
                int(batch.get("game_count", 0) or 0),
                batch.get("evaluation_set_id"),
                batch.get("seed_set_id"),
                int(batch.get("max_days", 20) or 20),
                1 if batch.get("rankable") else 0,
                batch.get("rankable_reason", ""),
                json.dumps(summary, ensure_ascii=False) if summary is not None else None,
                started_at,
                finished_at,
                created_at,
            ),
        )
        conn.commit()
        return None
    except Exception as exc:  # noqa: BLE001 — persistence is best-effort
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 — keep original persistence warning
            pass
        _log.warning("save_evaluation_batch failed", exc_info=True)
        return _persistence_warning("save_evaluation_batch", exc)


def _nullable_timestamp(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def load_comparison_group(conn: Any, comparison_group_id: str, *, exclude_batch_id: str = "") -> list[dict[str, Any]]:
    """Load sibling batches in a comparison group (excluding the current batch).

    Read failures are raised so callers can distinguish storage problems from
    a genuinely empty comparison group.
    """
    if not comparison_group_id:
        return []
    try:
        rows = conn.execute(
            "SELECT id, comparison_group_id, comparison_type, mode, model_id, "
            "model_config_hash, target_role, target_version_id, seed_set_id, game_count "
            "FROM evaluation_batches WHERE comparison_group_id = ? AND id != ?",
            (comparison_group_id, exclude_batch_id),
        ).fetchall()
    except Exception:  # noqa: BLE001 — keep the original error for caller diagnostics
        _log.warning("load_comparison_group failed", exc_info=True)
        raise
    result: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        d["batch_id"] = d.get("id")
        result.append(d)
    return result


def compute_group_fairness(
    conn: Any,
    *,
    comparison_group_id: str | None,
    comparison_type: str | None,
    target_role: str | None,
    batch_id: str,
    current_batch: dict[str, Any] | None = None,
) -> FairnessResult:
    """Validate fairness of a comparison group by loading its sibling batches.

    Standalone batches (no comparison_group_id) are trivially fair. For grouped
    batches, the current batch is included alongside its siblings before
    delegating to the role_version / model validators.
    """
    if not comparison_group_id:
        return FairnessResult(True, "standalone batch")
    batches = load_comparison_group(conn, comparison_group_id, exclude_batch_id=batch_id)
    if current_batch is not None:
        batches = [*batches, {**current_batch, "batch_id": batch_id}]
    if len(batches) < 2 and comparison_type == "model" and current_batch is not None:
        seed_set_id = current_batch.get("seed_set_id")
        evaluation_set_id = current_batch.get("evaluation_set_id")
        if seed_set_id and evaluation_set_id:
            return FairnessResult(True, "model benchmark fixed evaluation_set/seed_set")
    if len(batches) < 2:
        return FairnessResult(False, "comparison group needs at least 2 batches")
    if comparison_type == "role_version":
        if not target_role:
            return FairnessResult(False, "role_version comparison requires target_role")
        return validate_role_version_comparison(batches, target_role)
    return validate_model_comparison(batches)
