"""Operate the PostgreSQL-backed UI task queue from the command line."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from app.config import DEFAULT_PATHS, PathConfig
from storage.artifacts import LocalArtifactStore
from storage.ui import TaskArtifactRepository
from ui.backend.store import BackendStore


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect and operate UI task queue rows.")
    parser.add_argument("--root", type=Path, default=None, help="Project root used to resolve PathConfig.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List recent task queue rows.")
    list_parser.add_argument("--status", action="append", default=[], help="Task status filter. Can be repeated or comma-separated.")
    list_parser.add_argument("--limit", type=int, default=50)

    cancel_parser = subparsers.add_parser("cancel", help="Request cancellation for a task.")
    cancel_parser.add_argument("task_id")

    retry_parser = subparsers.add_parser("retry", help="Retry an interrupted task.")
    retry_parser.add_argument("task_id")

    verify_parser = subparsers.add_parser("verify-artifacts", help="Verify indexed task artifact files.")
    verify_parser.add_argument("--task-id", default="", help="Limit verification to one task.")
    verify_parser.add_argument("--limit", type=int, default=100)

    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, Any]:
    paths = PathConfig(root=args.root) if args.root is not None else DEFAULT_PATHS
    store = BackendStore(paths=paths)
    try:
        return run_with_service(args, store.task_service)
    finally:
        store.close()


def run_with_service(args: argparse.Namespace, service: Any) -> dict[str, Any]:
    command = str(args.command)
    if command == "list":
        return list_tasks(service, statuses=_status_values(getattr(args, "status", [])), limit=int(args.limit))
    if command == "cancel":
        return task_action(service, task_id=str(args.task_id), action="cancel")
    if command == "retry":
        return task_action(service, task_id=str(args.task_id), action="retry")
    if command == "verify-artifacts":
        return verify_artifacts(service, task_id=str(getattr(args, "task_id", "") or ""), limit=int(args.limit))
    return {"ok": False, "command": command, "error": f"unsupported command: {command}", "exit_code": 2}


def list_tasks(service: Any, *, statuses: Iterable[str] | None = None, limit: int = 50) -> dict[str, Any]:
    status_values = [status for status in statuses or [] if status]
    rows = service.list_task_queue_rows(statuses=status_values or None, limit=max(1, int(limit)))
    return {
        "ok": True,
        "operation": "list",
        "statuses": status_values,
        "count": len(rows),
        "tasks": [_task_summary(row) for row in rows],
    }


def task_action(service: Any, *, task_id: str, action: str) -> dict[str, Any]:
    if action == "cancel":
        result = service.cancel_task(task_id)
    elif action == "retry":
        result = service.retry_task(task_id)
    else:
        return {"ok": False, "operation": action, "task_id": task_id, "error": f"unsupported action: {action}", "exit_code": 2}
    if result is None:
        return {"ok": False, "operation": action, "task_id": task_id, "error": "task not found", "exit_code": 1}
    return {
        "ok": True,
        "operation": action,
        "task_id": task_id,
        "changed": bool(result.get("changed")),
        "task": _task_summary(result.get("task") or {}),
    }


def verify_artifacts(service: Any, *, task_id: str = "", limit: int = 100) -> dict[str, Any]:
    artifacts = _list_artifacts(service, task_id=task_id, limit=max(1, int(limit)))
    root = Path(getattr(service, "task_artifact_root", Path("runs") / "tasks"))
    results = [_verify_artifact(service, root=root, artifact=artifact) for artifact in artifacts]
    ok = all(item["ok"] for item in results)
    return {
        "ok": ok,
        "operation": "verify-artifacts",
        "task_id": task_id or None,
        "checked": len(results),
        "failed": sum(1 for item in results if not item["ok"]),
        "artifacts": results,
        "exit_code": 0 if ok else 2,
    }


def _list_artifacts(service: Any, *, task_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
    if task_id:
        return service.list_task_artifacts(task_id)[:limit]
    conn = service.open_connection()
    try:
        return TaskArtifactRepository(conn).list_recent(limit=limit)
    finally:
        conn.close()


def _verify_artifact(service: Any, *, root: Path, artifact: dict[str, Any]) -> dict[str, Any]:
    artifact_id = str(artifact.get("artifact_id") or "")
    expected_sha = str(artifact.get("sha256") or "").removeprefix("sha256:")
    expected_size = artifact.get("size_bytes")
    try:
        conn = service.open_connection()
        try:
            path = LocalArtifactStore(root=root, repo=TaskArtifactRepository(conn)).get_path(artifact_id)
        finally:
            conn.close()
        data = path.read_bytes()
    except Exception as exc:  # noqa: BLE001 - operation should report all artifact failures
        return {
            "ok": False,
            "artifact_id": artifact_id,
            "task_id": artifact.get("task_id"),
            "name": artifact.get("name"),
            "status": "missing_file",
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }

    actual_sha = hashlib.sha256(data).hexdigest()
    actual_size = len(data)
    failures: list[str] = []
    if expected_sha and actual_sha != expected_sha:
        failures.append("sha256_mismatch")
    if expected_size is not None and int(expected_size) != actual_size:
        failures.append("size_mismatch")
    return {
        "ok": not failures,
        "artifact_id": artifact_id,
        "task_id": artifact.get("task_id"),
        "name": artifact.get("name"),
        "path": str(path),
        "status": "ok" if not failures else ",".join(failures),
        "expected_sha256": expected_sha or None,
        "actual_sha256": actual_sha,
        "expected_size_bytes": expected_size,
        "actual_size_bytes": actual_size,
    }


def _status_values(values: Iterable[str]) -> list[str]:
    statuses: list[str] = []
    for value in values:
        statuses.extend(part.strip() for part in str(value).split(",") if part.strip())
    return statuses


def _task_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": row.get("task_id"),
        "kind": row.get("kind"),
        "status": row.get("status"),
        "priority": row.get("priority"),
        "attempt": row.get("attempt"),
        "max_attempts": row.get("max_attempts"),
        "cancel_requested": row.get("cancel_requested"),
        "queued_at": row.get("queued_at"),
        "started_at": row.get("started_at"),
        "updated_at": row.get("updated_at"),
        "finished_at": row.get("finished_at"),
        "lease_owner": row.get("lease_owner"),
        "lease_expires_at": row.get("lease_expires_at"),
        "progress": row.get("progress"),
        "error": row.get("error"),
        "source": row.get("source"),
    }


def main(argv: Sequence[str] | None = None) -> int:
    result = run(parse_args(argv))
    exit_code = int(result.pop("exit_code", 0) or 0)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
