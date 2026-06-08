"""Request schemas for the UI backend API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from ui.backend.constants import ROLE_ORDER

DEFAULT_EVOLUTION_TRAINING_GAMES = 5
DEFAULT_EVOLUTION_BATTLE_GAMES = 4
LEGACY_EVOLUTION_TRAINING_GAMES = 20
LEGACY_EVOLUTION_BATTLE_GAMES = 10


def _normalize_requested_roles(raw: Any) -> list[str]:
    if raw in (None, ""):
        return []
    if not isinstance(raw, list):
        return raw
    valid_roles = set(ROLE_ORDER)
    roles: list[str] = []
    seen: set[str] = set()
    for item in raw:
        role = str(item or "").strip().lower()
        if not role:
            continue
        if role not in valid_roles:
            raise ValueError(f"unsupported role: {role}")
        if role in seen:
            continue
        seen.add(role)
        roles.append(role)
    return roles


class GameStartRequest(BaseModel):
    seed: int | None = None
    max_days: int = Field(default=20, ge=1, le=100)
    enable_sheriff: bool = True
    player_count: int = Field(default=12, ge=12, le=12)
    skill_dir: str | None = None
    human_player_id: int | None = None
    role_versions: dict[str, str] = Field(default_factory=dict)


class HumanActionRequest(BaseModel):
    action_type: str = ""
    target: int | None = None
    choice: str | None = None
    text: str = ""


class EvolutionStartRequest(BaseModel):
    roles: list[str] = Field(default_factory=list)
    training_games: int = Field(default=DEFAULT_EVOLUTION_TRAINING_GAMES, ge=0, le=200)
    battle_games: int = Field(default=DEFAULT_EVOLUTION_BATTLE_GAMES, ge=0, le=200)
    max_days: int = Field(default=5, ge=1, le=100)
    auto_promote: bool = True

    @field_validator("roles", mode="before")
    @classmethod
    def normalize_roles(cls, value: Any) -> Any:
        return _normalize_requested_roles(value)


def automatic_evolution_request(request: EvolutionStartRequest) -> EvolutionStartRequest:
    """The UI backend currently runs self-evolution without a manual review gate."""
    if request.auto_promote:
        return request
    updates: dict[str, Any] = {"auto_promote": True}
    if (
        request.training_games == LEGACY_EVOLUTION_TRAINING_GAMES
        and request.battle_games == LEGACY_EVOLUTION_BATTLE_GAMES
    ):
        updates["training_games"] = DEFAULT_EVOLUTION_TRAINING_GAMES
        updates["battle_games"] = DEFAULT_EVOLUTION_BATTLE_GAMES
    return request.model_copy(update=updates)


class EvolutionActionRequest(BaseModel):
    action: str = ""


class EvolutionProposalRejectRequest(BaseModel):
    reason: str = ""
    tags: list[str] = Field(default_factory=list)


class BenchmarkRequest(BaseModel):
    roles: list[str] = Field(default_factory=list)
    battle_games: int = Field(default=10, ge=0, le=200)
    max_days: int = Field(default=5, ge=1, le=100)

    @field_validator("roles", mode="before")
    @classmethod
    def normalize_roles(cls, value: Any) -> Any:
        return _normalize_requested_roles(value)


class TtsSpeechRequest(BaseModel):
    text: str = Field(default="", max_length=2000)
    speaker: str = Field(default="", max_length=64)
    seat: int | None = Field(default=None, ge=1, le=12)
