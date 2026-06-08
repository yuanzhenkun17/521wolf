"""Time helpers — Beijing time (UTC+8)."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

BEIJING_TZ = timezone(timedelta(hours=8))


def beijing_now() -> datetime:
    """Return the current datetime in Beijing time (UTC+8)."""
    return datetime.now(BEIJING_TZ)


def beijing_now_iso() -> str:
    """Return the current Beijing time as an ISO-8601 string."""
    return beijing_now().isoformat()


def beijing_now_str(fmt: str = "%Y%m%d_%H%M%S") -> str:
    """Return the current Beijing time formatted with *fmt*."""
    return beijing_now().strftime(fmt)
