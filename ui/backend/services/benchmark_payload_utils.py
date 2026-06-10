"""Shared pure helpers for benchmark payload modules."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.util.redaction import redact, redact_text


def dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def text_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def unique_texts(*values: Any) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        items.append(text)
    return items


def json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def sanitize_model_runtime(value: Any) -> dict[str, Any]:
    """Return a public model runtime payload with credentials removed."""
    if not isinstance(value, dict):
        return {}
    runtime = redact(json_clone(value), context="diagnostic")
    if not isinstance(runtime, dict):
        return {}
    return _strip_url_queries(runtime)


def sanitize_config_model_runtime(value: Any) -> Any:
    if not isinstance(value, dict):
        return json_clone(value)
    return sanitize_model_runtime_containers(value)


def sanitize_model_runtime_containers(value: Any) -> Any:
    """Sanitize nested ``model_runtime`` dictionaries inside public payloads."""
    return _sanitize_model_runtime_containers(json_clone(value))


def sanitize_public_payload(value: Any) -> Any:
    """Return a public diagnostic/report payload with secrets and URL queries removed."""
    return _strip_url_queries(redact(json_clone(value), context="diagnostic"))


def sanitize_public_text(value: Any) -> str:
    return redact_text(str(value if value is not None else ""), context="diagnostic")


def decode_json_field(value: Any, *, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return fallback


def row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    keys = getattr(row, "keys", None)
    if callable(keys):
        return {key: row[key] for key in keys()}
    return {}


def _strip_url_queries(value: Any, *, key: str = "") -> Any:
    key_lower = str(key or "").lower()
    if isinstance(value, dict):
        return {str(item_key): _strip_url_queries(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_strip_url_queries(item, key=key) for item in value]
    if isinstance(value, tuple):
        return tuple(_strip_url_queries(item, key=key) for item in value)
    if isinstance(value, str) and ("url" in key_lower or "endpoint" in key_lower):
        return _public_url(value)
    return value


def _sanitize_model_runtime_containers(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for item_key, item_value in value.items():
            key = str(item_key)
            if key == "model_runtime" and isinstance(item_value, dict):
                sanitized[key] = sanitize_model_runtime(item_value)
            else:
                sanitized[key] = _sanitize_model_runtime_containers(item_value)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_model_runtime_containers(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_sanitize_model_runtime_containers(item) for item in value)
    return value


def _public_url(value: str) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return ""
    try:
        parts = urlsplit(text)
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    except ValueError:
        return text.split("?", 1)[0].split("#", 1)[0].rstrip("/")
