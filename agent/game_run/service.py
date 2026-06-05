"""GameRunService – the single entry point for creating game runs.

All routes (ordinary, evaluation, evolution) must create runs through this
service so that every game carries correct run_type, learning_eligible,
leaderboard_scope, and promote_eligible fields.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.common.run_policy import (
    LeaderboardScope,
    RunPolicy,
    RunType,
    policy_for_run_type,
)
from storage.runtime import GamePersistence


@dataclass
class GameRunConfig:
    """Configuration for creating a new game run."""

    run_type: RunType = RunType.ORDINARY_GAME
    mode: str = "dev"
    seed: int | None = None
    max_days: int = 20
    player_count: int = 12
    ruleset_version: str = "werewolf_12p_v1"
    model_id: str | None = None
    model_config_hash: str | None = None
    # Role version configuration: seat -> role_version_id
    role_version_config: dict[str, str] = field(default_factory=dict)
    # Evaluation/benchmark metadata
    comparison_group_id: str | None = None
    comparison_type: str | None = None
    target_role: str | None = None
    target_version_id: str | None = None
    seed_set_id: str | None = None
    evaluation_set_id: str | None = None
    paired_seed: bool = False


class GameRunService:
    """Centralized service for creating game runs.

    Enforces run policy boundaries and creates GamePersistence sessions
    with the correct policy fields.
    """

    def __init__(self, *, db_path: Path | str | None = None, paths: Any | None = None) -> None:
        self._db_path = Path(db_path) if db_path else None
        self._paths = paths

    def create_run(self, config: GameRunConfig) -> GameRunHandle:
        """Create a new game run and return a handle with run_id and persistence."""
        run_id = _generate_id()
        policy = policy_for_run_type(config.run_type)

        run_metadata = {
            "mode": config.mode,
            "model_id": config.model_id,
            "model_config_hash": config.model_config_hash,
            "ruleset_version": config.ruleset_version,
        }
        if config.comparison_group_id:
            run_metadata["comparison_group_id"] = config.comparison_group_id
        if config.comparison_type:
            run_metadata["comparison_type"] = config.comparison_type
        if config.target_role:
            run_metadata["target_role"] = config.target_role
        if config.target_version_id:
            run_metadata["target_version_id"] = config.target_version_id
        if config.seed_set_id:
            run_metadata["seed_set_id"] = config.seed_set_id
        if config.evaluation_set_id:
            run_metadata["evaluation_set_id"] = config.evaluation_set_id
        if config.paired_seed:
            run_metadata["paired_seed"] = True

        db_path = self._resolve_db_path()
        persistence = GamePersistence(
            game_id=run_id,
            db_path=db_path,
            run_policy=policy,
            run_metadata=run_metadata,
        )

        return GameRunHandle(
            run_id=run_id,
            config=config,
            policy=policy,
            persistence=persistence,
        )

    def _resolve_db_path(self) -> Path | None:
        if self._db_path is not None:
            return self._db_path
        if self._paths is not None:
            return self._paths.db_path if hasattr(self._paths, "db_path") else None
        return None


@dataclass
class GameRunHandle:
    """Handle returned by GameRunService.create_run()."""

    run_id: str
    config: GameRunConfig
    policy: RunPolicy
    persistence: GamePersistence

    @property
    def game_id(self) -> str:
        return self.run_id

    def close(self) -> None:
        self.persistence.close()


def _generate_id() -> str:
    return uuid.uuid4().hex[:16]
