"""Callback helpers."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

_log = logging.getLogger(__name__)


def notify(callback: Callable[..., Any] | None, stage: str, data: dict) -> None:
    """Safely invoke an optional progress callback."""
    if callback is None:
        return
    try:
        callback(stage, data)
    except Exception:
        _log.debug("on_progress callback raised for stage %s", stage, exc_info=True)
