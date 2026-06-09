"""DashScope realtime TTS streaming helpers."""

from __future__ import annotations

import asyncio
import base64
import queue
import threading
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import HTTPException

from ui.backend.schemas import TtsSpeechRequest

_DONE = object()


class _StreamError:
    def __init__(self, error: BaseException) -> None:
        self.error = error


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
    return str(config.get("voice") or "Cherry")


def ensure_dashscope_realtime_dependency() -> None:
    try:
        import dashscope  # noqa: F401
        from dashscope.audio.qwen_tts_realtime import QwenTtsRealtime  # noqa: F401
    except ImportError as exc:
        raise HTTPException(status_code=503, detail="DashScope realtime TTS 依赖未安装。") from exc


def _audio_format(config: dict[str, Any]) -> Any:
    from dashscope.audio.qwen_tts_realtime import AudioFormat

    sample_rate = int(config.get("sample_rate") or 24000)
    if sample_rate != 24000:
        raise HTTPException(status_code=400, detail="DashScope realtime TTS 目前仅配置为 24000Hz PCM。")
    return AudioFormat.PCM_24000HZ_MONO_16BIT


def _dashscope_text_chunks(config: dict[str, Any], request: TtsSpeechRequest) -> list[str]:
    text = _clip_tts_text(request.text, int(config.get("max_chars") or 320))
    if not text:
        raise HTTPException(status_code=400, detail="朗读文本不能为空。")

    chunks: list[str] = []
    buffer = ""
    max_chunk_chars = 42
    for char in text:
        buffer += char
        if char in "。！？；，、,.!?;" or len(buffer) >= max_chunk_chars:
            chunk = buffer.strip()
            if chunk:
                chunks.append(chunk)
            buffer = ""
    tail = buffer.strip()
    if tail:
        chunks.append(tail)
    return chunks or [text]


def _dashscope_instructions(config: dict[str, Any], request: TtsSpeechRequest) -> str:
    style = _clean_tts_text(config.get("style"))
    speaker = _clean_tts_text(request.speaker)
    instructions = style or "自然、清晰地朗读中文狼人杀玩家发言。"
    if speaker:
        instructions = f"{instructions} 当前说话人：{speaker}。"
    return instructions


def prepare_dashscope_realtime_request(config: dict[str, Any], request: TtsSpeechRequest) -> dict[str, Any]:
    ensure_dashscope_realtime_dependency()
    return {
        "audio_format": _audio_format(config),
        "chunks": _dashscope_text_chunks(config, request),
        "instructions": _dashscope_instructions(config, request),
        "mode": str(config.get("mode") or "server_commit"),
        "model": str(config.get("model") or "qwen3-tts-flash-realtime"),
        "sample_rate": int(config.get("sample_rate") or 24000),
        "url": str(config.get("ws_url") or "") or None,
        "voice": _tts_voice(config, request),
    }


async def stream_dashscope_realtime_audio(
    config: dict[str, Any],
    request: TtsSpeechRequest,
    *,
    prepared: dict[str, Any] | None = None,
) -> AsyncIterator[bytes]:
    prepared = prepared or prepare_dashscope_realtime_request(config, request)

    import dashscope
    from dashscope.audio.qwen_tts_realtime import QwenTtsRealtime, QwenTtsRealtimeCallback

    output: queue.Queue[bytes | object | _StreamError] = queue.Queue()
    stop_event = threading.Event()

    class Callback(QwenTtsRealtimeCallback):
        def on_event(self, response: Any) -> None:
            try:
                event_type = response.get("type") if isinstance(response, dict) else None
                if event_type == "response.audio.delta":
                    delta = response.get("delta") if isinstance(response, dict) else None
                    if isinstance(delta, str) and delta:
                        output.put(base64.b64decode(delta))
                elif event_type == "session.finished":
                    output.put(_DONE)
            except BaseException as exc:  # pragma: no cover - SDK callback boundary.
                output.put(_StreamError(exc))

        def on_close(self, close_status_code: Any, close_msg: Any) -> None:
            output.put(_DONE)

    def run() -> None:
        session = None
        try:
            dashscope.api_key = str(config.get("api_key") or "")
            session = QwenTtsRealtime(
                model=prepared["model"],
                callback=Callback(),
                url=prepared["url"],
            )
            session.connect()
            session.update_session(
                voice=prepared["voice"],
                response_format=prepared["audio_format"],
                mode=prepared["mode"],
                sample_rate=prepared["sample_rate"],
                instructions=prepared["instructions"],
            )
            for chunk in prepared["chunks"]:
                if stop_event.is_set():
                    break
                session.append_text(chunk)
                time.sleep(0.04)
            if not stop_event.is_set():
                session.finish()
        except BaseException as exc:  # pragma: no cover - exercised through integration.
            output.put(_StreamError(exc))
            output.put(_DONE)

    thread = threading.Thread(target=run, name="dashscope-tts-realtime", daemon=True)
    thread.start()
    timeout = max(1.0, float(config.get("timeout") or 60.0))
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                item = await asyncio.to_thread(output.get, True, 0.5)
            except queue.Empty:
                if time.monotonic() > deadline:
                    raise HTTPException(status_code=504, detail="DashScope realtime TTS 响应超时。")
                continue
            deadline = time.monotonic() + timeout
            if item is _DONE:
                break
            if isinstance(item, _StreamError):
                raise HTTPException(status_code=502, detail="DashScope realtime TTS 服务调用失败。") from item.error
            if isinstance(item, bytes) and item:
                yield item
    finally:
        stop_event.set()
