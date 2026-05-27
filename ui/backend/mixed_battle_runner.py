from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from agent.evaluation.mixed_version_battle import (
    MixedVersionBattleConfig,
    MixedVersionBattleResult,
    TeamVersionMatchup,
    run_team_mixed_version_battle,
)
from agent.evaluation.version_battle import version_spec_from_manifest


RunMixedBattleFunc = Callable[[MixedVersionBattleConfig], Awaitable[MixedVersionBattleResult]]


@dataclass(slots=True)
class RunningMixedBattle:
    run_id: str
    config: MixedVersionBattleConfig
    status: str = "running"
    result: MixedVersionBattleResult | None = None
    error: str | None = None
    started_at: str = ""
    task: asyncio.Task[None] | None = None

    def snapshot(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at,
            "config": self.config.to_dict(),
        }
        if self.result is not None:
            data["result"] = self.result.to_dict()
            data["leaderboard"] = [entry.to_dict() for entry in self.result.leaderboard]
        if self.error:
            data["error"] = self.error
        return data


class MixedBattleManager:
    def __init__(
        self,
        output_dir: Path = Path("runs/mixed_version_battle"),
        runner: RunMixedBattleFunc = run_team_mixed_version_battle,
    ) -> None:
        self.output_dir = output_dir
        self._runner = runner
        self._runs: dict[str, RunningMixedBattle] = {}

    async def start_run(
        self,
        *,
        wolves_manifest_path: Path,
        villagers_manifest_path: Path,
        games_per_side: int = 5,
        seed_start: int = 1,
        max_days: int = 20,
        enable_review: bool = True,
    ) -> RunningMixedBattle:
        run_id = f"mixed_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        config = MixedVersionBattleConfig(
            matchup=TeamVersionMatchup(
                version_a=version_spec_from_manifest(wolves_manifest_path),
                version_b=version_spec_from_manifest(villagers_manifest_path),
                label="team-level",
            ),
            games_per_side=games_per_side,
            seed_start=seed_start,
            output_dir=self.output_dir / run_id,
            max_days=max_days,
            enable_review=enable_review,
        )
        run = RunningMixedBattle(
            run_id=run_id,
            config=config,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self._runs[run_id] = run
        run.task = asyncio.create_task(self._execute(run), name=f"mixed-battle-{run_id}")
        return run

    def get_run(self, run_id: str) -> RunningMixedBattle | None:
        return self._runs.get(run_id)

    def list_runs(self) -> list[dict[str, Any]]:
        return [run.snapshot() for run in self._runs.values()]

    async def _execute(self, run: RunningMixedBattle) -> None:
        try:
            run.result = await self._runner(run.config)
            run.status = "completed"
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
