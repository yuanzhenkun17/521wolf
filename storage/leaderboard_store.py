"""Leaderboard table read helpers."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


class LeaderboardStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def list_entries(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM leaderboard "
            "ORDER BY updated_at DESC, role ASC, version_id ASC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_entry(row) for row in rows]


def _row_to_entry(row: sqlite3.Row) -> dict[str, Any]:
    version_id = str(row["version_id"])
    return {
        "version_id": version_id,
        "version": version_id,
        "role": row["role"],
        "games_played": int(row["games_played"] or 0),
        "games": int(row["games_played"] or 0),
        "wins": int(row["wins"] or 0),
        "losses": int(row["losses"] or 0),
        "win_rate": float(row["win_rate"] or 0.0),
        "avg_survival_rounds": float(row["avg_survival_rounds"] or 0.0),
        "target_side_win_rate": float(row["target_side_win_rate"] or 0.0),
        "target_side_win_rate_ci": [
            float(row["win_rate_ci_low"] or 0.0),
            float(row["win_rate_ci_high"] or 0.0),
        ],
        "scores": _load_json(row["scores"], {}),
        "is_baseline": bool(row["is_baseline"]),
        "data_sufficient": bool(row["data_sufficient"]),
        "updated_at": row["updated_at"],
    }


def _load_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default
