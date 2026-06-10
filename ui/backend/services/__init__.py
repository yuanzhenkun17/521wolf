"""Backend service facades."""

from ui.backend.services.benchmark_service import (
    BENCHMARK_PUBLIC_METHODS,
    BenchmarkService,
    BenchmarkServiceContextProtocol,
)
from ui.backend.services.benchmark_catalog_service import BenchmarkCatalogService
from ui.backend.services.benchmark_snapshot_service import (
    BenchmarkSnapshotService,
    BenchmarkSnapshotServiceContextProtocol,
)
from ui.backend.services.evolution_service import EvolutionService
from ui.backend.services.evolution_proposal_service import EvolutionProposalService
from ui.backend.services.evolution_read_service import EvolutionReadService
from ui.backend.services.game_delete_service import GameDeleteCoordinator
from ui.backend.services.game_persistence_service import GamePersistenceService
from ui.backend.services.game_read_service import GameHistoryService, GameReadGateway
from ui.backend.services.live_game_lifecycle import LiveGameLifecycleCoordinator
from ui.backend.services.role_service import RoleService, RoleServiceStoreProtocol
from ui.backend.services.task_persistence_service import TaskPersistenceService
from ui.backend.services.task_service import BackgroundTaskServiceProtocol, TaskService

__all__ = [
    "BENCHMARK_PUBLIC_METHODS",
    "BackgroundTaskServiceProtocol",
    "BenchmarkCatalogService",
    "BenchmarkService",
    "BenchmarkServiceContextProtocol",
    "BenchmarkSnapshotService",
    "BenchmarkSnapshotServiceContextProtocol",
    "EvolutionService",
    "EvolutionProposalService",
    "EvolutionReadService",
    "GameDeleteCoordinator",
    "GameHistoryService",
    "GamePersistenceService",
    "GameReadGateway",
    "LiveGameLifecycleCoordinator",
    "RoleService",
    "RoleServiceStoreProtocol",
    "TaskPersistenceService",
    "TaskService",
]
