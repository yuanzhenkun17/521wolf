"""Slim FastAPI application — creates the app, configures middleware, and includes routers.

All route handlers have been moved into modular APIRouter files under:
  - ui.backend.battle.game_routes
  - ui.backend.battle.leaderboard_routes
  - ui.backend.evolution.version_routes
  - ui.backend.evolution.facade_routes
  - ui.backend.game_adapter.selfplay_routes
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.common.paths import DEFAULT as DEFAULT_PATHS
from agent.learning.evolution.registry import VersionRegistry

from ui.backend.game_runner import GameManager
from ui.backend.selfplay_runner import SelfplayManager
from ui.backend.role_evolution_runner import RoleEvolutionRunner
from ui.backend.batch_role_evolution_runner import RoleBatchEvolutionRunner


# ---------------------------------------------------------------------------
# Path constants (re-exported so tests can monkey-patch app_module.DEFAULT_PATHS
# and app_module._LEADERBOARD_PATHS; route files access these via helpers)
# ---------------------------------------------------------------------------


_LEADERBOARD_PATHS = [
    DEFAULT_PATHS.runs_dir / "evolution" / "leaderboard.json",
    DEFAULT_PATHS.data_dir / "leaderboard.json",
]


# Router imports
from ui.backend.battle.game_routes import router as game_router
from ui.backend.battle.leaderboard_routes import router as leaderboard_router
from ui.backend.evaluation_routes import router as evaluation_router
from ui.backend.evolution.version_routes import router as version_router
from ui.backend.evolution.facade_routes import router as facade_router
from ui.backend.game_adapter.selfplay_routes import router as selfplay_router


# ---------------------------------------------------------------------------
# Singleton manager instances (shared across all route modules via app.state)
# ---------------------------------------------------------------------------


def _default_version_registry():
    return VersionRegistry(DEFAULT_PATHS.registry_dir)


manager = GameManager()
selfplay_manager = SelfplayManager()
version_registry = _default_version_registry()
role_evolution_runner = RoleEvolutionRunner(version_registry)
role_batch_evolution_runner = RoleBatchEvolutionRunner(version_registry)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Attach managers to app.state so route handlers can access them
    app.state.game_manager = manager
    app.state.selfplay_manager = selfplay_manager
    app.state.version_registry = version_registry
    app.state.role_evolution_runner = role_evolution_runner
    app.state.role_batch_evolution_runner = role_batch_evolution_runner

    # Restore / recover persisted state
    selfplay_manager.restore_runs()
    role_evolution_runner.recover_on_startup()
    role_evolution_runner.restore_runs()
    yield


# ---------------------------------------------------------------------------
# App creation
# ---------------------------------------------------------------------------


app = FastAPI(title="521wolf UI Backend", lifespan=_lifespan)


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


app.add_middleware(
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


# ---------------------------------------------------------------------------
# Include routers
#
# Evolution starts, status, actions, events, diffs, and evidence games are
# exposed through the canonical "/api/evolution-runs/*" facade.
# ---------------------------------------------------------------------------


app.include_router(game_router)
app.include_router(leaderboard_router)
app.include_router(evaluation_router)
app.include_router(version_router)
app.include_router(facade_router)
app.include_router(selfplay_router)


# ---------------------------------------------------------------------------
# Health endpoint (kept in app.py for simplicity)
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health() -> dict[str, Any]:
    active = next((g for g in manager._games.values() if g.is_active), None)
    return {
        "status": "ok",
        "mode": "api",
        "external": {
            "provider": "local-backend",
            "supports_human": True,
            "supports_sse": True,
            "active_game_id": active.game_id if active is not None else None,
        },
    }
