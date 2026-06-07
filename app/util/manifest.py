"""Run manifest helpers for game/eval/evolve artifacts."""

from __future__ import annotations

import os
import shutil
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.util.json import to_jsonable, write_json

MANIFEST_SCHEMA_VERSION = 1


def build_run_manifest(
    *,
    run_type: str,
    run_id: str | None = None,
    game_id: str | None = None,
    batch_id: str | None = None,
    model_config_hash: str | None = None,
    seed: int | None = None,
    config: dict[str, Any] | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
    status: str | None = None,
    error_summary: str | None = None,
    paths: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a stable manifest payload shared by all run artifacts."""
    return {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "run_type": str(run_type),
        "run_id": str(run_id or game_id or batch_id or ""),
        "game_id": str(game_id or ""),
        "batch_id": str(batch_id or ""),
        "model_config_hash": str(model_config_hash or ""),
        "seed": seed,
        "config": to_jsonable(dict(config or {})),
        "started_at": str(started_at or ""),
        "finished_at": str(finished_at or ""),
        "status": str(status or ""),
        "error_summary": str(error_summary or ""),
        "paths": to_jsonable(dict(paths or {})),
        "metadata": to_jsonable(dict(metadata or {})),
    }


def write_manifest(path: str | Path, manifest: dict[str, Any]) -> None:
    """Write a manifest using the repository's atomic JSON writer."""
    write_json(Path(path), manifest)


@contextmanager
def atomic_artifact_dir(final_dir: str | Path) -> Iterator[Path]:
    """Yield a writable directory and expose it as ``final_dir`` only on success.

    If ``final_dir`` already exists, callers get the existing directory for
    backward compatibility with tests/tools that pass a pre-created directory.
    Otherwise, files are written to a hidden sibling temp directory and renamed
    into place after the context exits without error.
    """
    final_path = Path(final_dir)
    if final_path.exists():
        final_path.mkdir(parents=True, exist_ok=True)
        yield final_path
        return

    final_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = final_path.parent / (
        f".{final_path.name}.{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}.tmp"
    )
    tmp_path.mkdir(parents=True, exist_ok=False)
    committed = False
    try:
        yield tmp_path
        tmp_path.rename(final_path)
        committed = True
    finally:
        if not committed and tmp_path.exists():
            shutil.rmtree(tmp_path, ignore_errors=True)
