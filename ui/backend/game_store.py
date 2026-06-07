"""Game loading, live-session, and history mixin for the UI backend store."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.util.json import read_json, write_json
from app.util.time import BEIJING_TZ, beijing_now_iso
from ui.backend.constants import EVOLUTION_PHASE_LABELS, LOG_SOURCE_LABELS
from ui.backend.history_index import GameHistoryIndex, history_facets, source_counts
from ui.backend.live_game import (
    LIVE_GAME_HEARTBEAT_TIMEOUT_SECONDS,
    LIVE_GAME_TERMINAL_STATUSES,
    BroadcastEventSink,
    LiveGameSession,
    live_game_heartbeat_timed_out,
)
from ui.backend.schemas import GameStartRequest, HumanActionRequest
from ui.backend.serializers import (
    _archive_payload,
    _dead_players,
    _fallback_version,
    _frontend_review,
    _normalize_decision,
    _normalize_event,
    _normalize_roles,
    _read_jsonl,
    _role_label,
    _sheriff_from_events,
    _team_for_role,
    _vote_tally,
)
from ui.backend.task_state import _match_filter, _pagination


class GameStoreMixin:
    def _game_history_index_path(self) -> Path:
        return self.paths.runs_dir / "game_history_index.json"

    def _game_history_index(self) -> GameHistoryIndex:
        index = getattr(self, "_game_history_index_cache", None)
        if index is None:
            index = GameHistoryIndex(
                self._game_history_index_path(),
                build_rows=self._build_game_history_rows,
                fingerprint=self._game_history_fingerprint,
            )
            setattr(self, "_game_history_index_cache", index)
        return index

    def invalidate_game_history_index(self) -> None:
        index = getattr(self, "_game_history_index_cache", None)
        if index is not None:
            index.invalidate()

    def _game_history_fingerprint(self) -> dict[str, Any]:
        return {
            "memory": self._game_history_memory_fingerprint(),
            "disk": {
                "normal": self._directory_children_signature(self.paths.games_dir, include_children=True),
                "benchmark": self._benchmark_history_signature(),
                "evolution": self._evolution_history_signature(),
            },
        }

    def _game_history_memory_fingerprint(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for game_id, game in self.games.items():
            items.append(self._game_history_memory_item(game_id, game))
        for game_id, session in self.live_sessions.items():
            items.append(
                {
                    "game_id": game_id,
                    "status": session.status,
                    "last_heartbeat_at": getattr(session, "last_heartbeat_at", None),
                    "interrupted_at": getattr(session, "interrupted_at", None),
                    "diagnostic_count": len(getattr(session, "diagnostics", []) or []),
                    "event_count": len(getattr(session.event_sink, "backlog", []) or []),
                }
            )
        return sorted(items, key=lambda item: str(item.get("game_id") or ""))

    def _game_history_memory_item(self, game_id: str, game: dict[str, Any]) -> dict[str, Any]:
        events = game.get("events") if isinstance(game.get("events"), list) else []
        decisions = game.get("decisions") if isinstance(game.get("decisions"), list) else []
        return {
            "game_id": str(game_id),
            "status": game.get("status"),
            "log_source": game.get("log_source"),
            "log_time": self._snapshot_log_time(game),
            "last_heartbeat_at": game.get("last_heartbeat_at"),
            "interrupted_at": game.get("interrupted_at"),
            "diagnostic_count": len(game.get("diagnostics") if isinstance(game.get("diagnostics"), list) else []),
            "event_count": len(events),
            "decision_count": len(decisions),
        }

    def _benchmark_history_signature(self) -> dict[str, Any]:
        base = self.paths.runs_dir / "evaluation_batches"
        batches = []
        for batch_dir in self._iter_dirs(base):
            batches.append(
                {
                    "name": batch_dir.name,
                    "dir": self._path_signature(batch_dir),
                    "games": self._directory_children_signature(batch_dir / "games", include_children=True),
                }
            )
        return {"root": self._path_signature(base), "batches": batches}

    def _evolution_history_signature(self) -> dict[str, Any]:
        runs = []
        for run_dir in self._iter_dirs(self.paths.evolution_dir):
            phases = []
            for phase_dir in self._iter_dirs(run_dir):
                phases.append(
                    {
                        "name": phase_dir.name,
                        "dir": self._directory_children_signature(phase_dir, include_children=True),
                    }
                )
            runs.append({"name": run_dir.name, "dir": self._path_signature(run_dir), "phases": phases})
        return {"root": self._path_signature(self.paths.evolution_dir), "runs": runs}

    def _directory_children_signature(self, path: Path, *, include_children: bool) -> dict[str, Any]:
        signature = self._path_signature(path)
        if not signature.get("exists"):
            return signature
        children = self._iter_dirs(path)
        signature["dir_count"] = len(children)
        if include_children:
            signature["children"] = [self._game_dir_signature(child) for child in children]
        return signature

    def _game_dir_signature(self, path: Path) -> dict[str, Any]:
        return {
            "name": path.name,
            **self._path_signature(path),
            "files": {
                name: self._path_signature(path / name)
                for name in ("ui_snapshot.json", "meta.json", "game_events.jsonl", "agent_decisions.jsonl")
            },
        }

    @staticmethod
    def _path_signature(path: Path) -> dict[str, Any]:
        try:
            stat = path.stat()
        except OSError:
            return {"exists": False}
        return {"exists": True, "mtime_ns": stat.st_mtime_ns}

    @staticmethod
    def _iter_dirs(path: Path) -> list[Path]:
        try:
            return sorted((item for item in path.iterdir() if item.is_dir()), key=lambda item: item.name)
        except OSError:
            return []

    def _live_game_heartbeat_timeout_seconds(self) -> float:
        value = getattr(self, "live_game_heartbeat_timeout_seconds", LIVE_GAME_HEARTBEAT_TIMEOUT_SECONDS)
        try:
            return max(1.0, float(value))
        except (TypeError, ValueError):
            return LIVE_GAME_HEARTBEAT_TIMEOUT_SECONDS

    @staticmethod
    def _append_live_game_diagnostic(snapshot: dict[str, Any], diagnostic: dict[str, Any]) -> None:
        diagnostics = snapshot.get("diagnostics")
        if not isinstance(diagnostics, list):
            diagnostics = []
            snapshot["diagnostics"] = diagnostics
        item = {key: value for key, value in diagnostic.items() if value is not None}
        identity = (item.get("kind"), item.get("stage"), item.get("message"))
        for existing in diagnostics:
            if not isinstance(existing, dict):
                continue
            if (existing.get("kind"), existing.get("stage"), existing.get("message")) == identity:
                return
        diagnostics.append(item)

    def _mark_loaded_live_game_interrupted(
        self,
        snapshot: dict[str, Any],
        *,
        reason: str,
        stage: str,
        kind: str,
        fallback_time: str | None = None,
    ) -> dict[str, Any]:
        status = str(snapshot.get("status") or "").lower()
        if status in LIVE_GAME_TERMINAL_STATUSES and status != "interrupted":
            return snapshot
        now = beijing_now_iso()
        last_heartbeat_at = (
            snapshot.get("last_heartbeat_at")
            or snapshot.get("updated_at")
            or snapshot.get("finished_at")
            or snapshot.get("started_at")
            or fallback_time
            or now
        )
        interrupted = {
            **snapshot,
            "status": "interrupted",
            "stop_requested": False,
            "cancelled": False,
            "interrupted": True,
            "failed": False,
            "last_heartbeat_at": last_heartbeat_at,
            "interrupted_at": snapshot.get("interrupted_at") or now,
            "finished_at": snapshot.get("finished_at") or now,
            "error": snapshot.get("error") or reason,
        }
        self._append_live_game_diagnostic(
            interrupted,
            {
                "kind": kind,
                "stage": stage,
                "message": reason,
                "last_heartbeat_at": last_heartbeat_at,
                "at": interrupted["interrupted_at"],
            },
        )
        return interrupted

    def _persist_recovered_live_game(self, game_dir: Path, snapshot: dict[str, Any]) -> None:
        try:
            write_json(game_dir / "ui_snapshot.json", snapshot)
            write_json(game_dir / "review.json", snapshot.get("review") or {})
            write_json(game_dir / "archive.json", _archive_payload(str(snapshot.get("game_id") or game_dir.name), snapshot))
        except Exception:
            # Recovery metadata is best-effort; the in-memory response still carries the interruption.
            return

    def skill_dir_for_request(self, request: GameStartRequest) -> str | None:
        if not request.role_versions:
            return request.skill_dir
        from app.lib.version import SkillVersionConfig, build_composite_skill_dir

        role_versions = self._effective_role_versions(request.role_versions)
        if not role_versions:
            return request.skill_dir
        try:
            skill_dir = build_composite_skill_dir(
                self.registry,
                SkillVersionConfig(
                    name=f"ui_{uuid.uuid4().hex[:8]}",
                    created_at=beijing_now_iso(),
                    role_versions=role_versions,
                ),
            )
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            raise HTTPException(status_code=404, detail=f"role version not found: {exc}") from exc
        return str(skill_dir) if skill_dir is not None else request.skill_dir

    def _effective_role_versions(self, role_versions: dict[str, str]) -> dict[str, str]:
        effective: dict[str, str] = {}
        registry = self.registry
        for role, version_id in role_versions.items():
            if not role or not version_id:
                continue
            if version_id == _fallback_version(role)["version_id"]:
                try:
                    registry.read_skill_contents(role, version_id)
                except FileNotFoundError:
                    continue
            effective[str(role)] = str(version_id)
        return effective

    def _log_source_id(
        self,
        source: str,
        run_id: str,
        game_dir_name: str,
        *,
        phase: str | None = None,
    ) -> str:
        if source == "benchmark":
            return f"benchmark:{run_id}:{game_dir_name}"
        if source == "evolution" and phase:
            return f"evolution:{run_id}:{phase}:{game_dir_name}"
        return str(game_dir_name)

    def _parse_external_log_id(self, game_id: str) -> dict[str, str] | None:
        parts = str(game_id or "").split(":")
        if parts[0] == "benchmark" and len(parts) == 3:
            batch_id, game_dir = parts[1], parts[2]
            if self._safe_log_part(batch_id) and self._safe_log_part(game_dir):
                return {"source": "benchmark", "run_id": batch_id, "game_dir": game_dir}
        if parts[0] == "evolution" and len(parts) == 4:
            run_id, phase, game_dir = parts[1], parts[2], parts[3]
            if self._safe_log_part(run_id) and self._safe_log_part(phase) and self._safe_log_part(game_dir):
                return {"source": "evolution", "run_id": run_id, "phase": phase, "game_dir": game_dir}
        return None

    @staticmethod
    def _safe_log_part(value: str) -> bool:
        text = str(value or "")
        return bool(text) and text not in {".", ".."} and "/" not in text and "\\" not in text

    def _source_phase_label(self, phase: str | None) -> str | None:
        if not phase:
            return None
        return EVOLUTION_PHASE_LABELS.get(phase, str(phase))

    def _directory_time_iso(self, path: Path) -> str | None:
        try:
            return datetime.fromtimestamp(path.stat().st_mtime, tz=BEIJING_TZ).isoformat()
        except OSError:
            return None

    def _snapshot_log_time(self, snapshot: dict[str, Any], fallback: str | None = None) -> str | None:
        config = snapshot.get("config") if isinstance(snapshot.get("config"), dict) else {}
        return (
            snapshot.get("finished_at")
            or snapshot.get("started_at")
            or snapshot.get("log_time")
            or snapshot.get("last_heartbeat_at")
            or snapshot.get("created_at")
            or snapshot.get("updated_at")
            or config.get("finished_at")
            or config.get("started_at")
            or config.get("log_time")
            or config.get("last_heartbeat_at")
            or config.get("created_at")
            or config.get("updated_at")
            or fallback
        )

    def _with_log_source(
        self,
        snapshot: dict[str, Any],
        *,
        public_game_id: str,
        source: str,
        original_game_id: str | None = None,
        source_run_id: str | None = None,
        source_phase: str | None = None,
        fallback_time: str | None = None,
    ) -> dict[str, Any]:
        data = dict(snapshot)
        original = str(original_game_id or data.get("source_game_id") or data.get("log_name") or data.get("game_id") or public_game_id)
        source_label = LOG_SOURCE_LABELS.get(source, "人机/玩家")
        phase_label = self._source_phase_label(source_phase)
        config = data.get("config") if isinstance(data.get("config"), dict) else {}
        log_time = self._snapshot_log_time(data, fallback_time)
        data["game_id"] = public_game_id
        data["log_name"] = data.get("log_name") or original
        data["source_game_id"] = original
        data["log_source"] = source
        data["log_source_label"] = source_label
        data["source_run_id"] = source_run_id
        data["source_phase"] = source_phase
        data["source_phase_label"] = phase_label
        data["log_time"] = log_time
        data["config"] = {
            **config,
            "log_source": source,
            "log_source_label": source_label,
            "source_game_id": original,
            "source_run_id": source_run_id,
            "source_phase": source_phase,
            "source_phase_label": phase_label,
            "log_time": log_time,
        }
        return data

    def _load_game_from_directory(
        self,
        game_dir: Path,
        *,
        public_game_id: str,
        source: str,
        source_run_id: str | None = None,
        source_phase: str | None = None,
    ) -> dict[str, Any] | None:
        fallback_time = self._directory_time_iso(game_dir)
        path = game_dir / "ui_snapshot.json"
        if path.exists():
            try:
                data = read_json(path)
                if not isinstance(data, dict):
                    return None
                if source == "normal" and str(data.get("status") or "").lower() not in LIVE_GAME_TERMINAL_STATUSES:
                    data = self._mark_loaded_live_game_interrupted(
                        data,
                        reason="interrupted by backend restart",
                        kind="live_game_interrupted",
                        stage="live_game.recover",
                        fallback_time=fallback_time,
                    )
                    self._persist_recovered_live_game(game_dir, data)
                return self._with_log_source(
                    data,
                    public_game_id=public_game_id,
                    source=source,
                    original_game_id=data.get("game_id"),
                    source_run_id=source_run_id,
                    source_phase=source_phase,
                    fallback_time=fallback_time,
                )
            except (OSError, json.JSONDecodeError):
                return None

        meta_path = game_dir / "meta.json"
        events_path = game_dir / "game_events.jsonl"
        decisions_path = game_dir / "agent_decisions.jsonl"
        if not meta_path.exists() and (events_path.exists() or decisions_path.exists()):
            original_game_id = game_dir.name
            events = _read_jsonl(events_path)
            decisions = _read_jsonl(decisions_path)
            result = {
                "game_id": public_game_id,
                "events": events,
                "decisions": decisions,
                "status": "running",
                "started_at": fallback_time,
                "last_heartbeat_at": fallback_time,
            }
            snapshot = self.snapshot_from_result(result, mode="watch", config={"started_at": fallback_time})
            snapshot["log_name"] = original_game_id
            if source == "normal":
                snapshot = self._mark_loaded_live_game_interrupted(
                    snapshot,
                    reason="interrupted by backend restart",
                    kind="live_game_interrupted",
                    stage="live_game.recover",
                    fallback_time=fallback_time,
                )
                self._persist_recovered_live_game(game_dir, snapshot)
            return self._with_log_source(
                snapshot,
                public_game_id=public_game_id,
                source=source,
                original_game_id=original_game_id,
                source_run_id=source_run_id,
                source_phase=source_phase,
                fallback_time=fallback_time,
            )
        if not meta_path.exists():
            return None
        try:
            meta = read_json(meta_path)
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(meta, dict):
            return None

        original_game_id = str(meta.get("game_id") or game_dir.name)
        events = _read_jsonl(game_dir / "game_events.jsonl")
        decisions = _read_jsonl(game_dir / "agent_decisions.jsonl")
        config = {
            **meta,
            "source_run_id": source_run_id,
            "source_phase": source_phase,
            "source_phase_label": self._source_phase_label(source_phase),
        }
        result = {
            "game_id": public_game_id,
            "seed": meta.get("seed"),
            "winner": meta.get("winner"),
            "player_roles": meta.get("player_roles", {}),
            "events": events,
            "decisions": decisions,
            "status": "completed" if meta.get("finished") else "running",
            "started_at": meta.get("started_at") or fallback_time,
            "finished_at": meta.get("finished_at") or fallback_time,
            "last_heartbeat_at": meta.get("last_heartbeat_at") or meta.get("updated_at") or fallback_time,
            "diagnostics": meta.get("diagnostics") if isinstance(meta.get("diagnostics"), list) else [],
        }
        snapshot = self.snapshot_from_result(result, mode="watch", config=config)
        snapshot["log_name"] = original_game_id
        if source == "normal" and str(snapshot.get("status") or "").lower() not in LIVE_GAME_TERMINAL_STATUSES:
            snapshot = self._mark_loaded_live_game_interrupted(
                snapshot,
                reason="interrupted by backend restart",
                kind="live_game_interrupted",
                stage="live_game.recover",
                fallback_time=fallback_time,
            )
            self._persist_recovered_live_game(game_dir, snapshot)
        return self._with_log_source(
            snapshot,
            public_game_id=public_game_id,
            source=source,
            original_game_id=original_game_id,
            source_run_id=source_run_id,
            source_phase=source_phase,
            fallback_time=fallback_time,
        )

    def _load_external_game_from_disk(self, game_id: str) -> dict[str, Any] | None:
        parsed = self._parse_external_log_id(game_id)
        if parsed is None:
            return None
        if parsed["source"] == "benchmark":
            game_dir = self.paths.runs_dir / "evaluation_batches" / parsed["run_id"] / "games" / parsed["game_dir"]
            return self._load_game_from_directory(
                game_dir,
                public_game_id=game_id,
                source="benchmark",
                source_run_id=parsed["run_id"],
            )
        if parsed["source"] == "evolution":
            game_dir = self.paths.evolution_dir / parsed["run_id"] / parsed["phase"] / parsed["game_dir"]
            return self._load_game_from_directory(
                game_dir,
                public_game_id=game_id,
                source="evolution",
                source_run_id=parsed["run_id"],
                source_phase=parsed["phase"],
            )
        return None

    def _game_list_row(self, game: dict[str, Any]) -> dict[str, Any]:
        source = str(game.get("log_source") or "normal")
        config = game.get("config") if isinstance(game.get("config"), dict) else {}
        log_time = self._snapshot_log_time(game)
        diagnostics = game.get("diagnostics") if isinstance(game.get("diagnostics"), list) else []
        return {
            "game_id": game["game_id"],
            "log_name": game.get("log_name", game["game_id"]),
            "source_game_id": game.get("source_game_id") or game.get("log_name") or game["game_id"],
            "log_source": source,
            "log_source_label": game.get("log_source_label") or LOG_SOURCE_LABELS.get(source, "人机/玩家"),
            "source_run_id": game.get("source_run_id"),
            "source_phase": game.get("source_phase"),
            "source_phase_label": game.get("source_phase_label"),
            "log_time": log_time,
            "started_at": game.get("started_at") or config.get("started_at"),
            "finished_at": game.get("finished_at") or config.get("finished_at"),
            "day": game.get("day", 0),
            "phase": game.get("phase", "finished"),
            "event_count": len(game.get("logs") or game.get("events") or []),
            "decision_count": len(game.get("decisions") or []),
            "winner": game.get("winner"),
            "status": game.get("status"),
            "stop_requested": bool(game.get("stop_requested", False)),
            "cancelled": bool(game.get("cancelled", False)),
            "interrupted": bool(game.get("interrupted", False)),
            "failed": bool(game.get("failed", game.get("status") == "failed")),
            "cancelled_at": game.get("cancelled_at"),
            "interrupted_at": game.get("interrupted_at"),
            "last_heartbeat_at": game.get("last_heartbeat_at") or config.get("last_heartbeat_at"),
            "diagnostics": list(diagnostics),
            "error": game.get("error"),
            "mode": game.get("mode", "watch"),
            "seed": game.get("seed"),
            "max_days": game.get("max_days"),
            "enable_sheriff": game.get("enable_sheriff", True),
            "skill_dir": game.get("skill_dir"),
            "role_skill_dirs": game.get("role_skill_dirs") or config.get("role_skill_dirs") or {},
            "player_count": len(game.get("players", [])) or game.get("player_count") or 12,
            "human_player_id": game.get("human_player_id"),
            "config": config,
        }

    def _list_benchmark_games_from_disk(self) -> list[dict[str, Any]]:
        base = self.paths.runs_dir / "evaluation_batches"
        if not base.exists():
            return []
        rows: list[dict[str, Any]] = []
        for batch_dir in sorted((item for item in base.iterdir() if item.is_dir()), key=lambda item: item.name, reverse=True):
            games_dir = batch_dir / "games"
            if not games_dir.exists():
                continue
            for game_dir in sorted((item for item in games_dir.iterdir() if item.is_dir()), key=lambda item: item.name):
                public_id = self._log_source_id("benchmark", batch_dir.name, game_dir.name)
                loaded = self._load_game_from_directory(
                    game_dir,
                    public_game_id=public_id,
                    source="benchmark",
                    source_run_id=batch_dir.name,
                )
                if loaded is not None:
                    rows.append(self._game_list_row(loaded))
        return rows

    def _list_evolution_games_from_disk(self) -> list[dict[str, Any]]:
        if not self.paths.evolution_dir.exists():
            return []
        rows: list[dict[str, Any]] = []
        for run_dir in sorted((item for item in self.paths.evolution_dir.iterdir() if item.is_dir()), key=lambda item: item.name, reverse=True):
            for phase_dir in sorted((item for item in run_dir.iterdir() if item.is_dir()), key=lambda item: item.name):
                for game_dir in sorted((item for item in phase_dir.iterdir() if item.is_dir()), key=lambda item: item.name):
                    public_id = self._log_source_id(
                        "evolution",
                        run_dir.name,
                        game_dir.name,
                        phase=phase_dir.name,
                    )
                    loaded = self._load_game_from_directory(
                        game_dir,
                        public_game_id=public_id,
                        source="evolution",
                        source_run_id=run_dir.name,
                        source_phase=phase_dir.name,
                    )
                    if loaded is not None:
                        rows.append(self._game_list_row(loaded))
        return rows

    async def start_game(self, request: GameStartRequest) -> dict[str, Any]:
        game_id = f"ui_{uuid.uuid4().hex[:12]}"
        skill_dir = self.skill_dir_for_request(request)
        return await self.start_live_game(game_id=game_id, request=request, skill_dir=skill_dir)

    async def start_live_game(self, *, game_id: str, request: GameStartRequest, skill_dir: str | None) -> dict[str, Any]:
        human_player_id = request.human_player_id
        if human_player_id is not None and (human_player_id < 1 or human_player_id > request.player_count):
            raise HTTPException(status_code=400, detail="human_player_id must be a valid player seat")

        from dataclasses import replace

        from app.lib.game import create_agents, create_engine
        from app.lib.store import AgentDecisionRecorder
        from engine import STANDARD_12, GameLogger, assign_roles

        config = replace(STANDARD_12, max_days=request.max_days, enable_sheriff=request.enable_sheriff)
        roles = assign_roles(config, seed=request.seed)
        event_sink = BroadcastEventSink()
        recorder = AgentDecisionRecorder(sink=event_sink)
        agents = create_agents(
            roles,
            client=self.model_for_run(),
            decision_recorder=recorder,
            game_id=game_id,
            skill_dir=skill_dir,
            human_player_id=human_player_id,
            paths=self.paths,
        )
        game_dir = self.paths.games_dir / game_id
        logger = GameLogger(stream_path=game_dir / "game_events.jsonl", sink=event_sink)
        engine = create_engine(
            roles,
            agents,
            seed=request.seed or 0,
            max_days=request.max_days,
            enable_sheriff=request.enable_sheriff,
            logger=logger,
        )
        session = LiveGameSession(
            game_id=game_id,
            request=request,
            engine=engine,
            recorder=recorder,
            human=agents.get(human_player_id) if human_player_id is not None else None,
            event_sink=event_sink,
            skill_dir=skill_dir,
        )
        self.live_sessions[game_id] = session
        session.task = asyncio.create_task(self.run_live_session(game_id))
        snapshot = session.snapshot()
        self.games[game_id] = snapshot
        self.invalidate_game_history_index()
        return snapshot

    async def run_live_session(self, game_id: str) -> None:
        session = self.live_sessions.get(game_id)
        if session is None:
            return
        try:
            await session.run()
            snapshot = session.snapshot()
            self.games[game_id] = snapshot
            self.write_live_session_files(session, snapshot)
        finally:
            if self.live_sessions.get(game_id) is session and session.status in LIVE_GAME_TERMINAL_STATUSES:
                self.live_sessions.pop(game_id, None)

    def check_live_game_watchdog(
        self,
        *,
        timeout_seconds: float | None = None,
    ) -> list[dict[str, Any]]:
        resolved_timeout = (
            timeout_seconds if timeout_seconds is not None else self._live_game_heartbeat_timeout_seconds()
        )
        interrupted: list[dict[str, Any]] = []
        for game_id, session in list(self.live_sessions.items()):
            status = str(getattr(session, "status", "") or "").lower()
            if status in LIVE_GAME_TERMINAL_STATUSES:
                continue
            if not hasattr(session, "mark_interrupted"):
                continue
            if not live_game_heartbeat_timed_out(
                getattr(session, "last_heartbeat_at", None),
                timeout_seconds=resolved_timeout,
            ):
                continue
            session.mark_interrupted(
                "live game heartbeat timed out",
                stage="live_game.watchdog",
                kind="live_game_heartbeat_timeout",
                timeout_seconds=resolved_timeout,
            )
            snapshot = session.snapshot()
            self.games[game_id] = snapshot
            try:
                self.write_live_session_files(session, snapshot)
            except Exception:
                # Keep the interrupted state visible even if archival persistence fails.
                pass
            self.live_sessions.pop(game_id, None)
            interrupted.append(snapshot)
        if interrupted:
            self.invalidate_game_history_index()
        return interrupted

    def get_game(self, game_id: str) -> dict[str, Any] | None:
        self.check_live_game_watchdog()
        external = self._load_external_game_from_disk(game_id)
        if external is not None:
            return external
        live = self.live_sessions.get(game_id)
        if live is not None:
            snapshot = live.snapshot()
            self.games[game_id] = snapshot
            if live.status in LIVE_GAME_TERMINAL_STATUSES:
                self.write_live_session_files(live, snapshot)
            return snapshot
        if game_id in self.games:
            return self.games[game_id]
        loaded = self.load_game_from_disk(game_id)
        if loaded is not None:
            self.games[game_id] = loaded
        return loaded

    def _build_game_history_rows(self) -> list[dict[str, Any]]:
        self.check_live_game_watchdog()
        games = {game_id: game for game_id, game in self.games.items()}
        for game_id, session in self.live_sessions.items():
            games[game_id] = session.snapshot()
        if self.paths.games_dir.exists():
            for child in self.paths.games_dir.iterdir():
                if not child.is_dir() or child.name in games:
                    continue
                loaded = self.load_game_from_disk(child.name)
                if loaded is not None:
                    games[child.name] = loaded
        rows = [
            self._game_list_row(game)
            for game in sorted(games.values(), key=lambda item: str(item.get("game_id", "")), reverse=True)
        ]
        rows.extend(self._list_benchmark_games_from_disk())
        rows.extend(self._list_evolution_games_from_disk())
        return sorted(rows, key=lambda item: str(item.get("log_time") or item.get("game_id") or ""), reverse=True)

    def list_games(self) -> list[dict[str, Any]]:
        self.check_live_game_watchdog()
        return self._build_game_history_rows()

    def query_game_history(
        self,
        *,
        sources: set[str] | None = None,
        statuses: set[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        self.check_live_game_watchdog()
        rows = self._game_history_index().rows()
        filtered = rows
        if sources is not None:
            filtered = [row for row in filtered if _match_filter(row.get("log_source", "normal"), sources)]
        if statuses is not None:
            filtered = [row for row in filtered if _match_filter(row.get("status"), statuses)]
        page, pagination = _pagination(filtered, limit=limit, offset=offset)
        counts = source_counts(rows)
        return {
            "games": page,
            "pagination": pagination,
            "counts": counts,
            "facets": history_facets(rows),
        }

    def get_human_action(self, game_id: str) -> dict[str, Any] | None:
        self.check_live_game_watchdog()
        live = self.live_sessions.get(game_id)
        if live is not None:
            return live.pending_action()
        if self.get_game(game_id) is None:
            raise HTTPException(status_code=404, detail="game not found")
        return None

    def submit_human_action(self, game_id: str, request: HumanActionRequest) -> dict[str, Any]:
        self.check_live_game_watchdog()
        live = self.live_sessions.get(game_id)
        if live is None:
            if self.get_game(game_id) is None:
                raise HTTPException(status_code=404, detail="game not found")
            raise HTTPException(status_code=409, detail="game is not waiting for human input")
        if not live.submit(request):
            raise HTTPException(status_code=409, detail="game is not waiting for human input")
        snapshot = live.snapshot()
        self.games[game_id] = snapshot
        return snapshot

    def stop_game(self, game_id: str) -> dict[str, Any]:
        live = self.live_sessions.get(game_id)
        if live is not None:
            live.cancel()
            snapshot = live.snapshot()
            self.games[game_id] = snapshot
            if live.task is None or live.task.done():
                self.write_live_session_files(live, snapshot)
            return snapshot
        game = self.get_game(game_id)
        if game is None:
            now = beijing_now_iso()
            return {
                "game_id": game_id,
                "status": "cancelled",
                "stop_requested": True,
                "cancelled": True,
                "interrupted": False,
                "failed": False,
                "cancelled_at": now,
                "finished_at": now,
                "error": "cancelled",
                "players": [],
                "logs": [],
                "decisions": [],
            }
        now = beijing_now_iso()
        stopped = {
            **game,
            "status": "cancelled",
            "stop_requested": True,
            "cancelled": True,
            "interrupted": False,
            "failed": False,
            "cancelled_at": game.get("cancelled_at") or now,
            "finished_at": game.get("finished_at") or now,
            "error": game.get("error") or "cancelled",
        }
        self.games[game_id] = stopped
        return stopped

    def snapshot_from_result(
        self,
        result: dict[str, Any],
        *,
        mode: str,
        config: dict[str, Any],
    ) -> dict[str, Any]:
        game_id = str(result.get("game_id") or f"ui_{uuid.uuid4().hex[:12]}")
        events = list(result.get("events", []) or [])
        decisions = list(result.get("decisions", []) or [])
        roles = _normalize_roles(result.get("player_roles", {}))
        deaths = _dead_players(events)
        last_event = events[-1] if events else {}
        sheriff_id = _sheriff_from_events(events)
        players = [
            {
                "id": player_id,
                "seat": player_id,
                "name": f"{player_id}号",
                "role": role,
                "role_hint": _role_label(role),
                "team": _team_for_role(role),
                "alive": player_id not in deaths,
                "is_sheriff": player_id == sheriff_id,
                "is_human": False,
                "role_state": {},
            }
            for player_id, role in sorted(roles.items())
        ]
        normalized_decisions = [_normalize_decision(d, index) for index, d in enumerate(decisions, start=1)]
        review = _frontend_review(result.get("review"), events=events)
        day = int(last_event.get("day", 0) or 0) if isinstance(last_event, dict) else 0
        phase = str(last_event.get("phase", "finished") or "finished") if isinstance(last_event, dict) else "finished"
        diagnostics = result.get("diagnostics") if isinstance(result.get("diagnostics"), list) else []
        last_heartbeat_at = result.get("last_heartbeat_at") or config.get("last_heartbeat_at")
        manifest = result.get("manifest") if isinstance(result.get("manifest"), dict) else config.get("manifest")
        if not isinstance(manifest, dict):
            manifest = {
                "schema_version": 1,
                "run_type": "game",
                "game_id": game_id,
                "status": result.get("status", "completed"),
            }
        return {
            "game_id": game_id,
            "log_name": game_id,
            "status": result.get("status", "completed"),
            "stop_requested": bool(result.get("stop_requested", False)),
            "cancelled": bool(result.get("cancelled", False)),
            "interrupted": bool(result.get("interrupted", False)),
            "failed": bool(result.get("failed", result.get("status") == "failed")),
            "cancelled_at": result.get("cancelled_at"),
            "interrupted_at": result.get("interrupted_at"),
            "last_heartbeat_at": last_heartbeat_at,
            "mode": mode,
            "winner": result.get("winner"),
            "seed": result.get("seed") or config.get("seed"),
            "started_at": result.get("started_at") or config.get("started_at"),
            "finished_at": result.get("finished_at") or config.get("finished_at"),
            "log_time": (
                result.get("finished_at")
                or result.get("started_at")
                or result.get("last_heartbeat_at")
                or config.get("finished_at")
                or config.get("started_at")
                or config.get("last_heartbeat_at")
            ),
            "max_days": config.get("max_days"),
            "enable_sheriff": config.get("enable_sheriff", True),
            "skill_dir": config.get("skill_dir"),
            "human_player_id": None,
            "player_count": len(players) or int(config.get("player_count", 12) or 12),
            "day": day,
            "phase": phase,
            "sheriff_id": sheriff_id,
            "players": players,
            "logs": [_normalize_event(e) for e in events],
            "events": [_normalize_event(e) for e in events],
            "decisions": normalized_decisions,
            "review": review,
            "diagnostics": list(diagnostics),
            "waiting_for": "none",
            "pending_action": None,
            "pending_human_action": None,
            "current_speaker_id": None,
            "vote_tally": _vote_tally(
                normalized_decisions,
                current_day=day,
                current_phase=phase,
            ),
            "role_counts": dict(Counter(player["role"] for player in players)),
            "role_skill_dirs": dict(config.get("role_versions", {}) or {}),
            "config": config,
            "manifest": manifest,
            "error": result.get("error"),
        }

    def write_game_files(self, game_id: str, snapshot: dict[str, Any], result: dict[str, Any]) -> None:
        game_dir = self.paths.games_dir / game_id
        game_dir.mkdir(parents=True, exist_ok=True)
        write_json(game_dir / "ui_snapshot.json", snapshot)
        write_json(game_dir / "review.json", snapshot.get("review") or {})
        write_json(game_dir / "archive.json", _archive_payload(game_id, snapshot))
        self.invalidate_game_history_index()

    def write_live_session_files(self, session: LiveGameSession, snapshot: dict[str, Any] | None = None) -> None:
        with session.persist_lock:
            if session.files_written:
                return
            session.files_written = True
        try:
            self.write_game_files(session.game_id, snapshot or session.snapshot(), session.result())
        except Exception:
            with session.persist_lock:
                session.files_written = False
            raise

    def load_game_from_disk(self, game_id: str) -> dict[str, Any] | None:
        return self._load_game_from_directory(
            self.paths.games_dir / game_id,
            public_game_id=game_id,
            source="normal",
        )


