"""Langfuse utility task enqueue routes."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field


class LangfuseTaskRequest(BaseModel):
    task_id: str | None = Field(default=None, max_length=180)
    input_paths: list[str] = Field(default_factory=list, max_length=100)
    payload_files: list[str] = Field(default_factory=list, max_length=100)
    env: dict[str, str] | None = None
    apply_sync: bool = False
    verify_remote: bool = False
    apply: bool = False
    ui_base_url: str = Field(default="/", max_length=500)
    low_judge_score: float = 5.0
    max_items: int | None = Field(default=None, ge=0, le=10000)


def register_langfuse_task_routes(api: FastAPI, store: Any) -> None:
    @api.post("/api/langfuse/verification-tasks")
    def create_langfuse_verification_task(request: LangfuseTaskRequest) -> dict[str, Any]:
        return _enqueue_langfuse_task(store, "langfuse_verification", request)

    @api.post("/api/langfuse/annotation-export-tasks")
    def create_langfuse_annotation_export_task(request: LangfuseTaskRequest) -> dict[str, Any]:
        return _enqueue_langfuse_task(store, "langfuse_annotation_export", request)

    @api.post("/api/langfuse/link-manifest-tasks")
    def create_langfuse_link_manifest_task(request: LangfuseTaskRequest) -> dict[str, Any]:
        return _enqueue_langfuse_task(store, "langfuse_link_manifest", request)


def _enqueue_langfuse_task(store: Any, kind: str, request: LangfuseTaskRequest) -> dict[str, Any]:
    task_id = request.task_id or f"{kind}_{uuid.uuid4().hex[:10]}"
    payload = request.model_dump(mode="json", exclude_none=True, exclude={"task_id"})
    task = store.task_service.enqueue_task(
        task_id=task_id,
        kind=kind,
        payload=payload,
        priority=70,
        idempotency_key=f"{kind}:{task_id}",
        source="ui_langfuse",
        metadata={
            "kind": kind,
            "input_path_count": len(payload.get("input_paths") or []),
            "payload_file_count": len(payload.get("payload_files") or []),
        },
    )
    return {
        "kind": "langfuse_task",
        "schema_version": 1,
        "task_id": task["task_id"],
        "task_kind": task["kind"],
        "task_queue_status": task["status"],
    }
