"""Error classification helpers."""

from __future__ import annotations


def is_rate_limit_error(exc: Exception) -> bool:
    """Check if an exception is a 429 rate limit error."""
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "too many requests" in msg
