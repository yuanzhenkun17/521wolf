"""Retention cleanup for runs/ artifacts.

Default behavior is dry-run. Executed cleanup prunes selected run directories
but keeps manifest.json and summary.json in place for auditability.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PRESERVED_NAMES = {"manifest.json", "summary.json"}
RUN_ROOT_NAMES = ("games", "selfplay", "evaluation_batches", "evolution")


@dataclass(frozen=True)
class RunCandidate:
    path: Path
    size_bytes: int
    mtime: float
    reason: str

    def to_dict(self, root: Path) -> dict[str, Any]:
        try:
            rel = self.path.relative_to(root)
        except ValueError:
            rel = self.path
        return {
            "path": rel.as_posix(),
            "size_bytes": self.size_bytes,
            "mtime": datetime.fromtimestamp(self.mtime, tz=timezone.utc).isoformat(),
            "reason": self.reason,
        }


def iter_run_dirs(runs_dir: Path) -> list[Path]:
    roots = [runs_dir / name for name in RUN_ROOT_NAMES]
    dirs: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        dirs.extend(child for child in root.iterdir() if child.is_dir())
    return sorted(dirs, key=lambda item: item.as_posix())


def dir_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        try:
            total += item.stat().st_size
        except OSError:
            continue
    return total


def dir_mtime(path: Path) -> float:
    newest = 0.0
    for item in [path, *path.rglob("*")]:
        try:
            newest = max(newest, item.stat().st_mtime)
        except OSError:
            continue
    return newest


def build_cleanup_plan(
    runs_dir: Path,
    *,
    max_age_days: int | None = None,
    max_total_mb: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    runs_dir = Path(runs_dir)
    current = (now or datetime.now(timezone.utc)).timestamp()
    candidates = [
        {
            "path": path,
            "size_bytes": dir_size(path),
            "mtime": dir_mtime(path),
        }
        for path in iter_run_dirs(runs_dir)
    ]
    selected: dict[Path, RunCandidate] = {}

    if max_age_days is not None:
        cutoff = current - max(0, int(max_age_days)) * 86400
        for candidate in candidates:
            if candidate["mtime"] < cutoff:
                path = candidate["path"]
                selected[path] = RunCandidate(
                    path=path,
                    size_bytes=candidate["size_bytes"],
                    mtime=candidate["mtime"],
                    reason=f"older_than_{max_age_days}_days",
                )

    if max_total_mb is not None:
        limit = max(0, int(max_total_mb)) * 1024 * 1024
        total = sum(int(candidate["size_bytes"]) for candidate in candidates)
        for candidate in sorted(candidates, key=lambda item: (item["mtime"], str(item["path"]))):
            if total <= limit:
                break
            path = candidate["path"]
            selected[path] = RunCandidate(
                path=path,
                size_bytes=candidate["size_bytes"],
                mtime=candidate["mtime"],
                reason=selected[path].reason if path in selected else f"total_size_over_{max_total_mb}_mb",
            )
            total -= int(candidate["size_bytes"])

    selected_items = sorted(selected.values(), key=lambda item: (item.mtime, str(item.path)))
    return {
        "runs_dir": str(runs_dir),
        "total_candidates": len(candidates),
        "total_size_bytes": sum(int(candidate["size_bytes"]) for candidate in candidates),
        "selected": [item.to_dict(runs_dir) for item in selected_items],
        "selected_size_bytes": sum(item.size_bytes for item in selected_items),
    }


def prune_run_dir(path: Path) -> dict[str, Any]:
    deleted_files: list[str] = []
    deleted_dirs: list[str] = []
    freed_bytes = 0
    for item in sorted(path.rglob("*"), key=lambda child: len(child.parts), reverse=True):
        if item.is_file():
            if item.name in PRESERVED_NAMES and item.parent == path:
                continue
            try:
                size = item.stat().st_size
                item.unlink()
            except OSError:
                continue
            freed_bytes += size
            deleted_files.append(item.relative_to(path).as_posix())
        elif item.is_dir():
            try:
                item.rmdir()
            except OSError:
                continue
            deleted_dirs.append(item.relative_to(path).as_posix())
    return {
        "path": str(path),
        "deleted_files": deleted_files,
        "deleted_dirs": deleted_dirs,
        "freed_bytes": freed_bytes,
    }


def cleanup_runs(
    runs_dir: Path,
    *,
    max_age_days: int | None = None,
    max_total_mb: int | None = None,
    execute: bool = False,
) -> dict[str, Any]:
    plan = build_cleanup_plan(runs_dir, max_age_days=max_age_days, max_total_mb=max_total_mb)
    report = {**plan, "dry_run": not execute, "pruned": []}
    if not execute:
        return report
    root = Path(runs_dir)
    for item in plan["selected"]:
        target = (root / item["path"]).resolve()
        if not target.is_dir():
            continue
        try:
            target.relative_to(root.resolve())
        except ValueError:
            continue
        report["pruned"].append(prune_run_dir(target))
    report["freed_bytes"] = sum(item["freed_bytes"] for item in report["pruned"])
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prune old or oversized runs artifacts.")
    parser.add_argument("--runs-dir", type=Path, default=Path("runs"))
    parser.add_argument("--max-age-days", type=int, default=None)
    parser.add_argument("--max-total-mb", type=int, default=None)
    parser.add_argument("--execute", action="store_true", help="Apply cleanup. Omit for dry-run.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = cleanup_runs(
        args.runs_dir,
        max_age_days=args.max_age_days,
        max_total_mb=args.max_total_mb,
        execute=args.execute,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
