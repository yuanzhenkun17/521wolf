"""Archive importer — migrate existing JSON archives into SQLite."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from agent.infrastructure.archive import DecisionArchive, GameArchive
from agent.infrastructure.storage.game_store import GameStore
from agent.infrastructure.storage.decision_store import DecisionStore

_log = logging.getLogger(__name__)


class ArchiveImporter:
    """Import existing JSON archive files into SQLite."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._game_store = GameStore(conn)
        self._decision_store = DecisionStore(conn)

    def import_archive(self, archive_path: Path) -> str | None:
        """Import a single archive.json file. Returns game_id or None on error."""
        try:
            raw = json.loads(archive_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            _log.warning("import_archive: failed to read %s: %s", archive_path, e)
            return None

        game_id = raw.get("game_id", "")
        if not game_id:
            _log.warning("import_archive: no game_id in %s", archive_path)
            return None

        # Check if already imported
        existing = self._game_store.get_game(game_id)
        if existing is not None:
            _log.debug("import_archive: skipping already-imported %s", game_id)
            return game_id

        # Extract final alive states from final_state
        final_state = raw.get("final_state", {})
        final_alive: dict[int, bool] | None = None
        if "players" in final_state:
            final_alive = {}
            for pid_str, ps in final_state["players"].items():
                final_alive[int(pid_str)] = ps.get("alive", True)

        # Extract death records from events
        deaths = _extract_deaths(raw.get("public_events", []))

        # Insert game
        self._game_store.insert_game(
            game_id=game_id,
            seed=raw.get("seed", 0),
            config=raw.get("config"),
            winner=raw.get("winner"),
            started_at=raw.get("started_at", ""),
            finished_at=raw.get("finished_at"),
            total_rounds=_count_rounds(raw.get("public_events", [])),
            public_events=raw.get("public_events"),
            final_state=final_state,
        )

        # Insert players
        player_roles = raw.get("player_roles", {})
        if player_roles:
            self._game_store.insert_players(
                game_id, player_roles, final_alive=final_alive, deaths=deaths,
            )

        # Insert decisions
        for i, d in enumerate(raw.get("decisions", [])):
            try:
                archive = DecisionArchive(
                    decision_id=d.get("decision_id", f"unknown_{i}"),
                    index=d.get("index", i),
                    player_id=d.get("player_id", 0),
                    role=d.get("role", ""),
                    day=d.get("day", 0),
                    phase=d.get("phase", ""),
                    action_type=d.get("action_type", ""),
                    candidates=d.get("candidates", []),
                    observation_summary=d.get("observation_summary", {}),
                    memory_context=d.get("memory_context", {}),
                    selected_skills=d.get("selected_skills", []),
                    prompt_messages=d.get("prompt_messages", []),
                    raw_output=d.get("raw_output", ""),
                    parsed_decision=d.get("parsed_decision", {}),
                    final_response=d.get("final_response", {}),
                    source=d.get("source", "llm"),
                    confidence=d.get("confidence"),
                    policy_adjustments=d.get("policy_adjustments", []),
                    errors=d.get("errors", []),
                )
                self._decision_store.insert_archive(
                    game_id=game_id,
                    archive=archive,
                    player_id=d.get("player_id"),
                    created_at=raw.get("started_at", ""),
                )
            except Exception as e:
                _log.warning(
                    "import_archive: failed to import decision %d in %s: %s",
                    i, game_id, e,
                )

        _log.info(
            "import_archive: imported %s (%d decisions)",
            game_id, len(raw.get("decisions", [])),
        )
        return game_id

    def import_directory(self, dir_path: Path) -> int:
        """Import all archive.json files in a directory tree. Returns count."""
        if not dir_path.exists():
            _log.warning("import_directory: %s does not exist", dir_path)
            return 0

        count = 0
        for archive_file in sorted(dir_path.rglob("archive.json")):
            result = self.import_archive(archive_file)
            if result is not None:
                count += 1

        _log.info("import_directory: imported %d games from %s", count, dir_path)
        return count


def _extract_deaths(events: list[dict]) -> list[dict]:
    """Extract death records from game events."""
    deaths: list[dict] = []
    for ev in events:
        if ev.get("type") in ("death", "killed", "exile", "hunter_shot", "self_explode"):
            deaths.append({
                "player_id": ev.get("target") or ev.get("player_id"),
                "cause": ev.get("type"),
                "day": ev.get("day", 0),
            })
    return deaths


def _count_rounds(events: list[dict]) -> int:
    """Count the maximum day number from events."""
    max_day = 0
    for ev in events:
        day = ev.get("day", 0)
        if day > max_day:
            max_day = day
    return max_day
