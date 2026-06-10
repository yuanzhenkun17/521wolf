# ArtifactStore 与 PostgreSQL 任务队列执行方案

日期：2026-06-10

## 结论

在单机部署前提下，不需要 Redis、RabbitMQ、Kafka、MinIO 或 S3。下一阶段最合适的目标架构是：

```text
PostgreSQL-backed task queue
+ PostgreSQL task_events + SSE
+ 本地文件系统 ArtifactStore
+ PostgreSQL artifact metadata index
```

它要解决两个当前已经暴露的问题：

1. 长耗时任务仍由 FastAPI `BackgroundTasks` 执行，任务状态和事件虽然已持久化，但 worker claim、lease、retry、cancel、resume 还不是 durable queue。
2. benchmark、evaluation、evolution、Langfuse 验证会产生报告、manifest、diagnostics、replay bundle 等产物，目前没有统一 artifact index 和下载 API。

本方案不引入外部中间件。PostgreSQL 承担任务队列、任务事件、artifact 元数据索引；大文件继续放本地 `runs/`。

## 当前执行状态

已完成 Phase A 基础设施骨架，范围刻意控制在低耦合层：

- 已新增 `20260610_0003_task_queue_artifacts` migration，创建 `wolf.ui_task_queue` 与 `wolf.ui_task_artifacts`。
- 已新增 `TaskQueueRepository`，覆盖 enqueue、claim、heartbeat、complete、cancel、retry、expired interrupted 等基础操作。
- 已新增 `TaskArtifactRepository`，覆盖 artifact metadata upsert、get、list、delete。
- 已新增本地 `LocalArtifactStore`，写入 `runs/tasks/<task_id>/...`，并记录 `sha256`、`size_bytes`、`content_type` 和 metadata。
- 已更新 PostgreSQL adapter JSONB 列映射。
- 已新增聚焦测试 `tests/test_task_queue_artifacts.py`。

本阶段没有接入 benchmark/evolution 路由，没有改前端，也没有启动 worker。后续接线必须等前后端重构边界稳定后再做。

已验证：

```text
uv run pytest tests/test_task_queue_artifacts.py -q
uv run pytest tests/test_postgres_adapter.py -q
```

## 当前状态

当前运行链路更准确地说是：

```text
FastAPI BackgroundTasks
+ BackendStore 进程内状态
+ wolf.ui_background_tasks 任务快照
+ wolf.ui_task_events 任务事件回放
+ evolution.evolution_runs runtime_state
+ runs/ 下分散产物
```

已经具备的能力：

- `wolf.ui_background_tasks` 可以让前端刷新后恢复部分后台任务快照。
- `wolf.ui_task_events` 可以支持 evolution/benchmark SSE replay。
- `evolution.evolution_runs.runtime_state` 保存自进化运行结果、gate report、trust bundle 等状态。
- benchmark report 已经有 reproducibility/hash 概念。
- `runs/` 已经承载 game/evolution/smoke/diagnostics 等本地产物。

不足：

- active task 仍绑定当前 Python 进程；进程重启后不能真正恢复执行。
- 云端 UI backend 和本地 worker 之间没有统一任务队列语义。
- UI 列表主要读 `ui_background_tasks`，不是直接以 durable task 表为权威。
- task payload 可能继续膨胀，不适合放大报告、zip、manifest、diagnostics。
- 没有 `task_id -> artifacts[]` 的通用索引。
- artifact 清理只能按目录粗粒度做，不能按 task、status、retention 精确清理。

## 目标边界

### 做什么

- 新增 `wolf.ui_task_queue` 作为长任务权威队列表。
- 新增单机 worker loop，通过 PostgreSQL claim task。
- 统一任务状态机：`queued -> running -> succeeded | failed | cancelled | interrupted`。
- 保留并强化 `wolf.ui_task_events` 作为进度事件和 SSE replay。
- 新增 `wolf.ui_task_artifacts` 作为 artifact 元数据索引。
- 新增本地文件系统 ArtifactStore：实际文件写入 `runs/tasks/<task_id>/...`。
- 将 benchmark/evaluation/evolution/Langfuse 长任务逐步迁入 queue。
- 前端从任务状态和 artifact index 展示进度、结果和下载入口。

### 不做什么

- 不引入 Redis/RabbitMQ/Kafka。
- 不引入 MinIO/S3。
- 不把大 artifact 存 PostgreSQL。
- 不在第一阶段做多机调度。
- 不把所有 CLI 一次性改成后台任务；先迁 UI 触发的长任务。

## 数据模型

### `wolf.ui_task_queue`

建议字段：

```text
task_id text primary key
kind text not null
status text not null
priority integer not null default 100
payload jsonb not null
result jsonb
error jsonb
progress jsonb
attempt integer not null default 0
max_attempts integer not null default 1
lease_owner text
lease_expires_at timestamptz
queued_at timestamptz not null
started_at timestamptz
updated_at timestamptz not null
finished_at timestamptz
cancel_requested boolean not null default false
idempotency_key text
parent_task_id text
source text
metadata jsonb
```

索引：

```text
idx_ui_task_queue_status_priority(status, priority, queued_at)
idx_ui_task_queue_lease(lease_expires_at)
idx_ui_task_queue_kind(kind, updated_at)
idx_ui_task_queue_idempotency(idempotency_key)
```

状态语义：

| 状态 | 含义 |
|---|---|
| `queued` | 已入队，等待 worker claim |
| `running` | 已被 worker claim 且 lease 未过期 |
| `succeeded` | 任务完成，result 可读 |
| `failed` | 任务失败，error 可读 |
| `cancelled` | 用户取消或 stop 请求生效 |
| `interrupted` | worker 失联或进程重启后 lease 过期 |

### `wolf.ui_task_artifacts`

建议字段：

```text
artifact_id text primary key
task_id text not null
artifact_type text not null
name text not null
relative_path text not null
content_type text
size_bytes bigint
sha256 text
created_at timestamptz not null
metadata jsonb
```

索引：

```text
idx_ui_task_artifacts_task(task_id, created_at)
idx_ui_task_artifacts_type(artifact_type, created_at)
idx_ui_task_artifacts_sha256(sha256)
```

### 文件布局

```text
runs/
  tasks/
    <task_id>/
      result.json
      events.jsonl
      benchmark-report.json
      reproducibility-manifest.json
      langfuse-verification.json
      annotation-queue.json
      link-manifest.json
      diagnostics.zip
```

规则：

- PostgreSQL 保存 artifact metadata、hash、size、relative path。
- 本地文件系统保存 bytes。
- `relative_path` 必须限制在 `runs/tasks/<task_id>/` 下，下载 API 不接受任意路径。
- 写入 artifact 时必须计算 `sha256` 和 `size_bytes`。
- task payload 不再塞大报告，只放 summary 和 artifact ids。

## 影响面

| 影响面 | 当前行为 | 改造后行为 | 风险 | 控制方式 |
|---|---|---|---|---|
| benchmark/evaluation 启动 | `BackgroundTasks` 直接执行 | 写入 `ui_task_queue`，worker claim | 任务延迟可见 | 队列状态实时返回，SSE 显示 queued/running |
| evolution 启动 | 进程内 run/batch 状态主导 | task queue 为执行权威，evolution runtime 为结果权威 | 状态双写漂移 | 先桥接，再收口为 task facade |
| 前端进度 | 依赖 SSE + task snapshot | task queue + task_events + SSE | 老事件污染新任务 | per-task local event id 继续保留 |
| 前端结果下载 | 多接口散落返回 payload | 统一 artifacts API | 下载路径安全 | relative path 校验 + content-type 白名单 |
| 数据库 | 只有 task snapshot/event | 增加 queue/artifact 两张表 | migration 风险 | Alembic + repository tests |
| 本地磁盘 | `runs/` 分散产物 | `runs/tasks/<task_id>/` 归档 | 磁盘增长 | retention job 按 task 清理 |
| 部署 | 只启动 API 进程 | API + 单机 worker loop | worker 未启动 | health check 增加 worker freshness |
| 测试 | contract 覆盖 UI API | 增加 queue/artifact repo + worker tests | 长任务测试慢 | fake executor + 小样本 integration |

## 上线门禁

每个阶段必须满足对应 gate，不能把“可运行 demo”当作“生产可用”。

### Gate 0：兼容性门禁

- 现有 `/api/benchmark`、`/api/evolution-runs` 响应结构保持兼容。
- 老的 `ui_background_tasks` 和 `ui_task_events` 仍可读。
- 未启用 worker 时，开发环境可以保留 fallback，但生产 health 必须提示 degraded。

### Gate 1：Schema 门禁

- Alembic migration 创建 `ui_task_queue`、`ui_task_artifacts`。
- repository 单测覆盖 insert/list/claim/update/cancel/artifact put/list。
- migration rollback 至少能 drop 新表，不影响既有表。

### Gate 2：Queue 执行门禁

- queued task 能被 worker claim。
- running task 有 lease 和 heartbeat。
- worker 崩溃后 lease 过期，task 进入 interrupted 或重新 queued。
- cancel_requested 能让 evolution/benchmark 在下一检查点停止。
- 同一个 idempotency key 不重复创建同类任务。

### Gate 3：Artifact 门禁

- task 完成后 artifacts 可列出、可下载。
- 下载 API 不能读取 `runs/tasks/<task_id>/` 之外文件。
- artifact `sha256` 与实际文件一致。
- 删除 task artifact metadata 不应误删非 task 目录。

### Gate 4：UI 门禁

- 前端能看到 queued/running/succeeded/failed/cancelled。
- 任务详情能展示 artifacts。
- 页面刷新后状态来自 PostgreSQL，不依赖原进程内存。
- SSE 断线后可用 Last-Event-ID 续传。

### Gate 5：发布门禁

- `uv run pytest tests/test_api_contracts.py -q -k "benchmark or evolution or task"` 通过或失败原因已记录。
- repository 和 worker 单测通过。
- 前端相关 node tests/build 通过。
- 部署 smoke 检查 API、worker、DB migration、artifact 目录可写。

## 阶段与 Step

### P0：契约和文档定稿

目标：先把状态机、schema、API、迁移策略定死。

Steps：

1. 定义 task kind：
   - `benchmark_run`
   - `benchmark_batch`
   - `evaluation_run`
   - `evolution_run`
   - `evolution_batch`
   - `langfuse_verification`
   - `langfuse_annotation_export`
   - `langfuse_link_manifest`
2. 定义 status transition：
   - `queued -> running`
   - `running -> succeeded`
   - `running -> failed`
   - `running -> cancelled`
   - `running -> interrupted`
   - `interrupted -> queued` 只允许显式 retry。
3. 定义 API contract：
   - `GET /api/tasks`
   - `GET /api/tasks/{task_id}`
   - `POST /api/tasks/{task_id}/cancel`
   - `POST /api/tasks/{task_id}/retry`
   - `GET /api/tasks/{task_id}/events`
   - `GET /api/tasks/{task_id}/artifacts`
   - `GET /api/tasks/{task_id}/artifacts/{artifact_id}`
4. 定义兼容映射：
   - `/api/benchmark/batch/{batch_id}/events` 映射到 task events。
   - `/api/evolution-runs/{run_id}/events` 映射到 task events。
   - 旧 response 继续带 `run_id`/`batch_id`。

验收：

- 文档合并。
- API contract 测试 skeleton 加入。
- 没有 runtime 行为变化。

### P1：ArtifactStore 基础设施

目标：先解决产物存储，不改变任务执行方式。

Steps：

1. 新增 migration：`wolf.ui_task_artifacts`。
2. 新增 repository：`storage/ui/task_artifact_repo.py`。
3. 新增本地实现：`storage/artifacts.py` 或 `ui/backend/artifact_store.py`。
4. 支持方法：
   - `put_json(task_id, name, payload, artifact_type, metadata=None)`
   - `put_bytes(task_id, name, data, artifact_type, content_type=None, metadata=None)`
   - `list(task_id)`
   - `open(artifact_id)`
   - `delete_task(task_id)`
5. 新增下载 API：
   - `GET /api/tasks/{task_id}/artifacts`
   - `GET /api/tasks/{task_id}/artifacts/{artifact_id}`
6. 先接 benchmark report：
   - JSON report。
   - Markdown/CSV export。
   - reproducibility manifest。

验收：

- artifact repository 单测。
- path traversal 测试。
- benchmark report artifact list/download contract。
- 现有 benchmark report API 不破坏。

### P2：PostgreSQL Task Queue 基础设施

目标：实现 durable queue，但先只跑 fake executor 和一个低风险任务。

Steps：

1. 新增 migration：`wolf.ui_task_queue`。
2. 新增 repository：`storage/ui/task_queue_repo.py`。
3. 新增 service：`ui/backend/services/task_queue_service.py`。
4. 实现 worker claim：
   - `SELECT ... FOR UPDATE SKIP LOCKED`
   - 设置 `lease_owner`
   - 设置 `lease_expires_at`
   - attempt +1
5. 实现 heartbeat：
   - 更新 `lease_expires_at`
   - 更新 `progress`
   - 写 `ui_task_events`
6. 实现 cancel：
   - API 设置 `cancel_requested=true`
   - executor 通过 cancel_check 停止。
7. 实现 interrupted recovery：
   - lease 过期后标记 interrupted。
   - retry 必须显式触发。

验收：

- claim 并发测试：两个 worker 不 claim 同一 task。
- lease 过期测试。
- cancel 测试。
- task event replay 测试。
- API health 能报告 worker freshness。

### P3：迁移 Benchmark/Evaluation 长任务

目标：把 benchmark/evaluation 从 `BackgroundTasks` 迁到 queue。

Steps：

1. `POST /api/benchmark` 不再直接 `background_tasks.add_task`。
2. 创建 `benchmark_batch` task。
3. worker 执行原有 `run_queued_benchmark` 逻辑。
4. progress_sink 写 queue progress 和 task events。
5. 完成后写 artifacts：
   - report JSON
   - Markdown/CSV export
   - reproducibility manifest
   - diagnostics
6. 旧 `/api/benchmark/batch/{batch_id}/report` 保持兼容。
7. `GET /api/benchmark/batch/{batch_id}/artifacts` 可转发到 task artifacts。

验收：

- benchmark 创建后立即返回 queued/running task。
- 页面刷新后任务仍可见。
- API contract 中 benchmark report、events、artifacts 通过。
- worker 重启时 running task 不静默丢失。

### P4：迁移 Evolution 长任务

目标：解决本地 worker 跑任务、云端前端看不到的问题。

Steps：

1. `POST /api/evolution-runs` 创建 `evolution_run` 或 `evolution_batch` task。
2. `run_id`/`batch_id` 与 `task_id` 建立稳定映射。
3. worker 执行 `run_evolution`。
4. progress_sink 写：
   - `ui_task_queue.progress`
   - `ui_task_events`
   - `evolution.evolution_runs.runtime_state`
5. `GET /api/evolution-runs` 以 PostgreSQL 权威状态为主：
   - active/progress 从 task queue。
   - final/runtime 从 `evolution.evolution_runs`。
   - legacy `ui_background_tasks` 只作为兼容输入。
6. completion 写 artifacts：
   - result.json
   - gate-report.json
   - trust-bundle.json
   - paired-seed-battle-table.json
   - scenario-replay-report.json
   - diagnostics.json
7. proposal accept/reject/apply 继续作用于 evolution runtime state，并写审计事件。

验收：

- 本地 worker 写同一 PostgreSQL 后，云端前端能看到任务。
- evolution list/detail/proposals/trust-bundle/events contract 通过。
- cancel/terminate 能停止 queued/running task。
- trust bundle artifact 与 API payload hash 一致。

### P5：Langfuse 工具任务化

目标：把 Langfuse 验证、annotation queue、link manifest 纳入统一任务和 artifact 体系。

Steps：

1. 包装任务类型：
   - `langfuse_verification`
   - `langfuse_annotation_export`
   - `langfuse_link_manifest`
2. CLI 保持 `--output` 兼容。
3. UI/API 触发时输出写 ArtifactStore。
4. result payload 只保存 summary、artifact ids、counts、diagnostics。
5. 失败时写 error artifact，保留排查上下文。

验收：

- 无 Langfuse 配置时 fail-open/fail-closed 行为清晰。
- 有 Langfuse 配置时 verification report 可下载。
- annotation queue JSON 可下载。
- link manifest JSON 可下载。

### P6：前端任务中心和 Artifact UI

目标：前端不再把 benchmark/evolution 的长任务状态各自散落处理。

Steps：

1. 新增 task service：
   - list tasks
   - get task
   - cancel
   - retry
   - events
   - artifacts
2. Benchmark/Evolution 页面仍保留领域视图，但共享 task 状态组件。
3. 任务详情展示：
   - status
   - progress
   - current stage
   - started/finished
   - error diagnostics
   - artifacts download list
4. Artifact download 按 content-type 展示：
   - JSON inline preview
   - CSV/Markdown download
   - zip download

验收：

- 刷新页面不丢任务。
- queued/running/succeeded/failed/cancelled UI 明确。
- artifact 缺失时显示可操作错误，而不是空白。
- 移动端不出现布局重叠。

### P7：Retention、清理和运维

目标：防止 `runs/tasks/` 和任务表无限增长。

Steps：

1. 扩展 `app/tools/cleanup_runs.py` 或新增 `cleanup_task_artifacts.py`。
2. 策略：
   - succeeded/failed 超过 N 天清理 artifacts。
   - retained release artifacts 可打标不删。
   - DB metadata 可保留更久，文件可先删。
3. 新增 health check：
   - artifact root exists/writable。
   - worker freshness。
   - queue backlog。
   - stuck running tasks。
4. 新增运维命令：
   - list queued/running tasks。
   - retry interrupted task。
   - cancel task。
   - verify artifact hashes。

验收：

- dry-run cleanup 输出准确。
- execute cleanup 不越界删除。
- artifact missing 能在 UI/API 中降级为 diagnostics。

## 推荐实施顺序

最稳顺序：

```text
P0 契约
P1 ArtifactStore
P2 Task Queue
P3 Benchmark/Evaluation 迁移
P4 Evolution 迁移
P5 Langfuse 工具任务化
P6 Frontend Task/Artifact UI
P7 Retention/Operations
```

原因：

- ArtifactStore 可以先落地，风险小，并且马上减少 task payload 膨胀。
- Queue 是执行语义变化，必须在低风险任务验证后再迁 evolution。
- Evolution 最复杂，涉及 runtime_state、trust bundle、proposal review、registry promote，应该在 queue 基础稳定后做。

## 回滚策略

### ArtifactStore 回滚

- 保留老 API payload 返回。
- artifact 写入失败时只记录 warning，不阻断主任务。
- 下载 API 独立，可关闭路由或隐藏前端入口。

### Task Queue 回滚

- 保留 feature flag：

```text
WOLF_USE_PG_TASK_QUEUE=false
```

- 关闭后回到原 `BackgroundTasks` 路径。
- 新表保留，不影响旧路径。
- 已入队任务可通过运维脚本 cancel 或 retry。

### Evolution 回滚

- `evolution.evolution_runs` runtime_state 继续作为结果权威。
- 若 queue executor 出问题，允许手动以旧路径运行单次 evolution。
- promotion 操作保持原 API guard，不因 queue 改造放宽。

## 测试矩阵

后端：

```text
uv run pytest tests/test_api_contracts.py -q -k "benchmark or evolution or task"
uv run pytest tests/test_evolution_state_gateway.py -q
uv run pytest tests/test_postgres_adapter.py -q
uv run pytest tests/test_services.py -q
```

新增建议：

```text
tests/test_task_queue_repo.py
tests/test_task_worker.py
tests/test_artifact_store.py
tests/test_task_artifact_api.py
tests/test_evolution_task_queue_integration.py
tests/test_benchmark_task_queue_integration.py
```

前端：

```text
node --test ui/frontend/tests/*.test.js
npm run build --prefix ui/frontend
```

新增建议：

```text
ui/frontend/tests/task-artifacts-contract.test.js
ui/frontend/tests/task-status-recovery-contract.test.js
```

部署 smoke：

```text
uv run alembic upgrade head
curl http://127.0.0.1:8000/api/health
curl http://127.0.0.1:8000/api/tasks
```

## 最小可上线版本

如果要压缩范围，最小可上线版本是：

1. `ui_task_queue` + worker claim/lease/cancel。
2. `ui_task_artifacts` + local ArtifactStore。
3. benchmark/evolution 创建任务走 queue。
4. progress 写 `ui_task_events`。
5. artifacts 可 list/download。
6. health 显示 worker freshness 和 artifact root writable。

可以暂缓：

- Langfuse 工具任务化。
- 完整前端任务中心。
- artifact retention UI。
- 多 worker 高级调度。

## 完成定义

该路线完成时必须满足：

- 本地 worker 跑 evolution，云端前端能通过同一 PostgreSQL 看到任务状态。
- 进程重启不会静默丢失 running task。
- benchmark/evolution 结果不再依赖 task payload 承载大报告。
- 任务产物都有 artifact metadata、sha256、size 和下载 API。
- 页面刷新、SSE 断线、worker 重启都有可解释状态。
- 单机部署无需新增外部中间件。
