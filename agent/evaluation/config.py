"""Evaluation batch configuration.

Defines the config for batch evaluation runs that compare model_id or
single-role role/version_id across matched seeds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class EvaluationBatchConfig:
    """Configuration for a batch evaluation run."""

    batch_id: str = ""
    comparison_group_id: str | None = None
    comparison_type: Literal["model_id", "role_version"] = "model_id"
    mode: Literal["dev", "formal"] = "dev"
    evaluation_set_id: str = ""
    seed_set_id: str = ""
    model_id: str = ""
    model_config_hash: str = ""
    game_count: int = 20
    max_days: int = 20
    player_count: int = 12
    ruleset_version: str = "werewolf_12p_v1"
    temperature: float = 1.0
    paired_seed: bool = True
    target_role: str | None = None
    target_version_id: str | None = None
    role_version_config: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "batch_id": self.batch_id,
            "comparison_group_id": self.comparison_group_id,
            "comparison_type": self.comparison_type,
            "mode": self.mode,
            "evaluation_set_id": self.evaluation_set_id,
            "seed_set_id": self.seed_set_id,
            "model_id": self.model_id,
            "model_config_hash": self.model_config_hash,
            "game_count": self.game_count,
            "max_days": self.max_days,
            "player_count": self.player_count,
            "ruleset_version": self.ruleset_version,
            "temperature": self.temperature,
            "paired_seed": self.paired_seed,
            "target_role": self.target_role,
            "target_version_id": self.target_version_id,
            "role_version_config": self.role_version_config,
        }
