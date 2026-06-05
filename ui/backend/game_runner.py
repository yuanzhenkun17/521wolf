from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent.common import beijing_now_iso
from agent.common.json import to_jsonable
from ui.backend.runner_utils import RunnerStatus
from agent.common.paths import PathConfig, DEFAULT as DEFAULT_PATHS
from agent.common.run_policy import RunType, policy_for_run_type
from agent.infrastructure.archive import AgentTraceRecorder
from agent.infrastructure.decision_log import AgentDecisionRecorder
from agent.api.factory import create_agents, load_llm_client
from agent.learning.review.service import ReviewService
from storage.replay import read_config_for_artifact, read_decisions_for_artifact, read_events_for_artifact
from storage.runtime import GamePersistence
from engine.config import GameConfig, STANDARD_12
from engine.engine import GameEngine
from engine.logging import next_game_log_name
from engine.models import ActionResponse, ActionType, Observation
from engine.players import HumanPlayer
from engine.roles import random_standard_roles

_log = logging.getLogger(__name__)


@dataclass(slots=True)
class _GameManagerPaths:
    games_dir: Path
    data_dir: Path
    runs_dir: Path


@dataclass(slots=True)
class RunningGame:
    game_id: str
    log_name: str
    seed: int | None
    max_days: int = 20
    enable_sheriff: bool = True
    skill_dir: str | None = None
    role_skill_dirs: dict[str, Path] | None = None
    human_player_id: int | None = None
    player_count: int = 12
    status: str = "starting"
    winner: str | None = None
    engine: GameEngine | None = None
    error: str | None = None
    decision_recorder: AgentDecisionRecorder | None = None
    trace_recorder: AgentTraceRecorder | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    task: asyncio.Task[None] | None = None

    @property
    def is_active(self) -> bool:
        return self.status in {"starting", RunnerStatus.RUNNING}


class GameManager:
    def __init__(
        self,
        paths: PathConfig = DEFAULT_PATHS,
        *,
        log_dir: str | Path | None = None,
        db_path: str | Path | None = None,
        game_run_service: Any | None = None,
    ) -> None:
        self._paths = (
            _GameManagerPaths(
                games_dir=Path(log_dir),
                data_dir=paths.data_dir,
                runs_dir=Path(log_dir).parent,
            )
            if log_dir is not None
            else paths
        )
        self._db_path = (
            Path(db_path)
            if db_path is not None
            else (paths.data_dir / "wolf.db" if log_dir is None else None)
        )
        self._paths.games_dir.mkdir(parents=True, exist_ok=True)
        self._games: dict[str, RunningGame] = {}
        self._lock = asyncio.Lock()
        self._game_run_service = game_run_service

    async def start_game(
        self,
        seed: int | None = None,
        max_days: int = 20,
        enable_sheriff: bool = True,
        skill_dir: str | None = None,
        player_count: int = 12,
        role_skill_dirs: dict[str, Path] | None = None,
        human_player_id: int | None = None,
    ) -> RunningGame:
        async with self._lock:
            active = next((game for game in self._games.values() if game.is_active), None)
            if active is not None:
                raise RuntimeError(f"{active.game_id} is still running")
            if human_player_id is not None and not 1 <= human_player_id <= player_count:
                raise ValueError("human_player_id must be between 1 and player_count")

            log_name = next_game_log_name(self._paths.games_dir)
            game = RunningGame(
                game_id=log_name,
                log_name=log_name,
                seed=seed,
                max_days=max_days,
                enable_sheriff=enable_sheriff,
                skill_dir=skill_dir,
                role_skill_dirs=role_skill_dirs,
                human_player_id=human_player_id,
                player_count=player_count,
            )
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
        for path in sorted(self._paths.games_dir.iterdir()):
            game_id = _game_id_from_log_path(path)
            if game_id is None:
                continue
            if game_id in seen:
                continue
            events = self._read_game_events(game_id)
            if events is None:
                continue
            games.append(self._snapshot_from_events(game_id, events, include_events=False))
        return sorted(games, key=lambda game: _game_sort_key(str(game["game_id"])), reverse=True)

    def snapshot(self, game: RunningGame, include_events: bool = True) -> dict[str, Any]:
        engine = game.engine
        state = engine.state if engine is not None else None
        if state is None and game.events:
            return self._snapshot_from_events(game.game_id, game.events, include_events)
        config = self._game_config_payload(game)
        players = []
        if state is not None:
            players = [
                {
                    "id": player.id,
                    "role": player.role.value,
                    "team": player.team.value,
                    "alive": player.alive,
                    "is_sheriff": state.sheriff_id == player.id,
                    "is_human": game.human_player_id == player.id,
                    "role_state": dict(player.role_state) if player.role_state else {},
                }
                for player in state.players.values()
            ]
        return {
            "game_id": game.game_id,
            "log_name": game.log_name,
            "status": game.status,
            "winner": game.winner,
            "seed": game.seed,
            "config": config,
            "max_days": game.max_days,
            "enable_sheriff": game.enable_sheriff,
            "skill_dir": game.skill_dir,
            "role_skill_dirs": config["role_skill_dirs"],
            "human_player_id": game.human_player_id,
            "player_count": game.player_count,
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
        pending_human_action = self._pending_human_action_for(game)
        if pending_human_action is not None:
            queue.put_nowait({"kind": "decision_needed", "payload": pending_human_action})
        if game.status in RunnerStatus.terminal_statuses():
            queue.put_nowait({"kind": "done", "payload": self.snapshot(game, include_events=False)})
            return queue
        game.subscribers.add(queue)
        return queue

    def unsubscribe(self, game: RunningGame, queue: asyncio.Queue[dict[str, Any]]) -> None:
        game.subscribers.discard(queue)

    async def _run_game(self, game: RunningGame) -> None:
        game.status = RunnerStatus.RUNNING
        cursor = 0
        persistence: GamePersistence | None = None
        started_at = beijing_now_iso()
        try:
            roles = random_standard_roles(seed=game.seed)
            game_dir = self._game_dir(game.log_name)
            run_policy = policy_for_run_type(RunType.ORDINARY_GAME)
            if self._game_run_service is not None:
                from agent.game_run.service import GameRunConfig
                run_config = GameRunConfig(
                    run_type=RunType.ORDINARY_GAME,
                    mode="dev",
                    max_days=game.max_days,
                )
                handle = self._game_run_service.create_run(run_config)
                persistence = handle.persistence
                persistence.game_dir = game_dir
                game.game_id = handle.run_id
            else:
                persistence = GamePersistence(
                    game_id=game.game_id,
                    game_dir=game_dir,
                    db_path=self._db_path,
                    run_policy=run_policy,
                    run_metadata={"mode": "dev", "ruleset_version": "werewolf_12p_v1"},
                )

            game.decision_recorder = persistence.create_decision_recorder()
            game.trace_recorder = AgentTraceRecorder()
            client = load_llm_client()
            game_config = GameConfig(
                name=STANDARD_12.name,
                role_counts=STANDARD_12.role_counts,
                enable_sheriff=game.enable_sheriff,
                max_days=game.max_days,
                sheriff_vote_weight=STANDARD_12.sheriff_vote_weight,
                night_order=STANDARD_12.night_order,
            )
            game.engine = GameEngine(
                roles,
                create_agents(
                    roles,
                    client=client,
                    decision_recorder=game.decision_recorder,
                    trace_recorder=game.trace_recorder,
                    game_id=game.game_id,
                    skill_dir=game.skill_dir,
                    role_skill_dirs=game.role_skill_dirs,
                    human_player_id=game.human_player_id,
                    paths=self._paths,
                ),
                config=game_config,
                logger=persistence.create_event_logger(game_dir / "game_events.jsonl"),
            )
            task = asyncio.create_task(game.engine.run_until_finished())
            while not task.done():
                cursor = await self._publish_new_entries(game, cursor)
                await asyncio.sleep(0.1)
            winner = await task
            cursor = await self._publish_new_entries(game, cursor)
            game.winner = winner.value
            config = self._game_config_payload(game)
            player_roles_dict = {pid: r.value for pid, r in roles.items()}
            # game_events.jsonl already written via streaming; decisions in archive.json
            if game.trace_recorder is not None:
                game.trace_recorder.flush(
                    game_id=game.log_name,
                    output_dir=game_dir,
                    seed=game.seed or 0,
                    config=config,
                    player_roles=player_roles_dict,
                    winner=game.winner,
                    public_events=game.events,
                    final_state={"player_roles": player_roles_dict, "winner": game.winner, "config": config},
                )
            # Write game + player records to SQLite
            deaths = [
                {"player_id": d.player_id, "cause": d.cause.value if hasattr(d.cause, "value") else str(d.cause), "day": d.day}
                for d in game.engine.state.deaths
            ]
            persistence.save_game_result(
                seed=game.seed or 0,
                player_roles=player_roles_dict,
                config=config,
                winner=game.winner,
                started_at=started_at,
                total_rounds=getattr(game.engine.state, "day", 0) or 0,
                public_events=[e.to_dict() for e in game.engine.logger.entries],
                final_state={"player_roles": player_roles_dict, "winner": game.winner, "config": config},
                deaths=deaths,
            )
            # Persist structured review (evaluations, decision_reviews, counterfactuals, reports)
            # ordinary_game must NOT write episodic memory, patterns, or experience
            try:
                review_service = ReviewService()
                player_roles_dict_for_review = {int(k): v for k, v in player_roles_dict.items()}
                review_result = review_service.review_game(
                    game_id=game.game_id,
                    events=[e.to_dict() for e in game.engine.logger.entries],
                    decisions=self._decision_dicts(game),
                    player_roles=player_roles_dict_for_review,
                    winner=game.winner or "unknown",
                )
                if persistence.conn:
                    ReviewService.persist_to_db(persistence.conn, review_result)
            except Exception:
                _log.debug("ReviewService failed for %s", game.game_id, exc_info=True)
            self._cache_completed_review(game.game_id)
            game.status = RunnerStatus.COMPLETED
            done_snapshot = self.snapshot(game, include_events=False)
            done_snapshot["decisions"] = self._decision_dicts(game)
            await self._broadcast(game, {"kind": "done", "payload": done_snapshot})
        except Exception as exc:
            game.error = str(exc)
            game.status = RunnerStatus.FAILED
            await self._broadcast(game, {"kind": "error", "payload": {"message": str(exc)}})
        finally:
            if persistence is not None:
                persistence.close()

    async def _publish_new_entries(self, game: RunningGame, cursor: int) -> int:
        if game.engine is None:
            return cursor
        entries = game.engine.logger.entries
        for entry in entries[cursor:]:
            payload = entry.to_dict()
            game.events.append(payload)
            await self._broadcast(game, {"kind": "log", "payload": payload})
            decision_needed = self._decision_needed_payload(game, payload)
            if decision_needed is not None:
                await self._broadcast(game, {"kind": "decision_needed", "payload": decision_needed})
        return len(entries)

    async def _broadcast(self, game: RunningGame, item: dict[str, Any]) -> None:
        for queue in tuple(game.subscribers):
            queue.put_nowait(item)

    def _load_completed_game(self, game_id: str) -> RunningGame | None:
        events = self._read_game_events(game_id)
        if events is None:
            return None
        game = RunningGame(game_id=game_id, log_name=game_id, seed=None, status=RunnerStatus.COMPLETED)
        game.events = events
        game.winner = self._winner_from_events(events)
        self._games[game_id] = game
        return game

    def _read_events(self, path: Path) -> list[dict[str, Any]]:
        try:
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except OSError:
            return []

    def _read_game_events(self, game_id: str) -> list[dict[str, Any]] | None:
        game_dir = self._game_dir(game_id)
        if self._db_path is not None:
            events = read_events_for_artifact(
                self._db_path,
                game_dir,
                root=self._paths.runs_dir,
            )
            if events is not None:
                return events
        events_path = self._events_path(game_id)
        return self._read_events(events_path) if events_path is not None else None

    def _snapshot_from_events(
        self,
        game_id: str,
        events: list[dict[str, Any]],
        include_events: bool,
    ) -> dict[str, Any]:
        last_event = events[-1] if events else {}
        sheriff_id = self._sheriff_from_events(events)
        config = self._read_archive_config(game_id)
        players = self._players_from_events(events, sheriff_id)
        return {
            "game_id": game_id,
            "log_name": game_id,
            "status": RunnerStatus.COMPLETED,
            "winner": self._winner_from_events(events),
            "seed": config.get("seed"),
            "config": config,
            "max_days": config.get("max_days"),
            "enable_sheriff": config.get("enable_sheriff"),
            "skill_dir": config.get("skill_dir"),
            "role_skill_dirs": config.get("role_skill_dirs") or {},
            "human_player_id": None,
            "player_count": config.get("player_count") or len(players) or None,
            "day": last_event.get("day", 0),
            "phase": last_event.get("phase", "finished"),
            "sheriff_id": sheriff_id,
            "players": players,
            "event_count": len(events),
            "events": events if include_events else [],
            "decisions": self._read_decisions(game_id) if include_events else [],
            "error": None,
        }

    def _game_config_payload(self, game: RunningGame) -> dict[str, Any]:
        role_skill_dirs = {
            role: str(path)
            for role, path in (game.role_skill_dirs or {}).items()
        }
        return {
            "seed": game.seed,
            "max_days": game.max_days,
            "enable_sheriff": game.enable_sheriff,
            "skill_dir": game.skill_dir,
            "role_skill_dirs": role_skill_dirs,
            "player_count": game.player_count,
            "human_player_id": game.human_player_id,
        }

    def _read_archive_config(self, game_id: str) -> dict[str, Any]:
        merged = self._read_db_config(game_id)
        path = self._archive_path(game_id)
        if path is None:
            return merged
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return merged
        if not isinstance(data, dict):
            return merged
        config = data.get("config")
        if not isinstance(config, dict):
            config = {}
        merged = {**merged, **config}
        if merged.get("seed") is None and "seed" in data:
            merged["seed"] = data.get("seed")
        return merged

    def _read_db_config(self, game_id: str) -> dict[str, Any]:
        if self._db_path is None:
            return {}
        config = read_config_for_artifact(
            self._db_path,
            self._game_dir(game_id),
            root=self._paths.runs_dir,
        )
        return config if isinstance(config, dict) else {}

    def _decision_dicts(self, game: RunningGame) -> list[dict[str, Any]]:
        if game.decision_recorder is not None:
            return [
                {**record.to_dict(), "index": index}
                for index, record in enumerate(game.decision_recorder.records, start=1)
            ]
        return self._read_decisions(game.log_name)

    def _read_decisions(self, game_id: str) -> list[dict[str, Any]]:
        if self._db_path is not None:
            decisions = read_decisions_for_artifact(
                self._db_path,
                self._game_dir(game_id),
                root=self._paths.runs_dir,
            )
            if decisions is not None:
                return decisions
        archive_path = self._archive_path(game_id)
        if archive_path is not None:
            try:
                archive = json.loads(archive_path.read_text(encoding="utf-8"))
                return [
                    {**d, "index": idx}
                    for idx, d in enumerate(archive.get("decisions", []), start=1)
                ]
            except (OSError, json.JSONDecodeError):
                pass
        decisions_path = self._game_dir(game_id) / "agent_decisions.jsonl"
        try:
            return [
                {**json.loads(line), "index": idx}
                for idx, line in enumerate(decisions_path.read_text(encoding="utf-8").splitlines(), start=1)
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError):
            return []

    def pending_human_action(self, game_id: str) -> dict[str, Any] | None:
        game = self.get_game(game_id)
        if game is None:
            return None
        return self._pending_human_action_for(game)

    def _pending_human_action_for(self, game: RunningGame) -> dict[str, Any] | None:
        human = self._human_agent_for(game)
        if human is None or not human.is_waiting:
            return None
        request = human.current_request
        if request is None:
            return None
        observation = request.observation
        return {
            "player_id": request.player_id,
            "action_type": request.action_type.value,
            "phase": request.phase.value,
            "day": observation.day,
            "role": observation.self_role.value,
            "alive_players": list(observation.alive_players),
            "candidates": list(request.candidates),
            "metadata": to_jsonable(request.metadata),
            "retry_count": request.retry_count,
            "observation": self._human_observation_payload(observation),
        }

    def _decision_needed_payload(
        self,
        game: RunningGame,
        event: dict[str, Any],
    ) -> dict[str, Any] | None:
        if game.human_player_id is None or event.get("event_type") != "action_request":
            return None
        try:
            actor = int(event.get("actor"))
        except (TypeError, ValueError):
            return None
        if actor != game.human_player_id:
            return None
        return self._pending_human_action_for(game)

    def submit_human_action(
        self,
        game_id: str,
        *,
        action_type: str,
        target: int | None = None,
        choice: str | None = None,
        text: str = "",
    ) -> bool:
        game = self.get_game(game_id)
        if game is None:
            return False
        human = self._human_agent_for(game)
        if human is None or not human.is_waiting or human.current_request is None:
            return False
        try:
            parsed_action_type = ActionType(action_type)
        except ValueError as exc:
            raise ValueError(f"unsupported action_type: {action_type}") from exc
        if parsed_action_type is not human.current_request.action_type:
            raise ValueError("action_type does not match pending request")
        return human.submit(
            ActionResponse(
                parsed_action_type,
                target=target,
                choice=choice,
                text=text or "",
            )
        )

    def _human_agent_for(self, game: RunningGame) -> HumanPlayer | None:
        if game.human_player_id is None or game.engine is None:
            return None
        agent = game.engine.agents.get(game.human_player_id)
        return agent if isinstance(agent, HumanPlayer) else None

    def _human_observation_payload(self, observation: Observation) -> dict[str, Any]:
        return {
            "player_id": observation.player_id,
            "role": observation.self_role.value,
            "self_role": observation.self_role.value,
            "phase": observation.phase.value,
            "day": observation.day,
            "alive_players": list(observation.alive_players),
            "dead_players": list(observation.dead_players),
            "sheriff_id": observation.sheriff_id,
            "visible_events": [e.to_dict() for e in observation.visible_events],
            "known_roles": {
                str(player_id): role.value
                for player_id, role in observation.known_roles.items()
            },
            "seer_checks": {
                str(player_id): {
                    str(target_id): team.value
                    for target_id, team in checks.items()
                }
                for player_id, checks in observation.seer_checks.items()
            },
            "metadata": to_jsonable(observation.metadata),
        }

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
                "is_human": False,
                "role_state": {},
            }
            for player_id, role in sorted(roles.items())
        ]

    def build_review(self, game_id: str) -> dict[str, Any] | None:
        """Build structured review report using the unified ReviewService."""
        cached = self._read_review_cache(game_id)
        if cached is not None:
            return cached

        events = self._read_game_events(game_id)
        if not events:
            return None

        # Extract roles from game_init
        roles: dict[int, str] = {}
        for event in events:
            if event.get("event_type") == "game_init":
                raw_roles = event.get("payload", {}).get("roles", {})
                if isinstance(raw_roles, dict):
                    for pid_str, role_str in raw_roles.items():
                        try:
                            roles[int(pid_str)] = str(role_str)
                        except (ValueError, TypeError):
                            pass
                break
        if not roles:
            return None

        decisions: list[dict] = list(self._read_decisions(game_id))
        winner = self._winner_from_events(events)

        try:
            review_service = ReviewService()
            review_result = review_service.review_game(
                game_id=game_id,
                events=events,
                decisions=decisions,
                player_roles=roles,
                winner=winner or "unknown",
            )

            # Build summary dict compatible with existing UI
            data: dict[str, Any] = {
                "game_id": game_id,
                "winner": winner,
                "review_status": review_result.review_status,
                "scoring_version": review_result.scoring_version,
                "player_evaluations": [
                    {
                        "player_seat": pe.player_seat,
                        "role": pe.role,
                        "speech_score": pe.speech_score,
                        "vote_score": pe.vote_score,
                        "skill_score": pe.skill_score,
                        "information_score": getattr(pe, "information_score", 0),
                        "cooperation_score": getattr(pe, "cooperation_score", 0),
                        "overall_score": getattr(pe, "overall_score", 0),
                    }
                    for pe in review_result.player_evaluations
                ],
            }
            if review_result.review_report:
                data.update(review_result.review_report.summary)

            self._write_review_cache(game_id, data)
            return data
        except Exception:
            _log.warning("Review generation failed for %s", game_id, exc_info=True)
            return None


    def _cache_completed_review(self, game_id: str) -> None:
        try:
            self.build_review(game_id)
        except Exception:
            _log.warning("Failed to cache review for %s", game_id, exc_info=True)

    def _read_review_cache(self, game_id: str) -> dict[str, Any] | None:
        path = self._review_path(game_id)
        if path is None:
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, json.JSONDecodeError):
            return None

    def _write_review_cache(self, game_id: str, data: dict[str, Any]) -> None:
        path = self._game_dir(game_id) / "review.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _review_path(self, game_id: str) -> Path | None:
        path = self._game_dir(game_id) / "review.json"
        return path if path.exists() else None

    def read_archive(self, game_id: str) -> dict[str, Any] | None:
        """Read archive.json, falling back to persisted events and decisions."""
        path = self._archive_path(game_id)
        if path is not None:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (OSError, json.JSONDecodeError):
                pass
        events = self._read_game_events(game_id)
        if events is None:
            return None
        decisions = self._read_decisions(game_id)
        config = self._read_archive_config(game_id)
        return {
            "kind": "game_trace_archive",
            "schema_version": 1,
            "source": "events_fallback",
            "game_id": game_id,
            "seed": config.get("seed"),
            "config": config,
            "winner": self._winner_from_events(events),
            "event_count": len(events),
            "decision_count": len(decisions),
            "events": events,
            "decisions": decisions,
        }

    def _game_dir(self, game_id: str) -> Path:
        return self._paths.games_dir / game_id

    def _events_path(self, game_id: str) -> Path | None:
        game_dir = self._game_dir(game_id)
        for name in ("game_events.jsonl", "events.jsonl"):
            path = game_dir / name
            if path.exists():
                return path
        return None


    def _archive_path(self, game_id: str) -> Path | None:
        path = self._game_dir(game_id) / "archive.json"
        return path if path.exists() else None

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


def _game_sort_key(game_id: str) -> tuple[str, str]:
    """Sort by timestamp string (lexicographic works for yyyyMMdd_HHmmss_N)."""
    return game_id, game_id


def _game_id_from_log_path(path: Path) -> str | None:
    if path.is_dir():
        return path.name if re.fullmatch(r"\d{8}_\d{6}_\d+", path.name) else None
    return None
