"""Run type and policy definitions for route-specific persistence gates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class RunType(str, Enum):
    ORDINARY_GAME = "ordinary_game"
    EVALUATION_BATCH = "evaluation_batch"
    EVOLUTION_TRAINING = "evolution_training"
    EVOLUTION_AB_BASELINE = "evolution_ab_baseline"
    EVOLUTION_AB_CANDIDATE = "evolution_ab_candidate"


class LeaderboardScope(str, Enum):
    DEMO = "demo"
    BENCHMARK = "benchmark"
    EVOLUTION_TRAINING = "evolution_training"
    EVOLUTION_AB = "evolution_ab"
    NONE = "none"


@dataclass(frozen=True)
class RunPolicy:
    """Immutable policy derived from RunType."""

    run_type: RunType
    learning_eligible: bool
    leaderboard_scope: LeaderboardScope
    promote_eligible: bool


_POLICY_TABLE: dict[RunType, RunPolicy] = {
    RunType.ORDINARY_GAME: RunPolicy(
        run_type=RunType.ORDINARY_GAME,
        learning_eligible=False,
        leaderboard_scope=LeaderboardScope.DEMO,
        promote_eligible=False,
    ),
    RunType.EVALUATION_BATCH: RunPolicy(
        run_type=RunType.EVALUATION_BATCH,
        learning_eligible=False,
        leaderboard_scope=LeaderboardScope.BENCHMARK,
        promote_eligible=False,
    ),
    RunType.EVOLUTION_TRAINING: RunPolicy(
        run_type=RunType.EVOLUTION_TRAINING,
        learning_eligible=True,
        leaderboard_scope=LeaderboardScope.EVOLUTION_TRAINING,
        promote_eligible=False,
    ),
    RunType.EVOLUTION_AB_BASELINE: RunPolicy(
        run_type=RunType.EVOLUTION_AB_BASELINE,
        learning_eligible=False,
        leaderboard_scope=LeaderboardScope.EVOLUTION_AB,
        promote_eligible=False,
    ),
    RunType.EVOLUTION_AB_CANDIDATE: RunPolicy(
        run_type=RunType.EVOLUTION_AB_CANDIDATE,
        learning_eligible=False,
        leaderboard_scope=LeaderboardScope.EVOLUTION_AB,
        promote_eligible=True,
    ),
}


def policy_for_run_type(run_type: RunType) -> RunPolicy:
    return _POLICY_TABLE[run_type]


def run_policy_to_config(policy: RunPolicy, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Serialize policy + optional metadata into a game config dict."""
    cfg: dict[str, Any] = {
        "run_type": policy.run_type.value,
        "learning_eligible": policy.learning_eligible,
        "leaderboard_scope": policy.leaderboard_scope.value,
        "promote_eligible": policy.promote_eligible,
    }
    if extra:
        cfg.update(extra)
    return cfg


def run_policy_from_config(config: dict[str, Any]) -> RunPolicy:
    """Reconstruct RunPolicy from a game config dict."""
    raw = config.get("run_type", RunType.ORDINARY_GAME.value)
    run_type = RunType(raw) if isinstance(raw, str) else raw
    return policy_for_run_type(run_type)


def assert_learning_allowed(policy: RunPolicy) -> None:
    if not policy.learning_eligible:
        raise PermissionError(
            f"Learning writes not allowed for run_type={policy.run_type.value}"
        )


def assert_benchmark_allowed(policy: RunPolicy) -> None:
    if policy.leaderboard_scope not in {LeaderboardScope.BENCHMARK, LeaderboardScope.EVOLUTION_AB}:
        raise PermissionError(
            f"Benchmark writes not allowed for leaderboard_scope={policy.leaderboard_scope.value}"
        )


__all__ = [
    "LeaderboardScope",
    "RunPolicy",
    "RunType",
    "assert_benchmark_allowed",
    "assert_learning_allowed",
    "policy_for_run_type",
    "run_policy_from_config",
    "run_policy_to_config",
]
