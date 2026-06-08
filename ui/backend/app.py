"""FastAPI backend that adapts the current app/ implementation to the Vue UI."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import DEFAULT_PATHS, PathConfig
from ui.backend.constants import ROLE_ORDER
from ui.backend.routes.benchmark import register_benchmark_routes
from ui.backend.routes.core import register_core_routes
from ui.backend.routes.evolution import register_evolution_routes
from ui.backend.routes.games import register_game_routes
from ui.backend.routes.roles import register_role_routes
from ui.backend.store import BackendStore, _FakeModel

_log = logging.getLogger(__name__)


def create_app(
    *,
    paths: PathConfig | None = None,
    model: Any | None = None,
    restore_background: bool = True,
) -> FastAPI:
    store = BackendStore(paths=paths or _paths_from_env(), model=model)
    store.paths.runs_dir.mkdir(parents=True, exist_ok=True)
    store.paths.games_dir.mkdir(parents=True, exist_ok=True)
    store.paths.registry_dir.mkdir(parents=True, exist_ok=True)
    if restore_background:
        store.restore_background_tasks()

    @asynccontextmanager
    async def _lifespan(_api: FastAPI) -> AsyncIterator[None]:
        store.refresh_startup_checks()
        try:
            yield
        finally:
            store.close()

    api = FastAPI(title="521wolf UI Backend", lifespan=_lifespan)
    api.state.backend_store = store
    _register_error_handlers(api)
    api.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:5174",
            "http://127.0.0.1:5174",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_core_routes(api, store)
    register_game_routes(api, store)
    register_role_routes(api, store)
    register_evolution_routes(api, store)
    register_benchmark_routes(api, store)

    return api


def _paths_from_env() -> PathConfig:
    root = os.environ.get("UI_BACKEND_ROOT")
    return PathConfig(root=Path(root)) if root else DEFAULT_PATHS


def _register_error_handlers(api: FastAPI) -> None:
    @api.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        fallback = _status_message(exc.status_code)
        detail = exc.detail if exc.detail is not None else fallback
        message = _detail_message(detail, fallback=fallback)
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_response(
                detail=detail,
                code=_http_error_code(exc.status_code),
                message=message,
                diagnostics=[],
            ),
            headers=getattr(exc, "headers", None),
        )

    @api.exception_handler(RequestValidationError)
    async def validation_exception_handler(_request: Request, exc: RequestValidationError) -> JSONResponse:
        diagnostics = exc.errors()
        return JSONResponse(
            status_code=422,
            content=_error_response(
                detail=diagnostics,
                code="validation_error",
                message="Request validation failed",
                diagnostics=diagnostics,
            ),
        )

    @api.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        _log.exception("Unhandled UI backend error on %s %s", request.method, request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content=_error_response(
                detail="Internal Server Error",
                code="internal_error",
                message="Internal Server Error",
                diagnostics=[],
            ),
        )


def _error_response(*, detail: Any, code: str, message: str, diagnostics: list[Any]) -> dict[str, Any]:
    return {
        "detail": jsonable_encoder(detail),
        "error": {
            "code": code,
            "message": message,
            "diagnostics": jsonable_encoder(diagnostics),
        },
    }


def _status_message(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "HTTP error"


def _http_error_code(status_code: int) -> str:
    names = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        500: "internal_error",
        502: "bad_gateway",
        503: "service_unavailable",
    }
    if status_code in names:
        return names[status_code]
    return f"http_{status_code}"


def _detail_message(detail: Any, *, fallback: str) -> str:
    if isinstance(detail, str) and detail:
        return detail
    if isinstance(detail, dict):
        for key in ("message", "detail"):
            value = detail.get(key)
            if isinstance(value, str) and value:
                return value
    return fallback


app = create_app(restore_background=False)
