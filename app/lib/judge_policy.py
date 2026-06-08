"""Shared policy defaults for LLM-backed decision judging."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class JudgePolicy:
    profile: str
    enabled: bool
    max_decisions: int
    concurrency: int
    timeout_seconds: float


_PROFILE_DEFAULTS: dict[str, JudgePolicy] = {
    "play": JudgePolicy(profile="play", enabled=True, max_decisions=3, concurrency=1, timeout_seconds=20.0),
    "eval": JudgePolicy(profile="eval", enabled=True, max_decisions=1, concurrency=1, timeout_seconds=20.0),
    "evolve": JudgePolicy(profile="evolve", enabled=True, max_decisions=1, concurrency=1, timeout_seconds=20.0),
}

_ENABLE_KEYS: dict[str, tuple[str, ...]] = {
    "play": (
        "enable_llm_judge",
        "enable_decision_judge",
        "review_llm_judge",
        "review_decision_judge",
    ),
    "eval": (
        "enable_llm_judge",
        "enable_decision_judge",
        "eval_llm_judge",
        "eval_decision_judge",
        "review_llm_judge",
        "review_decision_judge",
    ),
    "evolve": (
        "enable_llm_judge",
        "enable_decision_judge",
        "evolve_llm_judge",
        "evolve_decision_judge",
        "training_llm_judge",
        "training_decision_judge",
    ),
}

_MAX_KEYS: dict[str, tuple[str, ...]] = {
    "play": (
        "review_judge_max_decisions",
        "judge_max_decisions",
        "decision_judge_max_decisions",
    ),
    "eval": (
        "eval_judge_max_decisions",
        "review_judge_max_decisions",
        "judge_max_decisions",
        "decision_judge_max_decisions",
    ),
    "evolve": (
        "training_judge_max_decisions",
        "evolve_judge_max_decisions",
        "judge_max_decisions",
        "decision_judge_max_decisions",
    ),
}

_CONCURRENCY_KEYS: dict[str, tuple[str, ...]] = {
    "play": (
        "review_judge_concurrency",
        "judge_concurrency",
    ),
    "eval": (
        "eval_judge_concurrency",
        "review_judge_concurrency",
        "judge_concurrency",
    ),
    "evolve": (
        "training_judge_concurrency",
        "evolve_judge_concurrency",
        "judge_concurrency",
    ),
}

_TIMEOUT_KEYS: dict[str, tuple[str, ...]] = {
    "play": (
        "review_judge_timeout_seconds",
        "judge_timeout_seconds",
    ),
    "eval": (
        "eval_judge_timeout_seconds",
        "review_judge_timeout_seconds",
        "judge_timeout_seconds",
    ),
    "evolve": (
        "training_judge_timeout_seconds",
        "evolve_judge_timeout_seconds",
        "judge_timeout_seconds",
    ),
}


def resolve_judge_policy(profile: str, config: Any = None, state: Any = None) -> JudgePolicy:
    """Resolve the judge budget for a play/eval/evolve profile.

    Explicit enable/disable flags always win. Defaults are intentionally small:
    judging should improve feedback without making the main pipeline fragile.
    """
    normalized = _normalize_profile(profile)
    default = _PROFILE_DEFAULTS[normalized]
    containers = _containers(config, state)
    return JudgePolicy(
        profile=normalized,
        enabled=_first_bool(containers, _ENABLE_KEYS[normalized], default.enabled),
        max_decisions=_first_positive_int(containers, _MAX_KEYS[normalized], default.max_decisions),
        concurrency=_first_positive_int(containers, _CONCURRENCY_KEYS[normalized], default.concurrency),
        timeout_seconds=_first_positive_float(containers, _TIMEOUT_KEYS[normalized], default.timeout_seconds),
    )


def apply_judge_policy(profile: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a config copy with profile defaults materialized.

    The function never overwrites explicitly supplied keys. It writes the
    compatibility keys consumed by existing graph nodes.
    """
    normalized = _normalize_profile(profile)
    next_config = dict(config or {})
    policy = resolve_judge_policy(normalized, next_config)

    if not any(key in next_config for key in _ENABLE_KEYS[normalized]):
        if normalized == "play":
            next_config["enable_llm_judge"] = policy.enabled
            next_config["review_decision_judge"] = policy.enabled
        elif normalized == "eval":
            next_config["enable_llm_judge"] = policy.enabled
            next_config["eval_decision_judge"] = policy.enabled
        else:
            next_config["enable_llm_judge"] = policy.enabled
            next_config["training_decision_judge"] = policy.enabled
            next_config["evolve_decision_judge"] = policy.enabled

    if not any(key in next_config for key in _MAX_KEYS[normalized]):
        if normalized == "play":
            next_config["judge_max_decisions"] = policy.max_decisions
            next_config["review_judge_max_decisions"] = policy.max_decisions
        elif normalized == "eval":
            next_config["judge_max_decisions"] = policy.max_decisions
            next_config["eval_judge_max_decisions"] = policy.max_decisions
        else:
            next_config["training_judge_max_decisions"] = policy.max_decisions
            next_config["evolve_judge_max_decisions"] = policy.max_decisions

    if not any(key in next_config for key in _CONCURRENCY_KEYS[normalized]):
        if normalized == "play":
            next_config["judge_concurrency"] = policy.concurrency
            next_config["review_judge_concurrency"] = policy.concurrency
        elif normalized == "eval":
            next_config["judge_concurrency"] = policy.concurrency
            next_config["eval_judge_concurrency"] = policy.concurrency
        else:
            next_config["training_judge_concurrency"] = policy.concurrency
            next_config["evolve_judge_concurrency"] = policy.concurrency

    if not any(key in next_config for key in _TIMEOUT_KEYS[normalized]):
        if normalized == "play":
            next_config["judge_timeout_seconds"] = policy.timeout_seconds
            next_config["review_judge_timeout_seconds"] = policy.timeout_seconds
        elif normalized == "eval":
            next_config["judge_timeout_seconds"] = policy.timeout_seconds
            next_config["eval_judge_timeout_seconds"] = policy.timeout_seconds
        else:
            next_config["training_judge_timeout_seconds"] = policy.timeout_seconds
            next_config["evolve_judge_timeout_seconds"] = policy.timeout_seconds

    return next_config


def _normalize_profile(profile: str) -> str:
    normalized = str(profile or "").strip().lower()
    if normalized not in _PROFILE_DEFAULTS:
        raise ValueError(f"unknown judge policy profile: {profile!r}")
    return normalized


def _containers(config: Any = None, state: Any = None) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for item in (state, config):
        if isinstance(item, dict):
            rows.append(item)
    return tuple(rows)


def _first_bool(containers: tuple[dict[str, Any], ...], keys: tuple[str, ...], default: bool) -> bool:
    for container in containers:
        for key in keys:
            if key in container:
                return _as_bool(container.get(key))
    return default


def _first_positive_int(containers: tuple[dict[str, Any], ...], keys: tuple[str, ...], default: int) -> int:
    for container in containers:
        for key in keys:
            if key in container:
                value = _as_positive_int(container.get(key))
                return value if value is not None else default
    return default


def _first_positive_float(containers: tuple[dict[str, Any], ...], keys: tuple[str, ...], default: float) -> float:
    for container in containers:
        for key in keys:
            if key in container:
                value = _as_positive_float(container.get(key))
                return value if value is not None else default
    return default


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on", "enabled"}


def _as_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _as_positive_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None
