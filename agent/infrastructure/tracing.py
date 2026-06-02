"""Optional tracing facade for Langfuse instrumentation.

Tracing is enabled only when Langfuse is fully configured. In local tests and
offline runs, the exported helpers become no-ops and avoid SDK warnings or
network export attempts.
"""

from __future__ import annotations

import os
import warnings
from contextlib import nullcontext
from typing import Any, Callable, TypeVar


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
