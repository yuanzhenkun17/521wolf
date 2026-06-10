"""Startup diagnostics for the UI backend.

The checks are intentionally read-only and return public, redacted diagnostics
that can be exposed through /api/health.
"""

from __future__ import annotations

import ast
import logging
import os
from pathlib import Path
from typing import Any

from app.config import load_llm_config
from app.util.redaction import redact_text
from ui.backend.constants import ROLE_ORDER

_log = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_MIGRATIONS_DIR = _PROJECT_ROOT / "migrations" / "versions"
_DEFAULT_STATUS = "unknown"
_STARTUP_CHECK_CONNECT_KWARGS = {"connect_timeout": 3}


def default_startup_checks() -> dict[str, Any]:
    return {
        "status": _DEFAULT_STATUS,
        "ready": False,
        "summary": "Startup checks have not run yet.",
        "checks": {},
        "degraded_features": [],
        "actions": [],
    }


def run_startup_checks(store: Any) -> dict[str, Any]:
    """Run read-only startup checks for dependencies used by the UI backend."""
    checks = {
        "postgresql": _check_postgresql(store),
        "alembic": _check_alembic(store),
        "registry_baseline": _check_registry_baseline(store),
        "llm": _check_llm(store),
    }
    statuses = {str(check.get("status") or _DEFAULT_STATUS) for check in checks.values()}
    if "error" in statuses:
        status = "error"
    elif "degraded" in statuses:
        status = "degraded"
    else:
        status = "ok"

    degraded_features = [
        feature
        for check in checks.values()
        for feature in check.get("degraded_features", [])
        if isinstance(feature, str)
    ]
    actions = [
        action
        for check in checks.values()
        for action in check.get("actions", [])
        if isinstance(action, str)
    ]
    return {
        "status": status,
        "ready": status != "error",
        "summary": _summary_for_status(status),
        "checks": checks,
        "degraded_features": sorted(set(degraded_features)),
        "actions": _dedupe(actions),
    }


def log_startup_checks(result: dict[str, Any]) -> None:
    status = str(result.get("status") or _DEFAULT_STATUS)
    details = ", ".join(
        f"{name}={check.get('status')}"
        for name, check in (result.get("checks") or {}).items()
        if isinstance(check, dict)
    )
    message = f"UI backend startup checks: {status} ({details})"
    if status == "error":
        _log.error(message)
    elif status == "degraded":
        _log.warning(message)
    else:
        _log.info(message)


def _check_postgresql(store: Any) -> dict[str, Any]:
    conn = None
    try:
        from storage.provider import open_wolf_connection

        conn = open_wolf_connection(
            paths=getattr(store, "paths", None),
            connect_kwargs=_STARTUP_CHECK_CONNECT_KWARGS,
        )
        conn.execute("SELECT 1 AS ok").fetchone()
        conn.commit()
        return {
            "status": "ok",
            "message": "PostgreSQL connection is available.",
        }
    except Exception as exc:  # noqa: BLE001 - diagnostics should not crash startup
        return {
            "status": "error",
            "message": "PostgreSQL connection failed.",
            "error": _safe_error(exc),
            "degraded_features": [
                "game persistence",
                "history",
                "benchmark",
                "evolution",
                "registry",
            ],
            "actions": [
                "Start PostgreSQL and verify POSTGRES_DATABASE_URL or DATABASE_URL.",
                "If using the remote server, ensure the SSH tunnel to 127.0.0.1:15432 is open.",
            ],
        }
    finally:
        _close_quietly(conn)


def _check_alembic(store: Any) -> dict[str, Any]:
    heads = _migration_heads()
    if not heads:
        return {
            "status": "error",
            "message": "No Alembic migration head could be resolved.",
            "actions": ["Check migrations/versions and alembic.ini."],
        }

    conn = None
    try:
        from storage.provider import open_wolf_connection

        conn = open_wolf_connection(
            paths=getattr(store, "paths", None),
            connect_kwargs=_STARTUP_CHECK_CONNECT_KWARGS,
        )
        rows = conn.execute(
            "SELECT version_num FROM public.alembic_version ORDER BY version_num"
        ).fetchall()
        current = sorted(str(_row_value(row, "version_num", 0)) for row in rows)
        conn.commit()
    except Exception as exc:  # noqa: BLE001 - diagnostics should not crash startup
        return {
            "status": "error",
            "message": "Alembic version check failed.",
            "expected_heads": heads,
            "error": _safe_error(exc),
            "degraded_features": ["database schema compatibility"],
            "actions": ["Run `uv run alembic upgrade head` against the configured PostgreSQL database."],
        }
    finally:
        _close_quietly(conn)

    if not current:
        return {
            "status": "error",
            "message": "Alembic version table is empty.",
            "expected_heads": heads,
            "current_versions": current,
            "degraded_features": ["database schema compatibility"],
            "actions": ["Run `uv run alembic upgrade head` against the configured PostgreSQL database."],
        }
    if not set(heads).issubset(set(current)):
        return {
            "status": "error",
            "message": "PostgreSQL schema is not at the expected Alembic head.",
            "expected_heads": heads,
            "current_versions": current,
            "degraded_features": ["database schema compatibility"],
            "actions": ["Run `uv run alembic upgrade head` before starting long-running jobs."],
        }
    return {
        "status": "ok",
        "message": "PostgreSQL schema is at an expected Alembic head.",
        "expected_heads": heads,
        "current_versions": current,
    }


def _check_registry_baseline(store: Any) -> dict[str, Any]:
    registry = None
    owns_registry = False
    try:
        registry, owns_registry = _registry_for_check(store)
        roles = sorted(
            {*ROLE_ORDER, *registry.list_roles()},
            key=lambda role: ROLE_ORDER.index(role) if role in ROLE_ORDER else len(ROLE_ORDER),
        )
        baselines = {role: registry.get_baseline(role) for role in roles}
    except Exception as exc:  # noqa: BLE001 - diagnostics should not crash startup
        return {
            "status": "error",
            "message": "Registry baseline check failed.",
            "error": _safe_error(exc),
            "degraded_features": ["role version registry", "benchmark", "evolution"],
            "actions": [
                "Verify registry tables exist and PostgreSQL is reachable.",
                "Run `uv run alembic upgrade head` if registry tables are missing.",
            ],
        }
    finally:
        if owns_registry:
            _close_quietly(registry)

    missing = [role for role, baseline in baselines.items() if not baseline]
    if missing:
        return {
            "status": "degraded",
            "message": "One or more roles do not have a registry baseline.",
            "baseline_roles": {role: version for role, version in baselines.items() if version},
            "missing_roles": missing,
            "degraded_features": ["benchmark baselines", "evolution baseline freeze"],
            "actions": [
                "Publish or promote baseline skill versions for the missing roles.",
                "Until then, affected flows may fall back to legacy/default baseline identifiers.",
            ],
        }
    return {
        "status": "ok",
        "message": "Registry baselines are available for all known roles.",
        "baseline_roles": baselines,
    }


def _check_llm(store: Any) -> dict[str, Any]:
    if getattr(store, "model", None) is not None:
        return {
            "status": "ok",
            "message": "LLM is provided by the UI backend process.",
            "source": "injected_model",
        }
    if os.environ.get("UI_BACKEND_USE_FAKE_LLM", "").lower() in {"1", "true", "yes"}:
        return {
            "status": "degraded",
            "message": "UI backend is configured to use the fake LLM.",
            "source": "fake_model",
            "degraded_features": ["real model play", "benchmark", "evolution"],
            "actions": ["Unset UI_BACKEND_USE_FAKE_LLM for real model runs."],
        }
    try:
        config = load_llm_config()
    except Exception as exc:  # noqa: BLE001 - diagnostics should not crash startup
        return {
            "status": "degraded",
            "message": "LLM configuration is missing or invalid; fallback model will be used.",
            "source": "fallback_model",
            "error": _safe_error(exc),
            "degraded_features": ["real model play", "benchmark", "evolution"],
            "actions": [
                "Set WEREWOLF_LLM_API_KEY, WEREWOLF_LLM_BASE_URL, and WEREWOLF_LLM_MODEL in .env.",
            ],
        }
    return {
        "status": "ok",
        "message": "LLM configuration is available.",
        "source": "configured",
        "model": str(config.get("model") or ""),
        "base_url": _public_base_url(str(config.get("base_url") or "")),
        "timeout": config.get("timeout"),
        "runtime_timeout": config.get("runtime_timeout"),
    }


def _registry_for_check(store: Any) -> tuple[Any, bool]:
    existing = getattr(store, "_registry", None)
    if existing is not None:
        return existing, False

    from app.lib.version import PostgresVersionRegistry
    from storage.provider import open_registry_connection

    registry_dir = getattr(getattr(store, "paths", None), "registry_dir", None)
    registry = PostgresVersionRegistry(
        open_registry_connection(
            paths=getattr(store, "paths", None),
            connect_kwargs=_STARTUP_CHECK_CONNECT_KWARGS,
        ),
        registry_dir=Path(registry_dir) if registry_dir is not None else _PROJECT_ROOT / "data" / "registry",
        owns_conn=True,
    )
    return registry, True


def _migration_heads() -> list[str]:
    revisions: dict[str, Path] = {}
    down_revisions: set[str] = set()
    for path in sorted(_MIGRATIONS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            module = ast.parse(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        revision = None
        down_revision = None
        for node in module.body:
            if not isinstance(node, ast.Assign):
                continue
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if "revision" in names:
                revision = _literal_string(node.value)
            if "down_revision" in names:
                down_revision = _literal_down_revisions(node.value)
        if revision:
            revisions[revision] = path
            down_revisions.update(down_revision or [])
    return sorted(set(revisions) - down_revisions)


def _literal_string(node: ast.AST) -> str | None:
    try:
        value = ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None
    return value if isinstance(value, str) else None


def _literal_down_revisions(node: ast.AST) -> set[str]:
    try:
        value = ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return set()
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    if isinstance(value, (tuple, list, set)):
        return {str(item) for item in value if item}
    return set()


def _safe_error(exc: Exception) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": redact_text(str(exc) or type(exc).__name__, context="diagnostic"),
    }


def _row_value(row: Any, key: str, index: int) -> Any:
    keys = getattr(row, "keys", None)
    if callable(keys) and key in set(keys()):
        return row[key]
    try:
        return row[key]
    except Exception:
        return row[index]


def _public_base_url(value: str) -> str:
    if not value:
        return ""
    return redact_text(value.rstrip("/"), context="public")


def _summary_for_status(status: str) -> str:
    if status == "ok":
        return "All startup checks passed."
    if status == "degraded":
        return "Startup checks passed with degraded features."
    if status == "error":
        return "One or more critical startup checks failed."
    return "Startup checks have not run yet."


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        result.append(value)
        seen.add(value)
    return result


def _close_quietly(conn: Any) -> None:
    if conn is None:
        return
    try:
        conn.close()
    except Exception:
        pass
