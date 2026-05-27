from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.evaluation.selfplay import SelfPlayConfig, SelfPlayGameResult, SelfPlayResult, run_selfplay
from engine.config import STANDARD_12


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


class SelfplayManager:
    def __init__(self, output_dir: Path = Path("runs/selfplay")) -> None:
        self.output_dir = output_dir
        self._runs: dict[str, RunningSelfplay] = {}
        self._lock = asyncio.Lock()

    async def start_run(
        self,
        *,
        num_games: int = 10,
        agent_version: str = "agent",
        skill_dir: str | None = None,
        model_name: str | None = None,
        temperature: float = 0.2,
        tot_enabled: bool = True,
        got_enabled: bool = True,
        got_trigger_threshold: float = 0.3,
        max_days: int = 20,
        enable_sheriff: bool = True,
        enable_batch_dream: bool = False,
        label: str | None = None,
    ) -> RunningSelfplay:
        run_id = f"run_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        started_at = datetime.now(timezone.utc).isoformat()

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
            tot_enabled=tot_enabled,
            got_enabled=got_enabled,
            got_trigger_threshold=got_trigger_threshold,
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

    def _on_game_complete(self, run: RunningSelfplay, game_index: int, _result: SelfPlayGameResult) -> None:
        run.completed_games = game_index + 1

    async def _execute(self, run: RunningSelfplay) -> None:
        try:
            result = await run_selfplay(
                run.config,
                on_game_complete=lambda idx, res: self._on_game_complete(run, idx, res),
            )
            run.result = result
            run.artifact_run_id = result.run_id
            run.status = "completed"
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
