"""Routes for /api/leaderboards."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter

from ui.backend.shared.helpers import (
    DEFAULT_PATHS,
    get_leaderboard_paths,
    read_leaderboard_entries_from_db,
)

router = APIRouter(prefix="/api", tags=["leaderboards"])


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/leaderboards")
def list_leaderboards() -> dict[str, Any]:
    """Read leaderboard from SQLite first, then known output paths."""
    sqlite_entries = read_leaderboard_entries_from_db()
    if sqlite_entries:
        return {
            "entries": sqlite_entries,
            "source": str(DEFAULT_PATHS.data_dir / "wolf.db"),
            "source_type": "sqlite",
        }

    for path in get_leaderboard_paths():
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, list):
                return {"entries": data, "source": str(path), "source_type": "json"}
            if isinstance(data, dict) and "entries" in data:
                return {**data, "source": str(path), "source_type": "json"}
    return {"entries": [], "source": None, "source_type": None}
