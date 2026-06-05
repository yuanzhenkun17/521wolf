"""Fairness validation for evaluation batches.

Ensures that comparison groups have controlled variables so that
leaderboard attribution is valid.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class FairnessResult:
    """Result of a fairness validation check."""

    is_fair: bool
    reason: str = ""
    violations: list[str] = None

    def __post_init__(self) -> None:
        if self.violations is None:
            self.violations = []


def validate_model_comparison(
    batches: list[dict[str, Any]],
) -> FairnessResult:
    """Validate that a group of batches can be fairly compared for model_id.

    Requirements (all must share):
    - evaluation_set_id
    - seed_set_id
    - game_count
    - max_days
    - player_count
    - ruleset_version
    - role_version_config
    Only model_id / model_config_hash should differ.
    """
    if len(batches) < 2:
        return FairnessResult(is_fair=False, reason="Need at least 2 batches to compare")

    violations: list[str] = []
    ref = batches[0]

    _check_field(batches, "evaluation_set_id", violations)
    _check_field(batches, "seed_set_id", violations)
    _check_field(batches, "game_count", violations)
    _check_field(batches, "max_days", violations)
    _check_field(batches, "player_count", violations)
    _check_field(batches, "ruleset_version", violations)
    _check_field(batches, "role_version_config", violations)

    # model_id must differ
    model_ids = {b.get("model_id") for b in batches}
    if len(model_ids) < 2:
        violations.append("model_id must differ between batches")

    is_fair = len(violations) == 0
    return FairnessResult(
        is_fair=is_fair,
        reason="" if is_fair else "; ".join(violations),
        violations=violations,
    )


def validate_role_version_comparison(
    batches: list[dict[str, Any]],
    target_role: str,
) -> FairnessResult:
    """Validate that a group of batches can be fairly compared for role version.

    Requirements (all must share):
    - model_id
    - model_config_hash
    - evaluation_set_id
    - seed_set_id
    - game_count
    - max_days
    - player_count
    - ruleset_version
    - other_role_version_config (all roles except target_role must match)
    Only target_role's version_id should differ.
    """
    if len(batches) < 2:
        return FairnessResult(is_fair=False, reason="Need at least 2 batches to compare")

    violations: list[str] = []

    _check_field(batches, "model_id", violations)
    _check_field(batches, "model_config_hash", violations)
    _check_field(batches, "evaluation_set_id", violations)
    _check_field(batches, "seed_set_id", violations)
    _check_field(batches, "game_count", violations)
    _check_field(batches, "max_days", violations)
    _check_field(batches, "player_count", violations)
    _check_field(batches, "ruleset_version", violations)

    # Other role versions must match
    for b in batches:
        rvc = b.get("role_version_config", {})
        other_versions = {k: v for k, v in rvc.items() if k != target_role}
        ref_rvc = batches[0].get("role_version_config", {})
        ref_other = {k: v for k, v in ref_rvc.items() if k != target_role}
        if other_versions != ref_other:
            violations.append(f"Other role versions must match (batch {b.get('batch_id', '?')})")
            break

    # Target role version must differ
    target_versions = set()
    for b in batches:
        rvc = b.get("role_version_config", {})
        target_versions.add(rvc.get(target_role))
    if len(target_versions) < 2:
        violations.append(f"Target role ({target_role}) version must differ between batches")

    is_fair = len(violations) == 0
    return FairnessResult(
        is_fair=is_fair,
        reason="" if is_fair else "; ".join(violations),
        violations=violations,
    )


def _check_field(
    batches: list[dict[str, Any]],
    field_name: str,
    violations: list[str],
) -> None:
    """Check that all batches share the same value for a field."""
    import json
    def _hashable(val):
        if isinstance(val, dict):
            return json.dumps(val, sort_keys=True)
        if isinstance(val, list):
            return tuple(val)
        return val
    values = {_hashable(b.get(field_name)) for b in batches}
    if len(values) > 1:
        violations.append(f"{field_name} must be identical across all batches")


def compute_rankable(
    *,
    mode: str,
    paired_seed: bool,
    game_count: int,
    valid_game_rate: float,
    is_fair: bool,
    min_games: int = 20,
    min_valid_rate: float = 0.8,
) -> tuple[bool, str]:
    """Compute whether a batch is rankable.

    Returns (rankable, reason).
    """
    if mode != "formal":
        return False, "mode must be formal"
    if not paired_seed:
        return False, "paired_seed required"
    if game_count < min_games:
        return False, f"game_count {game_count} < {min_games}"
    if valid_game_rate < min_valid_rate:
        return False, f"valid_game_rate {valid_game_rate:.2f} < {min_valid_rate}"
    if not is_fair:
        return False, "fairness check failed"
    return True, "rankable"
