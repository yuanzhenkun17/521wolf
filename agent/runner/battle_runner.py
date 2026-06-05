"""Battle runner for interactive/evaluation games.

Handles single games that may include human players, with real-time event
callbacks for UI streaming (SSE). After each game the runner persists
archives, decision logs, and SQLite records.
"""
from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent.common import beijing_now_iso
from agent.common.run_policy import RunPolicy, RunType, policy_for_run_type
from agent.runner.shared import create_agents_for_game, create_engine

_log = logging.getLogger(__name__)


@dataclass
class BattleGameConfig:
    """Configuration for a single battle game."""

    seed: int | None = None
    max_days: int = 20
    enable_sheriff: bool = True
    skill_dir: Path | str | None = None
    role_skill_dirs: dict[str, Path] | None = None
    human_player_id: int | None = None
    model: Any = None  # LLM ModelAdapter
    on_event: Callable[[dict[str, Any]], Any] | None = None  # SSE callback
    game_id: str | None = None
    output_dir: Path | None = None  # Override game log directory
    db_path: Path | None = None  # SQLite DB path
    run_type: RunType = RunType.ORDINARY_GAME
    model_id: str | None = None
    model_config_hash: str | None = None


@dataclass
class BattleGameResult:
    """Result of a battle game."""

    game_id: str
    winner: str
    days: int
    player_roles: dict[int, str]
    events: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    started_at: str
    finished_at: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "game_id": self.game_id,
            "winner": self.winner,
            "days": self.days,
            "player_roles": {str(k): v for k, v in self.player_roles.items()},
            "events": self.events,
            "decisions": self.decisions,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }
        if self.error:
            d["error"] = self.error
        return d


class BattleRunner:
    """Runner for interactive/evaluation games.

    - Supports human players
    - Random seed (not fixed) for variety
    - Real-time event callbacks (for UI SSE)
    - Loads skills from Registry baseline (read-only)
    - Persists archives, decisions, and SQLite records after each game
    """

    def __init__(self, *, registry: Any | None = None, paths: Any | None = None, game_run_service: Any | None = None) -> None:
        self._registry = registry
        self._paths = paths
        self._game_run_service = game_run_service

    def _resolve_paths(self) -> Any:
        """Resolve PathConfig, falling back to the project default."""
        if self._paths is not None:
            return self._paths
        from agent.common.paths import DEFAULT as DEFAULT_PATHS
        return DEFAULT_PATHS

    async def run_game(self, config: BattleGameConfig) -> BattleGameResult:
        """Run a single battle game and return the result.

        Steps:
        1. Generate game_id if not provided.
        2. Generate random seed if not provided.
        3. Assign roles via random_standard_roles.
        4. Create recorder and trace_recorder.
        5. Create agents via create_agents_for_game.
        6. Create engine via create_engine.
        7. Run engine to completion.
        8. Collect events and decisions.
        9. Return BattleGameResult.
        """
        from agent.api.factory import load_llm_client
        from agent.infrastructure.archive import AgentTraceRecorder
        from agent.infrastructure.decision_log import AgentDecisionRecorder
        from engine.logging import next_game_log_name, GameLogger
        from engine.roles import random_standard_roles
        from storage.runtime import GamePersistence

        paths = self._resolve_paths()
        started_at = beijing_now_iso()

        # Resolve role_skill_dirs from registry baselines if not explicitly set
        if config.role_skill_dirs is None and self._registry is not None:
            config.role_skill_dirs = {}
            for role in self._registry.list_roles():
                baseline_id = self._registry.get_baseline(role)
                if baseline_id:
                    try:
                        config.role_skill_dirs[role] = self._registry.get_skill_dir(role, baseline_id)
                    except FileNotFoundError:
                        _log.warning("Missing Registry skills for %s/%s", role, baseline_id)

        # 1. Resolve games directory (but not game_id yet — service may generate it)
        games_dir = config.output_dir if config.output_dir is not None else paths.games_dir
        games_dir.mkdir(parents=True, exist_ok=True)

        # 2. Generate seed
        seed = config.seed if config.seed is not None else random.randint(0, 2**31 - 1)

        # 3. Assign roles
        roles = random_standard_roles(seed=seed)
        player_roles = {pid: r.value for pid, r in roles.items()}

        # 4. Create persistence (and resolve game_id)
        db_path = config.db_path if config.db_path is not None else paths.battle_db_path
        run_policy = policy_for_run_type(config.run_type)
        if self._game_run_service is not None:
            from agent.game_run.service import GameRunConfig
            run_config = GameRunConfig(
                run_type=config.run_type,
                mode="dev",
                max_days=config.max_days,
                model_id=config.model_id,
                model_config_hash=config.model_config_hash,
            )
            handle = self._game_run_service.create_run(run_config)
            persistence = handle.persistence
            game_id = handle.run_id
        else:
            game_id = config.game_id or next_game_log_name(games_dir)
            persistence = GamePersistence(
                game_id=game_id,
                game_dir=None,
                db_path=db_path,
                run_policy=run_policy,
                run_metadata={
                    "mode": "dev",
                    "model_id": config.model_id,
                    "model_config_hash": config.model_config_hash,
                    "ruleset_version": "werewolf_12p_v1",
                },
            )

        # 5. Create game directory using resolved game_id
        game_dir = games_dir / game_id
        game_dir.mkdir(parents=True, exist_ok=True)
        persistence.game_dir = game_dir

        decision_recorder: AgentDecisionRecorder = persistence.create_decision_recorder()
        trace_recorder = AgentTraceRecorder()

        # 6. Resolve LLM client
        model = config.model
        if model is None:
            model = load_llm_client()

        # 7. Create agents
        agents = create_agents_for_game(
            roles,
            model=model,
            skill_dir=config.skill_dir,
            role_skill_dirs=config.role_skill_dirs,
            human_player_id=config.human_player_id,
            game_id=game_id,
            recorder=decision_recorder,
            trace_recorder=trace_recorder,
            paths=paths,
        )

        # 8. Create engine with streaming logger
        game_logger = persistence.create_event_logger(game_dir / "game_events.jsonl")
        engine = create_engine(
            roles,
            agents,
            seed=seed,
            max_days=config.max_days,
            enable_sheriff=config.enable_sheriff,
            logger=game_logger,
        )

        # 9. Run engine and stream events
        events: list[dict[str, Any]] = []
        cursor = 0
        game_error: str | None = None
        winner_str = "error"

        try:
            run_task = asyncio.create_task(engine.run_until_finished())
            while not run_task.done():
                cursor = _publish_entries(engine, events, cursor, config.on_event)
                await asyncio.sleep(0.1)
            winner = await run_task
            # Flush remaining entries
            cursor = _publish_entries(engine, events, cursor, config.on_event)
            winner_str = winner.value if hasattr(winner, "value") else str(winner)
        except Exception as exc:
            _log.error("Battle game %s failed: %s", game_id, exc, exc_info=True)
            game_error = str(exc)

        # 10. Persist trace archive
        try:
            trace_recorder.flush(
                game_id=game_id,
                output_dir=game_dir,
                seed=seed,
                config={},
                player_roles=player_roles,
                winner=winner_str,
                started_at=started_at,
                public_events=events,
                final_state={"player_roles": player_roles, "winner": winner_str},
            )
        except Exception:
            _log.warning("Failed to write trace archive for %s", game_id, exc_info=True)

        # 11. Save game result to SQLite
        try:
            deaths = []
            if engine.state is not None:
                deaths = [
                    {
                        "player_id": d.player_id,
                        "cause": d.cause.value if hasattr(d.cause, "value") else str(d.cause),
                        "day": d.day,
                    }
                    for d in engine.state.deaths
                ]
            persistence.save_game_result(
                seed=seed,
                player_roles=player_roles,
                config={},
                winner=winner_str,
                started_at=started_at,
                finished_at=beijing_now_iso(),
                total_rounds=getattr(engine.state, "day", 0) or 0,
                public_events=[e.to_dict() for e in engine.logger.entries] if engine.state else [],
                final_state={"player_roles": player_roles, "winner": winner_str},
                deaths=deaths,
            )
        except Exception:
            _log.warning("Failed to save game result to SQLite for %s", game_id, exc_info=True)
        finally:
            persistence.close()

        # 12. Collect decisions
        decisions = [
            {**record.to_dict(), "index": index}
            for index, record in enumerate(decision_recorder.records, start=1)
        ]

        # 13. Post-game evolution: DISABLED per Phase 1/2 refactor.
        #     ordinary_game must not write episodic memory, patterns, or experience.
        #     Only evolution_training (learning_eligible=true) may write learning data.

        finished_at = beijing_now_iso()
        days = getattr(engine.state, "day", 0) or 0

        return BattleGameResult(
            game_id=game_id,
            winner=winner_str,
            days=days,
            player_roles=player_roles,
            events=events,
            decisions=decisions,
            started_at=started_at,
            finished_at=finished_at,
            error=game_error,
        )


def _publish_entries(
    engine: Any,
    events: list[dict[str, Any]],
    cursor: int,
    on_event: Callable[[dict[str, Any]], Any] | None,
) -> int:
    """Publish new log entries to the events list and optional callback."""
    entries = engine.logger.entries
    for entry in entries[cursor:]:
        payload = entry.to_dict()
        events.append(payload)
        if on_event is not None:
            try:
                on_event(payload)
            except Exception:
                _log.debug("on_event callback raised", exc_info=True)
    return len(entries)
