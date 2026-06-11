"""Benchmark run planning, budget, and runtime payload helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.run import LANGFUSE_EVAL_CONFIG_KEYS
from ui.backend.errors import domain_error_detail
from ui.backend.schemas import BenchmarkRequest
from ui.backend.services.benchmark_payload_utils import (
    json_clone as _json_clone,
    optional_text as _optional_text,
)

_BENCHMARK_PLAYER_COUNT = 12
_BENCHMARK_DEFAULT_GAME_CONCURRENCY = 4
_BENCHMARK_DEFAULT_JUDGE_CONCURRENCY = 1
_BENCHMARK_GAME_UNIT_TOKENS = 1120
_BENCHMARK_JUDGE_DECISION_TOKENS = 810
_BENCHMARK_COST_PER_1K_TOKENS = 0.002
_BENCHMARK_CURRENCY = "USD"
_BENCHMARK_GAME_UNIT_SECONDS = 1.2
_BENCHMARK_JUDGE_DECISION_SECONDS = 1.0
_BENCHMARK_EVAL_BATCH_SETUP_SECONDS = 10.0


def _ceil_div(numerator: int, denominator: int) -> int:
    if numerator <= 0:
        return 0
    safe_denominator = max(1, int(denominator or 1))
    return (int(numerator) + safe_denominator - 1) // safe_denominator


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _rounded_cost(value: Any) -> float:
    try:
        return round(float(value or 0.0), 6)
    except (TypeError, ValueError):
        return 0.0


def _benchmark_estimated_tokens(*, game_decision_units: int, judge_decision_units: int) -> int:
    return (
        int(game_decision_units or 0) * _BENCHMARK_GAME_UNIT_TOKENS
        + int(judge_decision_units or 0) * _BENCHMARK_JUDGE_DECISION_TOKENS
    )


def _benchmark_estimated_cost(estimated_tokens: int) -> float:
    return _rounded_cost((int(estimated_tokens or 0) / 1000.0) * _BENCHMARK_COST_PER_1K_TOKENS)


def _benchmark_concurrency_policy(
    *,
    eval_batch_count: int,
    game_count: int,
    max_days: int,
    player_count: int,
    judge_enabled: bool,
    judge_decision_units: int,
    judge_concurrency: Any,
    game_concurrency: Any = None,
) -> dict[str, Any]:
    requested_game_concurrency = _positive_int(game_concurrency) or _BENCHMARK_DEFAULT_GAME_CONCURRENCY
    game_concurrency = max(1, min(requested_game_concurrency, max(1, int(game_count or 1))))
    effective_judge_concurrency = 0
    if judge_enabled:
        effective_judge_concurrency = _positive_int(judge_concurrency) or _BENCHMARK_DEFAULT_JUDGE_CONCURRENCY
    game_units_per_eval_batch = int(game_count or 0) * int(max_days or 0) * int(player_count or 0)
    game_waves_per_eval_batch = _ceil_div(game_units_per_eval_batch, game_concurrency)
    judge_waves = _ceil_div(int(judge_decision_units or 0), effective_judge_concurrency) if judge_enabled else 0
    expected_duration_seconds = round(
        int(eval_batch_count or 0) * _BENCHMARK_EVAL_BATCH_SETUP_SECONDS
        + game_waves_per_eval_batch * int(eval_batch_count or 0) * _BENCHMARK_GAME_UNIT_SECONDS
        + judge_waves * _BENCHMARK_JUDGE_DECISION_SECONDS
    )
    return {
        "policy": "bounded_sequential_eval_batches",
        "role_batch_concurrency": 1,
        "eval_batch_count": int(eval_batch_count or 0),
        "game_concurrency": game_concurrency,
        "judge_concurrency": effective_judge_concurrency,
        "judge_enabled": bool(judge_enabled),
        "game_waves_per_eval_batch": game_waves_per_eval_batch,
        "judge_waves": judge_waves,
        "expected_duration_seconds": max(0, int(expected_duration_seconds)),
        "notes": [
            "role-version benchmarks run one evaluation batch per role",
            "model benchmarks run one full-role evaluation batch",
            "games inside each evaluation batch use bounded game concurrency",
        ],
    }


def _benchmark_budget_payload(
    request: BenchmarkRequest,
    *,
    estimated_units: int,
    estimated_tokens: int,
    estimated_cost: float,
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    reasons: list[str] = []
    if request.budget_limit_units is not None and int(estimated_units) > int(request.budget_limit_units):
        reasons.append("estimated_units_exceed_limit_units")
        evidence.append(
            {
                "metric": "estimated_units",
                "estimated": int(estimated_units),
                "limit": int(request.budget_limit_units),
                "delta": int(estimated_units) - int(request.budget_limit_units),
                "unit": "llm_call_unit",
            }
        )
    if request.budget_limit_cost is not None and float(estimated_cost) > float(request.budget_limit_cost):
        reasons.append("estimated_cost_exceed_limit_cost")
        evidence.append(
            {
                "metric": "estimated_cost",
                "estimated": _rounded_cost(estimated_cost),
                "limit": _rounded_cost(request.budget_limit_cost),
                "delta": _rounded_cost(float(estimated_cost) - float(request.budget_limit_cost)),
                "unit": _BENCHMARK_CURRENCY,
            }
        )
    return {
        "limit_units": request.budget_limit_units,
        "estimated_units": int(estimated_units),
        "limit_cost": _rounded_cost(request.budget_limit_cost) if request.budget_limit_cost is not None else None,
        "estimated_cost": _rounded_cost(estimated_cost),
        "estimated_tokens": int(estimated_tokens),
        "currency": _BENCHMARK_CURRENCY,
        "stop_after_budget_units": request.stop_after_budget_units,
        "stop_after_predicted": (
            request.stop_after_budget_units is not None
            and int(estimated_units) > int(request.stop_after_budget_units)
        ),
        "exceeded": {
            "value": bool(evidence),
            "reasons": reasons,
            "evidence": evidence,
        },
    }


def _benchmark_budget_exceeded(budget: dict[str, Any]) -> bool:
    exceeded = budget.get("exceeded")
    if isinstance(exceeded, dict):
        return bool(exceeded.get("value"))
    return bool(exceeded)


def _benchmark_budget_error_detail(run_plan: dict[str, Any]) -> dict[str, Any]:
    budget = run_plan.get("budget") if isinstance(run_plan.get("budget"), dict) else {}
    exceeded = budget.get("exceeded") if isinstance(budget.get("exceeded"), dict) else {}
    return domain_error_detail(
        code="benchmark_budget_exceeded",
        message="Benchmark budget exceeded.",
        detail={
            "message": "benchmark budget exceeded",
            "estimated": {
                "units": budget.get("estimated_units"),
                "tokens": budget.get("estimated_tokens"),
                "cost": budget.get("estimated_cost"),
                "currency": budget.get("currency"),
            },
            "limit": {
                "units": budget.get("limit_units"),
                "cost": budget.get("limit_cost"),
                "currency": budget.get("currency"),
            },
            "budget": budget,
        },
        diagnostics=[
            {
                "kind": "budget_exceeded",
                "estimated_units": budget.get("estimated_units"),
                "limit_units": budget.get("limit_units"),
                "estimated_tokens": budget.get("estimated_tokens"),
                "estimated_cost": budget.get("estimated_cost"),
                "limit_cost": budget.get("limit_cost"),
                "currency": budget.get("currency"),
                "reasons": exceeded.get("reasons", []) if isinstance(exceeded, dict) else [],
                "evidence": exceeded.get("evidence", []) if isinstance(exceeded, dict) else [],
            }
        ],
    )


def _benchmark_effective_game_count(spec_game_count: int) -> int:
    return max(0, int(spec_game_count or 0))


def _benchmark_eval_batch_id(batch_id: str, role: str | None) -> str:
    return f"{batch_id}_{role}" if role else batch_id


def _apply_benchmark_langfuse_config_defaults(
    cfg: dict[str, Any],
    *,
    frozen_config: dict[str, Any],
    request: BenchmarkRequest,
) -> None:
    for key in LANGFUSE_EVAL_CONFIG_KEYS:
        value = _optional_text(frozen_config.get(key)) or _optional_text(getattr(request, key, None))
        if value is not None:
            cfg[key] = value

    evaluation_set_id = _optional_text(cfg.get("evaluation_set_id"))
    benchmark_id = _optional_text(cfg.get("benchmark_id"))
    if _optional_text(cfg.get("langfuse_dataset_name")) is None and evaluation_set_id is not None:
        cfg["langfuse_dataset_name"] = evaluation_set_id
    if _optional_text(cfg.get("langfuse_experiment_name")) is None:
        experiment_name = benchmark_id or evaluation_set_id
        if experiment_name is not None:
            cfg["langfuse_experiment_name"] = experiment_name
    if _optional_text(cfg.get("langfuse_run_name")) is None:
        run_name = _optional_text(cfg.get("batch_id"))
        if run_name is not None:
            cfg["langfuse_run_name"] = run_name


def _benchmark_spec_snapshot(batch: dict[str, Any]) -> dict[str, Any]:
    benchmark = batch.get("benchmark") if isinstance(batch.get("benchmark"), dict) else {}
    snapshot = benchmark.get("spec_snapshot") if isinstance(benchmark.get("spec_snapshot"), dict) else {}
    return dict(snapshot)


def _benchmark_seed_sequence(spec_snapshot: dict[str, Any], game_count: int) -> list[int]:
    seeds = spec_snapshot.get("seeds")
    if not isinstance(seeds, list):
        return []
    normalized: list[int] = []
    for item in seeds[:game_count]:
        try:
            normalized.append(int(item))
        except (TypeError, ValueError):
            continue
    return normalized if len(normalized) >= game_count else []


def _apply_benchmark_gates(cfg: dict[str, Any], gates: dict[str, Any]) -> None:
    if not gates:
        return
    if gates.get("min_completed_games") is not None:
        cfg["data_sufficient_min_games"] = gates["min_completed_games"]
        cfg["leaderboard_min_games"] = gates["min_completed_games"]
    if gates.get("min_valid_game_rate") is not None:
        cfg["data_sufficient_min_valid_game_rate"] = gates["min_valid_game_rate"]
        cfg["leaderboard_min_valid_game_rate"] = gates["min_valid_game_rate"]
    if gates.get("max_llm_error_rate") is not None:
        cfg["max_llm_error_rate"] = gates["max_llm_error_rate"]
        cfg["leaderboard_llm_error_rate_ceiling"] = gates["max_llm_error_rate"]
    if gates.get("max_fallback_rate") is not None:
        cfg["max_fallback_rate"] = gates["max_fallback_rate"]
        cfg["leaderboard_fallback_rate_ceiling"] = gates["max_fallback_rate"]
    if gates.get("max_policy_adjusted_rate") is not None:
        cfg["max_policy_adjusted_rate"] = gates["max_policy_adjusted_rate"]
        cfg["leaderboard_policy_adjusted_rate_ceiling"] = gates["max_policy_adjusted_rate"]


def _apply_benchmark_judge(cfg: dict[str, Any], judge: dict[str, Any]) -> None:
    if not judge:
        return
    if judge.get("enable_decision_judge") is not None:
        cfg["eval_decision_judge"] = bool(judge.get("enable_decision_judge"))
    if judge.get("judge_max_decisions") is not None:
        cfg["eval_judge_max_decisions"] = judge["judge_max_decisions"]
    if judge.get("judge_concurrency") is not None:
        cfg["eval_judge_concurrency"] = judge["judge_concurrency"]
    if judge.get("judge_timeout_seconds") is not None:
        cfg["eval_judge_timeout_seconds"] = judge["judge_timeout_seconds"]


def _model_identifier(model: Any) -> str | None:
    for attr in ("model_name", "model", "model_id", "deployment_name", "azure_deployment", "name"):
        value = getattr(model, attr, None)
        if value:
            return str(value)
    return None


def _runtime_public_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        values: list[Any] = []
        for item in value:
            public_item = _runtime_public_value(item)
            if public_item is not None:
                values.append(public_item)
        return values
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key or "").strip()
            if not key_text or any(secret in key_text.lower() for secret in ("key", "secret", "token", "password")):
                continue
            public_item = _runtime_public_value(item)
            if public_item is not None:
                sanitized[key_text] = public_item
        return sanitized
    return str(value)


def _injected_model_runtime_hash_input(model: Any, *, model_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": "injected_model",
        "model_id": model_id,
        "class": f"{model.__class__.__module__}.{model.__class__.__qualname__}",
    }
    for attr in (
        "temperature",
        "top_p",
        "max_tokens",
        "timeout",
        "request_timeout",
        "max_retries",
        "model_kwargs",
    ):
        value = getattr(model, attr, None)
        public_value = _runtime_public_value(value)
        if public_value not in (None, "", {}, []):
            payload[attr] = public_value
    return payload


def _benchmark_model_runtime_payload(
    *,
    source: str,
    model_id: str,
    model_config_hash: str,
    hash_input: dict[str, Any] | None,
    hash_provided: bool,
) -> dict[str, Any]:
    runtime = {
        "schema_version": 1,
        "source": source,
        "hash_source": source,
        "hash_algorithm": "sha256",
        "hash_input_schema_version": 1,
        "model_id": model_id,
        "model_config_hash": model_config_hash,
        "hash_provided": bool(hash_provided),
        "externally_provided": bool(hash_provided),
        "hash_input": _json_clone(hash_input or {}),
    }
    return {
        "model_id": model_id,
        "model_config_hash": model_config_hash,
        "model_runtime": runtime,
    }


def _stable_runtime_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"
