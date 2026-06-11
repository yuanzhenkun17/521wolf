<div align="center">
  <img src="logo.png" alt="NightCouncil logo" width="168" />
  <h1>NightCouncil</h1>
  <p>
    <strong>Your AI Werewolf agent workbench.</strong><br />
    Run games, inspect decisions, benchmark agents, and evolve role skills.
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

NightCouncil is a 12-player Werewolf system for building and evaluating LLM-driven
agents. It combines a deterministic rules engine, role-specific skill prompts,
PostgreSQL-backed persistence, a FastAPI backend, and a Vue workbench for live
play, replay, benchmark, review, and self-evolution workflows.

PostgreSQL is the only supported runtime source of truth. Local `runs/` and
`data/` artifacts are auxiliary outputs and should not be treated as durable
state.

## Start Here

| You want to... | Go to |
| --- | --- |
| Install the project and open the workbench | [Quick Start](#quick-start) |
| Run a local demo without real model calls | [Fake LLM demo mode](#fake-llm-demo-mode) |
| Configure a real model, database, TTS, or tracing | [Configuration](#configuration) |
| Understand what the system can do | [Feature Surface](#feature-surface) |
| Find the major code areas | [Architecture Map](#architecture-map) |
| Run tests and production build checks | [Verification](#verification) |
| Understand what data may be committed | [Runtime Data Boundaries](#runtime-data-boundaries) |

## Feature Surface

| Area | What it provides |
| --- | --- |
| Rules engine | Standard 12-player White Wolf King flow, including night actions, sheriff election, speeches, PK/exile votes, death handling, and win detection. |
| Roles | Villager, werewolf, white wolf king, seer, witch, hunter, and guard. |
| Agent runtime | Role skills, LLM calls, policy constraints, retries, timeouts, decision records, and player-view information isolation. |
| Workbench UI | Lobby, live match, history archive, benchmark lab, self-evolution, task queue, and settings pages. |
| Benchmarking | Batch runs, leaderboards, snapshots, diagnostics, reports, and saved views backed by PostgreSQL. |
| Self-evolution | Candidate skill generation, proposal review, dry-run/preflight checks, and promotion flows. |
| Observability | Health gates, startup diagnostics, optional self-hosted Langfuse tracing, and runtime notices. |

## Architecture Map

| Path | Purpose |
| --- | --- |
| `engine/` | Deterministic Werewolf rules, phases, actions, and player-facing requests. |
| `app/` | Agent orchestration, LLM services, role skill loading, observability helpers, and CLI tools. |
| `storage/` | PostgreSQL repositories for games, decisions, benchmarks, evolution, registry, tasks, and artifacts. |
| `ui/backend/` | FastAPI API layer that adapts the engine, storage, health checks, settings, and background tasks for the frontend. |
| `ui/frontend/` | Vue/Vite workbench application. |
| `skills/default_baseline/` | Default role skill baselines. |
| `migrations/` | Alembic schema migrations. |
| `docs/` | Design notes, audits, execution plans, and runtime policies. |

## Requirements

- Python 3.11+
- `uv`
- Node.js 20+ and npm
- PostgreSQL 16+ recommended

## Quick Start

Install Python dependencies:

```powershell
uv sync
```

Install frontend dependencies:

```powershell
npm install --prefix ui/frontend
```

Create a local environment file:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set at least:

```dotenv
POSTGRES_DATABASE_URL=postgresql://wolf_app:password@127.0.0.1:5432/wolf_app
DATABASE_URL=${POSTGRES_DATABASE_URL}

WEREWOLF_LLM_API_KEY=your-api-key
WEREWOLF_LLM_BASE_URL=https://your-provider.example/v1
WEREWOLF_LLM_MODEL=your-model
```

Apply the database schema:

```powershell
uv run alembic upgrade head
```

Validate and publish default role baselines:

```powershell
uv run python -m app.tools.seed_default_baseline --dry-run
uv run python -m app.tools.seed_default_baseline
```

Start the backend:

```powershell
uv run uvicorn ui.backend.main:app --reload --host 127.0.0.1 --port 8000
```

Start the frontend:

```powershell
npm run dev --prefix ui/frontend
```

Open the Vite URL printed by the frontend command, usually
`http://127.0.0.1:5173`. The frontend proxies `/api` to
`http://127.0.0.1:8000` by default.

For a containerized single-node setup, use Docker Compose:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

Compose starts PostgreSQL, runs Alembic migrations, seeds default role baselines,
starts the API, starts the task worker, and serves the built frontend at
`http://127.0.0.1:8080`.

## Fake LLM Demo Mode

For UI and workflow demos that should not call a real model, enable the fake LLM
runtime before starting the backend:

```powershell
$env:UI_BACKEND_USE_FAKE_LLM = "true"
uv run uvicorn ui.backend.main:app --reload --host 127.0.0.1 --port 8000
```

Use real model credentials for benchmark or evolution results that must be
meaningful.

## Configuration

| Setting | Notes |
| --- | --- |
| `POSTGRES_DATABASE_URL` / `DATABASE_URL` | Required. PostgreSQL is the authoritative runtime store. |
| `WEREWOLF_LLM_API_KEY` | Required for real LLM runs. Keep it server-side only. |
| `WEREWOLF_LLM_BASE_URL` | OpenAI-compatible model endpoint. |
| `WEREWOLF_LLM_MODEL` | Default model used by runtime agents unless overridden by settings. |
| `WEREWOLF_LLM_*` retry settings | Optional retry, timeout, and circuit-breaker tuning. See `.env.example`. |
| `UI_BACKEND_USE_FAKE_LLM` | Optional local/demo switch. Do not enable for real evaluation. |
| `SETTINGS_ADMIN_ENABLED` / `SETTINGS_ADMIN_TOKEN` | Required for Settings page writes. |
| `SETTINGS_SECRET_ENCRYPTION_KEY` | Required to store model Profile API keys. Keep stable; rotating it invalidates saved secrets. |
| `WOLF_USE_PG_TASK_QUEUE` / `TASK_WORKER_REQUIRED` | Optional durable task queue and worker health gate controls. |
| `WEREWOLF_GAME_CONCURRENCY` | Optional shared concurrency cap for benchmark, evolution training, and evolution battle games. |
| `WEREWOLF_GAME_TIMEOUT` / `WEREWOLF_BATCH_GAME_TIMEOUT` | Optional game and batch execution timeouts. |
| `PG_POOL_MIN_SIZE` / `PG_POOL_MAX_SIZE` | Optional PostgreSQL connection-pool sizing. |
| `WEREWOLF_TTS_*` | Optional DashScope realtime TTS settings for spoken player lines. |
| `VITE_API_BASE` / `UI_FRONTEND_API_PROXY_TARGET` | Optional frontend API base and Vite dev proxy target. |
| `WOLF_APP_RELEASE` / `WOLF_GIT_SHA` / `WOLF_APP_ENVIRONMENT` | Optional release metadata shown in health/ops payloads. |
| `LANGFUSE_*` | Optional self-hosted Langfuse tracing. For enabled, non-degraded tracing set public/secret keys, base URL, environment, release, sample rate, and input/output capture. |

If PostgreSQL is only reachable through a remote host, keep an SSH tunnel open
and point `POSTGRES_DATABASE_URL` at the local forwarded port.

## Health Check

The backend exposes:

```text
GET /api/health
```

Startup diagnostics cover PostgreSQL connectivity, Alembic head status, role
registry baselines, model configuration, fake-model mode, and tracing readiness.
`status=degraded` can still be usable for fake LLM demos; `status=error` means a
required dependency such as PostgreSQL or the schema migration is missing.
Missing-table errors such as `ui_task_queue` mean `alembic upgrade head` has not
completed against the active database.

## Verification

Backend and engine tests:

```powershell
uv run pytest -q
```

Frontend tests:

```powershell
npm test --prefix ui/frontend
```

Frontend production build:

```powershell
npm run build --prefix ui/frontend
```

Useful focused checks:

```powershell
uv run python -m app.tools.seed_default_baseline --dry-run
uv run pytest tests/test_api_contracts.py tests/test_ui_backend_app.py -q
```

## Runtime Data Boundaries

PostgreSQL owns games, decisions, UI task events, benchmark/evolution state,
leaderboards, role registry baselines, and artifact metadata. Local generated
files under folders such as `runs/`, `data/`, `screenshots/`, `test-results/`,
and `playwright-report/` are workspace artifacts and should stay out of source
control.

Use PostgreSQL dump/restore or explicit one-shot import scripts for data
migration. Do not migrate by committing local JSON, SQLite, pid, log, screenshot,
or generated report files.

See [`docs/runtime-data-boundaries.md`](docs/runtime-data-boundaries.md) for the
full policy.

## Notes

- Keep secrets in `.env`; do not put API keys in frontend `VITE_*` variables.
- When `LANGFUSE_TRACING_ENABLED=true`, non-degraded health requires
  `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`,
  `LANGFUSE_ENVIRONMENT`, `LANGFUSE_RELEASE`, `LANGFUSE_SAMPLE_RATE>0`, and
  `LANGFUSE_CAPTURE_INPUT_OUTPUT=true`. Only enable input/output capture after
  prompt/response data has been reviewed and redacted.
- `POSTGRES_DISABLE_DOTENV=1` is useful for tests that must prove connection
  information is not implicitly loaded from `.env`.
- Self-evolution can promote candidate skill versions. Use dry-run/review
  workflows and inspect diffs before relying on automatic promotion for real
  baselines.
