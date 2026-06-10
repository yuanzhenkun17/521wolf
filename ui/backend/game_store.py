"""Game loading, live-session, and history mixin for the UI backend store."""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from fastapi import HTTPException

from app.util.json import to_jsonable
from app.util.time import beijing_now_iso
from app.lib.version import ReleaseStageNotAllowedError
from storage.game_store import delete_game_from_env
from storage.game_read_model import row_history_phase
from storage.provider import storage_provider_from_env
from storage.public_events import public_events_only
from storage.runtime import GamePersistence
from ui.backend.errors import domain_error_detail, release_stage_not_allowed_detail
from ui.backend.history_index import GameHistoryIndex, history_facets, source_counts
from ui.backend.live_game import (
    LIVE_GAME_HEARTBEAT_TIMEOUT_SECONDS,
    LIVE_GAME_TERMINAL_STATUSES,
    LiveGameSession,
)
from ui.backend.schemas import GameStartRequest, HumanActionRequest
from ui.backend.serializers import (
    _dead_players,
    _fallback_version,
    _frontend_review,
    _normalize_decision,
    _normalize_event,
    _normalize_roles,
    _player_view_snapshot,
    _role_label,
    _sheriff_from_events,
    _team_for_role,
    _vote_tally,
)
from ui.backend.task_state import _match_filter, _pagination


_DEFAULT_PHASE_LOG_LIMIT = 300
_DEFAULT_PHASE_DECISION_LIMIT = 200
_DEFAULT_REPLAY_LIMIT = 500


class GameStoreMixin:
    def _deleted_game_ids(self) -> set[str]:
        deleted = getattr(self, "_deleted_game_ids_cache", None)
        if deleted is None:
            deleted = set()
            setattr(self, "_deleted_game_ids_cache", deleted)
        return deleted

    def _mark_game_deleted(self, game_id: str) -> None:
        self._deleted_game_ids().add(str(game_id))

    def _clear_game_deleted(self, game_id: str) -> None:
        self._deleted_game_ids().discard(str(game_id))

    def _is_game_deleted(self, game_id: str) -> bool:
        return str(game_id) in self._deleted_game_ids()

    def _game_history_index(self) -> GameHistoryIndex:
        index = getattr(self, "_game_history_index_cache", None)
        if index is None:
            index = GameHistoryIndex(
                None,
                build_rows=lambda: self._build_game_history_rows(),
                fingerprint=self._game_history_fingerprint,
            )
            setattr(self, "_game_history_index_cache", index)
        return index

    def invalidate_game_history_index(self) -> None:
        index = getattr(self, "_game_history_index_cache", None)
        if index is not None:
            index.invalidate()
        self._close_wolf_read_connection()

    def prewarm_game_history_index(self) -> None:
        self._game_history_index().rows()

    def _wolf_read_lock(self) -> Any:
        return self._game_read_gateway().lock

    def _close_wolf_read_connection(self) -> None:
        gateway = getattr(self, "_game_read_gateway_cache", None)
        if gateway is not None:
            gateway.close()

    def _open_wolf_read_connection(self) -> Any:
        return self._game_read_gateway().open_connection()

    def _read_wolf_repository(self, read: Any) -> Any:
        return self._game_read_gateway().read_repository(read)

    def _game_history_fingerprint(self) -> dict[str, Any]:
        return self._game_history_service().history_fingerprint()

    def _game_history_memory_fingerprint(self) -> list[dict[str, Any]]:
        return self._game_history_service().memory_fingerprint()

    def _game_history_memory_item(self, game_id: str, game: dict[str, Any]) -> dict[str, Any]:
        return self._game_history_service().memory_item(game_id, game)

    def _postgres_history_fingerprint(self) -> dict[str, Any]:
        return self._game_history_service().postgres_fingerprint()

    def _open_wolf_connection(self) -> Any:
        import storage.provider as provider_mod

        return provider_mod.open_wolf_connection(paths=self.paths)

    def _load_game_from_pg(self, game_id: str) -> dict[str, Any] | None:
        return self._game_read_gateway().load_game_detail(game_id)

    def _load_game_history_shell_from_pg(self, game_id: str) -> dict[str, Any] | None:
        return self._game_read_gateway().load_game_history_shell(game_id)

    def _load_game_phase_detail_from_pg(
        self,
        game_id: str,
        *,
        day: int,
        phase: str,
        log_offset: int = 0,
        log_limit: int | None = _DEFAULT_PHASE_LOG_LIMIT,
        decision_offset: int = 0,
        decision_limit: int | None = _DEFAULT_PHASE_DECISION_LIMIT,
    ) -> dict[str, Any] | None:
        return self._game_read_gateway().load_game_phase_detail(
            game_id,
            day=day,
            phase=phase,
            log_offset=log_offset,
            log_limit=log_limit,
            decision_offset=decision_offset,
            decision_limit=decision_limit,
        )

    def _load_game_flow_data_from_pg(self, game_id: str) -> dict[str, Any] | None:
        return self._game_read_gateway().load_game_flow_data(game_id)

    def _load_game_replay_from_pg(
        self,
        game_id: str,
        *,
        cursor: int = 0,
        limit: int | None = _DEFAULT_REPLAY_LIMIT,
    ) -> dict[str, Any] | None:
        return self._game_read_gateway().load_game_replay(game_id, cursor=cursor, limit=limit)

    def _load_game_review_from_pg(self, game_id: str) -> dict[str, Any] | None:
        return self._game_read_gateway().load_game_review(game_id)

    def _list_games_from_pg(self) -> list[dict[str, Any]]:
        return self._game_read_gateway().list_history_rows()

    def _live_game_heartbeat_timeout_seconds(self) -> float:
        value = getattr(self, "live_game_heartbeat_timeout_seconds", LIVE_GAME_HEARTBEAT_TIMEOUT_SECONDS)
        try:
            return max(1.0, float(value))
        except (TypeError, ValueError):
            return LIVE_GAME_HEARTBEAT_TIMEOUT_SECONDS

    def skill_dir_for_request(self, request: GameStartRequest) -> str | None:
        if not request.role_versions:
            return request.skill_dir
        from app.lib.version import SkillVersionConfig, build_composite_skill_dir

        try:
            role_versions = self._effective_role_versions(request.role_versions)
            if not role_versions:
                return request.skill_dir
            skill_dir = build_composite_skill_dir(
                self.registry,
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

    def _effective_role_versions(self, role_versions: dict[str, str]) -> dict[str, str]:
        from app.lib.version import ensure_version_allowed_for_default_use

        effective: dict[str, str] = {}
        registry = self.registry
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

    def _snapshot_log_time(self, snapshot: dict[str, Any], fallback: str | None = None) -> str | None:
        return self._game_history_service().snapshot_log_time(snapshot, fallback)

    def _game_list_row(self, game: dict[str, Any]) -> dict[str, Any]:
        return self._game_history_service().game_list_row(game)

    async def start_game(self, request: GameStartRequest) -> dict[str, Any]:
        return await self._live_game_lifecycle().start_game(request)

    async def start_live_game(self, *, game_id: str, request: GameStartRequest, skill_dir: str | None) -> dict[str, Any]:
        return await self._live_game_lifecycle().start_live_game(
            game_id=game_id,
            request=request,
            skill_dir=skill_dir,
        )

    async def run_live_session(self, game_id: str) -> None:
        await self._live_game_lifecycle().run_live_session(game_id)

    def check_live_game_watchdog(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        return self._live_game_lifecycle().check_watchdog(timeout_seconds=timeout_seconds)

    def _live_session_waiting_for_human_within_timeout(self, session: Any) -> bool:
        return self._live_game_lifecycle().live_session_waiting_for_human_within_timeout(session)

    def get_game(self, game_id: str) -> dict[str, Any] | None:
        self.check_live_game_watchdog()
        live = self.live_sessions.get(game_id)
        if live is not None:
            snapshot = live.snapshot()
            self.games[game_id] = snapshot
            if live.status in LIVE_GAME_TERMINAL_STATUSES:
                self.persist_live_session(live, snapshot)
            return snapshot
        cached = self.games.get(game_id)
        if cached is not None and str(cached.get("status") or "").lower() in LIVE_GAME_TERMINAL_STATUSES:
            return cached
        loaded = self._load_game_from_pg(game_id)
        if loaded is not None:
            self.games[game_id] = loaded
            return loaded
        if cached is not None and str(cached.get("status") or "").lower() not in LIVE_GAME_TERMINAL_STATUSES:
            return cached
        return None

    def get_game_history_shell(self, game_id: str) -> dict[str, Any] | None:
        return self._game_history_service().get_game_history_shell(game_id)

    def get_game_phase_detail(
        self,
        game_id: str,
        *,
        day: int,
        phase: str,
        log_offset: int = 0,
        log_limit: int | None = _DEFAULT_PHASE_LOG_LIMIT,
        decision_offset: int = 0,
        decision_limit: int | None = _DEFAULT_PHASE_DECISION_LIMIT,
    ) -> dict[str, Any] | None:
        return self._game_history_service().get_game_phase_detail(
            game_id,
            day=day,
            phase=phase,
            log_offset=log_offset,
            log_limit=log_limit,
            decision_offset=decision_offset,
            decision_limit=decision_limit,
        )

    def get_game_flow_data(self, game_id: str) -> dict[str, Any] | None:
        self.check_live_game_watchdog()
        live = self.live_sessions.get(game_id)
        if live is not None:
            snapshot = live.snapshot()
            self.games[game_id] = snapshot
            return self._flow_data_from_snapshot(game_id, _player_view_snapshot(snapshot))
        cached = self.games.get(game_id)
        if cached is not None and isinstance(cached.get("decisions"), list):
            return self._flow_data_from_snapshot(game_id, _player_view_snapshot(cached))
        return self._load_game_flow_data_from_pg(game_id)

    def get_game_replay(
        self,
        game_id: str,
        *,
        cursor: int = 0,
        limit: int | None = _DEFAULT_REPLAY_LIMIT,
    ) -> dict[str, Any] | None:
        return self._game_history_service().get_game_replay(game_id, cursor=cursor, limit=limit)

    def get_game_review(self, game_id: str) -> dict[str, Any] | None:
        self.check_live_game_watchdog()
        live = self.live_sessions.get(game_id)
        if live is not None:
            return self._review_payload(game_id, live.snapshot())
        cached = self.games.get(game_id)
        if cached is not None:
            return self._review_payload(game_id, cached)
        return self._load_game_review_from_pg(game_id)

    def _review_payload(self, game_id: str, game: dict[str, Any]) -> dict[str, Any]:
        view_game = _player_view_snapshot(game)
        return view_game.get("review") or {
            "game_id": game_id,
            "winner": view_game.get("winner"),
            "review_status": "暂无复盘报告",
            "notes": [],
        }

    def _history_shell_from_snapshot(self, game_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        return self._game_history_service().history_shell_from_snapshot(game_id, snapshot)

    def _history_phase_summaries_from_snapshot(
        self,
        snapshot: dict[str, Any],
        logs: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return self._game_history_service().history_phase_summaries_from_snapshot(snapshot, logs, decisions)

    def _attach_history_state_to_phase_summaries(
        self,
        phases: list[dict[str, Any]],
        snapshot: dict[str, Any],
        logs: list[dict[str, Any]],
        has_authoritative_deaths: bool,
        sort_value: Any,
    ) -> None:
        self._game_history_service().attach_history_state_to_phase_summaries(
            phases,
            snapshot,
            logs,
            has_authoritative_deaths,
            sort_value,
        )

    def _phase_detail_from_snapshot(
        self,
        game_id: str,
        snapshot: dict[str, Any],
        *,
        day: int,
        phase: str,
        log_offset: int = 0,
        log_limit: int | None = _DEFAULT_PHASE_LOG_LIMIT,
        decision_offset: int = 0,
        decision_limit: int | None = _DEFAULT_PHASE_DECISION_LIMIT,
    ) -> dict[str, Any]:
        return self._game_history_service().phase_detail_from_snapshot(
            game_id,
            snapshot,
            day=day,
            phase=phase,
            log_offset=log_offset,
            log_limit=log_limit,
            decision_offset=decision_offset,
            decision_limit=decision_limit,
        )

    def _flow_data_from_snapshot(self, game_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        decisions = []
        for index, decision in enumerate(snapshot.get("decisions") or [], start=1):
            if not isinstance(decision, dict):
                continue
            normalized = _normalize_decision(decision, index)
            decisions.append({
                "id": normalized.get("id"),
                "decision_id": normalized.get("decision_id") or normalized.get("id"),
                "game_id": game_id,
                "actor_id": normalized.get("actor_id"),
                "player_id": normalized.get("player_id"),
                "target_id": normalized.get("target_id"),
                "selected_target": normalized.get("selected_target", normalized.get("target_id")),
                "selected_choice": normalized.get("selected_choice"),
                "day": normalized.get("day"),
                "phase": row_history_phase(normalized),
                "action": normalized.get("action"),
                "action_type": normalized.get("action_type"),
                "role": normalized.get("role"),
                "public_summary": normalized.get("public_summary") or normalized.get("public_text") or "",
                "public_text": normalized.get("public_text") or normalized.get("public_summary") or "",
                "private_reasoning": normalized.get("private_reasoning") or normalized.get("reason") or "",
                "confidence": normalized.get("confidence"),
                "candidates": normalized.get("candidates") if isinstance(normalized.get("candidates"), list) else [],
                "source": normalized.get("source"),
                "policy_adjustments": normalized.get("policy_adjustments") if isinstance(normalized.get("policy_adjustments"), list) else [],
                "errors": normalized.get("errors") if isinstance(normalized.get("errors"), list) else [],
                "created_at": normalized.get("created_at"),
            })
        return {
            "game_id": game_id,
            "detail_view": "flow-data",
            "players": list(snapshot.get("players") or []),
            "decisions": decisions,
            "decision_count": len(decisions),
        }

    def _replay_from_snapshot(
        self,
        game_id: str,
        snapshot: dict[str, Any],
        *,
        cursor: int = 0,
        limit: int | None = _DEFAULT_REPLAY_LIMIT,
    ) -> dict[str, Any]:
        return self._game_history_service().replay_from_snapshot(game_id, snapshot, cursor=cursor, limit=limit)

    def _build_game_history_rows(self) -> list[dict[str, Any]]:
        return self._game_history_service().build_game_history_rows()

    def list_games(self) -> list[dict[str, Any]]:
        self.check_live_game_watchdog()
        return self._build_game_history_rows()

    def query_game_history(
        self,
        *,
        sources: set[str] | None = None,
        statuses: set[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        self.check_live_game_watchdog()
        rows = self._game_history_index().rows()
        filtered = rows
        if sources is not None:
            filtered = [row for row in filtered if _match_filter(row.get("log_source", "normal"), sources)]
        if statuses is not None:
            filtered = [row for row in filtered if _match_filter(row.get("status"), statuses)]
        page, pagination = _pagination(filtered, limit=limit, offset=offset)
        counts = source_counts(rows)
        return {
            "games": page,
            "pagination": pagination,
            "counts": counts,
            "facets": history_facets(rows),
        }

    def get_human_action(self, game_id: str) -> dict[str, Any] | None:
        self.check_live_game_watchdog()
        live = self.live_sessions.get(game_id)
        if live is not None:
            return live.pending_action()
        if self.get_game(game_id) is None:
            raise HTTPException(status_code=404, detail="game not found")
        return None

    def submit_human_action(self, game_id: str, request: HumanActionRequest) -> dict[str, Any]:
        self.check_live_game_watchdog()
        live = self.live_sessions.get(game_id)
        if live is None:
            if self.get_game(game_id) is None:
                raise HTTPException(status_code=404, detail="game not found")
            raise HTTPException(status_code=409, detail="game is not waiting for human input")
        if not live.submit(request):
            raise HTTPException(status_code=409, detail="game is not waiting for human input")
        snapshot = live.snapshot()
        self.games[game_id] = snapshot
        return snapshot

    def stop_game(self, game_id: str) -> dict[str, Any]:
        return self._live_game_lifecycle().stop_game(game_id)

    def delete_game(self, game_id: str, *, force: bool = False) -> dict[str, Any]:
        return self._game_delete_coordinator().delete_game(game_id, force=force)

    def _snapshot_log_source(self, snapshot: dict[str, Any]) -> str:
        config = snapshot.get("config") if isinstance(snapshot.get("config"), dict) else {}
        source = snapshot.get("log_source") or config.get("log_source") or "normal"
        return str(source or "normal").lower()

    def _delete_game_from_pg(self, game_id: str) -> None:
        delete_game_from_env(game_id, paths=self.paths)

    def _persist_live_session_start(self, session: LiveGameSession) -> None:
        self._live_game_lifecycle().persist_start(session)

    def persist_live_session(self, session: LiveGameSession, snapshot: dict[str, Any] | None = None) -> None:
        self._live_game_lifecycle().persist_session(session, snapshot)

    def _create_game_persistence(self, game_id: str, *, run_metadata: dict[str, Any]) -> GamePersistence:
        return GamePersistence(
            game_id=game_id,
            provider=storage_provider_from_env(paths=self.paths),
            run_metadata=run_metadata,
        )

    def _persist_snapshot_to_pg(
        self,
        snapshot: dict[str, Any],
        *,
        persistence: GamePersistence | None = None,
    ) -> None:
        game_id = str(snapshot.get("game_id") or "")
        if not game_id:
            raise ValueError("snapshot game_id is required for PostgreSQL persistence")

        owns_persistence = persistence is None
        if persistence is None:
            persistence = GamePersistence(
                game_id=game_id,
                provider=storage_provider_from_env(paths=self.paths),
                run_metadata={
                    "mode": snapshot.get("mode") or "watch",
                    "source_run_id": game_id,
                    "ruleset_version": "werewolf_12p_v1",
                },
            )

        try:
            config = self._pg_snapshot_config(snapshot)
            events = self._pg_snapshot_events(snapshot)
            final_state = self._pg_snapshot_final_state(snapshot)
            player_roles = self._pg_snapshot_player_roles(snapshot)
            final_alive = self._pg_snapshot_final_alive(snapshot)
            persistence.save_game_result(
                seed=self._pg_snapshot_seed(snapshot),
                player_roles=player_roles,
                config=config,
                winner=self._pg_snapshot_winner(snapshot),
                started_at=str(snapshot.get("started_at") or config.get("started_at") or beijing_now_iso()),
                finished_at=snapshot.get("finished_at"),
                total_rounds=self._pg_snapshot_total_rounds(snapshot, events),
                public_events=public_events_only(events),
                final_state=final_state,
                deaths=self._pg_snapshot_deaths(snapshot),
                final_alive=final_alive,
            )
        finally:
            if owns_persistence:
                persistence.close()

    def _pg_snapshot_config(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        config = dict(snapshot.get("config") if isinstance(snapshot.get("config"), dict) else {})
        config.update(
            {
                "seed": snapshot.get("seed", config.get("seed")),
                "max_days": snapshot.get("max_days", config.get("max_days")),
                "enable_sheriff": snapshot.get("enable_sheriff", config.get("enable_sheriff", True)),
                "skill_dir": snapshot.get("skill_dir", config.get("skill_dir")),
                "role_versions": dict(
                    snapshot.get("role_skill_dirs")
                    if isinstance(snapshot.get("role_skill_dirs"), dict)
                    else config.get("role_versions") or {}
                ),
                "role_skill_dirs": dict(
                    snapshot.get("role_skill_dirs")
                    if isinstance(snapshot.get("role_skill_dirs"), dict)
                    else config.get("role_skill_dirs") or {}
                ),
                "player_count": snapshot.get("player_count", config.get("player_count", 12)),
                "human_player_id": snapshot.get("human_player_id", config.get("human_player_id")),
                "mode": snapshot.get("mode", config.get("mode", "watch")),
                "log_source": snapshot.get("log_source", config.get("log_source", "normal")),
                "log_name": snapshot.get("log_name", config.get("log_name", snapshot.get("game_id"))),
                "source_game_id": snapshot.get(
                    "source_game_id",
                    config.get("source_game_id", snapshot.get("game_id")),
                ),
                "started_at": snapshot.get("started_at", config.get("started_at")),
                "finished_at": snapshot.get("finished_at", config.get("finished_at")),
                "last_heartbeat_at": snapshot.get("last_heartbeat_at", config.get("last_heartbeat_at")),
            }
        )
        return to_jsonable(config)

    def _pg_snapshot_final_state(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "game_id",
            "log_name",
            "status",
            "stop_requested",
            "cancelled",
            "interrupted",
            "failed",
            "cancelled_at",
            "interrupted_at",
            "last_heartbeat_at",
            "mode",
            "winner",
            "seed",
            "max_days",
            "enable_sheriff",
            "skill_dir",
            "human_player_id",
            "player_count",
            "day",
            "phase",
            "sheriff_id",
            "review",
            "diagnostics",
            "waiting_for",
            "pending_action",
            "pending_human_action",
            "current_speaker_id",
            "vote_tally",
            "role_counts",
            "role_skill_dirs",
            "started_at",
            "finished_at",
            "manifest",
            "error",
        )
        final_state = {key: snapshot.get(key) for key in fields if key in snapshot}
        final_state.setdefault("status", "running")
        final_state["config"] = self._pg_snapshot_config(snapshot)
        final_state["players"] = list(snapshot.get("players") or [])
        final_state["deaths"] = self._pg_snapshot_deaths(snapshot)
        return to_jsonable(final_state)

    def _pg_snapshot_events(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        raw_events = snapshot.get("events") or snapshot.get("logs") or []
        return [to_jsonable(event) for event in raw_events if isinstance(event, dict)]

    def _pg_snapshot_player_roles(self, snapshot: dict[str, Any]) -> dict[int, str]:
        roles: dict[int, str] = {}
        player_roles = snapshot.get("player_roles")
        if isinstance(player_roles, dict):
            for player_id, role in player_roles.items():
                try:
                    roles[int(player_id)] = str(role)
                except (TypeError, ValueError):
                    continue
        for player in snapshot.get("players") or []:
            if not isinstance(player, dict):
                continue
            seat = player.get("seat", player.get("id"))
            role = player.get("role")
            if seat is None or role is None:
                continue
            try:
                roles[int(seat)] = str(role)
            except (TypeError, ValueError):
                continue
        return roles

    def _pg_snapshot_final_alive(self, snapshot: dict[str, Any]) -> dict[int, bool] | None:
        alive: dict[int, bool] = {}
        for player in snapshot.get("players") or []:
            if not isinstance(player, dict):
                continue
            seat = player.get("seat", player.get("id"))
            if seat is None:
                continue
            try:
                alive[int(seat)] = bool(player.get("alive", True))
            except (TypeError, ValueError):
                continue
        return alive or None

    def _pg_snapshot_deaths(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        raw_deaths = snapshot.get("deaths")
        if isinstance(raw_deaths, list):
            return [to_jsonable(death) for death in raw_deaths if isinstance(death, dict)]
        deaths: dict[int, dict[str, Any]] = {}
        for event in self._pg_snapshot_events(snapshot):
            event_type = str(event.get("event_type") or event.get("type") or "")
            if event_type != "death":
                continue
            target = event.get("target")
            try:
                seat = int(target)
            except (TypeError, ValueError):
                continue
            deaths[seat] = {
                "player_id": seat,
                "day": event.get("day"),
                "phase": event.get("phase"),
                "cause": (event.get("payload") if isinstance(event.get("payload"), dict) else {}).get("cause"),
            }
        return list(deaths.values())

    def _pg_snapshot_total_rounds(self, snapshot: dict[str, Any], events: list[dict[str, Any]]) -> int:
        days = [self._safe_int(snapshot.get("day"), default=0)]
        for event in events:
            days.append(self._safe_int(event.get("day"), default=0))
        return max(days) if days else 0

    def _pg_snapshot_seed(self, snapshot: dict[str, Any]) -> int:
        config = snapshot.get("config") if isinstance(snapshot.get("config"), dict) else {}
        return self._safe_int(snapshot.get("seed", config.get("seed")), default=0)

    def _pg_snapshot_winner(self, snapshot: dict[str, Any]) -> str | None:
        winner = snapshot.get("winner")
        return str(winner) if winner is not None and str(winner) else None

    @staticmethod
    def _safe_int(value: Any, *, default: int) -> int:
        try:
            if value is None or value == "":
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    def snapshot_from_result(
        self,
        result: dict[str, Any],
        *,
        mode: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        game_id = str(result.get("game_id") or f"ui_{uuid.uuid4().hex[:12]}")
        events = list(result.get("events", []) or [])
        decisions = list(result.get("decisions", []) or [])
        roles = _normalize_roles(result.get("player_roles", {}))
        deaths = _dead_players(events)
        last_event = events[-1] if events else {}
        sheriff_id = _sheriff_from_events(events)
        players = [
            {
                "id": player_id,
                "seat": player_id,
                "name": f"{player_id}号",
                "role": role,
                "role_hint": _role_label(role),
                "team": _team_for_role(role),
                "alive": player_id not in deaths,
                "is_sheriff": player_id == sheriff_id,
                "is_human": False,
                "role_state": {},
            }
            for player_id, role in sorted(roles.items())
        ]
        normalized_decisions = [_normalize_decision(d, index) for index, d in enumerate(decisions, start=1)]
        review = _frontend_review(result.get("review"), events=events)
        day = int(last_event.get("day", 0) or 0) if isinstance(last_event, dict) else 0
        phase = str(last_event.get("phase", "finished") or "finished") if isinstance(last_event, dict) else "finished"
        diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), list) else []
        last_heartbeat_at = result.get("last_heartbeat_at") or config.get("last_heartbeat_at")
        manifest = result.get("manifest") if isinstance(result.get("manifest"), dict) else config.get("manifest")
        if not isinstance(manifest, dict):
            manifest = {
                "schema_version": 1,
                "run_type": "game",
                "game_id": game_id,
                "status": result.get("status", "completed"),
            }
        return {
            "game_id": game_id,
            "log_name": game_id,
            "status": result.get("status", "completed"),
            "stop_requested": bool(result.get("stop_requested", False)),
            "cancelled": bool(result.get("cancelled", False)),
            "interrupted": bool(result.get("interrupted", False)),
            "failed": bool(result.get("failed", result.get("status") == "failed")),
            "cancelled_at": result.get("cancelled_at"),
            "interrupted_at": result.get("interrupted_at"),
            "last_heartbeat_at": last_heartbeat_at,
            "mode": mode,
            "winner": result.get("winner"),
            "seed": result.get("seed") or config.get("seed"),
            "started_at": result.get("started_at") or config.get("started_at"),
            "finished_at": result.get("finished_at") or config.get("finished_at"),
            "log_time": (
                result.get("finished_at")
                or result.get("started_at")
                or result.get("last_heartbeat_at")
                or config.get("finished_at")
                or config.get("started_at")
                or config.get("last_heartbeat_at")
            ),
            "max_days": config.get("max_days"),
            "enable_sheriff": config.get("enable_sheriff", True),
            "skill_dir": config.get("skill_dir"),
            "human_player_id": None,
            "player_count": len(players) or int(config.get("player_count", 12) or 12),
            "day": day,
            "phase": phase,
            "sheriff_id": sheriff_id,
            "players": players,
            "logs": [_normalize_event(e) for e in events],
            "events": [_normalize_event(e) for e in events],
            "decisions": normalized_decisions,
            "review": review,
            "diagnostics": list(diagnostics),
            "waiting_for": "none",
            "pending_action": None,
            "pending_human_action": None,
            "current_speaker_id": None,
            "vote_tally": _vote_tally(
                normalized_decisions,
                current_day=day,
                current_phase=phase,
            ),
            "role_counts": dict(Counter(player["role"] for player in players)),
            "role_skill_dirs": dict(config.get("role_versions", {}) or {}),
            "config": config,
            "manifest": manifest,
            "error": result.get("error"),
        }


