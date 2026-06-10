"""Game loading, live-session, and history mixin for the UI backend store."""

from __future__ import annotations

from typing import Any

from storage.game_history_rules import row_history_phase
from storage.game_store import delete_game_from_env
from storage.provider import storage_provider_from_env as storage_provider_from_env
from storage.runtime import GamePersistence
from ui.backend.history_index import GameHistoryIndex, history_facets, source_counts
from ui.backend.live_game import (
    LIVE_GAME_TERMINAL_STATUSES,
    LiveGameSession,
)
from ui.backend.schemas import GameStartRequest, HumanActionRequest
from ui.backend.serializers import (
    _normalize_decision,
    _player_view_snapshot,
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
        return self._game_session_service().live_game_heartbeat_timeout_seconds()

    def skill_dir_for_request(self, request: GameStartRequest) -> str | None:
        return self._game_session_service().skill_dir_for_request(request)

    def _effective_role_versions(self, role_versions: dict[str, str]) -> dict[str, str]:
        return self._game_session_service().effective_role_versions(role_versions)

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
        return self._game_session_service().get_human_action(game_id)

    def submit_human_action(self, game_id: str, request: HumanActionRequest) -> dict[str, Any]:
        return self._game_session_service().submit_human_action(game_id, request)

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
        return self._game_persistence_service().create_game_persistence(game_id, run_metadata=run_metadata)

    def _persist_snapshot_to_pg(
        self,
        snapshot: dict[str, Any],
        *,
        persistence: GamePersistence | None = None,
    ) -> None:
        self._game_persistence_service().persist_snapshot_to_pg(snapshot, persistence=persistence)

    def _pg_snapshot_config(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return self._game_persistence_service().pg_snapshot_config(snapshot)

    def _pg_snapshot_final_state(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return self._game_persistence_service().pg_snapshot_final_state(snapshot)

    def _pg_snapshot_events(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        return self._game_persistence_service().pg_snapshot_events(snapshot)

    def _pg_snapshot_player_roles(self, snapshot: dict[str, Any]) -> dict[int, str]:
        return self._game_persistence_service().pg_snapshot_player_roles(snapshot)

    def _pg_snapshot_final_alive(self, snapshot: dict[str, Any]) -> dict[int, bool] | None:
        return self._game_persistence_service().pg_snapshot_final_alive(snapshot)

    def _pg_snapshot_deaths(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        return self._game_persistence_service().pg_snapshot_deaths(snapshot)

    def _pg_snapshot_total_rounds(self, snapshot: dict[str, Any], events: list[dict[str, Any]]) -> int:
        return self._game_persistence_service().pg_snapshot_total_rounds(snapshot, events)

    def _pg_snapshot_seed(self, snapshot: dict[str, Any]) -> int:
        return self._game_persistence_service().pg_snapshot_seed(snapshot)

    def _pg_snapshot_winner(self, snapshot: dict[str, Any]) -> str | None:
        return self._game_persistence_service().pg_snapshot_winner(snapshot)

    @staticmethod
    def _safe_int(value: Any, *, default: int) -> int:
        from ui.backend.services.game_persistence_service import GamePersistenceService

        return GamePersistenceService.safe_int(value, default=default)

    def snapshot_from_result(
        self,
        result: dict[str, Any],
        *,
        mode: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        return self._game_persistence_service().snapshot_from_result(result, mode=mode, config=config)


