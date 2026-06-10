"""Task queue executors for local-first Langfuse tooling."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.tools.build_langfuse_link_manifest import build_link_manifest, load_json as load_link_manifest_json
from app.tools.export_langfuse_annotation_queue import export_annotation_queue
from app.tools.verify_langfuse_experiments import verify_langfuse_experiments


class LangfuseTaskService:
    """Run existing Langfuse utility workflows through the UI task worker."""

    def __init__(self, context: Any) -> None:
        self._context = context

    def __getattr__(self, name: str) -> Any:
        return getattr(self._context, name)

    def task_executors(self) -> dict[str, Any]:
        return {
            "langfuse_verification": self.execute_verification_task,
            "langfuse_annotation_export": self.execute_annotation_export_task,
            "langfuse_link_manifest": self.execute_link_manifest_task,
        }

    def execute_verification_task(self, task: dict[str, Any], context: Any) -> dict[str, Any]:
        payload = _task_payload(task)
        task_id = str(task.get("task_id") or "")
        context.heartbeat(progress={"stage": "langfuse_verification"})
        try:
            report = verify_langfuse_experiments(
                paths=self.paths,
                env=payload.get("env") if isinstance(payload.get("env"), dict) else None,
                payload_files=_path_list(payload.get("payload_files") or payload.get("input_paths")),
                apply_sync=bool(payload.get("apply_sync", False)),
                verify_remote=bool(payload.get("verify_remote", False)),
            )
        except Exception as exc:
            self._write_error_artifact(task_id, exc, stage="langfuse_verification")
            raise
        artifact = self.task_service.put_task_json_artifact(
            task_id=task_id,
            name="langfuse-verification.json",
            payload=report,
            artifact_type="langfuse_verification",
            metadata={
                "status": report.get("status"),
                "dry_run": report.get("dry_run"),
            },
        )
        return {
            "status": report.get("status"),
            "summary": report.get("summary") if isinstance(report.get("summary"), dict) else {},
            "artifact_ids": [artifact["artifact_id"]],
        }

    def execute_annotation_export_task(self, task: dict[str, Any], context: Any) -> dict[str, Any]:
        payload = _task_payload(task)
        task_id = str(task.get("task_id") or "")
        context.heartbeat(progress={"stage": "langfuse_annotation_export"})
        try:
            report = export_annotation_queue(
                _path_list(payload.get("input_paths") or payload.get("payload_files")),
                output_path=None,
                ui_base_url=str(payload.get("ui_base_url") or "/"),
                low_judge_score=float(payload.get("low_judge_score", 5.0)),
                max_items=_optional_int(payload.get("max_items")),
                apply=bool(payload.get("apply", False)),
            )
        except Exception as exc:
            self._write_error_artifact(task_id, exc, stage="langfuse_annotation_export")
            raise
        artifact = self.task_service.put_task_json_artifact(
            task_id=task_id,
            name="annotation-queue.json",
            payload=report,
            artifact_type="langfuse_annotation_export",
            metadata={
                "item_count": report.get("item_count"),
                "dry_run": report.get("dry_run"),
            },
        )
        langfuse = report.get("langfuse") if isinstance(report.get("langfuse"), dict) else {}
        return {
            "status": langfuse.get("status") or "local_only",
            "summary": {
                "item_count": report.get("item_count", 0),
                "applied_count": langfuse.get("applied_count", 0),
            },
            "artifact_ids": [artifact["artifact_id"]],
        }

    def execute_link_manifest_task(self, task: dict[str, Any], context: Any) -> dict[str, Any]:
        payload = _task_payload(task)
        task_id = str(task.get("task_id") or "")
        context.heartbeat(progress={"stage": "langfuse_link_manifest"})
        try:
            payloads = [load_link_manifest_json(path) for path in _path_list(payload.get("input_paths"))]
            manifest = build_link_manifest(payloads, ui_base_url=str(payload.get("ui_base_url") or "/"))
        except Exception as exc:
            self._write_error_artifact(task_id, exc, stage="langfuse_link_manifest")
            raise
        artifact = self.task_service.put_task_json_artifact(
            task_id=task_id,
            name="link-manifest.json",
            payload=manifest,
            artifact_type="langfuse_link_manifest",
            metadata={
                "item_count": manifest.get("item_count"),
                "missing_link_count": len(manifest.get("missing_links") or []),
            },
        )
        return {
            "status": "succeeded",
            "summary": {
                "item_count": manifest.get("item_count", 0),
                "missing_link_count": len(manifest.get("missing_links") or []),
            },
            "artifact_ids": [artifact["artifact_id"]],
        }

    def _write_error_artifact(self, task_id: str, exc: Exception, *, stage: str) -> None:
        if not task_id:
            return
        self.task_service.put_task_json_artifact(
            task_id=task_id,
            name="error.json",
            payload={
                "kind": "langfuse_task_error",
                "stage": stage,
                "message": str(exc),
                "exception_type": type(exc).__name__,
            },
            artifact_type="langfuse_task_error",
            metadata={"stage": stage},
        )


def _task_payload(task: dict[str, Any]) -> dict[str, Any]:
    payload = task.get("payload")
    return dict(payload) if isinstance(payload, dict) else {}


def _path_list(value: Any) -> list[Path]:
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [Path(value)]
    if isinstance(value, list):
        return [Path(item) for item in value if str(item)]
    return []


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
