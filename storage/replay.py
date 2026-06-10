"""Read replay data from PostgreSQL while preserving API-facing shapes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from storage.ids import artifact_game_id, public_decision_id
from storage.decision_order import decision_timeline_order_clause
from storage.provider import StorageProvider, open_wolf_connection
from storage.shared.database import StorageConnection, StorageRow

_REPLAY_TABLES = frozenset({"game_events", "decisions", "experience_candidates"})


@dataclass
class ReplayLookupResult:
    """Diagnostic result for artifact replay lookup."""

    status: str
    data: Any = None
    game_id: str | None = None
    table: str | None = None
    game_dir: str = ""
    message: str = ""
    error: str | None = None
    candidates: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def read_events_for_artifact(
    game_dir: Path | str,
    *,
    root: Path | str | None = None,
    provider: StorageProvider | None = None,
    conn: StorageConnection | None = None,
) -> list[dict[str, Any]] | None:
    """Return event dicts for a raw game artifact directory, if indexed."""
    result = explain_replay_lookup(
        game_dir,
        root=root,
        replay_type="events",
        provider=provider,
        conn=conn,
    )
    return result.data if result.ok else None


def read_decisions_for_artifact(
    game_dir: Path | str,
    *,
    root: Path | str | None = None,
    provider: StorageProvider | None = None,
    conn: StorageConnection | None = None,
) -> list[dict[str, Any]] | None:
    """Return decision dicts for a raw game artifact directory, if indexed."""
    result = explain_replay_lookup(
        game_dir,
        root=root,
        replay_type="decisions",
        provider=provider,
        conn=conn,
    )
    return result.data if result.ok else None


def read_config_for_artifact(
    game_dir: Path | str,
    *,
    root: Path | str | None = None,
    provider: StorageProvider | None = None,
    conn: StorageConnection | None = None,
) -> dict[str, Any] | None:
    """Return the games.config payload for a raw game artifact directory, if indexed."""
    result = explain_replay_lookup(
        game_dir,
        root=root,
        replay_type="config",
        provider=provider,
        conn=conn,
    )
    return result.data if result.ok else None


def resolve_game_id_for_artifact(
    game_dir: Path | str,
    *,
    root: Path | str | None = None,
    table: str,
    provider: StorageProvider | None = None,
    conn: StorageConnection | None = None,
) -> str | None:
    """Resolve the indexed game_id for an artifact directory and table."""
    _require_replay_table(table)
    result = _with_wolf_connection(
        provider=provider,
        conn=conn,
        callback=lambda connection: _explain_game_id_lookup(
            connection,
            Path(game_dir),
            root=Path(root) if root is not None else None,
            table=table,
        ),
    )
    return result.game_id if result.ok else None


def explain_replay_lookup(
    game_dir: Path | str,
    *,
    root: Path | str | None = None,
    replay_type: str = "events",
    provider: StorageProvider | None = None,
    conn: StorageConnection | None = None,
) -> ReplayLookupResult:
    """Return replay data plus a status explaining why lookup failed.

    ``replay_type`` accepts ``events``, ``decisions``, or ``config``. Existing
    read_* helpers intentionally keep returning only replay data or None.
    """
    game_path = Path(game_dir)
    root_path = Path(root) if root is not None else None
    try:
        table, loader = _replay_target(replay_type)
    except ValueError as exc:
        return _lookup_result(
            "unsupported_type",
            game_path,
            table=None,
            message=(
                f"unsupported replay_type {replay_type!r}; "
                "expected one of: events, decisions, config"
            ),
            error=str(exc),
        )

    def _lookup(connection: StorageConnection) -> ReplayLookupResult:
        if replay_type == "config":
            result = _explain_config_game_lookup(connection, game_path, root=root_path)
        else:
            result = _explain_game_id_lookup(connection, game_path, root=root_path, table=table)
        if not result.ok:
            return result

        if replay_type == "config":
            row = connection.execute(
                "SELECT seed, config FROM games WHERE id = ?",
                (result.game_id,),
            ).fetchone()
            if row is None:
                return _lookup_result(
                    "not_found",
                    game_path,
                    table="games",
                    game_id=result.game_id,
                    candidates=result.candidates,
                    message=f"game row not found for resolved game_id {result.game_id!r}",
                )
            config = _load_json(row["config"], {})
            if not isinstance(config, dict):
                config = {}
            if config.get("seed") is None and row["seed"] is not None:
                config["seed"] = row["seed"]
            return _lookup_result(
                "ok",
                game_path,
                table="games",
                game_id=result.game_id,
                data=config,
                candidates=result.candidates,
                message="config found",
            )

        rows = loader(connection, result.game_id)
        if not rows:
            return _lookup_result(
                "missing_rows",
                game_path,
                table=table,
                game_id=result.game_id,
                candidates=result.candidates,
                message=f"{table} has no rows for game_id {result.game_id!r}",
            )
        return _lookup_result(
            "ok",
            game_path,
            table=table,
            game_id=result.game_id,
            data=rows,
            candidates=result.candidates,
            message=f"{table} rows found",
        )

    try:
        return _with_wolf_connection(provider=provider, conn=conn, callback=_lookup)
    except Exception as exc:  # noqa: BLE001 - replay diagnostics should not crash callers
        return _lookup_result(
            "storage_error",
            game_path,
            table=table,
            candidates=tuple(_candidate_game_ids(game_path, root_path)),
            message=f"storage error while loading {replay_type}",
            error=f"{type(exc).__name__}: {exc}",
        )


def _with_wolf_connection(
    *,
    provider: StorageProvider | None,
    conn: StorageConnection | None,
    callback: Any,
) -> ReplayLookupResult:
    if conn is not None:
        return callback(conn)
    connection = open_wolf_connection(provider)
    try:
        return callback(connection)
    finally:
        connection.close()


def _explain_game_id_lookup(
    conn: StorageConnection,
    game_dir: Path,
    *,
    root: Path | None,
    table: str,
) -> ReplayLookupResult:
    _require_replay_table(table)
    try:
        return _find_game_id_with_diagnostics(conn, game_dir, root, table=table)
    except Exception as exc:  # noqa: BLE001 - convert storage failures to diagnostics
        return _storage_lookup_error(
            game_dir,
            table=table,
            candidates=tuple(_candidate_game_ids(game_dir, root)),
            message="storage error while resolving replay game_id",
            error=f"{type(exc).__name__}: {exc}",
        )


def _explain_config_game_lookup(
    conn: StorageConnection,
    game_dir: Path,
    *,
    root: Path | None,
) -> ReplayLookupResult:
    candidates = tuple(_candidate_game_ids(game_dir, root))
    try:
        game_id = _find_source_game_id(conn, game_dir)
        if game_id is not None:
            return _lookup_result(
                "ok",
                game_dir,
                table="games",
                game_id=game_id,
                candidates=candidates,
                message="matched games.config _storage.source_path",
            )
        for candidate in candidates:
            if _game_exists(conn, candidate):
                return _lookup_result(
                    "ok",
                    game_dir,
                    table="games",
                    game_id=candidate,
                    candidates=candidates,
                    message="matched artifact-derived game_id",
                )
        return _lookup_result(
            "not_found",
            game_dir,
            table="games",
            candidates=candidates,
            message="no indexed game matched the artifact path or derived ids",
        )
    except Exception as exc:  # noqa: BLE001 - convert storage failures to diagnostics
        return _storage_lookup_error(
            game_dir,
            table="games",
            candidates=candidates,
            message="storage error while resolving replay config",
            error=f"{type(exc).__name__}: {exc}",
        )


def _find_game_id_with_diagnostics(
    conn: StorageConnection,
    game_dir: Path,
    root: Path | None,
    *,
    table: str,
) -> ReplayLookupResult:
    candidates = tuple(_candidate_game_ids(game_dir, root))
    empty_game_id = _find_source_game_id(conn, game_dir)
    if empty_game_id and _has_rows(conn, table, empty_game_id):
        return ReplayLookupResult(
            status="ok",
            game_id=empty_game_id,
            table=table,
            message="matched games.config _storage.source_path",
            candidates=candidates,
        )

    for candidate in candidates:
        if _has_rows(conn, table, candidate):
            return ReplayLookupResult(
                status="ok",
                game_id=candidate,
                table=table,
                message="matched artifact-derived game_id",
                candidates=candidates,
            )
        if empty_game_id is None and _game_exists(conn, candidate):
            empty_game_id = candidate

    if empty_game_id is not None:
        return ReplayLookupResult(
            status="missing_rows",
            game_id=empty_game_id,
            table=table,
            message=f"{table} has no rows for matched game_id {empty_game_id!r}",
            candidates=candidates,
        )
    return ReplayLookupResult(
        status="not_found",
        table=table,
        message="no indexed game matched the artifact path or derived ids",
        candidates=candidates,
    )


def _find_source_game_id(conn: StorageConnection, game_dir: Path) -> str | None:
    target = _normalize_path(game_dir)
    for row in conn.execute("SELECT id, config FROM games WHERE config IS NOT NULL").fetchall():
        config = _load_json(row["config"], {})
        storage = config.get("_storage") if isinstance(config, dict) else None
        if not isinstance(storage, dict):
            continue
        source_path = storage.get("source_path")
        if source_path and _normalize_path(Path(str(source_path))) == target:
            return str(row["id"])
    return None


def _candidate_game_ids(game_dir: Path, root: Path | None) -> list[str]:
    candidates = [game_dir.name]
    if root is not None:
        candidates.insert(0, artifact_game_id(game_dir, root=root))
    result: list[str] = []
    for item in candidates:
        if item and item not in result:
            result.append(item)
    return result


def _has_rows(conn: StorageConnection, table: str, game_id: str) -> bool:
    _require_replay_table(table)
    row = conn.execute(f"SELECT 1 FROM {table} WHERE game_id = ? LIMIT 1", (game_id,)).fetchone()
    return row is not None


def _game_exists(conn: StorageConnection, game_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM games WHERE id = ? LIMIT 1", (game_id,)).fetchone()
    return row is not None


def _require_replay_table(table: str) -> None:
    if table not in _REPLAY_TABLES:
        raise ValueError(f"unsupported artifact lookup table: {table}")


def _lookup_result(
    status: str,
    game_dir: Path,
    *,
    table: str | None = None,
    data: Any = None,
    game_id: str | None = None,
    message: str = "",
    error: str | None = None,
    candidates: tuple[str, ...] = (),
) -> ReplayLookupResult:
    return ReplayLookupResult(
        status=status,
        data=data,
        game_id=game_id,
        table=table,
        game_dir=str(game_dir),
        message=message,
        error=error,
        candidates=candidates,
    )


def _storage_lookup_error(
    game_dir: Path,
    *,
    table: str | None,
    message: str,
    error: str,
    game_id: str | None = None,
    candidates: tuple[str, ...] = (),
) -> ReplayLookupResult:
    return _lookup_result(
        "storage_error",
        game_dir,
        table=table,
        game_id=game_id,
        candidates=candidates,
        message=message,
        error=error,
    )


def _replay_target(replay_type: str) -> tuple[str, Any]:
    if replay_type == "events":
        return "game_events", _load_events
    if replay_type == "decisions":
        return "decisions", _load_decisions
    if replay_type == "config":
        return "games", None
    raise ValueError(f"unsupported replay_type: {replay_type}")


def _load_events(conn: StorageConnection, game_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM game_events WHERE game_id = ? ORDER BY idx",
        (game_id,),
    ).fetchall()
    return [_event_row(row) for row in rows]


def _load_decisions(conn: StorageConnection, game_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM decisions WHERE game_id = ? "
        f"ORDER BY {decision_timeline_order_clause(conn)}",
        (game_id,),
    ).fetchall()
    return [_decision_row(row, index=index) for index, row in enumerate(rows, start=1)]


def _event_row(row: StorageRow) -> dict[str, Any]:
    public_val = row["public"] if "public" in row.keys() else 1
    return {
        "index": row["idx"],
        "day": row["day"],
        "phase": row["phase"],
        "event_type": row["event_type"],
        "message": row["message"] or "",
        "public": bool(public_val),
        "visibility": "public" if public_val else "private",
        "actor": row["actor"],
        "target": row["target"],
        "payload": _load_json(row["payload"], {}),
    }


def _decision_row(row: StorageRow, *, index: int) -> dict[str, Any]:
    game_id = str(row["game_id"])
    storage_id = str(row["id"])
    return {
        "decision_id": public_decision_id(storage_id, game_id),
        "index": index,
        "player_id": row["player_id"] if row["player_id"] is not None else row["seat"],
        "role": row["role"],
        "day": row["day"],
        "phase": row["phase"],
        "action_type": row["action_type"],
        "candidates": _load_json(row["candidates"], []),
        "observation_summary": _load_json(row["observation_summary"], {}),
        "memory_context": _load_json(row["memory_context"], {}),
        "selected_skills": _load_json(row["selected_skills"], []),
        "prompt_messages": _load_json(row["prompt_messages"], []),
        "raw_output": row["raw_output"] or "",
        "parsed_decision": _load_json(row["parsed_decision"], {}),
        "final_response": _load_json(row["final_response"], {}),
        "selected_target": row["selected_target"],
        "selected_choice": row["selected_choice"],
        "public_text": row["public_text"] or "",
        "private_reasoning": row["private_reasoning"] or "",
        "confidence": row["confidence"],
        "alternatives": _load_json(row["alternatives"], []),
        "rejected_reasons": _load_json(row["rejected_reasons"], []),
        "source": row["source"] or "",
        "policy_adjustments": _load_json(row["policy_adjustments"], []),
        "errors": _load_json(row["errors"], []),
    }


def _load_json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _normalize_path(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except OSError:
        return str(path).casefold()
