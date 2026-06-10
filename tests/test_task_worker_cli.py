from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ui.backend.services.task_worker import TaskWorkerRunResult

import app.tools.run_ui_task_worker as worker_cli


def test_run_ui_task_worker_once_outputs_summary(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    stores: list[Any] = []

    class FakeLoop:
        def mark_expired_running_interrupted(self) -> int:
            return 2

        def run_available(self, *, max_tasks: int | None = None) -> list[TaskWorkerRunResult]:
            assert max_tasks == 3
            return [
                TaskWorkerRunResult(
                    task_id="task_1",
                    kind="benchmark_batch",
                    status="succeeded",
                    executed=True,
                )
            ]

    class FakeStore:
        def __init__(self, *, paths: Any) -> None:
            self.paths = paths
            self.closed = False
            stores.append(self)

        def restore_background_tasks(self) -> int:
            return 1

        def create_task_worker_loop(
            self,
            *,
            worker_id: str,
            poll_interval_seconds: float,
            lease_seconds: int,
        ) -> FakeLoop:
            assert worker_id == "worker-test"
            assert poll_interval_seconds == 0.25
            assert lease_seconds == 30
            return FakeLoop()

        def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(worker_cli, "BackendStore", FakeStore)

    exit_code = worker_cli.main(
        [
            "--root",
            str(tmp_path),
            "--worker-id",
            "worker-test",
            "--lease-seconds",
            "30",
            "--poll-interval",
            "0.25",
            "--once",
            "--max-tasks",
            "3",
        ]
    )

    assert exit_code == 0
    assert stores and stores[0].closed is True
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "interrupted": 2,
        "mode": "once",
        "recovered_background_tasks": 1,
        "results": [
            {
                "error": None,
                "executed": True,
                "kind": "benchmark_batch",
                "status": "succeeded",
                "task_id": "task_1",
            }
        ],
        "worker_id": "worker-test",
    }
