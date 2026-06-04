"""Rebuild SQLite indexes from raw game artifacts."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from storage.interfaces import DecisionArchiveData, EvolutionRunData, SkillVersionConfigData
from storage.decision_store import DecisionStore
from storage.evolution_store import EvolutionStore
from storage.experience_store import ExperienceCandidateStore
from storage.game_store import GameStore
from storage.ids import artifact_game_id, storage_decision_id
from storage.schema import get_connection

_log = logging.getLogger(__name__)


@dataclass(slots=True)
class RebuildReport:
    scanned: int = 0
    imported: int = 0
    skipped: int = 0
    evolution_scanned: int = 0
    evolution_imported: int = 0
    errors: list[str] = field(default_factory=list)
    game_ids: list[str] = field(default_factory=list)
    evolution_run_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scanned": self.scanned,
            "imported": self.imported,
            "skipped": self.skipped,
            "evolution_scanned": self.evolution_scanned,
            "evolution_imported": self.evolution_imported,
            "errors": list(self.errors),
            "game_ids": list(self.game_ids),
            "evolution_run_ids": list(self.evolution_run_ids),
        }


class StorageRebuilder:
    """Rebuild query indexes from archive/event/evidence artifact files.

    When scanning multiple runs, archive ``game_id`` values such as ``game_001``
    are not globally unique. By default this rebuilder namespaces game and
    decision IDs using the artifact path relative to the scanned root.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        namespace_ids: bool = True,
    ) -> None:
        self._conn = conn
        self._game_store = GameStore(conn)
        self._decision_store = DecisionStore(conn)
        self._candidate_store = ExperienceCandidateStore(conn)
        self._evolution_store = EvolutionStore(conn)
        self._namespace_ids = namespace_ids

    def rebuild_directory(self, root: Path | str) -> RebuildReport:
        base = Path(root)
        report = RebuildReport()
        if not base.exists():
            report.errors.append(f"{base} does not exist")
            return report

        for archive_path in sorted(base.rglob("archive.json")):
            report.scanned += 1
            try:
                game_id = self.import_game_dir(archive_path.parent, root=base)
            except Exception as exc:
                message = f"{archive_path}: {exc}"
                _log.warning("rebuild failed for %s", archive_path, exc_info=True)
                report.errors.append(message)
                continue
            if game_id is None:
                report.skipped += 1
                continue
            report.imported += 1
            report.game_ids.append(game_id)

        for summary_path in sorted(base.rglob("battle_summary.json")):
            report.evolution_scanned += 1
            try:
                run_id = self.import_evolution_run_dir(summary_path.parent)
            except Exception as exc:
                message = f"{summary_path}: {exc}"
                _log.warning("evolution rebuild failed for %s", summary_path, exc_info=True)
                report.errors.append(message)
                continue
            if run_id is None:
                continue
            report.evolution_imported += 1
            report.evolution_run_ids.append(run_id)
        return report

    def import_game_dir(self, game_dir: Path | str, *, root: Path | str | None = None) -> str | None:
        base = Path(game_dir)
        archive_path = base / "archive.json"
        if not archive_path.exists():
            return None
        archive = _read_json(archive_path)
        raw_game_id = str(archive.get("game_id") or base.name)
        if not raw_game_id:
            return None

        scan_root = Path(root) if root is not None else None
        game_id = self._canonical_game_id(base, raw_game_id, scan_root)
        self._delete_game_indexes(game_id)

        events = _read_events(base)
        meta = _read_optional_json(base / "meta.json")
        config = dict(archive.get("config") or {})
        config["_storage"] = {
            "source_game_id": raw_game_id,
            "source_path": str(base),
        }

        final_state = archive.get("final_state") or {}
        public_events = archive.get("public_events") or []
        player_roles = _normalize_player_roles(archive.get("player_roles") or final_state.get("player_roles") or {})
        final_alive = _final_alive(final_state)
        deaths = _extract_deaths(public_events) + _extract_deaths(events)

        self._game_store.insert_game(
            game_id=game_id,
            seed=int(archive.get("seed") or meta.get("seed") or 0),
            config=config,
            winner=str(archive.get("winner") or meta.get("winner") or ""),
            started_at=str(archive.get("started_at") or ""),
            finished_at=archive.get("finished_at"),
            total_rounds=max(_count_rounds(public_events), _count_rounds(events), int(meta.get("days") or 0)),
            public_events=public_events,
            final_state=final_state,
        )
        if player_roles:
            self._game_store.insert_players(
                game_id,
                player_roles,
                final_alive=final_alive,
                deaths=deaths,
            )

        self._insert_events(game_id, events)
        decision_id_map = self._insert_decisions(game_id, archive)
        self._insert_candidates(game_id, base, decision_id_map)
        self._conn.commit()
        return game_id

    def _canonical_game_id(self, game_dir: Path, raw_game_id: str, root: Path | None) -> str:
        if not self._namespace_ids:
            return raw_game_id
        return artifact_game_id(game_dir, root=root, raw_game_id=raw_game_id)

    def _delete_game_indexes(self, game_id: str) -> None:
        for table in ("experience_candidates", "decisions", "game_events", "players"):
            self._conn.execute(f"DELETE FROM {table} WHERE game_id = ?", (game_id,))
        self._conn.execute("DELETE FROM games WHERE id = ?", (game_id,))
        self._conn.commit()

    def _insert_events(self, game_id: str, events: list[dict[str, Any]]) -> None:
        for fallback_idx, event in enumerate(events, start=1):
            idx = _as_int(event.get("index") or event.get("idx"), fallback_idx)
            payload = event.get("payload") or {}
            self._conn.execute(
                "INSERT INTO game_events "
                "(game_id, idx, day, phase, event_type, message, level, "
                "visibility, actor, target, payload, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    game_id,
                    idx,
                    _as_int(event.get("day"), 0),
                    str(event.get("phase") or ""),
                    str(event.get("event_type") or event.get("type") or ""),
                    str(event.get("message") or ""),
                    str(event.get("level") or ""),
                    str(event.get("visibility") or ""),
                    event.get("actor"),
                    event.get("target"),
                    json.dumps(payload, ensure_ascii=False, default=str),
                    event.get("created_at"),
                ),
            )

    def _insert_decisions(self, game_id: str, archive: dict[str, Any]) -> dict[str, str]:
        id_map: dict[str, str] = {}
        for index, decision in enumerate(archive.get("decisions") or [], start=1):
            if not isinstance(decision, dict):
                continue
            raw_decision_id = str(decision.get("decision_id") or f"decision_{index:03d}")
            decision_id = self._canonical_decision_id(game_id, raw_decision_id)
            id_map[raw_decision_id] = decision_id
            parsed_decision = dict(decision.get("parsed_decision") or {})
            final_response = dict(decision.get("final_response") or {})
            if "target" not in parsed_decision and decision.get("selected_target") is not None:
                parsed_decision["target"] = decision.get("selected_target")
            if "choice" not in parsed_decision and decision.get("selected_choice") is not None:
                parsed_decision["choice"] = decision.get("selected_choice")
            if "text" not in final_response and decision.get("public_text") is not None:
                final_response["text"] = decision.get("public_text")
            archive_row = DecisionArchiveData(
                decision_id=decision_id,
                index=_as_int(decision.get("index"), index),
                player_id=_as_int(decision.get("player_id"), 0),
                role=str(decision.get("role") or ""),
                day=_as_int(decision.get("day"), 0),
                phase=str(decision.get("phase") or ""),
                action_type=str(decision.get("action_type") or ""),
                candidates=list(decision.get("candidates") or []),
                observation_summary=dict(decision.get("observation_summary") or {}),
                memory_context=dict(decision.get("memory_context") or {}),
                selected_skills=[str(item) for item in decision.get("selected_skills") or []],
                prompt_messages=list(decision.get("prompt_messages") or []),
                raw_output=str(decision.get("raw_output") or ""),
                parsed_decision=parsed_decision,
                final_response=final_response,
                source=str(decision.get("source") or "llm"),
                confidence=decision.get("confidence"),
                policy_adjustments=list(decision.get("policy_adjustments") or []),
                errors=list(decision.get("errors") or []),
            )
            self._decision_store.insert_archive(
                game_id=game_id,
                archive=archive_row,
                player_id=decision.get("player_id"),
                created_at=str(archive.get("started_at") or ""),
            )
        return id_map

    def _canonical_decision_id(self, game_id: str, raw_decision_id: str) -> str:
        if not self._namespace_ids:
            return raw_decision_id
        return storage_decision_id(game_id, raw_decision_id)

    def _insert_candidates(
        self,
        game_id: str,
        game_dir: Path,
        decision_id_map: dict[str, str],
    ) -> None:
        candidates_path = game_dir / "learning_v2" / "experience_candidates.jsonl"
        candidates = _read_jsonl(candidates_path)
        if not candidates:
            return
        normalized: list[dict[str, Any]] = []
        for candidate in candidates:
            row = dict(candidate)
            if self._namespace_ids:
                original_ids = [str(item) for item in row.get("evidence_decision_ids") or []]
                row["source_evidence_decision_ids"] = original_ids
                row["evidence_decision_ids"] = [
                    decision_id_map.get(item, self._canonical_decision_id(game_id, item))
                    for item in original_ids
                ]
            normalized.append(row)
        self._candidate_store.save_candidates(game_id, normalized)

    def import_evolution_run_dir(self, evolution_dir: Path | str) -> str | None:
        base = Path(evolution_dir)
        summary_path = base / "battle_summary.json"
        if not summary_path.exists():
            return None

        summary = _read_json(summary_path)
        if not isinstance(summary, dict):
            return None
        state = _read_optional_json(base / "state.json")

        run_id = str(state.get("run_id") or base.name)
        role = str(state.get("role") or summary.get("role") or "")
        if not run_id or not role:
            return None

        baseline_config = None
        baseline_raw = state.get("baseline_config") or summary.get("baseline_config")
        if isinstance(baseline_raw, dict):
            baseline_config = SkillVersionConfigData.from_dict(baseline_raw)

        run = EvolutionRunData(
            run_id=run_id,
            role=role,
            parent_hash=str(state.get("parent_hash") or ""),
            status=str(state.get("status") or "reviewing"),
            training_games=_as_int(state.get("training_games"), 0),
            battle_games=_as_int(state.get("battle_games") or summary.get("battle_games"), 0),
            baseline_config=baseline_config,
            candidate_hash=state.get("candidate_hash") or summary.get("candidate_hash"),
            battle_result=summary,
            errors=[str(item) for item in state.get("errors") or []],
        )
        self._evolution_store.save_run(run)
        return run_id


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_optional_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = _read_json(path)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _read_events(game_dir: Path) -> list[dict[str, Any]]:
    for name in ("game_events.jsonl", "events.jsonl"):
        events = _read_jsonl(game_dir / name)
        if events:
            return events
    return []


def _normalize_player_roles(raw: Any) -> dict[int, str]:
    if not isinstance(raw, dict):
        return {}
    result: dict[int, str] = {}
    for key, value in raw.items():
        try:
            result[int(key)] = str(value)
        except (TypeError, ValueError):
            continue
    return result


def _final_alive(final_state: dict[str, Any]) -> dict[int, bool] | None:
    players = final_state.get("players")
    if not isinstance(players, dict):
        return None
    result: dict[int, bool] = {}
    for key, value in players.items():
        if not isinstance(value, dict):
            continue
        try:
            result[int(key)] = bool(value.get("alive", True))
        except (TypeError, ValueError):
            continue
    return result


def _extract_deaths(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deaths: list[dict[str, Any]] = []
    for event in events:
        event_type = str(event.get("event_type") or event.get("type") or "")
        if event_type in {"death", "killed", "exile", "hunter_shot", "self_explode", "night_death"}:
            deaths.append({
                "player_id": event.get("target") or event.get("player_id"),
                "cause": event_type,
                "day": _as_int(event.get("day"), 0),
            })
    return deaths


def _count_rounds(events: list[dict[str, Any]]) -> int:
    return max((_as_int(event.get("day"), 0) for event in events), default=0)


def _as_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Rebuild SQLite query indexes from raw run artifacts.",
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=str(Path("runs")),
        help="Directory to scan for archive.json files. Defaults to runs/.",
    )
    parser.add_argument(
        "--db",
        default=str(Path("data/wolf.db")),
        help="SQLite database path. Defaults to data/wolf.db.",
    )
    parser.add_argument(
        "--no-namespace",
        action="store_true",
        help="Use archive game_id and decision_id values directly.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the rebuild report as JSON.",
    )
    args = parser.parse_args(argv)

    conn = get_connection(Path(args.db))
    try:
        report = StorageRebuilder(
            conn,
            namespace_ids=not args.no_namespace,
        ).rebuild_directory(Path(args.root))
    finally:
        conn.close()

    payload = {
        **report.to_dict(),
        "root": str(Path(args.root)),
        "db": str(Path(args.db)),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(
            "rebuild complete: "
            f"scanned={report.scanned} imported={report.imported} "
            f"skipped={report.skipped} errors={len(report.errors)}"
        )
        for error in report.errors:
            print(f"error: {error}")
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())