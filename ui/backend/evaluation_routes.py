"""Evaluation batch API routes.

Endpoints:
  POST /api/evaluation-batches     – create and run a new evaluation batch
  GET  /api/evaluation-batches     – list all evaluation batches
  GET  /api/evaluation-batches/{id} – get a single batch result
  GET  /api/leaderboards/models    – model leaderboard
  GET  /api/leaderboards/role-versions – role-version leaderboard
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from agent.evaluation.config import EvaluationBatchConfig

_log = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class EvaluationBatchRequest(BaseModel):
    comparison_type: str = "model_id"
    mode: str = "dev"
    evaluation_set_id: str = ""
    seed_set_id: str = ""
    model_id: str = ""
    game_count: int = 20
    target_role: str | None = None
    target_version_id: str | None = None
    role_version_config: dict[str, str] = {}
    comparison_group_id: str | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/api/evaluation-batches")
async def create_evaluation_batch(req: EvaluationBatchRequest) -> dict[str, Any]:
    """Create and run a new evaluation batch."""
    from agent.evaluation.runner import EvaluationBatchRunner
    from agent.common.paths import DEFAULT as DEFAULT_PATHS

    config = EvaluationBatchConfig(
        comparison_type=req.comparison_type,
        mode=req.mode,
        evaluation_set_id=req.evaluation_set_id,
        seed_set_id=req.seed_set_id,
        model_id=req.model_id,
        game_count=req.game_count,
        target_role=req.target_role,
        target_version_id=req.target_version_id,
        role_version_config=req.role_version_config,
        comparison_group_id=req.comparison_group_id,
    )

    runner = EvaluationBatchRunner()
    # Run in background to avoid blocking the API
    result = await runner.run_batch(config)
    return result.to_dict()


@router.get("/api/evaluation-batches")
async def list_evaluation_batches() -> list[dict[str, Any]]:
    """List all evaluation batches from the database."""
    from agent.common.paths import DEFAULT as DEFAULT_PATHS
    from storage.schema import get_connection

    conn = get_connection(DEFAULT_PATHS.battle_db_path)
    try:
        rows = conn.execute(
            "SELECT id, comparison_group_id, comparison_type, mode, model_id, "
            "game_count, rankable, started_at, finished_at "
            "FROM evaluation_batches ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@router.get("/api/evaluation-batches/{batch_id}")
async def get_evaluation_batch(batch_id: str) -> dict[str, Any]:
    """Get a single evaluation batch by ID."""
    from agent.common.paths import DEFAULT as DEFAULT_PATHS
    from storage.schema import get_connection

    conn = get_connection(DEFAULT_PATHS.battle_db_path)
    try:
        row = conn.execute(
            "SELECT * FROM evaluation_batches WHERE id = ?", (batch_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Batch {batch_id} not found")
        result = dict(row)
        # Parse summary JSON
        if result.get("summary"):
            try:
                result["summary"] = json.loads(result["summary"])
            except (json.JSONDecodeError, TypeError):
                pass
        return result
    finally:
        conn.close()


@router.get("/api/leaderboards/models")
async def get_model_leaderboard() -> list[dict[str, Any]]:
    """Get the model leaderboard."""
    from agent.common.paths import DEFAULT as DEFAULT_PATHS
    from storage.schema import get_connection

    conn = get_connection(DEFAULT_PATHS.battle_db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM benchmark_leaderboard "
            "WHERE scope = 'model' "
            "ORDER BY strength_score DESC LIMIT 50"
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("by_role_category_scores"):
                try:
                    d["by_role_category_scores"] = json.loads(d["by_role_category_scores"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)
        return results
    finally:
        conn.close()


@router.get("/api/leaderboards/role-versions")
async def get_role_version_leaderboard() -> list[dict[str, Any]]:
    """Get the role-version leaderboard."""
    from agent.common.paths import DEFAULT as DEFAULT_PATHS
    from storage.schema import get_connection

    conn = get_connection(DEFAULT_PATHS.battle_db_path)
    try:
        rows = conn.execute(
            "SELECT * FROM benchmark_leaderboard "
            "WHERE scope = 'role_version' "
            "ORDER BY strength_score DESC LIMIT 50"
        ).fetchall()
        results = []
        for row in rows:
            d = dict(row)
            if d.get("by_role_category_scores"):
                try:
                    d["by_role_category_scores"] = json.loads(d["by_role_category_scores"])
                except (json.JSONDecodeError, TypeError):
                    pass
            results.append(d)
        return results
    finally:
        conn.close()
