"""Core and TTS routes for the UI backend."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse

from app.config import load_tts_config
from ui.backend.health import build_health_payload, probe_llm_connectivity
from ui.backend.ops_metrics import build_ops_metrics_payload
from ui.backend.preflight import check_runtime_ready
from ui.backend.schemas import TtsSpeechRequest
from ui.backend.settings_model_profiles import settings_admin_authorized, settings_admin_payload
from ui.backend.tts_dashscope import (
    prepare_dashscope_realtime_request,
    stream_dashscope_realtime_audio,
)


def register_core_routes(api: FastAPI, store: Any) -> None:
    @api.get("/api/health")
    def health() -> dict[str, Any]:
        return build_health_payload(store)

    @api.get("/api/ops/metrics")
    def ops_metrics() -> dict[str, Any]:
        return build_ops_metrics_payload(store)

    @api.post("/api/health/probes/llm")
    async def probe_llm(
        scope: str = "game_start",
        model_scope: str | None = None,
        model_profile_id: str | None = None,
        x_settings_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_settings_probe_admin(x_settings_admin_token)
        normalized_profile_id = str(model_profile_id or "").strip() or None
        return await probe_llm_connectivity(
            store,
            scope=scope,
            model_scope=model_scope,
            model_profile_id=normalized_profile_id,
            cache=normalized_profile_id is None,
        )

    @api.post("/api/health/preflight")
    async def health_preflight(
        scope: str = "game_start",
        model_scope: str | None = None,
        model_profile_id: str | None = None,
    ) -> dict[str, Any]:
        return await check_runtime_ready(
            store,
            scope=scope,
            model_scope=model_scope,
            model_profile_id=model_profile_id,
        )

    @api.post("/api/tts/speech/stream")
    async def tts_speech_stream(request: TtsSpeechRequest) -> StreamingResponse:
        try:
            config = load_tts_config()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="TTS 未配置，请在 .env 配置 WEREWOLF_TTS_API_KEY。") from exc

        prepared = prepare_dashscope_realtime_request(config, request)
        return StreamingResponse(
            stream_dashscope_realtime_audio(config, request, prepared=prepared),
            media_type="audio/L16",
            headers={
                "Cache-Control": "no-store",
                "X-TTS-Audio-Format": "pcm_s16le",
                "X-TTS-Sample-Rate": str(prepared["sample_rate"]),
                "X-TTS-Channels": "1",
            },
        )

    @api.get("/api/leaderboards")
    def leaderboards(
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return {
            "kind": "benchmark_leaderboard",
            "schema_version": 1,
            "scope": scope,
            "evaluation_set_id": evaluation_set_id,
            "target_role": target_role,
            "entries": store.leaderboard_entries(
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                target_role=target_role,
                limit=limit,
            ),
            "source": "app",
            "source_type": "app",
        }

    @api.get("/api/leaderboards/compare")
    def leaderboard_compare(
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        baseline_subject_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return store.leaderboard_compare(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role,
            baseline_subject_id=baseline_subject_id,
            limit=limit,
        )

    @api.get("/api/models/leaderboard")
    def model_leaderboard(evaluation_set_id: str | None = None, limit: int = 100) -> dict[str, Any]:
        return {
            "kind": "model_leaderboard",
            "schema_version": 1,
            "scope": "model",
            "evaluation_set_id": evaluation_set_id,
            "entries": store.model_leaderboard_entries(evaluation_set_id=evaluation_set_id, limit=limit),
            "source": "app",
            "source_type": "app",
        }


def _require_settings_probe_admin(token: str | None) -> None:
    if settings_admin_authorized(token):
        return
    admin = settings_admin_payload()
    if not admin["write_available"]:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "settings_admin_disabled",
                "message": "settings admin writes are disabled",
                "detail": "settings admin is disabled or token is not configured",
            },
        )
    raise HTTPException(
        status_code=403,
        detail={
            "code": "settings_admin_required",
            "message": "settings admin token is required",
            "detail": "missing or invalid settings admin token",
        },
    )
