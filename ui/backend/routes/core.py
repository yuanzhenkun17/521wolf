"""Core and TTS routes for the UI backend."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from app.config import load_tts_config
from ui.backend.schemas import TtsSpeechRequest
from ui.backend.tts_dashscope import (
    prepare_dashscope_realtime_request,
    stream_dashscope_realtime_audio,
)


def register_core_routes(api: FastAPI, store: Any) -> None:
    @api.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "status": "ok",
            "mode": "api",
            "external": {
                "provider": "app-langgraph",
                "supports_human": True,
                "supports_sse": True,
                "active_game_id": next(
                    (
                        game_id
                        for game_id, session in store.live_sessions.items()
                        if session.status == "running"
                    ),
                    None,
                ),
                "llm": store.llm_status(),
                "tts": store.tts_status(),
                "tts_streaming": store.tts_streaming_available(),
                "startup_checks": store.startup_checks,
            },
        }

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
