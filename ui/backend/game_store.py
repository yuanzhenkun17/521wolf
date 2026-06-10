"""Game loading, live-session, and history mixin for the UI backend store."""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections import Counter
from typing import Any

from fastapi import HTTPException

from app.util.json import to_jsonable
from app.util.time import beijing_now_iso
from app.lib.version import ReleaseStageNotAllowedError
from storage.game_store import delete_game_from_env
from storage.game_read_model import (
    GameReadRepository,
    death_target_ids,
    history_phase_key,
    history_phase_title,
    normalize_history_phase,
    row_history_phase,
    sheriff_id_after_log,
)
from storage.provider import storage_provider_from_env
from storage.public_events import public_events_only
from storage.runtime import GamePersistence
from ui.backend.constants import LOG_SOURCE_LABELS
from ui.backend.errors import domain_error_detail, release_stage_not_allowed_detail
from ui.backend.history_index import GameHistoryIndex, history_facets, source_counts
from ui.backend.live_game import (
    LIVE_GAME_HEARTBEAT_TIMEOUT_SECONDS,
    LIVE_GAME_TERMINAL_STATUSES,
    BroadcastEventSink,
    LiveGameSession,
    live_game_heartbeat_timed_out,
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
_MAX_PHASE_LOG_LIMIT = 1000
_MAX_PHASE_DECISION_LIMIT = 500
_DEFAULT_REPLAY_LIMIT = 500
_MAX_REPLAY_LIMIT = 2000


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _clean_role_versions(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(role): str(version)
        for role, version in value.items()
        if role is not None and version is not None and str(version) != ""
    }


def _source_phase_label(phase: Any) -> str | None:
    if not phase:
        return None
    text = str(phase)
    return {
        "training": "训练",
        "battle": "对战",
        "baseline": "基线",
        "candidate": "候选",
    }.get(text, text)


def _evidence_source_context(game: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config if isinstance(config, dict) else (game.get("config") if isinstance(game.get("config"), dict) else {})
    source = str(_first_present(game.get("log_source"), config.get("log_source"), "normal"))
    source_phase = _first_present(game.get("source_phase"), config.get("source_phase"))
    role_versions = _clean_role_versions(
        _first_present(
            game.get("role_versions"),
            config.get("role_versions"),
            game.get("role_skill_dirs"),
            config.get("role_skill_dirs"),
        )
    )
    return {
        "log_source": source,
        "log_source_label": _first_present(
            game.get("log_source_label"),
            config.get("log_source_label"),
            LOG_SOURCE_LABELS.get(source),
            "人机/玩家",
        ),
        "source_run_id": _first_present(game.get("source_run_id"), config.get("source_run_id")),
        "source_phase": source_phase,
        "source_phase_label": _first_present(
            game.get("source_phase_label"),
            config.get("source_phase_label"),
            _source_phase_label(source_phase),
        ),
        "seed": _first_present(game.get("seed"), config.get("seed")),
        "role_versions": role_versions,
    }


def _with_evidence_source_context(payload: dict[str, Any], source: dict[str, Any] | None = None) -> dict[str, Any]:
    context = _evidence_source_context(source or payload)
    payload["evidence_source"] = context
    for key in ("log_source", "log_source_label", "source_run_id", "source_phase", "source_phase_label", "seed"):
        if payload.get(key) is None or payload.get(key) == "":
            payload[key] = context[key]
    if not isinstance(payload.get("role_versions"), dict) or not payload.get("role_versions"):
        payload["role_versions"] = dict(context["role_versions"])
    return payload


def _paginate_history_rows(
    rows: list[dict[str, Any]],
    *,
    offset: int,
    limit: int | None,
    default_limit: int,
    max_limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    total = len(rows)
    try:
        safe_offset = max(0, int(offset or 0))
    except (TypeError, ValueError):
        safe_offset = 0
    try:
        safe_limit = int(limit) if limit is not None else default_limit
    except (TypeError, ValueError):
        safe_limit = default_limit
    safe_limit = max(1, min(safe_limit, max_limit))
    page = rows[safe_offset:safe_offset + safe_limit]
    return page, {
        "total": total,
        "offset": safe_offset,
        "limit": safe_limit,
        "returned": len(page),
        "has_more": safe_offset + len(page) < total,
    }


class _FanoutSink:
    def __init__(self, *sinks: Any) -> None:
        self._sinks = [sink for sink in sinks if sink is not None]

    def record_event(self, entry: Any) -> None:
        for sink in self._sinks:
            record = getattr(sink, "record_event", None)
            if callable(record):
                record(entry)

    def record_decision(self, decision: Any) -> None:
        for sink in self._sinks:
            record = getattr(sink, "record_decision", None)
            if callable(record):
                record(decision)


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

    def _wolf_read_lock(self) -> threading.RLock:
        lock = getattr(self, "_wolf_read_connection_lock", None)
        if lock is None:
            lock = threading.RLock()
            setattr(self, "_wolf_read_connection_lock", lock)
        return lock

    def _close_wolf_read_connection(self) -> None:
        with self._wolf_read_lock():
            conn = getattr(self, "_wolf_read_connection", None)
            if conn is None:
                return
            setattr(self, "_wolf_read_connection", None)
            close = getattr(conn, "close", None)
            if callable(close):
                close()

    def _open_wolf_read_connection(self) -> Any:
        conn = getattr(self, "_wolf_read_connection", None)
        if conn is not None and not getattr(conn, "closed", False):
            return conn
        conn = self._open_wolf_connection()
        setattr(self, "_wolf_read_connection", conn)
        return conn

    def _read_wolf_repository(self, read: Any) -> Any:
        with self._wolf_read_lock():
            conn = self._open_wolf_read_connection()
            try:
                result = read(GameReadRepository(conn))
                commit = getattr(conn, "commit", None)
                if callable(commit):
                    commit()
                return result
            except Exception:
                rollback = getattr(conn, "rollback", None)
                if callable(rollback):
                    rollback()
                self._close_wolf_read_connection()
                raise

    def _game_history_fingerprint(self) -> dict[str, Any]:
        return {
            "memory": self._game_history_memory_fingerprint(),
            "postgres": self._postgres_history_fingerprint(),
        }

    def _game_history_memory_fingerprint(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for game_id, game in self.games.items():
            items.append(self._game_history_memory_item(game_id, game))
        for game_id, session in self.live_sessions.items():
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

    def _game_history_memory_item(self, game_id: str, game: dict[str, Any]) -> dict[str, Any]:
        events = game.get("events") if isinstance(game.get("events"), list) else []
        decisions = game.get("decisions") if isinstance(game.get("decisions"), list) else []
        return {
            "game_id": str(game_id),
            "status": game.get("status"),
            "log_source": game.get("log_source"),
            "log_time": self._snapshot_log_time(game),
            "last_heartbeat_at": game.get("last_heartbeat_at"),
            "interrupted_at": game.get("interrupted_at"),
            "diagnostic_count": len(game.get("diagnostics") if isinstance(game.get("diagnostics"), list) else []),
            "event_count": len(events),
            "decision_count": len(decisions),
        }

    def _postgres_history_fingerprint(self) -> dict[str, Any]:
        try:
            return {
                "available": True,
                **self._read_wolf_repository(lambda repo: repo.history_fingerprint()),
            }
        except Exception as exc:  # noqa: BLE001 - history cache invalidation is best-effort.
            return {"available": False, "error": type(exc).__name__}

    def _open_wolf_connection(self) -> Any:
        return storage_provider_from_env(paths=self.paths).open_wolf_connection()

    def _load_game_from_pg(self, game_id: str) -> dict[str, Any] | None:
        return self._read_wolf_repository(lambda repo: repo.load_game_detail(game_id))

    def _load_game_history_shell_from_pg(self, game_id: str) -> dict[str, Any] | None:
        return self._read_wolf_repository(lambda repo: repo.load_game_history_shell(game_id))

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
        return self._read_wolf_repository(lambda repo: repo.load_game_phase_detail(
            game_id,
            day=day,
            phase=phase,
            log_offset=log_offset,
            log_limit=log_limit,
            decision_offset=decision_offset,
            decision_limit=decision_limit,
        ))

    def _load_game_flow_data_from_pg(self, game_id: str) -> dict[str, Any] | None:
        return self._read_wolf_repository(lambda repo: repo.load_game_flow_data(game_id))

    def _load_game_replay_from_pg(
        self,
        game_id: str,
        *,
        cursor: int = 0,
        limit: int | None = _DEFAULT_REPLAY_LIMIT,
    ) -> dict[str, Any] | None:
        return self._read_wolf_repository(lambda repo: repo.load_game_replay(game_id, cursor=cursor, limit=limit))

    def _load_game_review_from_pg(self, game_id: str) -> dict[str, Any] | None:
        return self._read_wolf_repository(lambda repo: repo.load_game_review(game_id))

    def _list_games_from_pg(self) -> list[dict[str, Any]]:
        return self._read_wolf_repository(lambda repo: repo.list_history_rows())

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

    def _game_list_row(self, game: dict[str, Any]) -> dict[str, Any]:
        config = game.get("config") if isinstance(game.get("config"), dict) else {}
        context = _evidence_source_context(game, config=config)
        source = str(context["log_source"])
        log_time = self._snapshot_log_time(game)
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

    async def start_game(self, request: GameStartRequest) -> dict[str, Any]:
        game_id = f"ui_{uuid.uuid4().hex[:12]}"
        skill_dir = self.skill_dir_for_request(request)
        return await self.start_live_game(game_id=game_id, request=request, skill_dir=skill_dir)

    async def start_live_game(self, *, game_id: str, request: GameStartRequest, skill_dir: str | None) -> dict[str, Any]:
        self._clear_game_deleted(game_id)
        human_player_id = request.human_player_id
        if human_player_id is not None and (human_player_id < 1 or human_player_id > request.player_count):
            raise HTTPException(status_code=400, detail="human_player_id must be a valid player seat")

        from dataclasses import replace

        from app.lib.game import create_agents, create_engine
        from app.lib.store import AgentDecisionRecorder
        from engine import STANDARD_12, GameLogger, assign_roles

        config = replace(STANDARD_12, max_days=request.max_days, enable_sheriff=request.enable_sheriff)
        roles = assign_roles(config, seed=request.seed)
        provider = storage_provider_from_env(paths=self.paths)
        persistence = GamePersistence(
            game_id=game_id,
            provider=provider,
            run_metadata={
                "mode": "play" if human_player_id is not None else "watch",
                "source_run_id": game_id,
                "ruleset_version": "werewolf_12p_v1",
            },
        )
        event_sink = BroadcastEventSink()
        db_event_sink = persistence.create_event_sink()
        db_decision_sink = persistence.create_decision_sink()
        recorder = AgentDecisionRecorder(sink=_FanoutSink(event_sink, db_decision_sink))
        agents = create_agents(
            roles,
            client=self.model_for_run(),
            decision_recorder=recorder,
            game_id=game_id,
            skill_dir=skill_dir,
            human_player_id=human_player_id,
            paths=self.paths,
        )
        logger = GameLogger(sink=_FanoutSink(event_sink, db_event_sink))
        engine = create_engine(
            roles,
            agents,
            seed=request.seed or 0,
            max_days=request.max_days,
            enable_sheriff=request.enable_sheriff,
            logger=logger,
        )
        session = LiveGameSession(
            game_id=game_id,
            request=request,
            engine=engine,
            recorder=recorder,
            human=agents.get(human_player_id) if human_player_id is not None else None,
            event_sink=event_sink,
            skill_dir=skill_dir,
        )
        setattr(session, "persistence", persistence)
        self._persist_live_session_start(session)
        self.live_sessions[game_id] = session
        session.task = asyncio.create_task(self.run_live_session(game_id))
        snapshot = session.snapshot()
        self.games[game_id] = snapshot
        self.invalidate_game_history_index()
        return snapshot

    async def run_live_session(self, game_id: str) -> None:
        session = self.live_sessions.get(game_id)
        if session is None:
            return
        try:
            await session.run()
            if self._is_game_deleted(game_id):
                return
            snapshot = session.snapshot()
            self.games[game_id] = snapshot
            self.persist_live_session(session, snapshot)
        finally:
            if self.live_sessions.get(game_id) is session and session.status in LIVE_GAME_TERMINAL_STATUSES:
                self.live_sessions.pop(game_id, None)

    def check_live_game_watchdog(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        resolved_timeout = (
            timeout_seconds if timeout_seconds is not None else self._live_game_heartbeat_timeout_seconds()
        )
        interrupted: list[dict[str, Any]] = []
        for game_id, session in list(self.live_sessions.items()):
            status = str(getattr(session, "status", "") or "").lower()
            if status in LIVE_GAME_TERMINAL_STATUSES:
                continue
            if not hasattr(session, "mark_interrupted"):
                continue
            if not live_game_heartbeat_timed_out(
                getattr(session, "last_heartbeat_at", None),
                timeout_seconds=resolved_timeout,
            ):
                continue
            if self._live_session_waiting_for_human_within_timeout(session):
                continue
            session.mark_interrupted(
                "live game heartbeat timed out",
                stage="live_game.watchdog",
                kind="live_game_interrupted",
                timeout_seconds=resolved_timeout,
            )
            snapshot = session.snapshot()
            self.games[game_id] = snapshot
            try:
                self.persist_live_session(session, snapshot)
            except Exception:
                # Keep the interrupted state visible even if final persistence fails.
                pass
            self.live_sessions.pop(game_id, None)
            interrupted.append(snapshot)
        if interrupted:
            self.invalidate_game_history_index()
        return interrupted

    def _live_session_waiting_for_human_within_timeout(self, session: Any) -> bool:
        human = getattr(session, "human", None)
        if human is None:
            return False
        try:
            is_waiting = bool(getattr(human, "is_waiting", False))
        except Exception:
            return False
        if not is_waiting:
            return False
        try:
            human_timeout = float(getattr(human, "timeout_seconds"))
        except (TypeError, ValueError):
            return False
        return not live_game_heartbeat_timed_out(
            getattr(session, "last_heartbeat_at", None),
            timeout_seconds=human_timeout,
        )

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
        self.check_live_game_watchdog()
        live = self.live_sessions.get(game_id)
        if live is not None:
            snapshot = live.snapshot()
            self.games[game_id] = snapshot
            return self._history_shell_from_snapshot(game_id, _player_view_snapshot(snapshot))
        cached = self.games.get(game_id)
        if cached is not None and (
            str(cached.get("status") or "").lower() not in LIVE_GAME_TERMINAL_STATUSES
            or isinstance(cached.get("logs") or cached.get("events"), list)
        ):
            return self._history_shell_from_snapshot(game_id, _player_view_snapshot(cached))
        return self._load_game_history_shell_from_pg(game_id)

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
        self.check_live_game_watchdog()
        live = self.live_sessions.get(game_id)
        if live is not None:
            snapshot = live.snapshot()
            self.games[game_id] = snapshot
            return self._phase_detail_from_snapshot(
                game_id,
                _player_view_snapshot(snapshot),
                day=day,
                phase=phase,
                log_offset=log_offset,
                log_limit=log_limit,
                decision_offset=decision_offset,
                decision_limit=decision_limit,
            )
        cached = self.games.get(game_id)
        if cached is not None and isinstance(cached.get("logs") or cached.get("events"), list):
            return self._phase_detail_from_snapshot(
                game_id,
                _player_view_snapshot(cached),
                day=day,
                phase=phase,
                log_offset=log_offset,
                log_limit=log_limit,
                decision_offset=decision_offset,
                decision_limit=decision_limit,
            )
        return self._load_game_phase_detail_from_pg(
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
        self.check_live_game_watchdog()
        live = self.live_sessions.get(game_id)
        if live is not None:
            snapshot = live.snapshot()
            self.games[game_id] = snapshot
            return self._replay_from_snapshot(game_id, _player_view_snapshot(snapshot), cursor=cursor, limit=limit)
        cached = self.games.get(game_id)
        if cached is not None and isinstance(cached.get("logs") or cached.get("events"), list):
            return self._replay_from_snapshot(game_id, _player_view_snapshot(cached), cursor=cursor, limit=limit)
        return self._load_game_replay_from_pg(game_id, cursor=cursor, limit=limit)

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
        logs = [_normalize_event(log) for log in (snapshot.get("logs") or snapshot.get("events") or []) if isinstance(log, dict)]
        decisions = [
            _normalize_decision(decision, index)
            for index, decision in enumerate(snapshot.get("decisions") or [], start=1)
            if isinstance(decision, dict)
        ]
        phases = self._history_phase_summaries_from_snapshot(snapshot, logs, decisions)
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
            seat = self._safe_int(player.get("seat", player.get("id")), default=0)
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

    def _history_phase_summaries_from_snapshot(
        self,
        snapshot: dict[str, Any],
        logs: list[dict[str, Any]],
        decisions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        phase_order = {
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

        def day_value(value: Any) -> int:
            return self._safe_int(value, default=1) or 1

        def sort_value(day: Any, phase: Any) -> int:
            normalized_phase = normalize_history_phase(phase)
            return day_value(day) * 100 + phase_order.get(normalized_phase, len(phase_order))

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
            event_index = self._safe_int(log.get("idx", log.get("index", log.get("sequence"))), default=index)
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
            phase["has_votes"] = bool(phase["has_votes"] or action in {"vote", "exile", "exile_vote", "pk_vote", "sheriff_vote"})
        if snapshot.get("winner"):
            max_day = max([day_value(snapshot.get("day")), *[day_value(log.get("day")) for log in logs], 1])
            ensure(phases, max_day, "ended")
        result = sorted(phases.values(), key=lambda item: (item["sort"], item["key"]))
        self._attach_history_state_to_phase_summaries(result, snapshot, logs, has_authoritative_deaths, sort_value)
        return result

    def _attach_history_state_to_phase_summaries(
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
            player_id = self._safe_int(player.get("id", player.get("seat")), default=0)
            if player_id > 0:
                alive[player_id] = True
        sheriff_id: int | None = None
        sorted_logs = sorted(
            logs,
            key=lambda log: (
                sort_value(log.get("day"), row_history_phase(log)),
                self._safe_int(log.get("idx", log.get("index", log.get("sequence"))), default=0),
            ),
        )
        log_index = 0
        for phase in phases:
            phase_sort = sort_value(phase.get("day"), phase.get("phase"))
            phase_last_index = phase.get("last_event_index")
            while log_index < len(sorted_logs):
                log = sorted_logs[log_index]
                log_sort = sort_value(log.get("day"), row_history_phase(log))
                event_index = self._safe_int(log.get("idx", log.get("index", log.get("sequence"))), default=0)
                if log_sort > phase_sort or (log_sort == phase_sort and phase_last_index is not None and event_index > phase_last_index):
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
        target_day = self._safe_int(day, default=1) or 1
        target_phase = normalize_history_phase(phase)
        all_logs = [
            _normalize_event(log)
            for log in (snapshot.get("logs") or snapshot.get("events") or [])
            if isinstance(log, dict)
            and self._safe_int(log.get("day"), default=1) == target_day
            and row_history_phase(log, target_phase) == target_phase
        ]
        all_decisions = [
            _normalize_decision(decision, index)
            for index, decision in enumerate(snapshot.get("decisions") or [], start=1)
            if isinstance(decision, dict)
            and self._safe_int(decision.get("day"), default=1) == target_day
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
                "vote_count": sum(1 for decision in all_decisions if str(decision.get("action") or "") in {"vote", "exile", "exile_vote", "pk_vote", "sheriff_vote"}),
                "death_count": sum(1 for log in all_logs if death_target_ids(log, True)),
            },
            "pagination": {
                "logs": log_pagination,
                "decisions": decision_pagination,
            },
        }

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
        events = [_normalize_event(log) for log in (snapshot.get("logs") or snapshot.get("events") or []) if isinstance(log, dict)]
        all_decisions = [
            _normalize_decision(decision, index)
            for index, decision in enumerate(snapshot.get("decisions") or [], start=1)
            if isinstance(decision, dict)
        ]
        safe_cursor = max(0, self._safe_int(cursor, default=0))
        safe_limit = max(1, min(self._safe_int(limit, default=_DEFAULT_REPLAY_LIMIT), _MAX_REPLAY_LIMIT))
        page_events = events[safe_cursor:safe_cursor + safe_limit]
        next_cursor = safe_cursor + len(page_events)
        has_more = next_cursor < len(events)
        allowed_pairs = {
            (self._safe_int(event.get("day"), default=1) or 1, row_history_phase(event))
            for event in page_events
        }
        decisions = [
            decision for decision in all_decisions
            if (self._safe_int(decision.get("day"), default=1) or 1, row_history_phase(decision)) in allowed_pairs
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

    def _build_game_history_rows(self) -> list[dict[str, Any]]:
        self.check_live_game_watchdog()
        rows = self._list_games_from_pg()
        games: dict[str, dict[str, Any]] = {}
        for game_id, game in self.games.items():
            if str(game.get("status") or "").lower() not in LIVE_GAME_TERMINAL_STATUSES:
                games[game_id] = game
        for game_id, session in self.live_sessions.items():
            games[game_id] = session.snapshot()
        rows.extend(
            self._game_list_row(game)
            for game in sorted(games.values(), key=lambda item: str(item.get("game_id", "")), reverse=True)
        )
        return sorted(rows, key=lambda item: str(item.get("log_time") or item.get("game_id") or ""), reverse=True)

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
        live = self.live_sessions.get(game_id)
        if live is not None:
            live.cancel()
            snapshot = live.snapshot()
            self.games[game_id] = snapshot
            if live.task is None or live.task.done():
                self.persist_live_session(live, snapshot)
            return snapshot
        game = self.get_game(game_id)
        if game is None:
            now = beijing_now_iso()
            return {
                "game_id": game_id,
                "status": "cancelled",
                "stop_requested": True,
                "cancelled": True,
                "interrupted": False,
                "failed": False,
                "cancelled_at": now,
                "finished_at": now,
                "error": "cancelled",
                "players": [],
                "logs": [],
                "decisions": [],
            }
        now = beijing_now_iso()
        stopped = {
            **game,
            "status": "cancelled",
            "stop_requested": True,
            "cancelled": True,
            "interrupted": False,
            "failed": False,
            "cancelled_at": game.get("cancelled_at") or now,
            "finished_at": game.get("finished_at") or now,
            "error": game.get("error") or "cancelled",
        }
        self.games[game_id] = stopped
        self._persist_snapshot_to_pg(stopped)
        return stopped

    def delete_game(self, game_id: str, *, force: bool = False) -> dict[str, Any]:
        self.check_live_game_watchdog()
        live = self.live_sessions.get(game_id)
        game = live.snapshot() if live is not None else self.games.get(game_id)
        if game is None:
            game = self._load_game_from_pg(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")

        log_source = self._snapshot_log_source(game)
        if log_source != "normal" and not force:
            raise HTTPException(
                status_code=409,
                detail=f"{log_source} game requires force delete",
            )

        if live is not None:
            self._mark_game_deleted(game_id)
            live.cancel()
            self.live_sessions.pop(game_id, None)
            persistence = getattr(live, "persistence", None)
            close = getattr(persistence, "close", None)
            if callable(close):
                close()

        self._delete_game_from_pg(game_id)
        self._mark_game_deleted(game_id)
        self.games.pop(game_id, None)
        self.invalidate_game_history_index()
        return {
            "game_id": game_id,
            "deleted": True,
            "log_source": log_source,
            "force": bool(force),
        }

    def _snapshot_log_source(self, snapshot: dict[str, Any]) -> str:
        config = snapshot.get("config") if isinstance(snapshot.get("config"), dict) else {}
        source = snapshot.get("log_source") or config.get("log_source") or "normal"
        return str(source or "normal").lower()

    def _delete_game_from_pg(self, game_id: str) -> None:
        delete_game_from_env(game_id, paths=self.paths)

    def _persist_live_session_start(self, session: LiveGameSession) -> None:
        self._persist_snapshot_to_pg(
            session.snapshot(),
            persistence=getattr(session, "persistence", None),
        )

    def persist_live_session(self, session: LiveGameSession, snapshot: dict[str, Any] | None = None) -> None:
        snapshot = snapshot or session.snapshot()
        terminal = str(snapshot.get("status") or session.status or "").lower() in LIVE_GAME_TERMINAL_STATUSES
        if terminal:
            with session.persist_lock:
                if session.files_written:
                    return
                session.files_written = True
        try:
            self._persist_snapshot_to_pg(
                snapshot,
                persistence=getattr(session, "persistence", None),
            )
            if terminal:
                persistence = getattr(session, "persistence", None)
                close = getattr(persistence, "close", None)
                if callable(close):
                    close()
        except Exception:
            if terminal:
                with session.persist_lock:
                    session.files_written = False
            raise
        finally:
            self.invalidate_game_history_index()

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


