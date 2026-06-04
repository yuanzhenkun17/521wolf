"""Archive importer: migrate existing JSON archives into SQLite."""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from storage.interfaces import DecisionArchiveData
from storage.game_store import GameStore
from storage.decision_store import DecisionStore

_log = logging.getLogger(__name__)


class ArchiveImporter:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._game_store = GameStore(conn)
        self._decision_store = DecisionStore(conn)

    def import_archive(self, archive_path: Path) -> str | None:
        try:
            raw = json.loads(archive_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            _log.warning("import_archive: failed to read %s: %s", archive_path, exc)
            return None

        game_id = raw.get("game_id", "")
        if not game_id:
            _log.warning("import_archive: no game_id in %s", archive_path)
            return None

        existing = self._game_store.get_game(game_id)
        if existing is not None:
            _log.debug("import_archive: skipping already-imported %s", game_id)
            return game_id

        final_state = raw.get("final_state", {})
        final_alive: dict[int, bool] | None = None
        if "players" in final_state:
            final_alive = {}
            for pid_str, player_state in final_state["players"].items():
                final_alive[int(pid_str)] = player_state.get("alive", True)

        deaths = _extract_deaths(raw.get("public_events", []))

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

        player_roles = raw.get("player_roles", {})
        if player_roles:
            self._game_store.insert_players(
                game_id,
                player_roles,
                final_alive=final_alive,
                deaths=deaths,
            )

        for index, decision in enumerate(raw.get("decisions", [])):
            try:
                archive = DecisionArchiveData(
                    decision_id=decision.get("decision_id", f"unknown_{index}"),
                    index=decision.get("index", index),
                    player_id=decision.get("player_id", 0),
                    role=decision.get("role", ""),
                    day=decision.get("day", 0),
                    phase=decision.get("phase", ""),
                    action_type=decision.get("action_type", ""),
                    candidates=decision.get("candidates", []),
                    observation_summary=decision.get("observation_summary", {}),
                    memory_context=decision.get("memory_context", {}),
                    selected_skills=decision.get("selected_skills", []),
                    prompt_messages=decision.get("prompt_messages", []),
                    raw_output=decision.get("raw_output", ""),
                    parsed_decision=decision.get("parsed_decision", {}),
                    final_response=decision.get("final_response", {}),
                    source=decision.get("source", "llm"),
                    confidence=decision.get("confidence"),
                    policy_adjustments=decision.get("policy_adjustments", []),
                    errors=decision.get("errors", []),
                )
                self._decision_store.insert_archive(
                    game_id=game_id,
                    archive=archive,
                    player_id=decision.get("player_id"),
                    created_at=raw.get("started_at", ""),
                )
            except Exception as exc:
                _log.error(
                    "import_archive: failed to import decision %d in %s: %s",
                    index,
                    game_id,
                    exc,
                )

        _log.info(
            "import_archive: imported %s (%d decisions)",
            game_id,
            len(raw.get("decisions", [])),
        )
        return game_id

    def import_directory(self, dir_path: Path) -> int:
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
    deaths: list[dict] = []
    for event in events:
        if event.get("type") in ("death", "killed", "exile", "hunter_shot", "self_explode"):
            deaths.append({
                "player_id": event.get("target") or event.get("player_id"),
                "cause": event.get("type"),
                "day": event.get("day", 0),
            })
    return deaths

def _count_rounds(events: list[dict]) -> int:
    max_day = 0
    for event in events:
        day = event.get("day", 0)
        if day > max_day:
            max_day = day
    return max_day