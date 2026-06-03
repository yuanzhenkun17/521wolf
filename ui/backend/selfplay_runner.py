from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from agent.common import beijing_now_iso, beijing_now_str
from agent.common.paths import DEFAULT as DEFAULT_PATHS
from agent.learning.selfplay import SelfPlayConfig, SelfPlayGameResult, SelfPlayResult, run_selfplay
from agent.infrastructure.llm import AsyncRateLimiter
from engine.config import STANDARD_12

_log = logging.getLogger(__name__)


def _is_rate_limit_error(exc: Exception) -> bool:
    """Check if an exception is a 429 rate limit error."""
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "too many requests" in msg


@dataclass(slots=True)
class RunningSelfplay:
    run_id: str
    config: SelfPlayConfig
    status: str = "running"
    total_games: int = 0
    completed_games: int = 0
    label: str = ""
    agent_version: str = "agent"
    skill_dir: str | None = None
    max_days: int = 20
    enable_sheriff: bool = True
    enable_batch_dream: bool = False
    game_concurrency: int = 1
    llm_concurrency: int = 5
    llm_rpm: int = 60
    retry_attempt: int = 0
    retry_total: int = 0
    result: SelfPlayResult | None = None
    artifact_run_id: str | None = None
    error: str | None = None
    started_at: str = ""
    task: asyncio.Task[None] | None = None

    def snapshot(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "run_id": self.run_id,
            "status": self.status,
            "progress": {
                "completed": self.completed_games,
                "total": self.total_games,
            },
            "num_games": self.total_games,
            "completed_games": self.completed_games,
            "label": self.label,
            "agent_version": self.agent_version,
            "skill_dir": self.skill_dir,
            "max_days": self.max_days,
            "enable_sheriff": self.enable_sheriff,
            "enable_batch_dream": self.enable_batch_dream,
            "game_concurrency": self.game_concurrency,
            "llm_concurrency": self.llm_concurrency,
            "llm_rpm": self.llm_rpm,
            "retry_attempt": self.retry_attempt,
            "retry_total": self.retry_total,
            "created_at": self.started_at,
            "started_at": self.started_at,
            "artifact_run_id": self.artifact_run_id,
        }
        if self.status == "completed" and self.result is not None:
            data["summary"] = self.result.summary
            data["results"] = self.result.summary
        if self.error:
            data["error"] = self.error
        return data

    def persist_state(self, run_dir: Path) -> None:
        """Write run_state.json for crash recovery."""
        state = {
            "run_id": self.run_id,
            "status": self.status,
            "total_games": self.total_games,
            "completed_games": self.completed_games,
            "label": self.label,
            "agent_version": self.agent_version,
            "skill_dir": self.skill_dir,
            "max_days": self.max_days,
            "enable_sheriff": self.enable_sheriff,
            "enable_batch_dream": self.enable_batch_dream,
            "game_concurrency": self.game_concurrency,
            "llm_concurrency": self.llm_concurrency,
            "llm_rpm": self.llm_rpm,
            "started_at": self.started_at,
            "artifact_run_id": self.artifact_run_id,
        }
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "run_state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class SelfplayManager:
    def __init__(self, output_dir: Path = DEFAULT_PATHS.selfplay_dir) -> None:
        self.output_dir = output_dir
        self._runs: dict[str, RunningSelfplay] = {}
        self._lock = asyncio.Lock()

    def restore_runs(self) -> None:
        """Scan disk for interrupted runs and resume them."""
        if not self.output_dir.exists():
            return
        for run_dir in sorted(self.output_dir.iterdir()):
            if not run_dir.is_dir():
                continue
            state_path = run_dir / "run_state.json"
            if not state_path.exists():
                continue
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if state.get("status") in ("completed", "failed"):
                continue

            run_id = state["run_id"]
            # Count already-completed games from disk
            games_dir = run_dir / "games"
            completed = 0
            if games_dir.exists():
                for gdir in games_dir.iterdir():
                    if gdir.is_dir() and (gdir / "meta.json").exists():
                        completed += 1

            num_games = state["total_games"]
            if completed >= num_games:
                # All games done on disk — mark completed
                state["status"] = "completed"
                state["completed_games"] = completed
                state_path.write_text(
                    json.dumps(state, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                continue

            # Rebuild config and resume
            skill_dir_raw = state.get("skill_dir")
            config = SelfPlayConfig(
                games=num_games,
                output_dir=self.output_dir,
                agent_version=state.get("agent_version", "agent"),
                max_days=state.get("max_days", 20),
                enable_batch_dream=state.get("enable_batch_dream", False),
                game_config=replace(STANDARD_12, enable_sheriff=state.get("enable_sheriff", True)),
                skill_dir=Path(skill_dir_raw) if skill_dir_raw else None,
                game_concurrency=state.get("game_concurrency", 1),
            )

            run = RunningSelfplay(
                run_id=run_id,
                config=config,
                total_games=num_games,
                completed_games=completed,
                started_at=state.get("started_at", ""),
                label=state.get("label", ""),
                agent_version=state.get("agent_version", "agent"),
                skill_dir=skill_dir_raw,
                max_days=state.get("max_days", 20),
                enable_sheriff=state.get("enable_sheriff", True),
                enable_batch_dream=state.get("enable_batch_dream", False),
                game_concurrency=state.get("game_concurrency", 1),
                llm_concurrency=state.get("llm_concurrency", 5),
                llm_rpm=state.get("llm_rpm", 60),
            )
            self._runs[run_id] = run
            _log.info("Resuming selfplay run %s (%d/%d games done)", run_id, completed, num_games)
            run.task = asyncio.create_task(
                self._execute(run, resume_dir=run_dir),
                name=f"selfplay-resume-{run_id}",
            )

    async def start_run(
        self,
        *,
        num_games: int = 10,
        agent_version: str = "agent",
        skill_dir: str | None = None,
        model_name: str | None = None,
        temperature: float = 0.2,
        max_days: int = 20,
        enable_sheriff: bool = True,
        enable_batch_dream: bool = False,
        game_concurrency: int = 1,
        llm_concurrency: int = 5,
        llm_rpm: int = 60,
        label: str | None = None,
    ) -> RunningSelfplay:
        run_id = f"run_{beijing_now_str('%Y%m%d_%H%M%S_%f')}"
        started_at = beijing_now_iso()

        config = SelfPlayConfig(
            games=num_games,
            output_dir=self.output_dir,
            agent_version=agent_version,
            model_name=model_name,
            max_days=max_days,
            enable_batch_dream=enable_batch_dream,
            temperature=temperature,
            game_config=replace(STANDARD_12, enable_sheriff=enable_sheriff),
            skill_dir=Path(skill_dir) if skill_dir else None,
            game_concurrency=game_concurrency,
        )

        run = RunningSelfplay(
            run_id=run_id,
            config=config,
            total_games=num_games,
            started_at=started_at,
            label=label or "",
            agent_version=agent_version,
            skill_dir=skill_dir,
            max_days=max_days,
            enable_sheriff=enable_sheriff,
            enable_batch_dream=enable_batch_dream,
            game_concurrency=game_concurrency,
            llm_concurrency=llm_concurrency,
            llm_rpm=llm_rpm,
        )
        self._runs[run_id] = run
        run.task = asyncio.create_task(
            self._execute(run), name=f"selfplay-{run_id}"
        )
        return run

    def get_run(self, run_id: str) -> RunningSelfplay | None:
        return self._runs.get(run_id)

    def list_runs(self) -> list[dict[str, Any]]:
        return [run.snapshot() for run in self._runs.values()]

    def stop_run(self, run_id: str) -> RunningSelfplay | None:
        """Stop a running selfplay task. The run can be resumed later."""
        run = self._runs.get(run_id)
        if run is None:
            return None
        if run.task and not run.task.done():
            run.task.cancel()
        run.status = "paused"
        run_dir = self.output_dir / (run.artifact_run_id or run.run_id)
        try:
            run.persist_state(run_dir)
        except Exception:
            _log.warning("Failed to persist run state for %s", run.run_id, exc_info=True)
        return run

    def terminate_run(self, run_id: str) -> RunningSelfplay | None:
        """Permanently stop a selfplay run. Cannot be resumed."""
        run = self._runs.get(run_id)
        if run is None:
            return None
        if run.task and not run.task.done():
            run.task.cancel()
        run.status = "failed"
        run.error = "用户终止"
        run_dir = self.output_dir / (run.artifact_run_id or run.run_id)
        try:
            run.persist_state(run_dir)
        except Exception:
            pass
        return run

    def resume_run(self, run_id: str) -> RunningSelfplay | None:
        """Resume a paused or interrupted selfplay run."""
        run = self._runs.get(run_id)
        if run is None:
            # Try to restore from disk
            self.restore_runs()
            run = self._runs.get(run_id)
        if run is None:
            return None
        if run.status not in ("paused", "failed"):
            return run  # already running or completed
        run_dir = self.output_dir / (run.artifact_run_id or run.run_id)
        run.status = "running"
        run.error = None
        run.task = asyncio.create_task(
            self._execute(run, resume_dir=run_dir),
            name=f"selfplay-resume-{run_id}",
        )
        return run

    def _on_game_complete(self, run: RunningSelfplay, game_index: int, _result: SelfPlayGameResult) -> None:
        run.completed_games = min(run.total_games, run.completed_games + 1)
        # Persist state after each game so we can resume if interrupted
        run_dir = self.output_dir / (run.artifact_run_id or run.run_id)
        try:
            run.persist_state(run_dir)
        except Exception:
            _log.warning("Failed to persist run state for %s", run.run_id, exc_info=True)

    async def _execute(
        self, run: RunningSelfplay, resume_dir: Path | None = None,
    ) -> None:
        max_retries = 5
        run.retry_total = max_retries
        for attempt in range(max_retries):
            run.retry_attempt = attempt
            try:
                result = await run_selfplay(
                    run.config,
                    on_game_complete=lambda idx, res: self._on_game_complete(run, idx, res),
                    llm_semaphore=asyncio.Semaphore(run.llm_concurrency),
                    llm_rate_limiter=AsyncRateLimiter(run.llm_rpm),
                    run_dir=resume_dir,
                )
                run.result = result
                run.artifact_run_id = result.run_id
                run.status = "completed"
                run_dir = self.output_dir / result.run_id
                run.persist_state(run_dir)
                return
            except Exception as exc:
                if _is_rate_limit_error(exc) and attempt < max_retries - 1:
                    wait = 30 * (attempt + 1)
                    _log.warning("Rate limited on run %s, retrying in %ds (attempt %d/%d)", run.run_id, wait, attempt + 1, max_retries)
                    run.status = "rate_limited"
                    run_dir = self.output_dir / (run.artifact_run_id or run.run_id)
                    run.persist_state(run_dir)
                    await asyncio.sleep(wait)
                    run.status = "running"
                    continue
                run.status = "failed"
                run.error = str(exc)
                run_dir = self.output_dir / (run.artifact_run_id or run.run_id)
            try:
                run.persist_state(run_dir)
            except Exception:
                pass
