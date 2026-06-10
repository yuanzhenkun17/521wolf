"""Local filesystem ArtifactStore with PostgreSQL metadata indexing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from storage.ui.task_artifact_repo import TaskArtifactRepository


class LocalArtifactStore:
    """Write task artifacts to local disk and index metadata in PostgreSQL.

    The root should normally be ``runs/tasks``. All artifact paths are validated
    to stay inside that root before reads or writes occur.
    """

    def __init__(self, *, root: str | Path, repo: TaskArtifactRepository) -> None:
        self._root = Path(root)
        self._repo = repo

    @property
    def root(self) -> Path:
        return self._root

    def put_json(
        self,
        *,
        task_id: str,
        name: str,
        payload: Any,
        artifact_type: str,
        created_at: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str).encode("utf-8")
        return self.put_bytes(
            task_id=task_id,
            name=name,
            data=data,
            artifact_type=artifact_type,
            created_at=created_at,
            content_type="application/json",
            metadata=metadata,
        )

    def put_bytes(
        self,
        *,
        task_id: str,
        name: str,
        data: bytes,
        artifact_type: str,
        created_at: str,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_segment = _safe_task_id(task_id)
        artifact_name = _safe_artifact_name(name)
        relative_path = str(PurePosixPath(task_segment) / artifact_name)
        target = self._resolve_artifact_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target.with_name(f".{target.name}.tmp")
        temp_path.write_bytes(data)
        temp_path.replace(target)

        digest = hashlib.sha256(data).hexdigest()
        artifact_id = _artifact_id(task_segment, relative_path, digest)
        self._repo.upsert(
            artifact_id=artifact_id,
            task_id=task_segment,
            artifact_type=artifact_type,
            name=str(artifact_name),
            relative_path=relative_path,
            content_type=content_type,
            size_bytes=len(data),
            sha256=digest,
            created_at=created_at,
            metadata=metadata or {},
        )
        stored = self._repo.get(artifact_id)
        if stored is None:  # pragma: no cover - repository contract guard
            raise RuntimeError(f"artifact metadata was not persisted: {artifact_id}")
        return stored

    def list(self, task_id: str) -> list[dict[str, Any]]:
        return self._repo.list_for_task(_safe_task_id(task_id))

    def get_path(self, artifact_id: str) -> Path:
        artifact = self._repo.get(artifact_id)
        if artifact is None:
            raise FileNotFoundError(artifact_id)
        return self._resolve_artifact_path(str(artifact["relative_path"]))

    def read_bytes(self, artifact_id: str) -> bytes:
        return self.get_path(artifact_id).read_bytes()

    def _resolve_artifact_path(self, relative_path: str) -> Path:
        normalized = _safe_relative_path(relative_path)
        root = self._root.resolve()
        target = (root / normalized).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"artifact path escapes root: {relative_path!r}") from exc
        return target


def _artifact_id(task_id: str, relative_path: str, digest: str) -> str:
    raw = f"{task_id}\0{relative_path}\0{digest}".encode("utf-8")
    return f"artifact_{hashlib.sha256(raw).hexdigest()[:32]}"


def _safe_task_id(task_id: str) -> str:
    text = str(task_id or "").strip()
    if not text:
        raise ValueError("task_id is required")
    if "/" in text or "\\" in text or text in {".", ".."}:
        raise ValueError(f"unsafe task_id: {task_id!r}")
    return text


def _safe_artifact_name(name: str) -> PurePosixPath:
    text = str(name or "").strip().replace("\\", "/")
    if not text:
        raise ValueError("artifact name is required")
    return _safe_relative_path(text)


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(str(value).replace("\\", "/"))
    if path.is_absolute():
        raise ValueError(f"absolute artifact paths are not allowed: {value!r}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"unsafe artifact path: {value!r}")
    return path
