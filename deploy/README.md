# GitHub Actions CI/CD

The repository is set up for layered GitHub Actions checks and SSH-based
deployment to a Linux server.

## Workflow Layers

### PR / Main CI

Workflow: `.github/workflows/ci.yml`

Triggers:

- Pull requests.
- Pushes to `main`.
- Manual `workflow_dispatch`.

Checks:

- PostgreSQL 16 service.
- Fake LLM environment.
- `uv sync --frozen --dev`.
- `uv run alembic upgrade head`.
- `uv run python -m app.tools.seed_default_baseline --dry-run`.
- `uv run pytest -q`.
- `npm ci --prefix ui/frontend`.
- `npm test --prefix ui/frontend`.
- `npm run build --prefix ui/frontend`.

### Nightly

Workflow: `.github/workflows/nightly.yml`

Triggers:

- Every night at 02:30 Asia/Shanghai.
- Manual `workflow_dispatch`.

Checks:

- Empty PostgreSQL migration.
- Default baseline seed.
- PostgreSQL integration tests.
- Fake LLM API evolution smoke.
- `/api/health` smoke.
- Frontend-to-backend browser smoke with Playwright Chromium.

### Release Gate

Workflow: `.github/workflows/release-gate.yml`

Trigger:

- Manual `workflow_dispatch`.

Checks:

- Real LLM and PostgreSQL preflight.
- Two real LLM full-game smoke runs.
- Optional real LLM evolution smoke.

Run this before production deployment when LLM behavior or long workflow
stability matters.

### Deploy

Workflow: `.github/workflows/deploy.yml`

Triggers:

- Automatically after `CI` succeeds on `main`.
- Manual `workflow_dispatch`.

Deployment:

- Checks out the repository in GitHub Actions.
- Uploads the checked-out source to the production server with `rsync`.
- Runs `deploy/scripts/deploy.sh` on the uploaded source.
- Fails if `/api/health` does not become reachable.

## Server Requirements For CD

Prepare a Linux server with:

- Python 3.11+
- `uv`
- Node.js 20+
- npm
- nginx
- PostgreSQL client tools
- Access to the production PostgreSQL database

Recommended layout:

```text
/opt/521wolf/app
/opt/521wolf/.env
/opt/521wolf/logs
```

The production `.env` should stay on the server or in GitHub Secrets. Do not
commit it.

Minimum production environment variables:

```dotenv
POSTGRES_DATABASE_URL=postgresql://wolf_app:password@127.0.0.1:5432/wolf_app
DATABASE_URL=${POSTGRES_DATABASE_URL}
WOLF_USE_PG_TASK_QUEUE=true

WEREWOLF_LLM_API_KEY=...
WEREWOLF_LLM_BASE_URL=...
WEREWOLF_LLM_MODEL=...
```

Optional:

```dotenv
WEREWOLF_TTS_API_KEY=...
WEREWOLF_TTS_WS_URL=wss://dashscope.aliyuncs.com/api-ws/v1/realtime
UI_BACKEND_USE_FAKE_LLM=false
PG_POOL_MIN_SIZE=1
PG_POOL_MAX_SIZE=10
```

## Deployment Templates

Templates added:

- `deploy/systemd/521wolf.service.example`
- `deploy/systemd/521wolf-worker.service.example`
- `deploy/nginx/521wolf.conf.example`
- `deploy/scripts/deploy.sh`

These are not active until copied/installed on the server.

## Manual Server Deployment

After uploading or copying source code to `/opt/521wolf/app`:

```bash
APP_DIR=/opt/521wolf/app \
SKIP_GIT_UPDATE=true \
bash /opt/521wolf/app/deploy/scripts/deploy.sh
```

## Self-Signed HTTPS

For an IP-only server or an internal deployment without a public domain, install
a self-signed nginx certificate:

```bash
SERVER_NAME=117.72.217.45 \
APP_DIR=/opt/521wolf/app \
bash /opt/521wolf/app/deploy/scripts/install_self_signed_ssl.sh
```

This generates:

```text
/etc/nginx/ssl/521wolf/521wolf.crt
/etc/nginx/ssl/521wolf/521wolf.key
```

and installs an nginx site that serves both HTTP and HTTPS and proxies `/api/`
to `http://127.0.0.1:8000`. Browsers will show a certificate warning because the
certificate is self-signed. For production public access, replace this with a
CA-issued certificate such as Let's Encrypt.

When using self-signed HTTPS in deployment smoke checks, set:

```text
APP_BASE_URL=https://117.72.217.45
REQUIRE_HTTPS=true
CURL_INSECURE=true
```

The script:

- Optionally updates the working tree to `origin/main` when
  `SKIP_GIT_UPDATE` is not `true`.
- Loads `/opt/521wolf/.env` when it exists.
- Installs Python dependencies from `uv.lock`.
- Installs and builds frontend assets.
- Applies Alembic migrations.
- Seeds missing default baselines.
- Restarts the `521wolf` systemd service when systemd is available.
- Restarts `521wolf-worker` when that systemd unit is installed. Set
  `RESTART_WORKER_SERVICE=false` to skip this on hosts that intentionally do
  not run the PostgreSQL task worker.
- Checks `http://127.0.0.1:8000/api/health`.
- Runs `deploy/scripts/post_deploy_smoke.sh` unless `POST_DEPLOY_SMOKE=false`.

The post-deploy smoke is intentionally black-box. It checks the API health URL,
task control health, `/api/tasks`, artifact hash verification, the nginx-served
app shell, referenced JS/CSS assets, nginx config, the API/worker systemd
services, and the HTTP listener. Useful overrides:

```text
APP_BASE_URL=http://117.72.217.45
API_HEALTH_URL=http://127.0.0.1:8000/api/health
APP_DIR=/opt/521wolf/app
POST_DEPLOY_SMOKE=true
CHECK_NGINX=true
CHECK_SYSTEMD=true
CHECK_TASK_QUEUE=true
CHECK_TASK_WORKER=true
CHECK_TASK_ARTIFACTS=true
TASK_ARTIFACT_VERIFY_LIMIT=100
CHECK_PORTS=true
REQUIRE_HTTPS=false
CURL_INSECURE=false
```

Install the worker service on single-node deployments that enable the
PostgreSQL task queue:

```bash
sudo cp /opt/521wolf/app/deploy/systemd/521wolf-worker.service.example /etc/systemd/system/521wolf-worker.service
sudo systemctl daemon-reload
sudo systemctl enable --now 521wolf-worker
```

Langfuse can be checked without touching backend code:

```bash
ENV_FILE=/opt/521wolf/.env \
EXPECT_LANGFUSE_ENABLED=true \
bash /opt/521wolf/app/deploy/scripts/check_langfuse_env.sh
```

This check prints only boolean/configuration status, never secret values. It
fails when tracing is expected but disabled or missing required keys. It warns
when `LANGFUSE_CAPTURE_INPUT_OUTPUT=false`, because traces can still be created
while Langfuse shows `Input null` and `Output undefined`.

For backend health to report Langfuse as non-degraded when tracing is enabled,
configure all of these in the backend service environment and restart it:

```dotenv
LANGFUSE_TRACING_ENABLED=true
LANGFUSE_PUBLIC_KEY=...
LANGFUSE_SECRET_KEY=...
LANGFUSE_BASE_URL=http://your-langfuse-host:3000
LANGFUSE_ENVIRONMENT=production
LANGFUSE_RELEASE=<release-name-or-git-sha>
LANGFUSE_SAMPLE_RATE=1.0
LANGFUSE_CAPTURE_INPUT_OUTPUT=true
```

## GitHub Secrets And Variables

Required GitHub Secrets:

```text
DEPLOY_HOST
DEPLOY_USER
DEPLOY_SSH_KEY
```

Required GitHub Secrets for `Release Gate`:

```text
WEREWOLF_LLM_API_KEY
WEREWOLF_LLM_BASE_URL
WEREWOLF_LLM_MODEL
```

Optional GitHub Secrets:

```text
WEREWOLF_TTS_API_KEY
WEREWOLF_TTS_WS_URL
LANGFUSE_PUBLIC_KEY
LANGFUSE_SECRET_KEY
LANGFUSE_BASE_URL
```

Optional GitHub Variables:

```text
DEPLOY_PORT=22
DEPLOY_PATH=/opt/521wolf/app
DEPLOY_ENV_FILE=/opt/521wolf/.env
DEPLOY_SERVICE_NAME=521wolf
DEPLOY_HEALTH_URL=http://127.0.0.1:8000/api/health
DEPLOY_HEALTH_TIMEOUT_SECONDS=60
DEPLOY_APP_BASE_URL=http://117.72.217.45
DEPLOY_API_HEALTH_URL=http://127.0.0.1:8000/api/health
POST_DEPLOY_SMOKE=true
POST_DEPLOY_CHECK_NGINX=true
POST_DEPLOY_CHECK_SYSTEMD=true
POST_DEPLOY_CHECK_PORTS=true
POST_DEPLOY_REQUIRE_HTTPS=false
POST_DEPLOY_CURL_INSECURE=false
DEPLOY_ENABLE_SELF_SIGNED_SSL=false
DEPLOY_SERVER_NAME=117.72.217.45
DEPLOY_HTTPS_BASE_URL=https://117.72.217.45
PYPI_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
UV_RELOCK_FOR_INDEX=true
WEREWOLF_LLM_TIMEOUT=60
WEREWOLF_GAME_TIMEOUT=900
WEREWOLF_BATCH_GAME_TIMEOUT=900
WEREWOLF_GAME_CONCURRENCY=0
TASK_WORKER_REQUIRED=false
WOLF_USE_PG_TASK_QUEUE=true
LANGFUSE_TRACING_ENABLED=false
LANGFUSE_ENVIRONMENT=production
LANGFUSE_RELEASE=<release-name>
LANGFUSE_SAMPLE_RATE=1.0
EXPECT_LANGFUSE_ENABLED=false
REQUIRE_LANGFUSE_CAPTURE_INPUT_OUTPUT=false
```

On China-based servers, keep `UV_RELOCK_FOR_INDEX=true`. `uv.lock` records
resolved package URLs, so `uv sync --frozen` can still download from
`files.pythonhosted.org` unless the lock is temporarily rewritten for the
selected mirror. The deploy script restores `uv.lock` after dependency sync.

Keep production database and server runtime secrets in `/opt/521wolf/.env`.
Keep GitHub-side deployment and real LLM smoke secrets in the protected
`production` environment. Do not commit them.

Model Profile writes require both settings admin auth and a stable encryption
key in `/opt/521wolf/.env`:

```text
SETTINGS_ADMIN_ENABLED=true
SETTINGS_ADMIN_TOKEN=<strong-random-token>
SETTINGS_SECRET_ENCRYPTION_KEY=<openssl rand -hex 32>
```

Do not rotate `SETTINGS_SECRET_ENCRYPTION_KEY` casually. Existing saved model
profile secrets are encrypted with it and must be re-entered if the key changes.

## Docker Compose Deployment

The repository also includes a Docker Compose stack for single-node deployment:

- `postgres`: PostgreSQL 16 runtime database.
- `migrate`: one-shot Alembic migration and default role baseline seed.
- `api`: FastAPI backend on port `8000`.
- `worker`: PostgreSQL task queue worker for Benchmark/Evolution background jobs.
- `frontend`: nginx-served Vue build on `APP_PORT`, default `8080`.

Prepare environment values first:

```bash
cp .env.example .env
```

Edit `.env` and set at least the model credentials, settings admin token,
settings encryption key, and any Langfuse/TTS values you need. Compose overrides
`POSTGRES_DATABASE_URL` and `DATABASE_URL` so the app talks to the `postgres`
container, even if `.env` points at a host database for non-Docker runs.

Start the stack:

```bash
docker compose up -d --build
```

Check status:

```bash
docker compose ps
docker compose logs -f migrate api worker
```

Open:

```text
http://127.0.0.1:8080
```

If you see an error such as `relation "ui_task_queue" does not exist`, the
database schema has not been migrated. In the Compose stack, inspect the
`migrate` service logs and rerun:

```bash
docker compose run --rm migrate
```

The SQL table definitions live in Alembic migrations under
`migrations/versions/`; they are not maintained as separate hand-written `.sql`
bootstrap files. Current UI/task/settings tables include:

- `wolf.ui_task_queue`, `wolf.ui_task_artifacts`, `wolf.ui_task_events`,
  `wolf.ui_task_workers`
- `wolf.ui_model_profiles`, `wolf.ui_runtime_settings`,
  `wolf.ui_settings_audit_log`
- the baseline game, benchmark, registry, and evolution tables created by
  `20260608_0001_postgresql_baseline.py`

Keep CD restricted to `main` and the protected `production` environment.
