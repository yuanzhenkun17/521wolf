"""PostgreSQL-backed UI read model for game history and details."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, TypeAlias
from zoneinfo import ZoneInfo

from storage.public_events import public_events_only
from storage.shared.database import StorageConnection, StorageRow


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

_HISTORY_PHASE_ALIASES = {
    "result": "night",
    "sheriff_election": "sheriff",
    "day_speech": "speech",
    "pk_speak": "speech",
    "finished": "ended",
}
_HISTORY_PHASE_ORDER = (
    "setup",
    "night",
    "sheriff",
    "sheriff_vote",
    "sheriff_result",
    "speech",
    "exile_vote",
    "pk_vote",
    "vote",
    "ended",
)
_HISTORY_PHASE_RANK = {phase: index for index, phase in enumerate(_HISTORY_PHASE_ORDER)}
_VOTE_PHASE_BY_TYPE = {
    "vote": "exile_vote",
    "exile": "exile_vote",
    "exile_vote": "exile_vote",
    "exile_vote_start": "exile_vote",
    "exile_vote_end": "exile_vote",
    "exile_vote_tie": "exile_vote",
    "pk_vote": "pk_vote",
    "pk_vote_start": "pk_vote",
    "pk_vote_end": "pk_vote",
    "sheriff_vote": "sheriff_vote",
    "sheriff_vote_tie": "sheriff_vote",
}
_PHASE_QUERY_ALIASES = {
    "night": {"night", "result"},
    "sheriff": {"sheriff", "sheriff_election"},
    "speech": {"speech", "day_speech", "pk_speak"},
    "exile_vote": {"exile_vote", "vote"},
    "pk_vote": {"pk_vote", "vote"},
    "sheriff_vote": {"sheriff_vote", "vote"},
    "ended": {"ended", "finished"},
}
_VOTE_ACTION_TYPES = {"vote", "exile", "exile_vote", "pk_vote", "sheriff_vote"}
_AUTHORITATIVE_DEATH_EVENTS = {
    "death",
    "exile",
    "exile_vote_end",
    "pk_vote_end",
    "white_wolf_burst_kill",
    "white_wolf_burst_death",
    "white_wolf_explosion",
}
_FALLBACK_DEATH_EVENTS = {"werewolf_kill", "hunter_shoot"}
_NIGHT_OUTCOME_EVENTS = {"night_end", "night_result", "night_death", "night_death_reveal", "death_result"}
_SHERIFF_RESULT_EVENTS = {"sheriff_election_end", "sheriff_result"}
_SHERIFF_TRANSFER_EVENTS = {"sheriff_badge_transfer", "sheriff_transfer"}
_SHERIFF_DESTROY_EVENTS = {"sheriff_badge_destroy", "sheriff_destroy"}
_SHELL_STATE_EVENT_TYPES = tuple(sorted(
    _AUTHORITATIVE_DEATH_EVENTS
    | _FALLBACK_DEATH_EVENTS
    | _NIGHT_OUTCOME_EVENTS
    | _SHERIFF_RESULT_EVENTS
    | _SHERIFF_TRANSFER_EVENTS
    | _SHERIFF_DESTROY_EVENTS
    | {"white_wolf_explode"}
))


EVOLUTION_RUN_TYPES = {
    "evolution_training",
    "evolution_battle",
    "evolution_ab_baseline",
    "evolution_ab_candidate",
}


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
        all_logs = [self._event_row(row) for row in event_rows]
        all_decisions = [self._decision_row(row) for row in decision_rows]
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
        players = [self._player_row(_row_dict(row)) for row in self._conn.execute(
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
        decisions = [_flow_decision_row(self._decision_row(row)) for row in decision_rows]
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
        players = [self._player_row(_row_dict(row)) for row in self._conn.execute(
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
        events = [self._event_row(row) for row in event_rows]
        decisions = [self._decision_row(row) for row in decision_rows]
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
        events = [self._event_row(row) for row in event_rows]
        decisions = [self._decision_row(row) for row in decision_rows]
        players = [self._player_row(row) for row in player_rows]
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
        players = [self._player_row(row) for row in player_rows]
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
        state_events = [self._event_row(row) for row in state_event_rows]
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

    @staticmethod
    def _event_row(row: dict[str, Any]) -> dict[str, Any]:
        payload = _json_object(row.get("payload"))
        return {
            "index": _int_or_none(row.get("idx")) or 0,
            "idx": _int_or_none(row.get("idx")) or 0,
            "day": _int_or_none(row.get("day")) or 0,
            "phase": _first_text(row.get("phase"), ""),
            "type": _first_text(row.get("event_type"), ""),
            "event_type": _first_text(row.get("event_type"), ""),
            "message": _first_text(row.get("message"), ""),
            "public": _bool(row.get("public"), True),
            "actor": _int_or_none(row.get("actor")),
            "target": _int_or_none(row.get("target")),
            "payload": payload,
            "created_at": _first_text(row.get("created_at")),
        }

    @staticmethod
    def _decision_row(row: dict[str, Any]) -> dict[str, Any]:
        seat = _int_or_none(_first_value(row.get("player_id"), row.get("seat")))
        target = _int_or_none(row.get("selected_target"))
        parsed = _json_object(row.get("parsed_decision"))
        final_response = _json_object(row.get("final_response"))
        public_text = _first_text(row.get("public_text"), final_response.get("text"), parsed.get("public_text"), "")
        return {
            **row,
            "id": str(row.get("id") or ""),
            "decision_id": str(row.get("decision_id") or row.get("id") or ""),
            "player_id": seat,
            "actor_id": seat,
            "target_id": target,
            "selected_target": target,
            "action": _first_text(row.get("action_type"), ""),
            "action_type": _first_text(row.get("action_type"), ""),
            "day": _int_or_none(row.get("day")) or 0,
            "phase": _first_text(row.get("phase"), ""),
            "role": _first_text(row.get("role"), ""),
            "public_text": public_text,
            "private_reasoning": _first_text(row.get("private_reasoning"), ""),
            "confidence": _float_or_none(row.get("confidence")),
            "candidates": _json_array(row.get("candidates")),
            "selected_skills": _json_array(row.get("selected_skills")),
            "alternatives": _json_array(row.get("alternatives")),
            "rejected_reasons": _json_array(row.get("rejected_reasons")),
            "policy_adjustments": _json_array(row.get("policy_adjustments")),
            "errors": _json_array(row.get("errors")),
            "parsed_decision": parsed,
            "final_response": final_response,
        }

    @staticmethod
    def _player_row(row: dict[str, Any]) -> dict[str, Any]:
        seat = _int_or_none(row.get("seat"))
        return {
            "id": seat,
            "seat": seat,
            "name": f"{seat}号" if seat is not None else "",
            "role": _first_text(row.get("role"), ""),
            "team": _first_text(row.get("team"), ""),
            "alive": _bool(row.get("alive"), True),
            "killed_day": _int_or_none(row.get("killed_day")),
            "killed_cause": _first_text(row.get("killed_cause")),
            "role_version_id": _first_text(row.get("role_version_id")),
            "skill_package_hash": _first_text(row.get("skill_package_hash")),
        }


def _json_object(value: Any) -> dict[str, Any]:
    decoded = _json_value(value)
    return decoded if isinstance(decoded, dict) else {}


def _row_dict(row: StorageRow) -> dict[str, Any]:
    return {str(key): row[key] for key in row.keys()}


def _json_array(value: Any) -> list[Any]:
    decoded = _json_value(value)
    return decoded if isinstance(decoded, list) else []


def _json_object_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in _json_array(value) if isinstance(item, dict)]


def _normalize_history_day(day: Any) -> int:
    value = _int_or_none(day)
    return value if value is not None and value > 0 else 1


def normalize_history_phase(phase: Any = "setup") -> str:
    text = str(phase or "setup").strip() or "setup"
    return _HISTORY_PHASE_ALIASES.get(text, text)


def history_phase_key(day: Any, phase: Any) -> str:
    return f"day-{_normalize_history_day(day)}-{normalize_history_phase(phase)}"


def history_phase_title(day: Any, phase: Any) -> str:
    normalized_day = _normalize_history_day(day)
    normalized_phase = normalize_history_phase(phase)
    titles = {
        "setup": "准备",
        "night": f"第{normalized_day}夜",
        "sheriff": "警长竞选",
        "sheriff_vote": "警长投票",
        "sheriff_result": "上警/退水",
        "speech": f"第{normalized_day}天",
        "exile_vote": f"第{normalized_day}天放逐投票",
        "pk_vote": f"第{normalized_day}天对决投票",
        "vote": f"第{normalized_day}天投票",
        "ended": "结果",
    }
    return titles.get(normalized_phase, normalized_phase)


def _phase_sort(day: Any, phase: Any) -> int:
    normalized_phase = normalize_history_phase(phase)
    rank = _HISTORY_PHASE_RANK.get(normalized_phase, len(_HISTORY_PHASE_ORDER))
    return _normalize_history_day(day) * 100 + rank


def _row_type(row: dict[str, Any]) -> str:
    return str(
        row.get("type")
        or row.get("event_type")
        or row.get("action")
        or row.get("action_type")
        or row.get("kind")
        or ""
    ).strip()


def _vote_action_phase(row: dict[str, Any]) -> str:
    return _VOTE_PHASE_BY_TYPE.get(_row_type(row), "")


def row_history_phase(row: dict[str, Any], fallback: str = "setup") -> str:
    raw_phase = normalize_history_phase(row.get("phase", fallback))
    vote_phase = _vote_action_phase(row)
    if raw_phase == "vote" and vote_phase and vote_phase != "sheriff_vote":
        return vote_phase
    if (row.get("phase") is None or row.get("phase") == "") and vote_phase:
        return vote_phase
    return raw_phase


def _phase_query_candidates(phase: str) -> set[str]:
    normalized = normalize_history_phase(phase)
    candidates = set(_PHASE_QUERY_ALIASES.get(normalized, {normalized}))
    candidates.add(normalized)
    return candidates


def _paginate_rows(
    rows: list[dict[str, Any]],
    *,
    offset: int,
    limit: int | None,
    default_limit: int,
    max_limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    total = len(rows)
    safe_offset = max(0, _int_or_none(offset) or 0)
    safe_limit = _int_or_none(limit)
    if safe_limit is None:
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


def _replay_window_phase_filters(event_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, set[str]] = {}
    for row in event_rows:
        day = _normalize_history_day(row.get("day"))
        phase = row_history_phase(row)
        grouped.setdefault(day, set()).add(phase)
    filters = []
    for day in sorted(grouped):
        normalized_phases = sorted(grouped[day], key=lambda item: _phase_sort(day, item))
        raw_phases = sorted({raw_phase for phase in normalized_phases for raw_phase in _phase_query_candidates(phase)})
        filters.append({
            "day": day,
            "normalized_phases": normalized_phases,
            "raw_phases": raw_phases,
        })
    return filters


def _empty_phase_summary(day: Any, phase: Any) -> dict[str, Any]:
    normalized_day = _normalize_history_day(day)
    normalized_phase = normalize_history_phase(phase)
    return {
        "key": history_phase_key(normalized_day, normalized_phase),
        "day": normalized_day,
        "phase": normalized_phase,
        "title": history_phase_title(normalized_day, normalized_phase),
        "sort": _phase_sort(normalized_day, normalized_phase),
        "log_count": 0,
        "decision_count": 0,
        "has_logs": False,
        "has_decisions": False,
        "has_votes": False,
        "has_deaths": False,
        "first_event_index": None,
        "last_event_index": None,
    }


def _payload_of(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    return payload if isinstance(payload, dict) else {}


def _numeric_id(value: Any) -> int | None:
    value = _int_or_none(value)
    return value if value is not None and value > 0 else None


def _truthy_flag(value: Any) -> bool:
    return value is True or value == 1 or value == "1" or str(value).lower() == "true"


def _row_choice(row: dict[str, Any]) -> str:
    payload = _payload_of(row)
    return str(
        payload.get("choice")
        or payload.get("selected_choice")
        or payload.get("selected_skill")
        or row.get("choice")
        or row.get("selected_choice")
        or row.get("selected_skill")
        or row.get("action_choice")
        or ""
    ).strip().lower()


def _payload_id_list(row: dict[str, Any], keys: list[str]) -> list[int]:
    payload = _payload_of(row)
    ids: list[int] = []
    seen: set[int] = set()
    for key in keys:
        raw = payload.get(key, row.get(key))
        values = raw if isinstance(raw, list) else ([] if raw is None else [raw])
        for value in values:
            if isinstance(value, dict):
                value = value.get("id", value.get("player_id", value.get("seat")))
            player_id = _numeric_id(value)
            if player_id is None or player_id in seen:
                continue
            seen.add(player_id)
            ids.append(player_id)
    return ids


def _event_target_id(row: dict[str, Any]) -> int | None:
    payload = _payload_of(row)
    return _numeric_id(
        row.get("target_id")
        or row.get("target")
        or row.get("selected_target")
        or payload.get("target_id")
        or payload.get("target")
        or payload.get("player_id")
    )


def _is_legacy_white_wolf_explode_kill(row: dict[str, Any]) -> bool:
    if _row_type(row) != "white_wolf_explode":
        return False
    return _row_choice(row) in {"explode", "burst"} and _event_target_id(row) is not None


def _event_kills_player(row: dict[str, Any], has_authoritative_death_events: bool = True) -> bool:
    row_type = _row_type(row)
    if _is_legacy_white_wolf_explode_kill(row):
        return True
    if row_type in _AUTHORITATIVE_DEATH_EVENTS:
        return True
    return not has_authoritative_death_events and row_type in _FALLBACK_DEATH_EVENTS


def _night_outcome_death_ids(row: dict[str, Any]) -> list[int]:
    row_type = _row_type(row)
    if row_type not in _NIGHT_OUTCOME_EVENTS:
        return []
    payload = _payload_of(row)
    if row_type == "night_end" and _truthy_flag(payload.get("deferred_death_reveal", row.get("deferred_death_reveal"))):
        return []
    if any(
        isinstance(payload.get(key), list) or isinstance(row.get(key), list)
        for key in ("deaths", "death_ids", "dead_players")
    ):
        return _payload_id_list(row, ["deaths", "death_ids", "dead_players"])
    ids: list[int] = []
    killed = _numeric_id(payload.get("killed_target", payload.get("killedTarget", row.get("killed_target", row.get("killedTarget")))))
    protected = _numeric_id(payload.get("protected_target", payload.get("protectedTarget", row.get("protected_target", row.get("protectedTarget")))))
    saved = _truthy_flag(payload.get("saved", payload.get("used_antidote", payload.get("antidote_used", row.get("saved")))))
    if killed and not saved and killed != protected:
        ids.append(killed)
    poisoned = _numeric_id(payload.get("poisoned_target", payload.get("poisonedTarget", payload.get("poison_target", payload.get("poisonTarget", row.get("poisoned_target"))))))
    if poisoned and poisoned not in ids:
        ids.append(poisoned)
    target = _event_target_id(row)
    if target and row_type != "night_end" and target not in ids:
        ids.append(target)
    return ids


def death_target_ids(row: dict[str, Any], has_authoritative_death_events: bool = True) -> list[int]:
    ids = _night_outcome_death_ids(row)
    if _event_kills_player(row, has_authoritative_death_events):
        target = _event_target_id(row) or _numeric_id(row.get("actor_id", row.get("actor")))
        if target and target not in ids:
            ids.append(target)
    return ids


def sheriff_id_after_log(row: dict[str, Any], current_sheriff_id: int | None = None) -> int | None:
    row_type = _row_type(row)
    payload = _payload_of(row)
    if row_type in _SHERIFF_RESULT_EVENTS:
        return _numeric_id(payload.get("winner") or row.get("target_id") or row.get("actor_id")) or current_sheriff_id
    if row_type in _SHERIFF_TRANSFER_EVENTS:
        return _event_target_id(row) or current_sheriff_id
    if row_type in _SHERIFF_DESTROY_EVENTS:
        return None
    return current_sheriff_id


def _flow_decision_row(decision: dict[str, Any]) -> dict[str, Any]:
    public_summary = _first_text(decision.get("public_summary"), decision.get("public_text"), decision.get("text"), "")
    return {
        "id": decision.get("id"),
        "decision_id": decision.get("decision_id"),
        "game_id": decision.get("game_id"),
        "actor_id": decision.get("actor_id"),
        "player_id": decision.get("player_id"),
        "target_id": decision.get("target_id"),
        "selected_target": decision.get("selected_target"),
        "selected_choice": decision.get("selected_choice"),
        "day": decision.get("day"),
        "phase": row_history_phase(decision),
        "action": decision.get("action"),
        "action_type": decision.get("action_type"),
        "role": decision.get("role"),
        "public_summary": public_summary,
        "public_text": decision.get("public_text") or public_summary,
        "private_reasoning": decision.get("private_reasoning") or "",
        "confidence": decision.get("confidence"),
        "candidates": decision.get("candidates") if isinstance(decision.get("candidates"), list) else [],
        "source": decision.get("source"),
        "policy_adjustments": decision.get("policy_adjustments") if isinstance(decision.get("policy_adjustments"), list) else [],
        "errors": decision.get("errors") if isinstance(decision.get("errors"), list) else [],
        "created_at": decision.get("created_at"),
    }


def _supports_detail_bundle(conn: StorageConnection) -> bool:
    if bool(getattr(conn, "supports_game_detail_bundle", False)):
        return True
    return conn.__class__.__name__ == "PostgresConnectionAdapter"


def _normalize_bundle_rows(rows: list[dict[str, Any]], storage_timezone: str) -> list[dict[str, Any]]:
    return [_normalize_bundle_row(row, storage_timezone) for row in rows]


def _normalize_bundle_row(row: dict[str, Any], storage_timezone: str) -> dict[str, Any]:
    created_at = row.get("created_at")
    if created_at is None:
        return row
    normalized = _datetime_text_in_storage_timezone(created_at, storage_timezone)
    if normalized == created_at:
        return row
    next_row = dict(row)
    next_row["created_at"] = normalized
    return next_row


def _datetime_text_in_storage_timezone(value: Any, storage_timezone: str) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        return value
    return parsed.astimezone(ZoneInfo(storage_timezone)).isoformat()


def _history_final_state(row: dict[str, Any]) -> dict[str, Any]:
    final_state = _json_object(row.get("final_state"))
    if final_state:
        return final_state
    fields = {
        "status": row.get("final_status"),
        "stop_requested": row.get("final_stop_requested"),
        "cancelled": row.get("final_cancelled"),
        "interrupted": row.get("final_interrupted"),
        "failed": row.get("final_failed"),
        "cancelled_at": row.get("final_cancelled_at"),
        "interrupted_at": row.get("final_interrupted_at"),
        "last_heartbeat_at": row.get("final_last_heartbeat_at"),
        "started_at": row.get("final_started_at"),
        "finished_at": row.get("final_finished_at"),
        "source_phase": row.get("final_source_phase"),
        "error": row.get("final_error"),
        "diagnostics": row.get("final_diagnostics"),
    }
    return {key: value for key, value in fields.items() if value is not None}


def _json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict | list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value


def _first_value(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _first_text(*values: Any) -> str | None:
    value = _first_value(*values)
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _source_label(source: str) -> str:
    return {"normal": "人机/玩家", "benchmark": "评测", "evolution": "进化"}.get(source, source)


def _source_phase_label(phase: str | None) -> str | None:
    if not phase:
        return None
    return {"training": "训练", "battle": "对战", "baseline": "基线", "candidate": "候选"}.get(phase, phase)


def _clean_role_versions(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(role): str(version)
        for role, version in value.items()
        if role is not None and version is not None and str(version) != ""
    }


def _evidence_source_context(
    game: dict[str, Any],
    config: dict[str, Any],
    final_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    final_state = final_state or {}
    source = _first_text(game.get("log_source"), config.get("log_source"))
    if not source:
        run_type = str(game.get("run_type") or "").lower()
        if run_type in EVOLUTION_RUN_TYPES or run_type.startswith("evolution_"):
            source = "evolution"
        elif run_type in {"evaluation_batch", "benchmark", "benchmark_game"}:
            source = "benchmark"
        else:
            source = "normal"
    source_phase = _first_text(game.get("source_phase"), config.get("source_phase"), final_state.get("source_phase"))
    role_versions = _clean_role_versions(
        _first_value(
            game.get("role_versions"),
            config.get("role_versions"),
            game.get("role_skill_dirs"),
            config.get("role_skill_dirs"),
        )
    )
    return {
        "log_source": source,
        "log_source_label": _source_label(source),
        "source_run_id": _first_text(game.get("source_run_id"), config.get("source_run_id")),
        "source_phase": source_phase,
        "source_phase_label": _source_phase_label(source_phase),
        "seed": _first_value(game.get("seed"), config.get("seed")),
        "role_versions": role_versions,
    }


def _default_manifest(game_id: str, status: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_type": "game",
        "game_id": game_id,
        "status": status,
    }


__all__ = ["GameReadRepository"]
