"""Run the single-node UI task queue worker."""

from __future__ import annotations

import argparse
import json
import os
import socket
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from app.config import DEFAULT_PATHS, PathConfig
from ui.backend.store import BackendStore


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the PostgreSQL-backed UI task worker.")
    parser.add_argument("--root", type=Path, default=None, help="Project root used to resolve PathConfig.")
    parser.add_argument("--worker-id", default=_default_worker_id(), help="Stable worker identifier.")
    parser.add_argument("--lease-seconds", type=int, default=300, help="Task lease duration in seconds.")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Idle poll sleep interval in seconds.")
    parser.add_argument("--once", action="store_true", help="Run one poll cycle and exit.")
    parser.add_argument("--max-tasks", type=int, default=None, help="Maximum tasks to execute with --once.")
    parser.add_argument(
        "--mark-expired-only",
        action="store_true",
        help="Only mark expired running tasks interrupted, then exit.",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> dict[str, object]:
    os.environ.setdefault("PG_POOL_ROLE", "worker")
    os.environ.setdefault("WOLF_PROCESS_ROLE", "worker")
    paths = PathConfig(root=args.root) if args.root is not None else DEFAULT_PATHS
    store = BackendStore(paths=paths)
    try:
        recovered = store.restore_background_tasks()
        loop = store.create_task_worker_loop(
            worker_id=str(args.worker_id),
            poll_interval_seconds=float(args.poll_interval),
            lease_seconds=int(args.lease_seconds),
        )
        interrupted = loop.mark_expired_running_interrupted()
        if args.mark_expired_only:
            return {
                "worker_id": str(args.worker_id),
                "mode": "mark_expired_only",
                "recovered_background_tasks": recovered,
                "interrupted": interrupted,
            }
        if args.once:
            results = loop.run_available(max_tasks=args.max_tasks)
            return {
                "worker_id": str(args.worker_id),
                "mode": "once",
                "recovered_background_tasks": recovered,
                "interrupted": interrupted,
                "results": [asdict(result) for result in results],
            }
        loop.run_forever()
        return {
            "worker_id": str(args.worker_id),
            "mode": "forever",
            "recovered_background_tasks": recovered,
            "interrupted": interrupted,
        }
    finally:
        store.close()


def main(argv: Sequence[str] | None = None) -> int:
    result = run(parse_args(argv))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
    return 0


def _default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


if __name__ == "__main__":
    raise SystemExit(main())
