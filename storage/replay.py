"""Read replay data from SQLite while preserving API-facing shapes."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from storage.ids import artifact_game_id, public_decision_id


def read_events_for_artifact(
    db_path: Path | str,
    game_dir: Path | str,
    *,
    root: Path | str | None = None,
) -> list[dict[str, Any]] | None:
    """Return event dicts for a raw game artifact directory, if indexed."""
    return _read_for_artifact(
        db_path,
        game_dir,
        root=root,
        table="game_events",
        loader=_load_events,
    )


def read_decisions_for_artifact(
    db_path: Path | str,
    game_dir: Path | str,
    *,
    root: Path | str | None = None,
) -> list[dict[str, Any]] | None:
    """Return decision dicts for a raw game artifact directory, if indexed."""
    return _read_for_artifact(
        db_path,
        game_dir,
        root=root,
        table="decisions",
        loader=_load_decisions,
    )


def read_config_for_artifact(
    db_path: Path | str,
    game_dir: Path | str,
    *,
    root: Path | str | None = None,
) -> dict[str, Any] | None:
    """Return the games.config payload for a raw game artifact directory, if indexed."""
    path = Path(db_path)
    if not path.exists():
        return None
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        game_id = _find_game_id(conn, Path(game_dir), Path(root) if root is not None else None, table="game_events")
        if game_id is None:
            return None
        row = conn.execute("SELECT seed, config FROM games WHERE id = ?", (game_id,)).fetchone()
        if row is None:
            return None
        config = _load_json(row["config"], {})
        if not isinstance(config, dict):
            config = {}
        if config.get("seed") is None and row["seed"] is not None:
            config["seed"] = row["seed"]
        return config
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def resolve_game_id_for_artifact(
    db_path: Path | str,
    game_dir: Path | str,
    *,
    root: Path | str | None = None,
    table: str,
) -> str | None:
    """Resolve the indexed game_id for an artifact directory and table."""
    if table not in {"game_events", "decisions", "experience_candidates"}:
        raise ValueError(f"unsupported artifact lookup table: {table}")
    path = Path(db_path)
    if not path.exists():
        return None
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        return _find_game_id(
            conn,
            Path(game_dir),
            Path(root) if root is not None else None,
            table=table,
        )
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _read_for_artifact(
    db_path: Path | str,
    game_dir: Path | str,
    *,
    root: Path | str | None,
    table: str,
    loader: Any,
) -> list[dict[str, Any]] | None:
    path = Path(db_path)
    if not path.exists():
        return None
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    try:
        game_id = _find_game_id(conn, Path(game_dir), Path(root) if root is not None else None, table=table)
        if game_id is None:
            return None
        rows = loader(conn, game_id)
        return rows if rows else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


def _find_game_id(
    conn: sqlite3.Connection,
    game_dir: Path,
    root: Path | None,
    *,
    table: str,
) -> str | None:
    source_match = _find_by_source_path(conn, game_dir, table=table)
    if source_match:
        return source_match

    for candidate in _candidate_game_ids(game_dir, root):
        if _has_rows(conn, table, candidate):
            return candidate
    return None


def _find_by_source_path(conn: sqlite3.Connection, game_dir: Path, *, table: str) -> str | None:
    target = _normalize_path(game_dir)
    for row in conn.execute("SELECT id, config FROM games WHERE config IS NOT NULL"):
        config = _load_json(row["config"], {})
        storage = config.get("_storage") if isinstance(config, dict) else None
        if not isinstance(storage, dict):
            continue
        source_path = storage.get("source_path")
        if source_path and _normalize_path(Path(str(source_path))) == target and _has_rows(conn, table, row["id"]):
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


def _has_rows(conn: sqlite3.Connection, table: str, game_id: str) -> bool:
    row = conn.execute(f"SELECT 1 FROM {table} WHERE game_id = ? LIMIT 1", (game_id,)).fetchone()
    return row is not None


def _load_events(conn: sqlite3.Connection, game_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM game_events WHERE game_id = ? ORDER BY idx",
        (game_id,),
    ).fetchall()
    return [_event_row(row) for row in rows]


def _load_decisions(conn: sqlite3.Connection, game_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM decisions WHERE game_id = ? ORDER BY day, seat, id",
        (game_id,),
    ).fetchall()
    return [_decision_row(row, index=index) for index, row in enumerate(rows, start=1)]


def _event_row(row: sqlite3.Row) -> dict[str, Any]:
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


def _decision_row(row: sqlite3.Row, *, index: int) -> dict[str, Any]:
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


def _load_json(value: str | None, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _normalize_path(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except OSError:
        return str(path).casefold()
