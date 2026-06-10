from __future__ import annotations

import os
import time
from pathlib import Path

from app.tools.cleanup_runs import build_cleanup_plan, cleanup_runs


def _write_run(root: Path, rel: str, *, age_seconds: int, payload: str = "payload") -> Path:
    run_dir = root / rel
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "manifest.json").write_text('{"run": true}', encoding="utf-8")
    (run_dir / "summary.json").write_text('{"summary": true}', encoding="utf-8")
    (run_dir / "events.jsonl").write_text(payload, encoding="utf-8")
    (run_dir / "nested").mkdir()
    (run_dir / "nested" / "trace.json").write_text(payload, encoding="utf-8")
    stamp = time.time() - age_seconds
    for item in sorted(run_dir.rglob("*"), reverse=True):
        os.utime(item, (stamp, stamp))
    os.utime(run_dir, (stamp, stamp))
    return run_dir


def test_cleanup_runs_default_is_dry_run_and_preserves_files(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    old_run = _write_run(runs_dir, "games/old", age_seconds=10 * 86400)
    new_run = _write_run(runs_dir, "games/new", age_seconds=60)

    report = cleanup_runs(runs_dir, max_age_days=1)

    assert report["dry_run"] is True
    assert [item["path"] for item in report["selected"]] == ["games/old"]
    assert report["pruned"] == []
    assert (old_run / "events.jsonl").exists()
    assert (new_run / "events.jsonl").exists()


def test_cleanup_runs_execute_prunes_artifacts_but_keeps_manifest_and_summary(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    old_run = _write_run(runs_dir, "evolution/run_001", age_seconds=10 * 86400)

    report = cleanup_runs(runs_dir, max_age_days=1, execute=True)

    assert report["dry_run"] is False
    assert report["freed_bytes"] > 0
    assert (old_run / "manifest.json").exists()
    assert (old_run / "summary.json").exists()
    assert not (old_run / "events.jsonl").exists()
    assert not (old_run / "nested").exists()


def test_cleanup_runs_size_retention_selects_oldest_until_under_limit(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    _write_run(runs_dir, "games/old", age_seconds=1000, payload="x" * 512)
    _write_run(runs_dir, "games/new", age_seconds=10, payload="x" * 512)

    plan = build_cleanup_plan(runs_dir, max_total_mb=0)

    assert plan["total_candidates"] == 2
    assert {item["path"] for item in plan["selected"]} == {"games/old", "games/new"}


def test_cleanup_runs_task_artifacts_are_opt_in(tmp_path: Path) -> None:
    runs_dir = tmp_path / "runs"
    task_dir = _write_run(runs_dir, "tasks/task-old", age_seconds=10 * 86400)

    default_plan = build_cleanup_plan(runs_dir, max_age_days=1)
    task_plan = build_cleanup_plan(runs_dir, max_age_days=1, include_task_artifacts=True)
    report = cleanup_runs(runs_dir, max_age_days=1, include_task_artifacts=True, execute=True)

    assert default_plan["include_task_artifacts"] is False
    assert default_plan["selected"] == []
    assert task_plan["include_task_artifacts"] is True
    assert [item["path"] for item in task_plan["selected"]] == ["tasks/task-old"]
    assert report["dry_run"] is False
    assert not (task_dir / "events.jsonl").exists()
