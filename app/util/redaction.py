"""Redaction helpers for logs, diagnostics, and public payloads."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any, Literal

RedactionContext = Literal["diagnostic", "public", "private"]

_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "access_key",
    "secret",
    "token",
    "password",
    "passwd",
    "credential",
    "authorization",
    "cookie",
    "private_key",
)
_PUBLIC_PRIVATE_KEYS = {
    "private_reasoning",
    "hidden_reasoning",
    "raw_messages",
    "prompt",
    "raw_prompt",
    "raw_output",
}
_DIAGNOSTIC_PAYLOAD_KEYS = {
    "messages",
    "raw_messages",
    "prompt",
    "raw_prompt",
}
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s,;]+"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
)
_MAX_STRING_LENGTH = {
    "public": 240,
    "diagnostic": 480,
    "private": 2000,
}


def redact(value: Any, *, context: RedactionContext = "diagnostic") -> Any:
    """Recursively redact sensitive values.

    ``private`` keeps game-private reasoning but still removes credentials.
    ``diagnostic`` and ``public`` remove prompts/raw message payloads and hidden
    reasoning, keeping only a short stable summary.
    """
    return _redact_value(value, context=context, key=None)


def redact_text(text: str, *, context: RedactionContext = "diagnostic") -> str:
    """Redact secrets inside a plain string and truncate very long text."""
    redacted = str(text)
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(_pattern_replacement, redacted)
    return _truncate(redacted, max_length=_MAX_STRING_LENGTH[context])


def redaction_summary(value: Any) -> str:
    """Return a compact non-reversible summary for a redacted payload."""
    text = str(value)
    digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"[REDACTED length={len(text)} sha256={digest}]"


def _redact_value(value: Any, *, context: RedactionContext, key: str | None) -> Any:
    key_name = (key or "").lower()
    if _is_secret_key(key_name):
        return "[REDACTED]"
    if context in ("diagnostic", "public"):
        if key_name in _PUBLIC_PRIVATE_KEYS or key_name in _DIAGNOSTIC_PAYLOAD_KEYS:
            return redaction_summary(value)
    if isinstance(value, str):
        return redact_text(value, context=context)
    if isinstance(value, Mapping):
        return {
            str(item_key): _redact_value(item_value, context=context, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, tuple):
        return tuple(_redact_value(item, context=context, key=key) for item in value)
    if isinstance(value, list):
        return [_redact_value(item, context=context, key=key) for item in value]
    if isinstance(value, set):
        return sorted(_redact_value(item, context=context, key=key) for item in value)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [_redact_value(item, context=context, key=key) for item in value]
    return value


def _is_secret_key(key: str) -> bool:
    return any(part in key for part in _SECRET_KEY_PARTS)


def _truncate(text: str, *, max_length: int) -> str:
    if len(text) <= max_length:
        return text
    digest = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]
    marker = f"...[truncated length={len(text)} sha256={digest}]"
    keep = max(0, max_length - len(marker))
    return text[:keep] + marker


def _pattern_replacement(match: re.Match[str]) -> str:
    text = match.group(0)
    if text.lower().startswith("bearer "):
        return "Bearer [REDACTED]"
    if "=" in text:
        key, _, _ = text.partition("=")
        return f"{key}=[REDACTED]"
    if ":" in text:
        key, _, _ = text.partition(":")
        return f"{key}: [REDACTED]"
    return "[REDACTED]"
