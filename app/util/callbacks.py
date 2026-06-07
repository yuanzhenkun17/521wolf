"""Callback helpers and tracing facade for Langfuse instrumentation.

Tracing is enabled only when Langfuse is fully configured. In local tests and
offline runs, the exported helpers become no-ops and avoid SDK warnings or
network export attempts.
"""

from __future__ import annotations

import logging
import os
import warnings
from collections.abc import Callable
from contextlib import nullcontext
from typing import Any, TypeVar

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Generic callback helper
# ---------------------------------------------------------------------------


def notify(callback: Callable[..., Any] | None, stage: str, data: dict) -> None:
    """Safely invoke an optional progress callback."""
    if callback is None:
        return
    try:
        callback(stage, data)
    except Exception:
        _log.debug("on_progress callback raised for stage %s", stage, exc_info=True)


# ---------------------------------------------------------------------------
# Langfuse tracing facade
# ---------------------------------------------------------------------------

_Func = TypeVar("_Func", bound=Callable[..., Any])

warnings.filterwarnings(
    "ignore",
    message=r"SelectableGroups dict interface is deprecated\. Use select\.",
    category=DeprecationWarning,
)


def tracing_enabled() -> bool:
    """Return whether Langfuse tracing should be active for this process."""
    flag = os.environ.get("LANGFUSE_TRACING_ENABLED")
    if flag is not None and flag.strip().lower() in {"0", "false", "no", "off"}:
        return False
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


def observe(*args: Any, **kwargs: Any) -> Callable[[_Func], _Func] | _Func:
    """Langfuse-compatible observe decorator with a no-op fallback."""
    if tracing_enabled():
        from langfuse import observe as _observe

        return _observe(*args, **kwargs)

    if args and callable(args[0]) and len(args) == 1 and not kwargs:
        return args[0]

    def decorator(func: _Func) -> _Func:
        return func

    return decorator


def propagate_attributes(**kwargs: Any):
    """Langfuse-compatible attribute propagation with a no-op fallback."""
    if tracing_enabled():
        from langfuse import propagate_attributes as _propagate_attributes

        return _propagate_attributes(**kwargs)
    return nullcontext()
