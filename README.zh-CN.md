<div align="center">
  <img src="logo.png" alt="夜议会 logo" width="168" />
  <h1>夜议会</h1>
  <p>
    <strong>面向 AI 狼人杀智能体的工作台。</strong><br />
    跑对局、看决策、做评测、迭代角色技能。
  </p>
  <p>
    <a href="README.md">English</a> |
    <a href="README.zh-CN.md">简体中文</a>
  </p>
  <p>
    <a href="https://github.com/yuanzhenkun17/521wolf/actions/workflows/ci.yml">
      <img alt="CI" src="https://github.com/yuanzhenkun17/521wolf/actions/workflows/ci.yml/badge.svg" />
    </a>
    <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-3776AB" />
    <img alt="FastAPI" src="https://img.shields.io/badge/backend-FastAPI-009688" />
    <img alt="Vue and Vite" src="https://img.shields.io/badge/frontend-Vue%20%2B%20Vite-42B883" />
    <img alt="PostgreSQL" src="https://img.shields.io/badge/database-PostgreSQL-4169E1" />
    <img alt="LLM agents" src="https://img.shields.io/badge/agents-LLM%20%2B%20skills-FF7A1A" />
  </p>
</div>

夜议会是一个 12 人狼人杀 AI 智能体系统，用来构建、运行、复盘和评测
LLM 驱动的角色智能体。它把确定性的规则引擎、角色技能提示词、PostgreSQL
持久化、FastAPI 后端和 Vue 工作台组合在一起，覆盖实时对局、对局档案、
Benchmark、复盘、自进化、任务和设置等工作流。

PostgreSQL 是唯一受支持的运行时权威数据源。`runs/`、`data/` 等本地文件
只是辅助产物，不应当作为可迁移或可恢复的正式状态。

## 从这里开始

| 你想做什么 | 去哪里 |
| --- | --- |
| 安装项目并打开前端工作台 | [快速开始](#快速开始) |
| 不调用真实模型，先跑本地演示 | [Fake LLM 演示模式](#fake-llm-演示模式) |
| 配置真实模型、数据库、语音或链路追踪 | [配置项](#配置项) |
| 了解系统能力边界 | [功能面](#功能面) |
| 找主要代码目录 | [架构地图](#架构地图) |
| 跑测试和生产构建检查 | [验证](#验证) |
| 弄清哪些运行数据不能提交 | [运行时数据边界](#运行时数据边界) |

## 功能面

| 模块 | 能力 |
| --- | --- |
| 规则引擎 | 标准 12 人白狼王局流程，包括夜间行动、警长竞选、发言、PK/放逐投票、死亡处理和胜负判定。 |
| 角色 | 村民、狼人、白狼王、预言家、女巫、猎人、守卫。 |
| 智能体运行时 | 角色技能、LLM 调用、策略约束、重试、超时、决策记录和玩家视角信息隔离。 |
| 前端工作台 | 大厅、实时对局、历史档案、Benchmark、自进化、任务队列和设置页。 |
| 评测系统 | 批量运行、排行榜、快照、诊断、报告和保存视图，全部落在 PostgreSQL。 |
| 自进化 | 技能候选生成、提案评审、dry-run/preflight 检查和晋级流程。 |
| 可观测性 | 健康门禁、启动诊断、可选自部署 Langfuse 链路追踪和运行时提示。 |

## 架构地图

| 路径 | 职责 |
| --- | --- |
| `engine/` | 确定性的狼人杀规则、阶段、动作和玩家视角请求。 |
| `app/` | 智能体编排、LLM 服务、角色技能加载、可观测性工具和 CLI 工具。 |
| `storage/` | PostgreSQL 仓储层，覆盖对局、决策、评测、自进化、角色注册表、任务和产物索引。 |
| `ui/backend/` | FastAPI API 层，把引擎、存储、健康检查、设置和后台任务暴露给前端。 |
| `ui/frontend/` | Vue/Vite 前端工作台。 |
| `skills/default_baseline/` | 默认角色技能基线。 |
| `migrations/` | Alembic 数据库迁移。 |
| `docs/` | 设计文档、审计报告、执行计划和运行时策略。 |

## 环境要求

- Python 3.11+
- `uv`
- Node.js 20+ 和 npm
- 推荐 PostgreSQL 16+

## 快速开始

安装 Python 依赖：

```powershell
uv sync
```

安装前端依赖：

```powershell
npm install --prefix ui/frontend
```

创建本地环境文件：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，至少设置：

```dotenv
POSTGRES_DATABASE_URL=postgresql://wolf_app:password@127.0.0.1:5432/wolf_app
DATABASE_URL=${POSTGRES_DATABASE_URL}

WEREWOLF_LLM_API_KEY=your-api-key
WEREWOLF_LLM_BASE_URL=https://your-provider.example/v1
WEREWOLF_LLM_MODEL=your-model
```

应用数据库结构：

```powershell
uv run alembic upgrade head
```

校验并发布默认角色技能基线：

```powershell
uv run python -m app.tools.seed_default_baseline --dry-run
uv run python -m app.tools.seed_default_baseline
```

启动后端：

```powershell
uv run uvicorn ui.backend.main:app --reload --host 127.0.0.1 --port 8000
```

启动前端：

```powershell
npm run dev --prefix ui/frontend
```

打开前端命令输出的 Vite 地址，通常是 `http://127.0.0.1:5173`。默认情况下，
前端会把 `/api` 代理到 `http://127.0.0.1:8000`。

## Fake LLM 演示模式

如果只是验证 UI 和工作流，不想调用真实模型，可以在启动后端前启用 fake LLM：

```powershell
$env:UI_BACKEND_USE_FAKE_LLM = "true"
uv run uvicorn ui.backend.main:app --reload --host 127.0.0.1 --port 8000
```

需要有意义的 Benchmark 或自进化结果时，应使用真实模型配置。

## 配置项

| 配置 | 说明 |
| --- | --- |
| `POSTGRES_DATABASE_URL` / `DATABASE_URL` | 必填。PostgreSQL 是运行时权威存储。 |
| `WEREWOLF_LLM_API_KEY` | 真实 LLM 运行必填。只放在服务端环境里。 |
| `WEREWOLF_LLM_BASE_URL` | OpenAI 兼容模型服务地址。 |
| `WEREWOLF_LLM_MODEL` | 默认智能体模型，可被设置页里的模型配置覆盖。 |
| `WEREWOLF_LLM_*` 重试配置 | 可选的超时、重试和熔断调优，详见 `.env.example`。 |
| `UI_BACKEND_USE_FAKE_LLM` | 本地/演示开关。真实评测不要启用。 |
| `SETTINGS_ADMIN_ENABLED` / `SETTINGS_ADMIN_TOKEN` | 设置页写入必需。 |
| `SETTINGS_SECRET_ENCRYPTION_KEY` | 保存模型 Profile API Key 必需，必须保持稳定；轮换后旧密钥需要重新录入。 |
| `WOLF_USE_PG_TASK_QUEUE` / `TASK_WORKER_REQUIRED` | 可选的 PostgreSQL 长任务队列和 worker 健康门禁控制。 |
| `WEREWOLF_GAME_CONCURRENCY` | 可选的多局并发上限，同时用于评测、自进化训练和自进化对战。 |
| `WEREWOLF_GAME_TIMEOUT` / `WEREWOLF_BATCH_GAME_TIMEOUT` | 可选的单局和批量任务超时。 |
| `PG_POOL_MIN_SIZE` / `PG_POOL_MAX_SIZE` | 可选 PostgreSQL 连接池大小。 |
| `WEREWOLF_TTS_*` | 可选 DashScope realtime TTS 配置，用于玩家发言朗读。 |
| `VITE_API_BASE` / `UI_FRONTEND_API_PROXY_TARGET` | 可选前端 API 基址和 Vite 开发代理目标。 |
| `WOLF_APP_RELEASE` / `WOLF_GIT_SHA` / `WOLF_APP_ENVIRONMENT` | 可选发布元数据，会显示在 health/ops payload。 |
| `LANGFUSE_*` | 可选自部署 Langfuse 链路追踪。开启且不降级时，需要 key、base URL、environment、release、sample rate 和 input/output capture 都配置好。 |

如果 PostgreSQL 只能通过远端机器访问，保持 SSH 隧道打开，并把
`POSTGRES_DATABASE_URL` 指向本地转发端口。

## 健康检查

后端提供：

```text
GET /api/health
```

启动诊断会检查 PostgreSQL 连接、Alembic 版本、角色基线、模型配置、
fake-model 模式和链路追踪可用性。`status=degraded` 对 fake LLM 演示通常仍可用；
`status=error` 表示缺少 PostgreSQL、迁移或其他必需依赖。

## 验证

后端和规则引擎测试：

```powershell
uv run pytest -q
```

前端测试：

```powershell
npm test --prefix ui/frontend
```

前端生产构建：

```powershell
npm run build --prefix ui/frontend
```

常用局部检查：

```powershell
uv run python -m app.tools.seed_default_baseline --dry-run
uv run pytest tests/test_api_contracts.py tests/test_ui_backend_app.py -q
```

## 运行时数据边界

PostgreSQL 保存对局、决策、UI 任务事件、Benchmark/自进化状态、排行榜、
角色注册表基线和产物元数据。本地生成的 `runs/`、`data/`、`screenshots/`、
`test-results/`、`playwright-report/` 等目录只是工作区产物，不应进入源码提交。

数据迁移应使用 PostgreSQL dump/restore 或明确的一次性导入脚本。不要通过提交本地
JSON、SQLite、pid、log、截图或生成报告来迁移运行数据。

完整策略见 [`docs/runtime-data-boundaries.md`](docs/runtime-data-boundaries.md)。

## 注意事项

- 密钥只放在 `.env`，不要放进前端 `VITE_*` 变量。
- 当 `LANGFUSE_TRACING_ENABLED=true` 时，不降级需要配置
  `LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`、`LANGFUSE_BASE_URL`、
  `LANGFUSE_ENVIRONMENT`、`LANGFUSE_RELEASE`、`LANGFUSE_SAMPLE_RATE>0` 和
  `LANGFUSE_CAPTURE_INPUT_OUTPUT=true`。只有在 prompt/response 已审查和脱敏后，
  才建议开启 input/output 捕获。
- `POSTGRES_DISABLE_DOTENV=1` 可用于验证测试没有隐式读取 `.env`。
- 自进化可以晋级候选技能版本。真实使用前建议先 dry-run/review，并检查 diff。
