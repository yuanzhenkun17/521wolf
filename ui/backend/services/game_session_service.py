"""Live game session helpers for role selection and human actions."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException

from app.lib.version import ReleaseStageNotAllowedError
from app.util.time import beijing_now_iso
from ui.backend.errors import domain_error_detail, release_stage_not_allowed_detail
from ui.backend.live_game import LIVE_GAME_HEARTBEAT_TIMEOUT_SECONDS
from ui.backend.schemas import GameStartRequest, HumanActionRequest
from ui.backend.serializers import _fallback_version


class GameSessionService:
    """Owns live-session request adaptation that does not belong in the store mixin."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def live_game_heartbeat_timeout_seconds(self) -> float:
        value = getattr(self._store, "live_game_heartbeat_timeout_seconds", LIVE_GAME_HEARTBEAT_TIMEOUT_SECONDS)
        try:
            return max(1.0, float(value))
        except (TypeError, ValueError):
            return LIVE_GAME_HEARTBEAT_TIMEOUT_SECONDS

    def skill_dir_for_request(self, request: GameStartRequest) -> str | None:
        if not request.role_versions:
            return request.skill_dir
        from app.lib.version import SkillVersionConfig, build_composite_skill_dir

        try:
            role_versions = self.effective_role_versions(request.role_versions)
            if not role_versions:
                return request.skill_dir
            skill_dir = build_composite_skill_dir(
                self._store.registry,
                SkillVersionConfig(
                    name=f"ui_{uuid.uuid4().hex[:8]}",
                    created_at=beijing_now_iso(),
                    role_versions=role_versions,
                ),
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"role version not found: {exc}") from exc
        except ReleaseStageNotAllowedError as exc:
            raise HTTPException(
                status_code=409,
                detail=domain_error_detail(
                    code="role_version_release_stage_not_allowed",
                    message="Role version is not allowed for normal games.",
                    detail=f"role version not allowed: {exc}",
                    diagnostics=[exc.diagnostic(kind="role_version_release_stage_not_allowed")],
                ),
            ) from exc
        except (RuntimeError, ValueError) as exc:
            release_stage_detail = release_stage_not_allowed_detail(
                exc,
                code="role_version_release_stage_not_allowed",
                message="Role version is not allowed for normal games.",
                detail_prefix="role version not allowed",
                kind="role_version_release_stage_not_allowed",
            )
            if release_stage_detail is not None:
                raise HTTPException(status_code=409, detail=release_stage_detail) from exc
            raise HTTPException(status_code=409, detail=f"role version not allowed: {exc}") from exc
        return str(skill_dir) if skill_dir is not None else request.skill_dir

    def effective_role_versions(self, role_versions: dict[str, str]) -> dict[str, str]:
        from app.lib.version import ensure_version_allowed_for_default_use

        effective: dict[str, str] = {}
        registry = self._store.registry
        for role, version_id in role_versions.items():
            if not role or not version_id:
                continue
            if version_id == _fallback_version(role)["version_id"]:
                try:
                    registry.read_skill_contents(role, version_id)
                except FileNotFoundError:
                    continue
            ensure_version_allowed_for_default_use(registry, str(role), str(version_id))
            effective[str(role)] = str(version_id)
        return effective

    def get_human_action(self, game_id: str) -> dict[str, Any] | None:
        self._store.check_live_game_watchdog()
        live = self._store.live_sessions.get(game_id)
        if live is not None:
            return live.pending_action()
        if self._store.get_game(game_id) is None:
            raise HTTPException(status_code=404, detail="game not found")
        return None

    def submit_human_action(self, game_id: str, request: HumanActionRequest) -> dict[str, Any]:
        self._store.check_live_game_watchdog()
        live = self._store.live_sessions.get(game_id)
        if live is None:
            if self._store.get_game(game_id) is None:
                raise HTTPException(status_code=404, detail="game not found")
            raise HTTPException(status_code=409, detail="game is not waiting for human input")
        if not live.submit(request):
            raise HTTPException(status_code=409, detail="game is not waiting for human input")
        snapshot = live.snapshot()
        self._store.games[game_id] = snapshot
        return snapshot


__all__ = ["GameSessionService"]
