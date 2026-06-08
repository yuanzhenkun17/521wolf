"""PostgreSQL-backed UI read model for game history and details."""

from __future__ import annotations

import json
from typing import Any

from storage.decision_order import decision_timeline_order_clause
from storage.public_events import public_events_only
from storage.shared.database import StorageConnection, StorageRow


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
            "players": self._aggregate_fingerprint("players"),
            "events": self._aggregate_fingerprint("game_events", "created_at", "idx"),
            "decisions": self._aggregate_fingerprint("decisions", "created_at"),
        }

    def list_history_rows(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT
                g.*,
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
        game_row = self._conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        if game_row is None:
            return None
        game = _row_dict(game_row)
        events = [self._event_row(_row_dict(row)) for row in self._conn.execute(
            "SELECT * FROM game_events WHERE game_id = ? ORDER BY idx, id",
            (game_id,),
        ).fetchall()]
        decisions = [self._decision_row(_row_dict(row)) for row in self._conn.execute(
            "SELECT * FROM decisions WHERE game_id = ? "
            f"ORDER BY {decision_timeline_order_clause(self._conn)}",
            (game_id,),
        ).fetchall()]
        players = [self._player_row(_row_dict(row)) for row in self._conn.execute(
            "SELECT * FROM players WHERE game_id = ? ORDER BY seat",
            (game_id,),
        ).fetchall()]

        config = _json_object(game.get("config"))
        final_state = _json_object(game.get("final_state"))
        public_events = public_events_only(_json_array(game.get("public_events")))
        source = self._source_for_game(game, config)
        source_phase = _first_text(game.get("source_phase"), config.get("source_phase"), final_state.get("source_phase"))
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
            "source_run_id": _first_text(game.get("source_run_id"), config.get("source_run_id")),
            "source_phase": source_phase,
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
        final_state = _json_object(row.get("final_state"))
        source = self._source_for_game(row, config)
        status = self._status_for_game(row, final_state)
        source_phase = _first_text(row.get("source_phase"), config.get("source_phase"), final_state.get("source_phase"))
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
            "log_source_label": _source_label(source),
            "source_run_id": _first_text(row.get("source_run_id"), config.get("source_run_id")),
            "source_phase": source_phase,
            "source_phase_label": _source_phase_label(source_phase),
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


def _default_manifest(game_id: str, status: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_type": "game",
        "game_id": game_id,
        "status": status,
    }


__all__ = ["GameReadRepository"]
