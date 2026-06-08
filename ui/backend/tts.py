"""TTS request helpers for the UI backend."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ui.backend.schemas import TtsSpeechRequest


def _clean_tts_text(text: Any) -> str:
    return " ".join(str(text or "").replace("\x00", "").split()).strip()


def _clip_tts_text(text: Any, max_chars: int) -> str:
    cleaned = _clean_tts_text(text)
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[:max_chars].rstrip()}。"


def _tts_voice(config: dict[str, Any], request: TtsSpeechRequest) -> str:
    pool = config.get("voice_pool") if isinstance(config.get("voice_pool"), list) else []
    if pool and request.seat:
        return str(pool[(request.seat - 1) % len(pool)])
    return str(config.get("voice") or "mimo_default")


def _tts_auth_headers(config: dict[str, Any]) -> dict[str, str]:
    api_key = str(config.get("api_key") or "")
    header = str(config.get("auth_header") or "api-key").strip() or "api-key"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if header.lower() == "authorization":
        headers["Authorization"] = api_key if api_key.lower().startswith("bearer ") else f"Bearer {api_key}"
    else:
        headers[header] = api_key
    return headers


def _tts_payload(config: dict[str, Any], request: TtsSpeechRequest) -> dict[str, Any]:
    max_chars = int(config.get("max_chars") or 320)
    text = _clip_tts_text(request.text, max_chars)
    if not text:
        raise HTTPException(status_code=400, detail="朗读文本不能为空。")
    style = _clean_tts_text(config.get("style"))
    speaker = _clean_tts_text(request.speaker)
    instruction = style or "自然、清晰地朗读中文狼人杀玩家发言。"
    if speaker:
        instruction = f"{instruction} 当前说话人：{speaker}。"
    return {
        "model": config.get("model") or "mimo-v2.5-tts",
        "modalities": ["text", "audio"],
        "messages": [
            {
                "role": "user",
                "content": instruction,
            },
            {
                "role": "assistant",
                "content": text,
            },
        ],
        "audio": {
            "voice": _tts_voice(config, request),
            "format": config.get("format") or "wav",
        },
        "stream": False,
    }


def _extract_tts_audio_data(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise HTTPException(status_code=502, detail="TTS 服务没有返回音频。")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    audio = message.get("audio") if isinstance(message, dict) else None
    if not isinstance(audio, dict):
        raise HTTPException(status_code=502, detail="TTS 服务没有返回音频。")
    data = audio.get("data") or audio.get("audio") or audio.get("content")
    if not isinstance(data, str) or not data:
        raise HTTPException(status_code=502, detail="TTS 服务没有返回音频。")
    return data.split(",", 1)[1] if data.startswith("data:") and "," in data else data


def _tts_media_type(audio_format: Any) -> str:
    normalized = str(audio_format or "wav").strip().lower()
    return {
        "mp3": "audio/mpeg",
        "mpeg": "audio/mpeg",
        "wav": "audio/wav",
        "wave": "audio/wav",
        "pcm": "audio/L16",
        "opus": "audio/ogg",
    }.get(normalized, "application/octet-stream")
