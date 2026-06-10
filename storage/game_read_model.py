"""PostgreSQL-backed UI read model for game history and details."""

from __future__ import annotations

from typing import Any, TypeAlias

from storage.game_history_rules import (
    AUTHORITATIVE_DEATH_EVENTS as _AUTHORITATIVE_DEATH_EVENTS,
    NIGHT_OUTCOME_EVENTS as _NIGHT_OUTCOME_EVENTS,
    SHELL_STATE_EVENT_TYPES as _SHELL_STATE_EVENT_TYPES,
    VOTE_ACTION_TYPES as _VOTE_ACTION_TYPES,
    death_target_ids,
    empty_phase_summary as _empty_phase_summary,
    history_phase_key,
    history_phase_title,
    normalize_history_day as _normalize_history_day,
    normalize_history_phase,
    phase_query_candidates as _phase_query_candidates,
    phase_sort as _phase_sort,
    replay_window_phase_filters as _replay_window_phase_filters,
    row_history_phase,
    row_type as _row_type,
    sheriff_id_after_log,
)
from storage.game_read_payloads import (
    EVOLUTION_RUN_TYPES,
    bool_value as _bool,
    decision_row as _decision_row,
    default_manifest as _default_manifest,
    event_row as _event_row,
    evidence_source_context as _evidence_source_context,
    first_text as _first_text,
    first_value as _first_value,
    flow_decision_row as _flow_decision_row,
    history_final_state as _history_final_state,
    int_or_none as _int_or_none,
    json_array as _json_array,
    json_object as _json_object,
    json_object_list as _json_object_list,
    normalize_bundle_rows as _normalize_bundle_rows,
    paginate_rows as _paginate_rows,
    player_row as _player_row,
    row_dict as _row_dict,
)
from storage.public_events import public_events_only
from storage.shared.database import StorageConnection


_BUNDLE_UNAVAILABLE = object()
_DETAIL_BUNDLE_FIELDS = frozenset({"__event_rows", "__decision_rows", "__player_rows"})
_SHELL_BUNDLE_FIELDS = frozenset({
    "__player_rows",
    "__event_phase_rows",
    "__decision_phase_rows",
    "__state_event_rows",
})
_DECISION_DETAIL_ORDER = "created_at, id"
_DEFAULT_PHASE_LOG_LIMIT = 300
_DEFAULT_PHASE_DECISION_LIMIT = 200
_MAX_PHASE_LOG_LIMIT = 1000
_MAX_PHASE_DECISION_LIMIT = 500
_DEFAULT_REPLAY_LIMIT = 500
_MAX_REPLAY_LIMIT = 2000
_DetailRows: TypeAlias = tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]


class GameReadRepository:
    """Read UI-facing game data from PostgreSQL tables only."""

    def __init__(self, conn: StorageConnection) -> None:
        self._conn = conn

    def history_fingerprint(self) -> dict[str, Any]:
        return {
            "games": self._aggregate_fingerprint("games", "started_at", "finished_at"),
        }

    def list_history_rows(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT
                g.id,
                g.seed,
                g.config,
                g.winner,
                g.started_at,
                g.finished_at,
                g.total_rounds,
                g.run_type,
                g.mode,
                g.source_run_id,
                g.final_state ->> 'status' AS final_status,
                g.final_state ->> 'stop_requested' AS final_stop_requested,
                g.final_state ->> 'cancelled' AS final_cancelled,
                g.final_state ->> 'interrupted' AS final_interrupted,
                g.final_state ->> 'failed' AS final_failed,
                g.final_state ->> 'cancelled_at' AS final_cancelled_at,
                g.final_state ->> 'interrupted_at' AS final_interrupted_at,
                g.final_state ->> 'last_heartbeat_at' AS final_last_heartbeat_at,
                g.final_state ->> 'started_at' AS final_started_at,
                g.final_state ->> 'finished_at' AS final_finished_at,
                g.final_state ->> 'source_phase' AS final_source_phase,
                g.final_state ->> 'error' AS final_error,
                g.final_state -> 'diagnostics' AS final_diagnostics,
                COALESCE(ev.event_count, 0) AS event_count,
                COALESCE(dec.decision_count, 0) AS decision_count,
                COALESCE(pl.player_count, 0) AS stored_player_count,
                ev.latest_day AS latest_day,
                ev.latest_phase AS latest_phase
            FROM games g
            LEFT JOIN (
                SELECT game_id, COUNT(*) AS event_count, MAX(day) AS latest_day, MAX(phase) AS latest_phase
                FROM game_events
                GROUP BY game_id
            ) ev ON ev.game_id = g.id
            LEFT JOIN (
                SELECT game_id, COUNT(*) AS decision_count
                FROM decisions
                GROUP BY game_id
            ) dec ON dec.game_id = g.id
            LEFT JOIN (
                SELECT game_id, COUNT(*) AS player_count
                FROM players
                GROUP BY game_id
            ) pl ON pl.game_id = g.id
            ORDER BY COALESCE(g.finished_at, g.started_at) DESC, g.id DESC
            """
        ).fetchall()
        return [self._history_row(_row_dict(row)) for row in rows]

    def load_game_detail(self, game_id: str) -> dict[str, Any] | None:
        if _supports_detail_bundle(self._conn):
            bundled = self._load_game_detail_bundle(game_id)
            if bundled is not _BUNDLE_UNAVAILABLE:
                if bundled is None:
                    return None
                game, events, decisions, players = bundled
                return self._detail_from_rows(game_id, game, events, decisions, players)
        return self._load_game_detail_legacy(game_id)

    def load_game_history_shell(self, game_id: str) -> dict[str, Any] | None:
        if _supports_detail_bundle(self._conn):
            bundled = self._load_game_history_shell_bundle(game_id)
            if bundled is not _BUNDLE_UNAVAILABLE:
                return bundled
        return self._load_game_history_shell_legacy(game_id)

    def _load_game_history_shell_bundle(self, game_id: str) -> dict[str, Any] | None | object:
        state_type_sql = ", ".join(f"'{event_type}'" for event_type in _SHELL_STATE_EVENT_TYPES)
        try:
            row = self._conn.execute(
                f"""
                SELECT
                    g.*,
                    COALESCE(pl.rows, '[]'::jsonb) AS __player_rows,
                    COALESCE(ev.rows, '[]'::jsonb) AS __event_phase_rows,
                    COALESCE(dec.rows, '[]'::jsonb) AS __decision_phase_rows,
                    COALESCE(state_ev.rows, '[]'::jsonb) AS __state_event_rows
                FROM games g
                LEFT JOIN LATERAL (
                    SELECT jsonb_agg(to_jsonb(p) ORDER BY p.seat) AS rows
                    FROM players p
                    WHERE p.game_id = g.id
                ) pl ON TRUE
                LEFT JOIN LATERAL (
                    SELECT jsonb_agg(to_jsonb(x) ORDER BY x.day, x.phase, x.event_type) AS rows
                    FROM (
                        SELECT
                            e.day,
                            e.phase,
                            e.event_type,
                            COUNT(*) AS log_count,
                            MIN(e.idx) AS first_event_index,
                            MAX(e.idx) AS last_event_index
                        FROM game_events e
                        WHERE e.game_id = g.id
                        GROUP BY e.day, e.phase, e.event_type
                    ) x
                ) ev ON TRUE
                LEFT JOIN LATERAL (
                    SELECT jsonb_agg(to_jsonb(x) ORDER BY x.day, x.phase, x.action_type) AS rows
                    FROM (
                        SELECT
                            d.day,
                            d.phase,
                            d.action_type,
                            COUNT(*) AS decision_count
                        FROM decisions d
                        WHERE d.game_id = g.id
                        GROUP BY d.day, d.phase, d.action_type
                    ) x
                ) dec ON TRUE
                LEFT JOIN LATERAL (
                    SELECT jsonb_agg(to_jsonb(e) ORDER BY e.idx, e.id) AS rows
                    FROM game_events e
                    WHERE e.game_id = g.id
                      AND e.event_type IN ({state_type_sql})
                ) state_ev ON TRUE
                WHERE g.id = ?
                """,
                (game_id,),
            ).fetchone()
        except Exception:  # noqa: BLE001 - keep older fake/test connections on legacy path
            return _BUNDLE_UNAVAILABLE
        if row is None:
            return None
        raw = _row_dict(row)
        game = {key: value for key, value in raw.items() if key not in _SHELL_BUNDLE_FIELDS}
        return self._history_shell_from_rows(
            game_id,
            game,
            _json_object_list(raw.get("__event_phase_rows")),
            _json_object_list(raw.get("__decision_phase_rows")),
            _json_object_list(raw.get("__player_rows")),
            _normalize_bundle_rows(_json_object_list(raw.get("__state_event_rows")), self._storage_timezone()),
        )

    def _load_game_history_shell_legacy(self, game_id: str) -> dict[str, Any] | None:
        game_row = self._conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        if game_row is None:
            return None
        placeholders = ", ".join("?" for _ in _SHELL_STATE_EVENT_TYPES)
        game = _row_dict(game_row)
        players = [_row_dict(row) for row in self._conn.execute(
            "SELECT * FROM players WHERE game_id = ? ORDER BY seat",
            (game_id,),
        ).fetchall()]
        event_phase_rows = [_row_dict(row) for row in self._conn.execute(
            """
            SELECT day, phase, event_type, COUNT(*) AS log_count,
                   MIN(idx) AS first_event_index, MAX(idx) AS last_event_index
            FROM game_events
            WHERE game_id = ?
            GROUP BY day, phase, event_type
            """,
            (game_id,),
        ).fetchall()]
        decision_phase_rows = [_row_dict(row) for row in self._conn.execute(
            """
            SELECT day, phase, action_type, COUNT(*) AS decision_count
            FROM decisions
            WHERE game_id = ?
            GROUP BY day, phase, action_type
            """,
            (game_id,),
        ).fetchall()]
        state_events = [_row_dict(row) for row in self._conn.execute(
            f"""
            SELECT id, game_id, idx, day, phase, event_type, public, actor, target, payload, created_at
            FROM game_events
            WHERE game_id = ? AND event_type IN ({placeholders})
            ORDER BY idx, id
            """,
            (game_id, *_SHELL_STATE_EVENT_TYPES),
        ).fetchall()]
        return self._history_shell_from_rows(game_id, game, event_phase_rows, decision_phase_rows, players, state_events)

    def load_game_phase_detail(
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
        game_row = self._conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        if game_row is None:
            return None
        normalized_day = _normalize_history_day(day)
        normalized_phase = normalize_history_phase(phase)
        raw_phases = sorted(_phase_query_candidates(normalized_phase))
        placeholders = ", ".join("?" for _ in raw_phases)
        event_rows = [_row_dict(row) for row in self._conn.execute(
            f"""
            SELECT *
            FROM game_events
            WHERE game_id = ? AND day = ? AND phase IN ({placeholders})
            ORDER BY idx, id
            """,
            (game_id, normalized_day, *raw_phases),
        ).fetchall()]
        decision_rows = [_row_dict(row) for row in self._conn.execute(
            f"""
            SELECT *
            FROM decisions
            WHERE game_id = ? AND day = ? AND phase IN ({placeholders})
            ORDER BY {_DECISION_DETAIL_ORDER}
            """,
            (game_id, normalized_day, *raw_phases),
        ).fetchall()]
        event_rows = [
            row for row in event_rows
            if row_history_phase(row, fallback=normalized_phase) == normalized_phase
        ]
        decision_rows = [
            row for row in decision_rows
            if row_history_phase(row, fallback=normalized_phase) == normalized_phase
        ]
        all_logs = [_event_row(row) for row in event_rows]
        all_decisions = [_decision_row(row) for row in decision_rows]
        logs, log_pagination = _paginate_rows(
            all_logs,
            offset=log_offset,
            limit=log_limit,
            default_limit=_DEFAULT_PHASE_LOG_LIMIT,
            max_limit=_MAX_PHASE_LOG_LIMIT,
        )
        decisions, decision_pagination = _paginate_rows(
            all_decisions,
            offset=decision_offset,
            limit=decision_limit,
            default_limit=_DEFAULT_PHASE_DECISION_LIMIT,
            max_limit=_MAX_PHASE_DECISION_LIMIT,
        )
        return {
            "game_id": game_id,
            "detail_view": "phase-detail",
            "phase_key": history_phase_key(normalized_day, normalized_phase),
            "day": normalized_day,
            "phase": normalized_phase,
            "title": history_phase_title(normalized_day, normalized_phase),
            "logs": logs,
            "decisions": decisions,
            "summary": {
                "log_count": len(all_logs),
                "decision_count": len(all_decisions),
                "vote_count": sum(1 for decision in all_decisions if str(decision.get("action") or "") in _VOTE_ACTION_TYPES),
                "death_count": sum(1 for log in all_logs if death_target_ids(log, True)),
            },
            "pagination": {
                "logs": log_pagination,
                "decisions": decision_pagination,
            },
        }

    def load_game_flow_data(self, game_id: str) -> dict[str, Any] | None:
        game_row = self._conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        if game_row is None:
            return None
        players = [_player_row(_row_dict(row)) for row in self._conn.execute(
            "SELECT * FROM players WHERE game_id = ? ORDER BY seat",
            (game_id,),
        ).fetchall()]
        decision_rows = [_row_dict(row) for row in self._conn.execute(
            """
            SELECT id, game_id, player_id, seat, role, day, phase, action_type,
                   selected_target, selected_choice, public_text, private_reasoning,
                   confidence, candidates, source, policy_adjustments, errors, created_at
            FROM decisions
            WHERE game_id = ?
            ORDER BY created_at, id
            """,
            (game_id,),
        ).fetchall()]
        decisions = [_flow_decision_row(_decision_row(row)) for row in decision_rows]
        return {
            "game_id": game_id,
            "detail_view": "flow-data",
            "players": players,
            "decisions": decisions,
            "decision_count": len(decisions),
        }

    def load_game_replay(
        self,
        game_id: str,
        *,
        cursor: int = 0,
        limit: int | None = _DEFAULT_REPLAY_LIMIT,
    ) -> dict[str, Any] | None:
        game_row = self._conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        if game_row is None:
            return None
        game = _row_dict(game_row)
        config = _json_object(game.get("config"))
        final_state = _json_object(game.get("final_state"))
        source_context = _evidence_source_context(game, config, final_state)
        safe_cursor = max(0, _int_or_none(cursor) or 0)
        safe_limit = _int_or_none(limit)
        if safe_limit is None:
            safe_limit = _DEFAULT_REPLAY_LIMIT
        safe_limit = max(1, min(safe_limit, _MAX_REPLAY_LIMIT))
        players = [_player_row(_row_dict(row)) for row in self._conn.execute(
            "SELECT * FROM players WHERE game_id = ? ORDER BY seat",
            (game_id,),
        ).fetchall()]
        total_row = self._conn.execute(
            "SELECT COUNT(*) AS total FROM game_events WHERE game_id = ?",
            (game_id,),
        ).fetchone()
        event_total = _int_or_none(_row_dict(total_row).get("total") if total_row is not None else 0) or 0
        event_rows = [_row_dict(row) for row in self._conn.execute(
            "SELECT * FROM game_events WHERE game_id = ? ORDER BY idx, id LIMIT ? OFFSET ?",
            (game_id, safe_limit, safe_cursor),
        ).fetchall()]
        next_cursor = safe_cursor + len(event_rows)
        has_more = next_cursor < event_total
        window_filters = _replay_window_phase_filters(event_rows)
        if window_filters:
            decision_clauses = " OR ".join(
                "(day = ? AND phase IN (" + ", ".join("?" for _ in item["raw_phases"]) + "))"
                for item in window_filters
            )
            decision_parameters: list[Any] = []
            allowed_pairs: set[tuple[int, str]] = set()
            for item in window_filters:
                decision_parameters.append(item["day"])
                decision_parameters.extend(item["raw_phases"])
                allowed_pairs.update((item["day"], phase) for phase in item["normalized_phases"])
            decision_rows = [_row_dict(row) for row in self._conn.execute(
                "SELECT * FROM decisions WHERE game_id = ? AND ("
                + decision_clauses
                + f") ORDER BY {_DECISION_DETAIL_ORDER}",
                (game_id, *decision_parameters),
            ).fetchall()]
            decision_rows = [
                row for row in decision_rows
                if (_normalize_history_day(row.get("day")), row_history_phase(row)) in allowed_pairs
            ]
        else:
            decision_rows = []
        events = [_event_row(row) for row in event_rows]
        decisions = [_decision_row(row) for row in decision_rows]
        return {
            "game_id": game_id,
            "detail_view": "replay",
            "cursor": safe_cursor,
            "limit": safe_limit,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "event_count": event_total,
            "decision_count": len(decisions),
            "players": players,
            "log_source": source_context["log_source"],
            "log_source_label": source_context["log_source_label"],
            "source_run_id": source_context["source_run_id"],
            "source_phase": source_context["source_phase"],
            "source_phase_label": source_context["source_phase_label"],
            "seed": source_context["seed"],
            "role_versions": dict(source_context["role_versions"]),
            "evidence_source": source_context,
            "events": events,
            "logs": events,
            "decisions": decisions,
            "winner": game.get("winner"),
            "status": self._status_for_game(game, final_state),
        }

    def _load_game_detail_bundle(
        self,
        game_id: str,
    ) -> _DetailRows | None | object:
        try:
            row = self._conn.execute(
                """
                SELECT
                    g.*,
                    COALESCE(ev.rows, '[]'::jsonb) AS __event_rows,
                    COALESCE(dec.rows, '[]'::jsonb) AS __decision_rows,
                    COALESCE(pl.rows, '[]'::jsonb) AS __player_rows
                FROM games g
                LEFT JOIN LATERAL (
                    SELECT jsonb_agg(to_jsonb(e) ORDER BY e.idx, e.id) AS rows
                    FROM game_events e
                    WHERE e.game_id = g.id
                ) ev ON TRUE
                LEFT JOIN LATERAL (
                    SELECT jsonb_agg(to_jsonb(d) ORDER BY d.created_at, d.id) AS rows
                    FROM decisions d
                    WHERE d.game_id = g.id
                ) dec ON TRUE
                LEFT JOIN LATERAL (
                    SELECT jsonb_agg(to_jsonb(p) ORDER BY p.seat) AS rows
                    FROM players p
                    WHERE p.game_id = g.id
                ) pl ON TRUE
                WHERE g.id = ?
                """,
                (game_id,),
            ).fetchone()
        except Exception:  # noqa: BLE001 - older test/fake connections may not implement PostgreSQL JSON bundle SQL
            return _BUNDLE_UNAVAILABLE
        if row is None:
            return None
        raw = _row_dict(row)
        game = {key: value for key, value in raw.items() if key not in _DETAIL_BUNDLE_FIELDS}
        return (
            game,
            _normalize_bundle_rows(_json_object_list(raw.get("__event_rows")), self._storage_timezone()),
            _normalize_bundle_rows(_json_object_list(raw.get("__decision_rows")), self._storage_timezone()),
            _json_object_list(raw.get("__player_rows")),
        )

    def _storage_timezone(self) -> str:
        return str(getattr(self._conn, "storage_timezone", "Asia/Shanghai") or "Asia/Shanghai")

    def _load_game_detail_legacy(self, game_id: str) -> dict[str, Any] | None:
        game_row = self._conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        if game_row is None:
            return None
        game = _row_dict(game_row)
        events = [_row_dict(row) for row in self._conn.execute(
            "SELECT * FROM game_events WHERE game_id = ? ORDER BY idx, id",
            (game_id,),
        ).fetchall()]
        decisions = [_row_dict(row) for row in self._conn.execute(
            "SELECT * FROM decisions WHERE game_id = ? "
            f"ORDER BY {_DECISION_DETAIL_ORDER}",
            (game_id,),
        ).fetchall()]
        players = [_row_dict(row) for row in self._conn.execute(
            "SELECT * FROM players WHERE game_id = ? ORDER BY seat",
            (game_id,),
        ).fetchall()]
        return self._detail_from_rows(game_id, game, events, decisions, players)

    def _detail_from_rows(
        self,
        game_id: str,
        game: dict[str, Any],
        event_rows: list[dict[str, Any]],
        decision_rows: list[dict[str, Any]],
        player_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        events = [_event_row(row) for row in event_rows]
        decisions = [_decision_row(row) for row in decision_rows]
        players = [_player_row(row) for row in player_rows]
        config = _json_object(game.get("config"))
        final_state = _json_object(game.get("final_state"))
        public_events = public_events_only(_json_array(game.get("public_events")))
        source_context = _evidence_source_context(game, config, final_state)
        source = str(source_context["log_source"])
        log_time = _first_text(
            final_state.get("finished_at"),
            game.get("finished_at"),
            final_state.get("started_at"),
            game.get("started_at"),
            final_state.get("last_heartbeat_at"),
            config.get("log_time"),
        )
        status = self._status_for_game(game, final_state)
        diagnostics = _json_array(_first_value(final_state.get("diagnostics"), game.get("diagnostics")))
        review = _json_object(final_state.get("review"))
        manifest = _json_object(_first_value(final_state.get("manifest"), game.get("manifest")))

        role_map = {int(player["seat"]): str(player.get("role") or "") for player in players if player.get("seat") is not None}
        result_events = events or public_events
        return {
            "game_id": str(game.get("id") or game_id),
            "log_name": _first_text(game.get("log_name"), config.get("log_name"), game.get("id"), game_id),
            "source_game_id": _first_text(game.get("source_game_id"), config.get("source_game_id"), game.get("id"), game_id),
            "log_source": source,
            "log_source_label": source_context["log_source_label"],
            "source_run_id": source_context["source_run_id"],
            "source_phase": source_context["source_phase"],
            "source_phase_label": source_context["source_phase_label"],
            "role_versions": dict(source_context["role_versions"]),
            "evidence_source": source_context,
            "status": status,
            "stop_requested": _bool(_first_value(final_state.get("stop_requested"), game.get("stop_requested")), False),
            "cancelled": _bool(_first_value(final_state.get("cancelled"), game.get("cancelled")), status == "cancelled"),
            "interrupted": _bool(_first_value(final_state.get("interrupted"), game.get("interrupted")), status == "interrupted"),
            "failed": _bool(_first_value(final_state.get("failed"), game.get("failed")), status == "failed"),
            "cancelled_at": _first_text(final_state.get("cancelled_at"), game.get("cancelled_at")),
            "interrupted_at": _first_text(final_state.get("interrupted_at"), game.get("interrupted_at")),
            "last_heartbeat_at": _first_text(final_state.get("last_heartbeat_at"), game.get("last_heartbeat_at")),
            "winner": game.get("winner"),
            "seed": game.get("seed"),
            "started_at": _first_text(game.get("started_at"), final_state.get("started_at"), config.get("started_at")),
            "finished_at": _first_text(game.get("finished_at"), final_state.get("finished_at"), config.get("finished_at")),
            "log_time": log_time,
            "max_days": _int_or_none(_first_value(game.get("max_days"), config.get("max_days"))),
            "enable_sheriff": _bool(_first_value(game.get("enable_sheriff"), config.get("enable_sheriff")), True),
            "skill_dir": _first_text(game.get("skill_dir"), config.get("skill_dir")),
            "role_skill_dirs": _json_object(_first_value(game.get("role_skill_dirs"), config.get("role_skill_dirs"), config.get("role_versions"))),
            "human_player_id": _int_or_none(_first_value(game.get("human_player_id"), config.get("human_player_id"))),
            "player_count": _int_or_none(_first_value(game.get("player_count"), len(players) or config.get("player_count"))) or 12,
            "player_roles": role_map,
            "players": players,
            "events": result_events,
            "logs": result_events,
            "decisions": decisions,
            "review": review if review else None,
            "diagnostics": diagnostics,
            "manifest": manifest if manifest else _default_manifest(game_id, status),
            "config": config,
            "error": _first_text(final_state.get("error"), game.get("error")),
        }

    def _history_shell_from_rows(
        self,
        game_id: str,
        game: dict[str, Any],
        event_phase_rows: list[dict[str, Any]],
        decision_phase_rows: list[dict[str, Any]],
        player_rows: list[dict[str, Any]],
        state_event_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        players = [_player_row(row) for row in player_rows]
        config = _json_object(game.get("config"))
        final_state = _json_object(game.get("final_state"))
        source_context = _evidence_source_context(game, config, final_state)
        source = str(source_context["log_source"])
        status = self._status_for_game(game, final_state)
        diagnostics = _json_array(_first_value(final_state.get("diagnostics"), game.get("diagnostics")))
        manifest = _json_object(_first_value(final_state.get("manifest"), game.get("manifest")))
        role_map = {int(player["seat"]): str(player.get("role") or "") for player in players if player.get("seat") is not None}
        phase_map = self._history_phase_map(event_phase_rows, decision_phase_rows)
        phases = sorted(
            phase_map.values(),
            key=lambda item: (
                _phase_sort(_normalize_history_day(item.get("day")), normalize_history_phase(item.get("phase"))),
                str(item.get("key") or ""),
            ),
        )
        if not phases:
            fallback_phase = normalize_history_phase(_first_text(final_state.get("phase"), game.get("phase"), "setup"))
            fallback_day = _normalize_history_day(_first_value(final_state.get("day"), game.get("total_rounds"), 1))
            phases = [_empty_phase_summary(fallback_day, fallback_phase)]
        self._attach_history_phase_state(phases, players, state_event_rows)
        default_phase_key = _first_text(phases[0].get("key")) or history_phase_key(1, "setup")
        latest = phases[-1] if phases else {}
        log_time = _first_text(
            final_state.get("finished_at"),
            game.get("finished_at"),
            final_state.get("started_at"),
            game.get("started_at"),
            final_state.get("last_heartbeat_at"),
            config.get("log_time"),
        )
        event_count = sum(_int_or_none(row.get("log_count")) or 0 for row in event_phase_rows)
        decision_count = sum(_int_or_none(row.get("decision_count")) or 0 for row in decision_phase_rows)
        return {
            "game_id": str(game.get("id") or game_id),
            "detail_view": "history-shell",
            "log_name": _first_text(game.get("log_name"), config.get("log_name"), game.get("id"), game_id),
            "source_game_id": _first_text(game.get("source_game_id"), config.get("source_game_id"), game.get("id"), game_id),
            "log_source": source,
            "log_source_label": source_context["log_source_label"],
            "source_run_id": source_context["source_run_id"],
            "source_phase": source_context["source_phase"],
            "source_phase_label": source_context["source_phase_label"],
            "role_versions": dict(source_context["role_versions"]),
            "evidence_source": source_context,
            "status": status,
            "stop_requested": _bool(_first_value(final_state.get("stop_requested"), game.get("stop_requested")), False),
            "cancelled": _bool(_first_value(final_state.get("cancelled"), game.get("cancelled")), status == "cancelled"),
            "interrupted": _bool(_first_value(final_state.get("interrupted"), game.get("interrupted")), status == "interrupted"),
            "failed": _bool(_first_value(final_state.get("failed"), game.get("failed")), status == "failed"),
            "cancelled_at": _first_text(final_state.get("cancelled_at"), game.get("cancelled_at")),
            "interrupted_at": _first_text(final_state.get("interrupted_at"), game.get("interrupted_at")),
            "last_heartbeat_at": _first_text(final_state.get("last_heartbeat_at"), game.get("last_heartbeat_at")),
            "winner": game.get("winner"),
            "seed": game.get("seed"),
            "started_at": _first_text(game.get("started_at"), final_state.get("started_at"), config.get("started_at")),
            "finished_at": _first_text(game.get("finished_at"), final_state.get("finished_at"), config.get("finished_at")),
            "log_time": log_time,
            "day": _normalize_history_day(_first_value(final_state.get("day"), latest.get("day"), game.get("total_rounds"), 1)),
            "phase": normalize_history_phase(_first_text(final_state.get("phase"), latest.get("phase"), "ended" if game.get("winner") else "setup")),
            "event_count": event_count,
            "decision_count": decision_count,
            "max_days": _int_or_none(_first_value(game.get("max_days"), config.get("max_days"))),
            "enable_sheriff": _bool(_first_value(game.get("enable_sheriff"), config.get("enable_sheriff")), True),
            "skill_dir": _first_text(game.get("skill_dir"), config.get("skill_dir")),
            "role_skill_dirs": _json_object(_first_value(game.get("role_skill_dirs"), config.get("role_skill_dirs"), config.get("role_versions"))),
            "human_player_id": _int_or_none(_first_value(game.get("human_player_id"), config.get("human_player_id"))),
            "player_count": _int_or_none(_first_value(game.get("player_count"), len(players) or config.get("player_count"))) or 12,
            "player_roles": role_map,
            "players": players,
            "phases": phases,
            "default_phase_key": default_phase_key,
            "capabilities": {
                "phase_detail": True,
                "replay": True,
                "flow_data": True,
                "archive": True,
                "review": True,
            },
            "diagnostics": diagnostics,
            "manifest": manifest if manifest else _default_manifest(game_id, status),
            "config": config,
            "error": _first_text(final_state.get("error"), game.get("error")),
        }

    def _history_phase_map(
        self,
        event_phase_rows: list[dict[str, Any]],
        decision_phase_rows: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        phases: dict[str, dict[str, Any]] = {}

        def ensure(day: Any, phase: Any) -> dict[str, Any]:
            normalized_day = _normalize_history_day(day)
            normalized_phase = normalize_history_phase(phase)
            key = history_phase_key(normalized_day, normalized_phase)
            if key not in phases:
                phases[key] = _empty_phase_summary(normalized_day, normalized_phase)
            return phases[key]

        ensure(1, "setup")
        for row in event_phase_rows:
            phase = ensure(row.get("day"), row_history_phase(row))
            log_count = _int_or_none(row.get("log_count")) or 0
            first_index = _int_or_none(row.get("first_event_index"))
            last_index = _int_or_none(row.get("last_event_index"))
            event_type = _row_type(row)
            phase["log_count"] += log_count
            phase["has_logs"] = phase["log_count"] > 0
            phase["has_deaths"] = bool(phase.get("has_deaths")) or event_type in _AUTHORITATIVE_DEATH_EVENTS or event_type in _NIGHT_OUTCOME_EVENTS
            if first_index is not None:
                current = _int_or_none(phase.get("first_event_index"))
                phase["first_event_index"] = first_index if current is None else min(current, first_index)
            if last_index is not None:
                current = _int_or_none(phase.get("last_event_index"))
                phase["last_event_index"] = last_index if current is None else max(current, last_index)

        for row in decision_phase_rows:
            phase = ensure(row.get("day"), row_history_phase(row))
            count = _int_or_none(row.get("decision_count")) or 0
            action_type = _row_type(row)
            phase["decision_count"] += count
            phase["has_decisions"] = phase["decision_count"] > 0
            phase["has_votes"] = bool(phase.get("has_votes")) or action_type in _VOTE_ACTION_TYPES

        return phases

    def _attach_history_phase_state(
        self,
        phases: list[dict[str, Any]],
        players: list[dict[str, Any]],
        state_event_rows: list[dict[str, Any]],
    ) -> None:
        state_events = [_event_row(row) for row in state_event_rows]
        state_events.sort(key=lambda item: (_phase_sort(_normalize_history_day(item.get("day")), row_history_phase(item)), _int_or_none(item.get("idx")) or 0))
        alive: dict[int, bool] = {}
        for player in players:
            player_id = _int_or_none(_first_value(player.get("id"), player.get("seat")))
            if player_id is not None:
                alive[player_id] = True
        sheriff_id: int | None = None
        event_index = 0
        has_authoritative_deaths = any(_row_type(log) in _AUTHORITATIVE_DEATH_EVENTS for log in state_events)
        for phase in phases:
            phase_day = _normalize_history_day(phase.get("day"))
            phase_name = normalize_history_phase(phase.get("phase"))
            phase_sort = _phase_sort(phase_day, phase_name)
            phase_last_index = _int_or_none(phase.get("last_event_index"))
            while event_index < len(state_events):
                event = state_events[event_index]
                event_sort = _phase_sort(_normalize_history_day(event.get("day")), row_history_phase(event, phase_name))
                event_idx = _int_or_none(event.get("idx")) or 0
                if event_sort > phase_sort or (event_sort == phase_sort and phase_last_index is not None and event_idx > phase_last_index):
                    break
                for target_id in death_target_ids(event, has_authoritative_deaths):
                    alive[target_id] = False
                sheriff_id = sheriff_id_after_log(event, sheriff_id)
                event_index += 1
            alive_ids = sorted(player_id for player_id, is_alive in alive.items() if is_alive)
            dead_ids = sorted(player_id for player_id, is_alive in alive.items() if not is_alive)
            phase["alive_player_ids"] = alive_ids
            phase["dead_player_ids"] = dead_ids
            phase["sheriff_id"] = sheriff_id
            phase["state_after"] = {
                "alive": alive_ids,
                "dead": dead_ids,
                "sheriff_id": sheriff_id,
            }

    def load_game_review(self, game_id: str) -> dict[str, Any] | None:
        game_row = self._conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        if game_row is None:
            return None
        game = _row_dict(game_row)
        config = _json_object(game.get("config"))
        final_state = _json_object(game.get("final_state"))
        status = self._status_for_game(game, final_state)
        review = _json_object(final_state.get("review"))
        winner = _first_value(game.get("winner"), final_state.get("winner"))
        if review and self._review_visible_for_game(game, config, final_state, status=status):
            return review
        return {
            "game_id": str(game.get("id") or game_id),
            "winner": winner,
            "review_status": "暂无复盘报告",
            "notes": [],
        }

    def _aggregate_fingerprint(self, table: str, *columns: str) -> dict[str, Any]:
        select_parts = ["COUNT(*) AS total"]
        for column in columns:
            safe = "".join(ch for ch in column if ch.isalnum() or ch == "_")
            if safe != column:
                continue
            select_parts.append(f"MAX({column}) AS max_{column}")
        row = self._conn.execute(f"SELECT {', '.join(select_parts)} FROM {table}").fetchone()
        return _row_dict(row) if row is not None else {"total": 0}

    def _history_row(self, row: dict[str, Any]) -> dict[str, Any]:
        config = _json_object(row.get("config"))
        final_state = _history_final_state(row)
        source_context = _evidence_source_context(row, config, final_state)
        source = str(source_context["log_source"])
        status = self._status_for_game(row, final_state)
        log_time = _first_text(
            final_state.get("finished_at"),
            row.get("finished_at"),
            final_state.get("started_at"),
            row.get("started_at"),
            final_state.get("last_heartbeat_at"),
            config.get("log_time"),
        )
        diagnostics = _json_array(_first_value(final_state.get("diagnostics"), row.get("diagnostics")))
        return {
            "game_id": str(row.get("id") or ""),
            "log_name": _first_text(row.get("log_name"), config.get("log_name"), row.get("id")),
            "source_game_id": _first_text(row.get("source_game_id"), config.get("source_game_id"), row.get("id")),
            "log_source": source,
            "log_source_label": source_context["log_source_label"],
            "source_run_id": source_context["source_run_id"],
            "source_phase": source_context["source_phase"],
            "source_phase_label": source_context["source_phase_label"],
            "role_versions": dict(source_context["role_versions"]),
            "evidence_source": source_context,
            "log_time": log_time,
            "started_at": _first_text(row.get("started_at"), final_state.get("started_at"), config.get("started_at")),
            "finished_at": _first_text(row.get("finished_at"), final_state.get("finished_at"), config.get("finished_at")),
            "day": _int_or_none(row.get("latest_day")) or 0,
            "phase": _first_text(row.get("latest_phase"), "finished"),
            "event_count": _int_or_none(row.get("event_count")) or 0,
            "decision_count": _int_or_none(row.get("decision_count")) or 0,
            "winner": row.get("winner"),
            "status": status,
            "stop_requested": _bool(_first_value(final_state.get("stop_requested"), row.get("stop_requested")), False),
            "cancelled": _bool(_first_value(final_state.get("cancelled"), row.get("cancelled")), status == "cancelled"),
            "interrupted": _bool(_first_value(final_state.get("interrupted"), row.get("interrupted")), status == "interrupted"),
            "failed": _bool(_first_value(final_state.get("failed"), row.get("failed")), status == "failed"),
            "cancelled_at": _first_text(final_state.get("cancelled_at"), row.get("cancelled_at")),
            "interrupted_at": _first_text(final_state.get("interrupted_at"), row.get("interrupted_at")),
            "last_heartbeat_at": _first_text(final_state.get("last_heartbeat_at"), row.get("last_heartbeat_at")),
            "diagnostics": diagnostics,
            "error": _first_text(final_state.get("error"), row.get("error")),
            "mode": _first_text(row.get("mode"), config.get("mode"), "watch"),
            "seed": row.get("seed"),
            "max_days": _int_or_none(_first_value(row.get("max_days"), config.get("max_days"))),
            "enable_sheriff": _bool(_first_value(row.get("enable_sheriff"), config.get("enable_sheriff")), True),
            "skill_dir": _first_text(row.get("skill_dir"), config.get("skill_dir")),
            "role_skill_dirs": _json_object(_first_value(row.get("role_skill_dirs"), config.get("role_skill_dirs"), config.get("role_versions"))),
            "player_count": _int_or_none(_first_value(row.get("player_count"), row.get("stored_player_count"), config.get("player_count"))) or 12,
            "human_player_id": _int_or_none(_first_value(row.get("human_player_id"), config.get("human_player_id"))),
            "config": config,
        }

    def _source_for_game(self, game: dict[str, Any], config: dict[str, Any]) -> str:
        explicit = _first_text(game.get("log_source"), config.get("log_source"))
        if explicit:
            return explicit
        run_type = str(game.get("run_type") or "").lower()
        if run_type in EVOLUTION_RUN_TYPES or run_type.startswith("evolution_"):
            return "evolution"
        if run_type in {"evaluation_batch", "benchmark", "benchmark_game"}:
            return "benchmark"
        return "normal"

    def _status_for_game(self, game: dict[str, Any], final_state: dict[str, Any]) -> str:
        status = _first_text(final_state.get("status"), game.get("status"))
        if status:
            return status.lower()
        if _bool(_first_value(final_state.get("cancelled"), game.get("cancelled")), False):
            return "cancelled"
        if _bool(_first_value(final_state.get("interrupted"), game.get("interrupted")), False):
            return "interrupted"
        if _bool(_first_value(final_state.get("failed"), game.get("failed")), False):
            return "failed"
        if game.get("finished_at") is not None or game.get("winner") is not None:
            return "completed"
        return "running"

    def _review_visible_for_game(
        self,
        game: dict[str, Any],
        config: dict[str, Any],
        final_state: dict[str, Any],
        *,
        status: str,
    ) -> bool:
        mode = _first_text(game.get("mode"), config.get("mode"), final_state.get("mode"))
        human_player_id = _int_or_none(_first_value(
            game.get("human_player_id"),
            config.get("human_player_id"),
            final_state.get("human_player_id"),
        ))
        if mode != "play" or human_player_id is None:
            return True
        if status in {"failed", "cancelled", "interrupted"}:
            return False
        return bool(_first_value(game.get("winner"), final_state.get("winner"))) or status == "completed"

def _supports_detail_bundle(conn: StorageConnection) -> bool:
    if bool(getattr(conn, "supports_game_detail_bundle", False)):
        return True
    return conn.__class__.__name__ == "PostgresConnectionAdapter"


__all__ = ["GameReadRepository"]
