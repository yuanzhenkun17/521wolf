from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playeragent.decision_log import AgentDecisionRecorder
from werewolf.engine import GameEngine
from werewolf.llm_agents import create_llm_demo_agents
from werewolf.logging import next_game_log_name
from werewolf.roles import random_standard_roles


LOG_DIR = Path("logs")


@dataclass(slots=True)
class RunningGame:
    game_id: str
    log_name: str
    seed: int | None
    status: str = "starting"
    winner: str | None = None
    engine: GameEngine | None = None
    error: str | None = None
    decision_recorder: AgentDecisionRecorder | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    task: asyncio.Task[None] | None = None

    @property
    def is_active(self) -> bool:
        return self.status in {"starting", "running"}


class GameManager:
    def __init__(self, log_dir: Path = LOG_DIR) -> None:
        self.log_dir = log_dir
        self._games: dict[str, RunningGame] = {}
        self._lock = asyncio.Lock()

    async def start_game(self, seed: int | None = None) -> RunningGame:
        async with self._lock:
            active = next((game for game in self._games.values() if game.is_active), None)
            if active is not None:
                raise RuntimeError(f"{active.game_id} is still running")

            log_name = next_game_log_name(self.log_dir)
            game = RunningGame(game_id=log_name, log_name=log_name, seed=seed)
            self._games[game.game_id] = game
            game.task = asyncio.create_task(self._run_game(game), name=f"werewolf-{game.game_id}")
            return game

    def get_game(self, game_id: str) -> RunningGame | None:
        return self._games.get(game_id) or self._load_completed_game(game_id)

    def list_games(self) -> list[dict[str, Any]]:
        seen = set()
        games: list[dict[str, Any]] = []
        for game in self._games.values():
            games.append(self.snapshot(game, include_events=False))
            seen.add(game.log_name)
        for path in self.log_dir.glob("game*.jsonl"):
            if not _is_game_log_path(path):
                continue
            if path.stem in seen:
                continue
            events = self._read_events(path)
            games.append(self._snapshot_from_events(path.stem, events, include_events=False))
        return sorted(games, key=lambda game: _game_sort_key(str(game["game_id"])), reverse=True)

    def snapshot(self, game: RunningGame, include_events: bool = True) -> dict[str, Any]:
        engine = game.engine
        state = engine.state if engine is not None else None
        if state is None and game.events:
            return self._snapshot_from_events(game.game_id, game.events, include_events)
        players = []
        if state is not None:
            players = [
                {
                    "id": player.id,
                    "role": player.role.value,
                    "team": player.team.value,
                    "alive": player.alive,
                    "is_sheriff": state.sheriff_id == player.id,
                }
                for player in state.players.values()
            ]
        return {
            "game_id": game.game_id,
            "log_name": game.log_name,
            "status": game.status,
            "winner": game.winner,
            "seed": game.seed,
            "day": state.day if state is not None else 0,
            "phase": state.phase.value if state is not None else "setup",
            "sheriff_id": state.sheriff_id if state is not None else None,
            "players": players,
            "event_count": len(game.events),
            "events": game.events if include_events else [],
            "decisions": self._decision_dicts(game) if include_events else [],
            "error": game.error,
        }

    async def subscribe(self, game: RunningGame) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        for event in game.events:
            queue.put_nowait({"kind": "log", "payload": event})
        if game.status in {"completed", "failed"}:
            queue.put_nowait({"kind": "done", "payload": self.snapshot(game, include_events=False)})
            return queue
        game.subscribers.add(queue)
        return queue

    def unsubscribe(self, game: RunningGame, queue: asyncio.Queue[dict[str, Any]]) -> None:
        game.subscribers.discard(queue)

    async def _run_game(self, game: RunningGame) -> None:
        game.status = "running"
        cursor = 0
        try:
            roles = random_standard_roles(seed=game.seed)
            game.decision_recorder = AgentDecisionRecorder()
            game.engine = GameEngine(roles, create_llm_demo_agents(roles, decision_recorder=game.decision_recorder))
            task = asyncio.create_task(game.engine.run_until_finished(max_days=20))
            while not task.done():
                cursor = await self._publish_new_entries(game, cursor)
                await asyncio.sleep(0.1)
            winner = await task
            cursor = await self._publish_new_entries(game, cursor)
            game.winner = winner.value
            game.engine.logger.write_jsonl(self.log_dir / f"{game.log_name}.jsonl")
            game.engine.logger.write_text(self.log_dir / f"{game.log_name}.txt")
            game.decision_recorder.write_jsonl(self.log_dir / f"{game.log_name}.agent.jsonl")
            game.status = "completed"
            await self._broadcast(game, {"kind": "done", "payload": self.snapshot(game, include_events=False)})
        except Exception as exc:
            game.error = str(exc)
            game.status = "failed"
            await self._broadcast(game, {"kind": "error", "payload": {"message": str(exc)}})

    async def _publish_new_entries(self, game: RunningGame, cursor: int) -> int:
        if game.engine is None:
            return cursor
        entries = game.engine.logger.entries
        for entry in entries[cursor:]:
            payload = entry.to_dict()
            game.events.append(payload)
            await self._broadcast(game, {"kind": "log", "payload": payload})
        return len(entries)

    async def _broadcast(self, game: RunningGame, item: dict[str, Any]) -> None:
        for queue in tuple(game.subscribers):
            queue.put_nowait(item)

    def _load_completed_game(self, game_id: str) -> RunningGame | None:
        path = self.log_dir / f"{game_id}.jsonl"
        if not path.exists():
            return None
        events = self._read_events(path)
        game = RunningGame(game_id=game_id, log_name=game_id, seed=None, status="completed")
        game.events = events
        game.winner = self._winner_from_events(events)
        self._games[game_id] = game
        return game

    def _read_events(self, path: Path) -> list[dict[str, Any]]:
        try:
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except OSError:
            return []

    def _snapshot_from_events(
        self,
        game_id: str,
        events: list[dict[str, Any]],
        include_events: bool,
    ) -> dict[str, Any]:
        last_event = events[-1] if events else {}
        sheriff_id = self._sheriff_from_events(events)
        return {
            "game_id": game_id,
            "log_name": game_id,
            "status": "completed",
            "winner": self._winner_from_events(events),
            "seed": None,
            "day": last_event.get("day", 0),
            "phase": last_event.get("phase", "finished"),
            "sheriff_id": sheriff_id,
            "players": self._players_from_events(events, sheriff_id),
            "event_count": len(events),
            "events": events if include_events else [],
            "decisions": self._read_decisions(game_id) if include_events else [],
            "error": None,
        }

    def _decision_dicts(self, game: RunningGame) -> list[dict[str, Any]]:
        if game.decision_recorder is not None:
            return [
                {**record.to_dict(), "index": index}
                for index, record in enumerate(game.decision_recorder.records, start=1)
            ]
        return self._read_decisions(game.log_name)

    def _read_decisions(self, game_id: str) -> list[dict[str, Any]]:
        path = self.log_dir / f"{game_id}.agent.jsonl"
        if not path.exists():
            return []
        decisions: list[dict[str, Any]] = []
        try:
            for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if isinstance(value, dict):
                    value.setdefault("index", index)
                    decisions.append(value)
        except (OSError, json.JSONDecodeError):
            return []
        return decisions

    def _winner_from_events(self, events: list[dict[str, Any]]) -> str | None:
        for event in reversed(events):
            winner = event.get("payload", {}).get("winner")
            if winner:
                return str(winner)
        return None

    def _players_from_events(self, events: list[dict[str, Any]], sheriff_id: int | None) -> list[dict[str, Any]]:
        roles: dict[int, str] = {}
        dead: set[int] = set()
        for event in events:
            if event.get("event_type") == "game_init":
                raw_roles = event.get("payload", {}).get("roles", {})
                if isinstance(raw_roles, dict):
                    roles = {int(player_id): str(role) for player_id, role in raw_roles.items()}
            if event.get("event_type") == "death" and event.get("target") is not None:
                dead.add(int(event["target"]))
        return [
            {
                "id": player_id,
                "role": role,
                "team": _team_for_role(role),
                "alive": player_id not in dead,
                "is_sheriff": sheriff_id == player_id,
            }
            for player_id, role in sorted(roles.items())
        ]

    def _sheriff_from_events(self, events: list[dict[str, Any]]) -> int | None:
        sheriff_id = None
        for event in events:
            event_type = event.get("event_type")
            if event_type == "sheriff_election_end":
                winner = event.get("payload", {}).get("winner")
                sheriff_id = int(winner) if winner is not None else None
            elif event_type == "sheriff_badge_destroy":
                sheriff_id = None
            elif event_type == "sheriff_badge_transfer":
                match = re.search(r"给 (\d+) 号", str(event.get("message", "")))
                if match:
                    sheriff_id = int(match.group(1))
        return sheriff_id


def _team_for_role(role: str) -> str:
    if role in {"werewolf", "white_wolf_king"}:
        return "werewolves"
    if role == "villager":
        return "villagers"
    return "gods"


def _game_sort_key(game_id: str) -> tuple[int, str]:
    match = re.fullmatch(r"game(\d+)", game_id)
    if match:
        return int(match.group(1)), game_id
    return 0, game_id


def _is_game_log_path(path: Path) -> bool:
    return re.fullmatch(r"game\d+", path.stem) is not None
