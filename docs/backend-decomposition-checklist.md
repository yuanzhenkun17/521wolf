# P0 Backend Decomposition Checklist

Status: P0 contract baseline.
Branch: `backend-p0-contract-baseline`.
Scope: backend decomposition planning only. This document freezes the current
contracts and ownership boundaries before any production refactor.

## P0 Guardrails

- Do not change production behavior in this branch.
- Do not move route, service, storage, or app-lib code in this branch.
- Do not broaden public API responses, error payloads, SSE events, task state
  shapes, or persistence schemas as part of P0.
- Keep `BackendStore` and `GameStoreMixin` as compatibility surfaces until a
  later branch introduces typed replacement contracts.
- Future branches must keep route/API contract tests green before and after each
  ownership move.

## Owner Buckets

| Owner | Frozen responsibility | Not allowed after decomposition |
| --- | --- | --- |
| route | FastAPI binding, dependency wiring, query/body parsing, HTTP status/error mapping, response model handoff. | Business state machines, background task mutation, storage gateway construction, multi-source payload assembly. |
| service | Use-case orchestration, lifecycle state transitions, task scheduling, domain actions, provider calls, SSE fallback policy. | Direct SQL/repository implementation details, ad hoc API envelope formatting that belongs to route serializers. |
| storage | Provider selection, repositories, database connections, persistence gateways, indexes, task event/background task storage. | Route response shaping, business promotion/reject/stop policy. |
| app-lib | Pure serializers, schemas, data normalization, scoring, graph/domain helpers, reusable config/status mapping. | Mutating store state, opening database connections, scheduling background work. |

## Module Ownership Baseline

Directory rows apply to every file under the path unless a more specific row
appears below.

| Module path | Owner | Baseline note |
| --- | --- | --- |
| `ui/backend/app.py` | route | App factory, exception handlers, route registration, lifespan wiring. |
| `ui/backend/main.py` | route | ASGI/app entrypoint. |
| `ui/backend/routes/core.py` | route | Route adapter today; health/TTS/leaderboard composition should move to service. |
| `ui/backend/routes/games.py` | route | Route adapter today; history detail/event stream composition should move to service/app-lib. |
| `ui/backend/routes/benchmark.py` | route | Route adapter today; start/stop/event orchestration should move to service. |
| `ui/backend/routes/evolution.py` | route | Route adapter today; proposal, trust bundle, action, list, and event orchestration should move to service/storage. |
| `ui/backend/routes/roles.py` | route | Route adapter today; version detail and rollback orchestration should move to service. |
| `ui/backend/routes/__init__.py` | route | Route package marker. |
| `ui/backend/store.py` | storage | Compatibility aggregate. Currently also holds benchmark/evolution implementation; later branches must extract service/storage contracts without breaking callers. |
| `ui/backend/game_store.py` | storage | Compatibility game aggregate. Currently mixes read gateway, live lifecycle, archive projection, and persistence helpers. |
| `ui/backend/background_store.py` | storage | Compatibility background-task persistence mixin over `TaskService`. |
| `ui/backend/history_index.py` | storage | Game history index/cache boundary. |
| `ui/backend/task_events.py` | storage | Task event log and event persistence/read helpers. |
| `ui/backend/services/benchmark_service.py` | service | Compatibility facade over `BackendStore` benchmark callables. |
| `ui/backend/services/task_service.py` | service | Background task use cases backed by storage state. Needs a typed context contract. |
| `ui/backend/services/role_service.py` | service | Role overview, summaries, cache, and leaderboard payload service. |
| `ui/backend/services/live_game_lifecycle.py` | service | Live game lifecycle orchestration. Needs a narrow game lifecycle store protocol. |
| `ui/backend/services/game_delete_service.py` | service | Delete orchestration across live sessions and persisted games. |
| `ui/backend/services/game_read_service.py` | storage | Read gateway around wolf storage connection/repositories. |
| `ui/backend/services/__init__.py` | service | Service package marker. |
| `ui/backend/evolution_actions.py` | service | Evolution proposal/action domain service helpers. |
| `ui/backend/live_game.py` | service | Live session runtime and human-action coordination. |
| `ui/backend/startup_checks.py` | service | Startup readiness checks over storage/model/registry context. |
| `ui/backend/tts_dashscope.py` | service | TTS provider integration. |
| `ui/backend/constants.py` | app-lib | Shared backend constants. |
| `ui/backend/errors.py` | app-lib | Error payload helpers and exception adapters. |
| `ui/backend/schemas.py` | app-lib | Request/response schemas and validators. |
| `ui/backend/serializers.py` | app-lib | Shared backend serializers. |
| `ui/backend/game_serializers.py` | app-lib | Game response/SSE serializers. |
| `ui/backend/evolution_serializers.py` | app-lib | Evolution response/SSE serializers. |
| `ui/backend/role_serializers.py` | app-lib | Role response serializers. |
| `ui/backend/sse.py` | app-lib | SSE formatting helpers. |
| `ui/backend/task_state.py` | app-lib | Background task state normalization/filtering helpers. |
| `ui/backend/__init__.py` | app-lib | Backend package marker. |
| `storage/**` | storage | Provider, repository, database, runtime replay, evolution, benchmark, battle, registry, and UI task persistence boundary. |
| `app/services/**` | service | App-layer LLM, prompt, memory, chain, tool, and observability services. |
| `app/run.py` | service | App-layer play/eval/evolve orchestration entrypoints. |
| `app/graphs/**` | service | Graph orchestration and node execution pipelines. |
| `app/lib/**` | app-lib | Domain helpers, benchmark specs, scoring, reviews, game/evolve/evidence primitives. |
| `app/util/**` | app-lib | Pure utility helpers. |
| `app/config.py` | app-lib | App configuration helpers. |
| `app/tools/**` | app-lib | Operational support scripts; not route/service ownership targets. |
| `tests/**` | app-lib | Verification assets only; tests do not own runtime behavior. |

## Current Store Contract Baseline

`BackendStore` is defined in `ui/backend/store.py` and remains the concrete
compatibility aggregate for P0. Its current responsibilities are:

- Lifecycle/config: `registry`, `close`, `refresh_startup_checks`,
  `invalidate_role_overview_cache`, `_open_ui_task_connection`.
- Benchmark facade: leaderboard methods, model leaderboard, benchmark
  snapshots/views/specs/seed sets, planning, batch detail, reports,
  diagnostics, queue/run methods.
- Benchmark implementation: `_leaderboard_*`, `_benchmark_*`, snapshot/view
  persistence, benchmark planning, report formatting, diagnostics, lifecycle
  overrides.
- Runtime/model status: `model_for_run`, `llm_status`, `tts_status`,
  `tts_streaming_available`.
- Evolution orchestration: `queue_evolution`, `_create_evolution_run`,
  progress/cancel helpers, `run_queued_evolution`,
  `run_queued_evolution_batch`, `_run_single_evolution`.
- Background task persistence inherited from `BackgroundTaskStoreMixin`.

`GameStoreMixin` is defined in `ui/backend/game_store.py` and remains the game
compatibility surface for P0. Its current responsibilities are:

- Deleted-game tracking: `_deleted_game_ids`, `_mark_game_deleted`,
  `_clear_game_deleted`, `_is_game_deleted`.
- Game history index/cache: `_game_history_index`,
  `invalidate_game_history_index`, `prewarm_game_history_index`,
  `_game_history_fingerprint`, `_build_game_history_rows`,
  `query_game_history`.
- Read gateway/Postgres reads: `_game_read_gateway`, `_open_wolf_connection`,
  `_load_game_*_from_pg`, `_list_games_from_pg`.
- Live lifecycle: `_live_game_lifecycle`, `start_game`, `start_live_game`,
  `run_live_session`, `check_live_game_watchdog`, `stop_game`.
- Public game API surface: `get_game`, `get_game_history_shell`,
  `get_game_phase_detail`, `get_game_flow_data`, `get_game_replay`,
  `get_game_review`, `list_games`, `get_human_action`,
  `submit_human_action`, `delete_game`.
- Snapshot/archive conversion: `_history_shell_from_snapshot`,
  `_phase_detail_from_snapshot`, `_flow_data_from_snapshot`,
  `_replay_from_snapshot`, `_review_payload`.
- Persistence: `_create_game_persistence`, `_persist_snapshot_to_pg`,
  `persist_live_session`, `_pg_snapshot_*`.

## Route Orchestration Still To Extract

| Route module | Current route-owned logic | Target owner |
| --- | --- | --- |
| `ui/backend/routes/evolution.py` | Proposal payload assembly, trust bundle lookup/fallback, run/batch listing, action state machine, proposal mutation persistence, evolution game detail projections, SSE fallback. | service plus storage gateway for trust bundle lookup |
| `ui/backend/routes/games.py` | History evidence normalization, live/history/detail path selection, human-action fallback lookup, archived/live event streaming. | service plus app-lib serializers |
| `ui/backend/routes/benchmark.py` | Benchmark SSE event naming, start/batch scheduling, stop mutation, event stream fallback. | service plus app-lib event naming |
| `ui/backend/routes/roles.py` | Version summary coercion, cache wrappers, version detail fallback, rollback policy/error mapping. | service plus app-lib normalization |
| `ui/backend/routes/core.py` | Health aggregation, TTS provider streaming, leaderboard response envelopes. | service |

## Service Store-Any Baseline

These untyped store dependencies are frozen for P0 and should be replaced by
typed protocols in later branches.

| Service/helper | Current untyped dependency | Future contract |
| --- | --- | --- |
| `TaskService.__init__(store: Any)` | Reads `paths`, task event log cache, background fingerprints, evolution run/batch maps, background lock. | `BackgroundTaskStoreProtocol` or `TaskServiceContext`. |
| `RoleService.__init__(store: Any)` | Uses registry, leaderboard score reader, overview cache private attributes. | `RoleOverviewStoreProtocol` with cache methods. |
| `LiveGameLifecycleCoordinator.__init__(store: Any)` | Uses game/session maps, paths, model/runtime helpers, persistence helpers, deletion markers, watchdog timeout, history invalidation. | `LiveGameStoreProtocol`. |
| `GameReadGateway.__init__(store: Any)` | Calls `_open_wolf_connection`. | `WolfConnectionFactory` or callable connection provider. |
| `GameDeleteCoordinator.__init__(store: Any)` | Uses watchdog, live sessions, persisted game reads/deletes, deleted markers, history invalidation. | `GameDeleteStoreProtocol`. |
| `BenchmarkService.__init__(context: Any)` | Uses untyped context paths and injected callable map. | `BenchmarkServiceContext` plus typed benchmark capability protocols. |
| `evolution_actions.py` helpers | Use `store.registry`; some helpers accept unused store parameters. | `EvolutionRegistryStoreProtocol`; remove unused params only in a behavior-preserving branch. |
| `startup_checks.py` helpers | Use paths, model, registry, provider connections. | `StartupCheckContext`. |

## P0 Checklist

- [x] Freeze owner buckets for route/service/storage/app-lib.
- [x] Record `BackendStore` and `GameStoreMixin` as compatibility aggregates.
- [x] Record route modules with business orchestration still present.
- [x] Record service/helper dependencies on `store: Any` or equivalent untyped context.
- [x] Define backend test matrix for future decomposition branches.
- [ ] Future branch: introduce narrow typed protocols without changing behavior.
- [ ] Future branch: move route orchestration into services one route group at a
  time.
- [ ] Future branch: move benchmark implementation out of `BackendStore`
  behind typed service/storage contracts.
- [ ] Future branch: split `GameStoreMixin` into read, live lifecycle, delete,
  archive projection, and persistence contracts.

## Required Test Matrix

P0 required command:

```powershell
uv run pytest tests/test_ui_backend_app.py tests/test_api_contracts.py -q
```

Route/API changes:

```powershell
uv run pytest tests/test_api_contracts.py tests/test_ui_backend_app.py -q
```

Storage/provider changes:

```powershell
uv run pytest tests/test_storage_provider.py tests/test_storage_runtime_replay.py tests/test_storage_batch_transactions.py tests/test_game_read_model.py tests/test_postgres_adapter.py tests/test_postgres_unit_of_work.py tests/test_postgresql_migrations.py tests/test_no_runtime_ddl_contract.py tests/test_postgres_only_contract.py -q
```

Service/app-lib changes:

```powershell
uv run pytest tests/test_services.py tests/test_graphs_lib.py tests/test_integration.py tests/test_game_batch.py tests/test_eval_pipeline.py tests/test_evolve_consolidate_apply.py tests/test_evolution_state_gateway.py -q
```

Useful marker suites:

```powershell
uv run pytest -m contract -q
uv run pytest -m integration -q
uv run pytest -m smoke -q
```

Environment-gated PostgreSQL runtime integration:

```powershell
$env:POSTGRES_ADMIN_DATABASE_URL="<admin-postgres-url>"; uv run pytest tests/test_postgres_runtime_integration.py -q
```

Full backend sweep when time allows:

```powershell
uv run pytest -q
```

## Parallel Follow-Up Branches

- `backend-p1-route-evolution-service`: extract evolution proposal/action/list/event orchestration from routes into services.
- `backend-p1-game-store-contracts`: type game read, live lifecycle, delete, archive, and persistence contracts around `GameStoreMixin`.
- `backend-p1-benchmark-service-contracts`: move benchmark planning/report/snapshot/view implementation behind benchmark services and repositories.
- `backend-p1-background-task-contracts`: type `TaskService` and remove private route calls to background task mutation helpers.
- `backend-p1-role-core-services`: move role rollback/version detail, health, TTS, and leaderboard envelopes behind service facades.
