# 521wolf

521wolf is a 12-player Werewolf MVP with a hardcoded rules engine, LLM-driven
agents, PostgreSQL persistence, a FastAPI backend, and a Vue workbench for live
play, replay, benchmark, review, and role-skill evolution.

The current runtime is PostgreSQL-only. SQLite/local JSON files are not a
supported source of truth; local `runs/` artifacts are only auxiliary outputs.

## What Is Included

- Standard 12-player White Wolf King rule set.
- Roles: villager, werewolf, white wolf king, seer, witch, hunter, guard.
- Full game flow: night actions, sheriff election, day speeches, exile/PK votes,
  death handling, win detection, and replayable event logs.
- Player-view information isolation for backend snapshots, archives, and SSE
  event streams.
- LLM agent pipeline with role skills, policy enforcement, retry/timeout
  handling, and decision records.
- Benchmark, review, leaderboard, and evolution workflows backed by PostgreSQL.
- Vue frontend with lobby, match, history, benchmark, and evolution pages.

## Requirements

- Python 3.11+
- `uv`
- Node.js and npm
- PostgreSQL

## Setup

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

Set at least these values in `.env`:

```dotenv
POSTGRES_DATABASE_URL=postgresql://wolf_app:password@127.0.0.1:5432/wolf_app
DATABASE_URL=${POSTGRES_DATABASE_URL}

WEREWOLF_LLM_API_KEY=your-api-key
WEREWOLF_LLM_BASE_URL=https://your-provider.example/v1
WEREWOLF_LLM_MODEL=your-model
```

For UI/demo flows that should avoid real model calls, set:

```dotenv
UI_BACKEND_USE_FAKE_LLM=true
```

Optional Langfuse tracing is intended for a self-hosted Langfuse server. Set
`LANGFUSE_BASE_URL` to your own deployment URL; do not rely on a Langfuse Cloud
default URL.

```dotenv
LANGFUSE_TRACING_ENABLED=false
LANGFUSE_PUBLIC_KEY=your-public-key
LANGFUSE_SECRET_KEY=your-secret-key
LANGFUSE_BASE_URL=http://127.0.0.1:3000

# Optional trace metadata and capture controls.
LANGFUSE_ENVIRONMENT=local
LANGFUSE_RELEASE=
LANGFUSE_SAMPLE_RATE=1.0
LANGFUSE_CAPTURE_INPUT_OUTPUT=false
```

If PostgreSQL is only reachable through a remote host, keep the tunnel open and
point `POSTGRES_DATABASE_URL` at the local forwarded port.

## Database

Apply the schema:

```powershell
uv run alembic upgrade head
```

Validate the default role baselines without writing:

```powershell
uv run python -m app.tools.seed_default_baseline --dry-run
```

Publish missing baselines:

```powershell
uv run python -m app.tools.seed_default_baseline
```

If an existing baseline intentionally needs to be replaced by
`skills/default_baseline`, rerun with `--force` after reviewing the diff:

```powershell
uv run python -m app.tools.seed_default_baseline --force
```

## Runtime Data Boundaries

PostgreSQL is the authoritative runtime store for games, decisions, UI task
events, benchmark/evolution state, leaderboards, and role registry baselines.
The local `runs/` and `data/` directories are ignored workspace artifacts, not
supported sources of truth.

Use PostgreSQL dump/restore or explicit one-shot import scripts for data
migration. Do not migrate by committing local JSON, SQLite, pid, log, screenshot,
or generated report files. The detailed boundary and migration policy is in
[`docs/runtime-data-boundaries.md`](docs/runtime-data-boundaries.md).

## Run Locally

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
`http://127.0.0.1:8000` by default. To use a different backend URL:

```powershell
$env:UI_FRONTEND_API_PROXY_TARGET = "http://127.0.0.1:8001"
npm run dev --prefix ui/frontend
```

## Health Check

The backend exposes:

```text
GET /api/health
```

Startup diagnostics cover PostgreSQL connectivity, Alembic head status, registry
baselines, and LLM configuration. `status=degraded` can still be usable for fake
LLM demos; `status=error` means a required dependency such as PostgreSQL or the
schema migration is missing.

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

Useful focused smoke checks:

```powershell
uv run python -m app.tools.seed_default_baseline --dry-run
```

```powershell
uv run pytest tests/test_api_contracts.py tests/test_ui_backend_app.py -q
```

## Notes

- Keep secrets in `.env`; do not put them in frontend `VITE_*` variables.
- Keep runtime artifacts, screenshots, pid files, and local logs out of source
  control. Use ignored folders such as `runs/`, `screenshots/`, `test-results/`,
  and `playwright-report/` for local diagnostics.
- `POSTGRES_DISABLE_DOTENV=1` is useful for tests that must prove connection
  information is not implicitly loaded from `.env`.
- Evolution can auto-promote candidate skill versions. Use dry-run/review
  workflows and inspect diffs before relying on automatic promotion for real
  baselines.
