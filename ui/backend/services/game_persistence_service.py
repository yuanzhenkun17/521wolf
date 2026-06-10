"""Game snapshot persistence helpers for the UI backend."""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from app.util.json import to_jsonable
from app.util.time import beijing_now_iso
from storage.public_events import public_events_only
from storage.runtime import GamePersistence
from ui.backend.serializers import (
    _dead_players,
    _frontend_review,
    _normalize_decision,
    _normalize_event,
    _normalize_roles,
    _role_label,
    _sheriff_from_events,
    _team_for_role,
    _vote_tally,
)


class GamePersistenceService:
    """Convert UI game snapshots to storage payloads and persist them."""

    def __init__(self, store: Any) -> None:
        self._store = store

    @property
    def paths(self) -> Any:
        return self._store.paths

    def create_game_persistence(self, game_id: str, *, run_metadata: dict[str, Any]) -> GamePersistence:
        game_persistence = self._game_persistence_class()
        return game_persistence(
            game_id=game_id,
            provider=self._storage_provider_from_env(),
            run_metadata=run_metadata,
        )

    def persist_snapshot_to_pg(
        self,
        snapshot: dict[str, Any],
        *,
        persistence: GamePersistence | None = None,
    ) -> None:
        game_id = str(snapshot.get("game_id") or "")
        if not game_id:
            raise ValueError("snapshot game_id is required for PostgreSQL persistence")

        owns_persistence = persistence is None
        if persistence is None:
            game_persistence = self._game_persistence_class()
            persistence = game_persistence(
                game_id=game_id,
                provider=self._storage_provider_from_env(),
                run_metadata={
                    "mode": snapshot.get("mode") or "watch",
                    "source_run_id": game_id,
                    "ruleset_version": "werewolf_12p_v1",
                },
            )

        try:
            config = self.pg_snapshot_config(snapshot)
            events = self.pg_snapshot_events(snapshot)
            final_state = self.pg_snapshot_final_state(snapshot)
            player_roles = self.pg_snapshot_player_roles(snapshot)
            final_alive = self.pg_snapshot_final_alive(snapshot)
            persistence.save_game_result(
                seed=self.pg_snapshot_seed(snapshot),
                player_roles=player_roles,
                config=config,
                winner=self.pg_snapshot_winner(snapshot),
                started_at=str(snapshot.get("started_at") or config.get("started_at") or beijing_now_iso()),
                finished_at=snapshot.get("finished_at"),
                total_rounds=self.pg_snapshot_total_rounds(snapshot, events),
                public_events=public_events_only(events),
                final_state=final_state,
                deaths=self.pg_snapshot_deaths(snapshot),
                final_alive=final_alive,
            )
        finally:
            if owns_persistence:
                persistence.close()

    def _storage_provider_from_env(self) -> Any:
        import ui.backend.game_store as game_store_mod

        return game_store_mod.storage_provider_from_env(paths=self.paths)

    @staticmethod
    def _game_persistence_class() -> Any:
        import ui.backend.game_store as game_store_mod

        return game_store_mod.GamePersistence

    def pg_snapshot_config(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        config = dict(snapshot.get("config") if isinstance(snapshot.get("config"), dict) else {})
        config.update(
            {
                "seed": snapshot.get("seed", config.get("seed")),
                "max_days": snapshot.get("max_days", config.get("max_days")),
                "enable_sheriff": snapshot.get("enable_sheriff", config.get("enable_sheriff", True)),
                "skill_dir": snapshot.get("skill_dir", config.get("skill_dir")),
                "role_versions": dict(
                    snapshot.get("role_skill_dirs")
                    if isinstance(snapshot.get("role_skill_dirs"), dict)
                    else config.get("role_versions") or {}
                ),
                "role_skill_dirs": dict(
                    snapshot.get("role_skill_dirs")
                    if isinstance(snapshot.get("role_skill_dirs"), dict)
                    else config.get("role_skill_dirs") or {}
                ),
                "player_count": snapshot.get("player_count", config.get("player_count", 12)),
                "human_player_id": snapshot.get("human_player_id", config.get("human_player_id")),
                "mode": snapshot.get("mode", config.get("mode", "watch")),
                "log_source": snapshot.get("log_source", config.get("log_source", "normal")),
                "log_name": snapshot.get("log_name", config.get("log_name", snapshot.get("game_id"))),
                "source_game_id": snapshot.get(
                    "source_game_id",
                    config.get("source_game_id", snapshot.get("game_id")),
                ),
                "started_at": snapshot.get("started_at", config.get("started_at")),
                "finished_at": snapshot.get("finished_at", config.get("finished_at")),
                "last_heartbeat_at": snapshot.get("last_heartbeat_at", config.get("last_heartbeat_at")),
            }
        )
        return to_jsonable(config)

    def pg_snapshot_final_state(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "game_id",
            "log_name",
            "status",
            "stop_requested",
            "cancelled",
            "interrupted",
            "failed",
            "cancelled_at",
            "interrupted_at",
            "last_heartbeat_at",
            "mode",
            "winner",
            "seed",
            "max_days",
            "enable_sheriff",
            "skill_dir",
            "human_player_id",
            "player_count",
            "day",
            "phase",
            "sheriff_id",
            "review",
            "diagnostics",
            "waiting_for",
            "pending_action",
            "pending_human_action",
            "current_speaker_id",
            "vote_tally",
            "role_counts",
            "role_skill_dirs",
            "started_at",
            "finished_at",
            "manifest",
            "error",
        )
        final_state = {key: snapshot.get(key) for key in fields if key in snapshot}
        final_state.setdefault("status", "running")
        final_state["config"] = self.pg_snapshot_config(snapshot)
        final_state["players"] = list(snapshot.get("players") or [])
        final_state["deaths"] = self.pg_snapshot_deaths(snapshot)
        return to_jsonable(final_state)

    @staticmethod
    def pg_snapshot_events(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        raw_events = snapshot.get("events") or snapshot.get("logs") or []
        return [to_jsonable(event) for event in raw_events if isinstance(event, dict)]

    @staticmethod
    def pg_snapshot_player_roles(snapshot: dict[str, Any]) -> dict[int, str]:
        roles: dict[int, str] = {}
        player_roles = snapshot.get("player_roles")
        if isinstance(player_roles, dict):
            for player_id, role in player_roles.items():
                try:
                    roles[int(player_id)] = str(role)
                except (TypeError, ValueError):
                    continue
        for player in snapshot.get("players") or []:
            if not isinstance(player, dict):
                continue
            seat = player.get("seat", player.get("id"))
            role = player.get("role")
            if seat is None or role is None:
                continue
            try:
                roles[int(seat)] = str(role)
            except (TypeError, ValueError):
                continue
        return roles

    @staticmethod
    def pg_snapshot_final_alive(snapshot: dict[str, Any]) -> dict[int, bool] | None:
        alive: dict[int, bool] = {}
        for player in snapshot.get("players") or []:
            if not isinstance(player, dict):
                continue
            seat = player.get("seat", player.get("id"))
            if seat is None:
                continue
            try:
                alive[int(seat)] = bool(player.get("alive", True))
            except (TypeError, ValueError):
                continue
        return alive or None

    def pg_snapshot_deaths(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        raw_deaths = snapshot.get("deaths")
        if isinstance(raw_deaths, list):
            return [to_jsonable(death) for death in raw_deaths if isinstance(death, dict)]
        deaths: dict[int, dict[str, Any]] = {}
        for event in self.pg_snapshot_events(snapshot):
            event_type = str(event.get("event_type") or event.get("type") or "")
            if event_type != "death":
                continue
            target = event.get("target")
            try:
                seat = int(target)
            except (TypeError, ValueError):
                continue
            deaths[seat] = {
                "player_id": seat,
                "day": event.get("day"),
                "phase": event.get("phase"),
                "cause": (event.get("payload") if isinstance(event.get("payload"), dict) else {}).get("cause"),
            }
        return list(deaths.values())

    def pg_snapshot_total_rounds(self, snapshot: dict[str, Any], events: list[dict[str, Any]]) -> int:
        days = [self.safe_int(snapshot.get("day"), default=0)]
        for event in events:
            days.append(self.safe_int(event.get("day"), default=0))
        return max(days) if days else 0

    def pg_snapshot_seed(self, snapshot: dict[str, Any]) -> int:
        config = snapshot.get("config") if isinstance(snapshot.get("config"), dict) else {}
        return self.safe_int(snapshot.get("seed", config.get("seed")), default=0)

    @staticmethod
    def pg_snapshot_winner(snapshot: dict[str, Any]) -> str | None:
        winner = snapshot.get("winner")
        return str(winner) if winner is not None and str(winner) else None

    @staticmethod
    def safe_int(value: Any, *, default: int) -> int:
        try:
            if value is None or value == "":
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def snapshot_from_result(
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


__all__ = ["GamePersistenceService"]
