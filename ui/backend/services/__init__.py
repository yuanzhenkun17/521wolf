"""Backend service facades."""

from ui.backend.services.benchmark_service import (
    BENCHMARK_PUBLIC_METHODS,
    BenchmarkService,
    BenchmarkServiceContextProtocol,
)
from ui.backend.services.game_delete_service import GameDeleteCoordinator
from ui.backend.services.game_read_service import GameReadGateway
from ui.backend.services.role_service import RoleService, RoleServiceStoreProtocol
from ui.backend.services.task_service import TaskService

__all__ = [
    "BENCHMARK_PUBLIC_METHODS",
    "BenchmarkService",
    "BenchmarkServiceContextProtocol",
    "GameDeleteCoordinator",
    "GameReadGateway",
    "RoleService",
    "RoleServiceStoreProtocol",
    "TaskService",
]
