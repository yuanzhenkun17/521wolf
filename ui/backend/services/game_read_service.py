"""Read gateway for UI backend game history and detail queries."""

from __future__ import annotations

import threading
from typing import Any, Callable

from storage.game_read_model import (
    GameReadRepository,
    death_target_ids,
    history_phase_key,
    history_phase_title,
    normalize_history_phase,
    row_history_phase,
    sheriff_id_after_log,
)
from ui.backend.game_history_helpers import (
    _evidence_source_context,
    _paginate_history_rows,
    _with_evidence_source_context,
)
from ui.backend.live_game import LIVE_GAME_TERMINAL_STATUSES
from ui.backend.serializers import _normalize_decision, _normalize_event, _player_view_snapshot


_DEFAULT_PHASE_LOG_LIMIT = 300
_DEFAULT_PHASE_DECISION_LIMIT = 200
_MAX_PHASE_LOG_LIMIT = 1000
_MAX_PHASE_DECISION_LIMIT = 500
_DEFAULT_REPLAY_LIMIT = 500
_MAX_REPLAY_LIMIT = 2000

_PHASE_ORDER = {
    "setup": 0,
    "night": 1,
    "sheriff": 2,
    "sheriff_vote": 3,
    "sheriff_result": 4,
    "speech": 5,
    "exile_vote": 6,
    "pk_vote": 7,
    "vote": 8,
    "ended": 9,
}


def _safe_int(value: Any, *, default: int) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


class GameReadGateway:
    """Owns the cached wolf read connection used by UI game read paths."""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._lock = threading.RLock()
        self._conn: Any | None = None

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def close(self) -> None:
        with self._lock:
            conn = self._conn
            if conn is None:
                return
            self._conn = None
            close = getattr(conn, "close", None)
            if callable(close):
                close()

    def open_connection(self) -> Any:
        with self._lock:
            return self._open_connection_unlocked()

    def _open_connection_unlocked(self) -> Any:
        conn = self._conn
        if conn is not None and not getattr(conn, "closed", False):
            return conn
        conn = self._store._open_wolf_connection()
        self._conn = conn
        return conn

    def read_repository(self, read: Callable[[GameReadRepository], Any]) -> Any:
        with self._lock:
            conn = self._open_connection_unlocked()
            try:
                result = read(GameReadRepository(conn))
                commit = getattr(conn, "commit", None)
                if callable(commit):
                    commit()
                return result
            except Exception:
                rollback = getattr(conn, "rollback", None)
                try:
                    if callable(rollback):
                        rollback()
                except Exception:  # noqa: BLE001 - preserve the original read failure
                    pass
                finally:
                    self.close()
                raise

    def history_fingerprint(self) -> dict[str, Any]:
        return self.read_repository(lambda repo: repo.history_fingerprint())

    def load_game_detail(self, game_id: str) -> dict[str, Any] | None:
        return self.read_repository(lambda repo: repo.load_game_detail(game_id))

    def load_game_history_shell(self, game_id: str) -> dict[str, Any] | None:
        return self.read_repository(lambda repo: repo.load_game_history_shell(game_id))

    def load_game_phase_detail(
        self,
        game_id: str,
        *,
        day: int,
        phase: str,
        log_offset: int = 0,
        log_limit: int | None = None,
        decision_offset: int = 0,
        decision_limit: int | None = None,
    ) -> dict[str, Any] | None:
        return self.read_repository(lambda repo: repo.load_game_phase_detail(
            game_id,
            day=day,
            phase=phase,
            log_offset=log_offset,
            log_limit=log_limit,
            decision_offset=decision_offset,
            decision_limit=decision_limit,
        ))

    def load_game_flow_data(self, game_id: str) -> dict[str, Any] | None:
        return self.read_repository(lambda repo: repo.load_game_flow_data(game_id))

    def load_game_replay(
        self,
        game_id: str,
        *,
        cursor: int = 0,
        limit: int | None = None,
    ) -> dict[str, Any] | None:
        return self.read_repository(lambda repo: repo.load_game_replay(game_id, cursor=cursor, limit=limit))

    def load_game_review(self, game_id: str) -> dict[str, Any] | None:
        return self.read_repository(lambda repo: repo.load_game_review(game_id))

    def list_history_rows(self) -> list[dict[str, Any]]:
        return self.read_repository(lambda repo: repo.list_history_rows())


class GameHistoryService:
    """Coordinates UI game history reads across memory snapshots and read storage."""

    def __init__(self, store: Any) -> None:
        self._store = store

    def history_fingerprint(self) -> dict[str, Any]:
        return {
            "memory": self._store._game_history_memory_fingerprint(),
            "postgres": self._store._postgres_history_fingerprint(),
        }

    def memory_fingerprint(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for game_id, game in self._store.games.items():
            items.append(self._store._game_history_memory_item(game_id, game))
        for game_id, session in self._store.live_sessions.items():
            items.append(
                {
                    "game_id": game_id,
                    "status": session.status,
                    "last_heartbeat_at": getattr(session, "last_heartbeat_at", None),
                    "interrupted_at": getattr(session, "interrupted_at", None),
                    "diagnostic_count": len(getattr(session, "diagnostics", []) or []),
                    "event_count": len(getattr(session.event_sink, "backlog", []) or []),
                }
            )
        return sorted(items, key=lambda item: str(item.get("game_id") or ""))

    def memory_item(self, game_id: str, game: dict[str, Any]) -> dict[str, Any]:
        events = game.get("events") if isinstance(game.get("events"), list) else []
        decisions = game.get("decisions") if isinstance(game.get("decisions"), list) else []
        return {
            "game_id": str(game_id),
            "status": game.get("status"),
            "log_source": game.get("log_source"),
            "log_time": self._store._snapshot_log_time(game),
            "last_heartbeat_at": game.get("last_heartbeat_at"),
            "interrupted_at": game.get("interrupted_at"),
            "diagnostic_count": len(game.get("diagnostics") if isinstance(game.get("diagnostics"), list) else []),
            "event_count": len(events),
            "decision_count": len(decisions),
        }

    def postgres_fingerprint(self) -> dict[str, Any]:
        try:
            return {
                "available": True,
                **self._store._game_read_gateway().history_fingerprint(),
            }
        except Exception as exc:  # noqa: BLE001 - history cache invalidation is best-effort.
            return {"available": False, "error": type(exc).__name__}

    def snapshot_log_time(self, snapshot: dict[str, Any], fallback: str | None = None) -> str | None:
        config = snapshot.get("config") if isinstance(snapshot.get("config"), dict) else {}
        return (
            snapshot.get("finished_at")
            or snapshot.get("started_at")
            or snapshot.get("log_time")
            or snapshot.get("last_heartbeat_at")
            or snapshot.get("created_at")
            or snapshot.get("updated_at")
            or config.get("finished_at")
            or config.get("started_at")
            or config.get("log_time")
            or config.get("last_heartbeat_at")
            or config.get("created_at")
            or config.get("updated_at")
            or fallback
        )

    def game_list_row(self, game: dict[str, Any]) -> dict[str, Any]:
        config = game.get("config") if isinstance(game.get("config"), dict) else {}
        context = _evidence_source_context(game, config=config)
        source = str(context["log_source"])
        log_time = self.snapshot_log_time(game)
        diagnostics = game.get("diagnostics") if isinstance(game.get("diagnostics"), list) else []
        return {
            "game_id": game["game_id"],
            "log_name": game.get("log_name", game["game_id"]),
            "source_game_id": game.get("source_game_id") or game.get("log_name") or game["game_id"],
            "log_source": source,
            "log_source_label": context["log_source_label"],
            "source_run_id": context["source_run_id"],
            "source_phase": context["source_phase"],
            "source_phase_label": context["source_phase_label"],
            "role_versions": dict(context["role_versions"]),
            "evidence_source": context,
            "log_time": log_time,
            "started_at": game.get("started_at") or config.get("started_at"),
            "finished_at": game.get("finished_at") or config.get("finished_at"),
            "day": game.get("day", 0),
            "phase": game.get("phase", "finished"),
            "event_count": len(game.get("logs") or game.get("events") or []),
            "decision_count": len(game.get("decisions") or []),
            "winner": game.get("winner"),
            "status": game.get("status"),
            "stop_requested": bool(game.get("stop_requested", False)),
            "cancelled": bool(game.get("cancelled", False)),
            "interrupted": bool(game.get("interrupted", False)),
            "failed": bool(game.get("failed", game.get("status") == "failed")),
            "cancelled_at": game.get("cancelled_at"),
            "interrupted_at": game.get("interrupted_at"),
            "last_heartbeat_at": game.get("last_heartbeat_at") or config.get("last_heartbeat_at"),
            "diagnostics": list(diagnostics),
            "error": game.get("error"),
            "mode": game.get("mode", "watch"),
            "seed": game.get("seed"),
            "max_days": game.get("max_days"),
            "enable_sheriff": game.get("enable_sheriff", True),
            "skill_dir": game.get("skill_dir"),
            "role_skill_dirs": game.get("role_skill_dirs") or config.get("role_skill_dirs") or {},
            "player_count": len(game.get("players", [])) or game.get("player_count") or 12,
            "human_player_id": game.get("human_player_id"),
            "config": config,
        }

    def get_game_history_shell(self, game_id: str) -> dict[str, Any] | None:
        self._store.check_live_game_watchdog()
        live = self._store.live_sessions.get(game_id)
        if live is not None:
            snapshot = live.snapshot()
            self._store.games[game_id] = snapshot
            return self._store._history_shell_from_snapshot(game_id, _player_view_snapshot(snapshot))
        cached = self._store.games.get(game_id)
        if cached is not None and (
            str(cached.get("status") or "").lower() not in LIVE_GAME_TERMINAL_STATUSES
            or isinstance(cached.get("logs") or cached.get("events"), list)
        ):
            return self._store._history_shell_from_snapshot(game_id, _player_view_snapshot(cached))
        return self._store._load_game_history_shell_from_pg(game_id)

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
        self._store.check_live_game_watchdog()
        live = self._store.live_sessions.get(game_id)
        if live is not None:
            snapshot = live.snapshot()
            self._store.games[game_id] = snapshot
            return self._store._phase_detail_from_snapshot(
                game_id,
                _player_view_snapshot(snapshot),
                day=day,
                phase=phase,
                log_offset=log_offset,
                log_limit=log_limit,
                decision_offset=decision_offset,
                decision_limit=decision_limit,
            )
        cached = self._store.games.get(game_id)
        if cached is not None and isinstance(cached.get("logs") or cached.get("events"), list):
            return self._store._phase_detail_from_snapshot(
                game_id,
                _player_view_snapshot(cached),
                day=day,
                phase=phase,
                log_offset=log_offset,
                log_limit=log_limit,
                decision_offset=decision_offset,
                decision_limit=decision_limit,
            )
        return self._store._load_game_phase_detail_from_pg(
            game_id,
            day=day,
            phase=phase,
            log_offset=log_offset,
            log_limit=log_limit,
            decision_offset=decision_offset,
            decision_limit=decision_limit,
        )

    def get_game_replay(
        self,
        game_id: str,
        *,
        cursor: int = 0,
        limit: int | None = _DEFAULT_REPLAY_LIMIT,
    ) -> dict[str, Any] | None:
        self._store.check_live_game_watchdog()
        live = self._store.live_sessions.get(game_id)
        if live is not None:
            snapshot = live.snapshot()
            self._store.games[game_id] = snapshot
            return self._store._replay_from_snapshot(game_id, _player_view_snapshot(snapshot), cursor=cursor, limit=limit)
        cached = self._store.games.get(game_id)
        if cached is not None and isinstance(cached.get("logs") or cached.get("events"), list):
            return self._store._replay_from_snapshot(game_id, _player_view_snapshot(cached), cursor=cursor, limit=limit)
        return self._store._load_game_replay_from_pg(game_id, cursor=cursor, limit=limit)

    def history_shell_from_snapshot(self, game_id: str, snapshot: dict[str, Any]) -> dict[str, Any]:
        logs = [
            _normalize_event(log)
            for log in (snapshot.get("logs") or snapshot.get("events") or [])
            if isinstance(log, dict)
        ]
        decisions = [
            _normalize_decision(decision, index)
            for index, decision in enumerate(snapshot.get("decisions") or [], start=1)
            if isinstance(decision, dict)
        ]
        phases = self.history_phase_summaries_from_snapshot(snapshot, logs, decisions)
        base = dict(snapshot)
        base.pop("logs", None)
        base.pop("events", None)
        base.pop("decisions", None)
        base.pop("review", None)
        players = list(base.get("players") or [])
        role_map: dict[int, str] = {}
        for player in players:
            if not isinstance(player, dict):
                continue
            seat = _safe_int(player.get("seat", player.get("id")), default=0)
            if seat > 0:
                role_map[seat] = str(player.get("role") or "")
        base.update(
            {
                "game_id": game_id,
                "detail_view": "history-shell",
                "event_count": len(logs),
                "decision_count": len(decisions),
                "player_roles": base.get("player_roles") or role_map,
                "players": players,
                "phases": phases,
                "default_phase_key": phases[0]["key"] if phases else history_phase_key(1, "setup"),
                "capabilities": {
                    "phase_detail": True,
                    "replay": True,
                    "flow_data": True,
                    "archive": True,
                    "review": True,
                },
            }
        )
        return _with_evidence_source_context(base)

    def history_phase_summaries_from_snapshot(
        self,
        snapshot: dict[str, Any],
        logs: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        def day_value(value: Any) -> int:
            return _safe_int(value, default=1) or 1

        def sort_value(day: Any, phase: Any) -> int:
            normalized_phase = normalize_history_phase(phase)
            return day_value(day) * 100 + _PHASE_ORDER.get(normalized_phase, len(_PHASE_ORDER))

        def ensure(phases: dict[str, dict[str, Any]], day: Any, phase: Any) -> dict[str, Any]:
            normalized_day = day_value(day)
            normalized_phase = normalize_history_phase(phase)
            key = history_phase_key(normalized_day, normalized_phase)
            if key not in phases:
                phases[key] = {
                    "key": key,
                    "day": normalized_day,
                    "phase": normalized_phase,
                    "title": history_phase_title(normalized_day, normalized_phase),
                    "sort": sort_value(normalized_day, normalized_phase),
                    "log_count": 0,
                    "decision_count": 0,
                    "has_logs": False,
                    "has_decisions": False,
                    "has_votes": False,
                    "has_deaths": False,
                    "first_event_index": None,
                    "last_event_index": None,
                }
            return phases[key]

        phases: dict[str, dict[str, Any]] = {}
        ensure(phases, 1, "setup")
        has_authoritative_deaths = any(
            str(log.get("event_type") or log.get("type") or "") in {
                "death",
                "exile",
                "exile_vote_end",
                "pk_vote_end",
                "white_wolf_burst_kill",
                "white_wolf_burst_death",
                "white_wolf_explosion",
            }
            for log in logs
        )
        for index, log in enumerate(logs, start=1):
            phase = ensure(phases, log.get("day"), row_history_phase(log))
            event_index = _safe_int(log.get("idx", log.get("index", log.get("sequence"))), default=index)
            phase["log_count"] += 1
            phase["has_logs"] = True
            phase["has_deaths"] = bool(phase["has_deaths"] or death_target_ids(log, has_authoritative_deaths))
            phase["first_event_index"] = (
                event_index
                if phase["first_event_index"] is None
                else min(phase["first_event_index"], event_index)
            )
            phase["last_event_index"] = (
                event_index
                if phase["last_event_index"] is None
                else max(phase["last_event_index"], event_index)
            )
        for decision in decisions:
            phase = ensure(phases, decision.get("day"), row_history_phase(decision))
            action = str(decision.get("action") or decision.get("action_type") or "")
            phase["decision_count"] += 1
            phase["has_decisions"] = True
            phase["has_votes"] = bool(
                phase["has_votes"] or action in {"vote", "exile", "exile_vote", "pk_vote", "sheriff_vote"}
            )
        if snapshot.get("winner"):
            max_day = max([day_value(snapshot.get("day")), *[day_value(log.get("day")) for log in logs], 1])
            ensure(phases, max_day, "ended")
        result = sorted(phases.values(), key=lambda item: (item["sort"], item["key"]))
        self.attach_history_state_to_phase_summaries(result, snapshot, logs, has_authoritative_deaths, sort_value)
        return result

    def attach_history_state_to_phase_summaries(
        self,
        phases: list[dict[str, Any]],
        snapshot: dict[str, Any],
        logs: list[dict[str, Any]],
        has_authoritative_deaths: bool,
        sort_value: Any,
    ) -> None:
        players = [player for player in snapshot.get("players") or [] if isinstance(player, dict)]
        alive: dict[int, bool] = {}
        for player in players:
            player_id = _safe_int(player.get("id", player.get("seat")), default=0)
            if player_id > 0:
                alive[player_id] = True
        sheriff_id: int | None = None
        sorted_logs = sorted(
            logs,
            key=lambda log: (
                sort_value(log.get("day"), row_history_phase(log)),
                _safe_int(log.get("idx", log.get("index", log.get("sequence"))), default=0),
            ),
        )
        log_index = 0
        for phase in phases:
            phase_sort = sort_value(phase.get("day"), phase.get("phase"))
            phase_last_index = phase.get("last_event_index")
            while log_index < len(sorted_logs):
                log = sorted_logs[log_index]
                log_sort = sort_value(log.get("day"), row_history_phase(log))
                event_index = _safe_int(log.get("idx", log.get("index", log.get("sequence"))), default=0)
                if log_sort > phase_sort or (
                    log_sort == phase_sort and phase_last_index is not None and event_index > phase_last_index
                ):
                    break
                for target_id in death_target_ids(log, has_authoritative_deaths):
                    alive[target_id] = False
                sheriff_id = sheriff_id_after_log(log, sheriff_id)
                log_index += 1
            alive_ids = sorted(player_id for player_id, is_alive in alive.items() if is_alive)
            dead_ids = sorted(player_id for player_id, is_alive in alive.items() if not is_alive)
            phase["alive_player_ids"] = alive_ids
            phase["dead_player_ids"] = dead_ids
            phase["sheriff_id"] = sheriff_id
            phase["state_after"] = {"alive": alive_ids, "dead": dead_ids, "sheriff_id": sheriff_id}

    def phase_detail_from_snapshot(
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
        target_day = _safe_int(day, default=1) or 1
        target_phase = normalize_history_phase(phase)
        all_logs = [
            _normalize_event(log)
            for log in (snapshot.get("logs") or snapshot.get("events") or [])
            if isinstance(log, dict)
            and _safe_int(log.get("day"), default=1) == target_day
            and row_history_phase(log, target_phase) == target_phase
        ]
        all_decisions = [
            _normalize_decision(decision, index)
            for index, decision in enumerate(snapshot.get("decisions") or [], start=1)
            if isinstance(decision, dict)
            and _safe_int(decision.get("day"), default=1) == target_day
            and row_history_phase(decision, target_phase) == target_phase
        ]
        logs, log_pagination = _paginate_history_rows(
            all_logs,
            offset=log_offset,
            limit=log_limit,
            default_limit=_DEFAULT_PHASE_LOG_LIMIT,
            max_limit=_MAX_PHASE_LOG_LIMIT,
        )
        decisions, decision_pagination = _paginate_history_rows(
            all_decisions,
            offset=decision_offset,
            limit=decision_limit,
            default_limit=_DEFAULT_PHASE_DECISION_LIMIT,
            max_limit=_MAX_PHASE_DECISION_LIMIT,
        )
        return {
            "game_id": game_id,
            "detail_view": "phase-detail",
            "phase_key": history_phase_key(target_day, target_phase),
            "day": target_day,
            "phase": target_phase,
            "title": history_phase_title(target_day, target_phase),
            "logs": logs,
            "decisions": decisions,
            "summary": {
                "log_count": len(all_logs),
                "decision_count": len(all_decisions),
                "vote_count": sum(
                    1
                    for decision in all_decisions
                    if str(decision.get("action") or "") in {"vote", "exile", "exile_vote", "pk_vote", "sheriff_vote"}
                ),
                "death_count": sum(1 for log in all_logs if death_target_ids(log, True)),
            },
            "pagination": {
                "logs": log_pagination,
                "decisions": decision_pagination,
            },
        }

    def replay_from_snapshot(
        self,
        game_id: str,
        snapshot: dict[str, Any],
        *,
        cursor: int = 0,
        limit: int | None = _DEFAULT_REPLAY_LIMIT,
    ) -> dict[str, Any]:
        events = [
            _normalize_event(log)
            for log in (snapshot.get("logs") or snapshot.get("events") or [])
            if isinstance(log, dict)
        ]
        all_decisions = [
            _normalize_decision(decision, index)
            for index, decision in enumerate(snapshot.get("decisions") or [], start=1)
            if isinstance(decision, dict)
        ]
        safe_cursor = max(0, _safe_int(cursor, default=0))
        safe_limit = max(1, min(_safe_int(limit, default=_DEFAULT_REPLAY_LIMIT), _MAX_REPLAY_LIMIT))
        page_events = events[safe_cursor:safe_cursor + safe_limit]
        next_cursor = safe_cursor + len(page_events)
        has_more = next_cursor < len(events)
        allowed_pairs = {
            (_safe_int(event.get("day"), default=1) or 1, row_history_phase(event))
            for event in page_events
        }
        decisions = [
            decision
            for decision in all_decisions
            if (_safe_int(decision.get("day"), default=1) or 1, row_history_phase(decision)) in allowed_pairs
        ]
        payload = {
            "game_id": game_id,
            "detail_view": "replay",
            "cursor": safe_cursor,
            "limit": safe_limit,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "event_count": len(events),
            "decision_count": len(decisions),
            "players": list(snapshot.get("players") or []),
            "events": page_events,
            "logs": page_events,
            "decisions": decisions,
            "winner": snapshot.get("winner"),
            "status": snapshot.get("status"),
        }
        return _with_evidence_source_context(payload, snapshot)

    def build_game_history_rows(self) -> list[dict[str, Any]]:
        self._store.check_live_game_watchdog()
        rows = self._store._list_games_from_pg()
        games: dict[str, dict[str, Any]] = {}
        for game_id, game in self._store.games.items():
            if str(game.get("status") or "").lower() not in LIVE_GAME_TERMINAL_STATUSES:
                games[game_id] = game
        for game_id, session in self._store.live_sessions.items():
            games[game_id] = session.snapshot()
        rows.extend(
            self._store._game_list_row(game)
            for game in sorted(games.values(), key=lambda item: str(item.get("game_id", "")), reverse=True)
        )
        return sorted(rows, key=lambda item: str(item.get("log_time") or item.get("game_id") or ""), reverse=True)


__all__ = ["GameHistoryService", "GameReadGateway"]
