"""Request schemas for the UI backend API."""

from __future__ import annotations

from typing import Any, Literal

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
    benchmark_id: str | None = None
    target_type: str = "role_version"
    roles: list[str] = Field(default_factory=list)
    battle_games: int | None = Field(default=None, ge=0, le=200)
    max_days: int | None = Field(default=None, ge=1, le=100)
    target_versions: dict[str, str] = Field(default_factory=dict)
    model_id: str | None = None
    model_config_hash: str | None = None
    budget_limit_units: int | None = Field(default=None, ge=0, le=1_000_000)

    @field_validator("roles", mode="before")
    @classmethod
    def normalize_roles(cls, value: Any) -> Any:
        return _normalize_requested_roles(value)

    @field_validator("target_type", mode="before")
    @classmethod
    def normalize_target_type(cls, value: Any) -> str:
        target_type = str(value or "role_version").strip().lower()
        if target_type not in {"role_version", "model"}:
            raise ValueError(f"unsupported benchmark target_type: {target_type}")
        return target_type

    @field_validator("target_versions", mode="before")
    @classmethod
    def normalize_target_versions(cls, value: Any) -> Any:
        if value in (None, ""):
            return {}
        if not isinstance(value, dict):
            return value
        valid_roles = set(ROLE_ORDER)
        normalized: dict[str, str] = {}
        for raw_role, raw_version in value.items():
            role = str(raw_role or "").strip().lower()
            version = str(raw_version or "").strip()
            if not role or not version:
                continue
            if role not in valid_roles:
                raise ValueError(f"unsupported role: {role}")
            normalized[role] = version
        return normalized


class BenchmarkSnapshotRequest(BaseModel):
    title: str = Field(default="", max_length=200)
    release_notes: str = Field(default="", max_length=4000)
    scope: Literal["role_version", "model"] = "role_version"
    benchmark_id: str | None = None
    benchmark_version: str | int | None = None
    evaluation_set_id: str | None = Field(default=None, max_length=240)
    seed_set_id: str | None = None
    benchmark_config_hash: str | None = None
    target_role: str | None = None
    source_filter: dict[str, Any] = Field(default_factory=dict)
    view_config: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=100, ge=1, le=500)

    @field_validator("scope", mode="before")
    @classmethod
    def normalize_scope(cls, value: Any) -> str:
        scope = str(value or "role_version").strip().lower()
        if scope not in {"role_version", "model"}:
            raise ValueError(f"unsupported benchmark snapshot scope: {scope}")
        return scope

    @field_validator("target_role", mode="before")
    @classmethod
    def normalize_target_role(cls, value: Any) -> str | None:
        role = str(value or "").strip().lower()
        if not role:
            return None
        if role not in set(ROLE_ORDER):
            raise ValueError(f"unsupported role: {role}")
        return role


class BenchmarkViewRequest(BaseModel):
    view_key: str = Field(default="", min_length=1, max_length=300)
    name: str = Field(default="Default view", max_length=200)
    scope: Literal["role_version", "model"] = "role_version"
    benchmark_id: str | None = Field(default=None, max_length=200)
    evaluation_set_id: str | None = Field(default=None, max_length=240)
    target_role: str | None = None
    view_config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("view_key", mode="before")
    @classmethod
    def normalize_view_key(cls, value: Any) -> str:
        view_key = str(value or "").strip()
        if not view_key:
            raise ValueError("view_key is required")
        return view_key

    @field_validator("scope", mode="before")
    @classmethod
    def normalize_scope(cls, value: Any) -> str:
        scope = str(value or "role_version").strip().lower()
        if scope not in {"role_version", "model"}:
            raise ValueError(f"unsupported benchmark view scope: {scope}")
        return scope

    @field_validator("target_role", mode="before")
    @classmethod
    def normalize_target_role(cls, value: Any) -> str | None:
        role = str(value or "").strip().lower()
        if not role:
            return None
        if role not in set(ROLE_ORDER):
            raise ValueError(f"unsupported role: {role}")
        return role


class TtsSpeechRequest(BaseModel):
    text: str = Field(default="", max_length=2000)
    speaker: str = Field(default="", max_length=64)
    seat: int | None = Field(default=None, ge=1, le=12)
