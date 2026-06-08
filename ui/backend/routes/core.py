"""Core and TTS routes for the UI backend."""

from __future__ import annotations

import base64
import binascii
import logging
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from app.config import load_tts_config
from ui.backend.schemas import TtsSpeechRequest
from ui.backend.tts import (
    _extract_tts_audio_data,
    _tts_auth_headers,
    _tts_media_type,
    _tts_payload,
)

_log = logging.getLogger(__name__)


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
                "startup_checks": store.startup_checks,
            },
        }

    @api.post("/api/tts/speech")
    async def tts_speech(request: TtsSpeechRequest) -> Response:
        try:
            config = load_tts_config()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="TTS 未配置，请在 .env 配置 WEREWOLF_TTS_API_KEY。") from exc

        payload = _tts_payload(config, request)
        url = f"{config['base_url']}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=float(config.get("timeout") or 60.0)) as client:
                upstream = await client.post(url, headers=_tts_auth_headers(config), json=payload)
                upstream.raise_for_status()
                data = upstream.json()
        except httpx.HTTPStatusError as exc:
            _log.warning("TTS upstream returned HTTP %s", exc.response.status_code, exc_info=True)
            raise HTTPException(status_code=502, detail="TTS 服务调用失败。") from exc
        except (httpx.HTTPError, ValueError) as exc:
            _log.warning("TTS upstream request failed", exc_info=True)
            raise HTTPException(status_code=502, detail="TTS 服务调用失败。") from exc

        audio_data = _extract_tts_audio_data(data)
        try:
            audio_bytes = base64.b64decode(audio_data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=502, detail="TTS 服务返回的音频无效。") from exc
        return Response(
            content=audio_bytes,
            media_type=_tts_media_type(config.get("format")),
            headers={"Cache-Control": "no-store"},
        )

    @api.get("/api/leaderboards")
    def leaderboards() -> dict[str, Any]:
        return {"entries": [], "source": "app", "source_type": "app"}
