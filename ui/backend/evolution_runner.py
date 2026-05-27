from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from agent.evaluation.evolution import (
    EvolutionPipelineConfig,
    EvolutionPipelineResult,
    run_evolution_pipeline,
)


RunEvolutionFunc = Callable[[EvolutionPipelineConfig], Awaitable[EvolutionPipelineResult]]


@dataclass(slots=True)
class RunningEvolution:
    run_id: str
    config: EvolutionPipelineConfig
    status: str = "running"
    stage: str = "queued"
    result: EvolutionPipelineResult | None = None
    error: str | None = None
    started_at: str = ""
    task: asyncio.Task[None] | None = None

    def snapshot(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "run_id": self.run_id,
            "status": self.status,
            "stage": self.stage,
            "started_at": self.started_at,
            "config": self.config.to_dict(),
        }
        if self.result is not None:
            data["result"] = self.result.to_dict()
            data["candidate_version"] = self.result.config.candidate_version
            data["promoted"] = self.result.promoted
            data["reasons"] = self.result.reasons
            data["metrics"] = self.result.metrics
        if self.error:
            data["error"] = self.error
        return data


class EvolutionManager:
    def __init__(
        self,
        output_dir: Path = Path("runs/evolution"),
        runner: RunEvolutionFunc = run_evolution_pipeline,
    ) -> None:
        self.output_dir = output_dir
        self._runner = runner
        self._runs: dict[str, RunningEvolution] = {}

    async def start_run(
        self,
        *,
        base_version: str,
        candidate_version: str,
        training_games: int = 5,
        battle_games: int = 20,
        training_seed_start: int = 1,
        battle_seed_start: int = 1001,
        max_days: int = 20,
        enable_dream: bool = True,
        enable_skill_proposals: bool = True,
        auto_apply_skill_proposals: bool = True,
        min_score_improvement: float = 0.05,
        max_win_rate_drop: float = 0.10,
        notes: str = "",
    ) -> RunningEvolution:
        provisional_id = f"evolution_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        config = EvolutionPipelineConfig(
            base_version=base_version,
            candidate_version=candidate_version,
            training_games=training_games,
            battle_games=battle_games,
            training_seed_start=training_seed_start,
            battle_seed_start=battle_seed_start,
            max_days=max_days,
            output_dir=self.output_dir,
            enable_dream=enable_dream,
            enable_skill_proposals=enable_skill_proposals,
            auto_apply_skill_proposals=auto_apply_skill_proposals,
            min_score_improvement=min_score_improvement,
            max_win_rate_drop=max_win_rate_drop,
            notes=notes,
        )
        run = RunningEvolution(
            run_id=provisional_id,
            config=config,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self._runs[provisional_id] = run
        run.task = asyncio.create_task(self._execute(run), name=f"evolution-{provisional_id}")
        return run

    def get_run(self, run_id: str) -> RunningEvolution | None:
        return self._runs.get(run_id)

    def list_runs(self) -> list[dict[str, Any]]:
        return [run.snapshot() for run in self._runs.values()]

    async def _execute(self, run: RunningEvolution) -> None:
        try:
            run.stage = "selfplay"
            result = await self._runner(run.config)
            old_run_id = run.run_id
            run.result = result
            run.run_id = result.run_id
            run.stage = "completed"
            run.status = "completed"
            if old_run_id != result.run_id:
                self._runs[result.run_id] = self._runs.pop(old_run_id, run)
        except Exception as exc:
            run.stage = "failed"
            run.status = "failed"
            run.error = str(exc)
