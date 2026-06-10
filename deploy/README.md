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

WEREWOLF_LLM_API_KEY=...
WEREWOLF_LLM_BASE_URL=...
WEREWOLF_LLM_MODEL=...
```

Optional:

```dotenv
WEREWOLF_TTS_API_KEY=...
WEREWOLF_TTS_BASE_URL=...
UI_BACKEND_USE_FAKE_LLM=false
```

## Deployment Templates

Templates added:

- `deploy/systemd/521wolf.service.example`
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

The script:

- Optionally updates the working tree to `origin/main` when
  `SKIP_GIT_UPDATE` is not `true`.
- Loads `/opt/521wolf/.env` when it exists.
- Installs Python dependencies from `uv.lock`.
- Installs and builds frontend assets.
- Applies Alembic migrations.
- Seeds missing default baselines.
- Restarts the `521wolf` systemd service when systemd is available.
- Checks `http://127.0.0.1:8000/api/health`.
- Runs `deploy/scripts/post_deploy_smoke.sh` unless `POST_DEPLOY_SMOKE=false`.

The post-deploy smoke is intentionally black-box. It does not require new
backend response fields. It checks the API health URL, the nginx-served app
shell, referenced JS/CSS assets, nginx config, the systemd service, and the
HTTP listener. Useful overrides:

```text
APP_BASE_URL=http://127.0.0.1
API_HEALTH_URL=http://127.0.0.1/api/health
POST_DEPLOY_SMOKE=true
CHECK_NGINX=true
CHECK_SYSTEMD=true
CHECK_PORTS=true
REQUIRE_HTTPS=false
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
WEREWOLF_TTS_BASE_URL
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
DEPLOY_APP_BASE_URL=http://127.0.0.1
DEPLOY_API_HEALTH_URL=http://127.0.0.1/api/health
POST_DEPLOY_SMOKE=true
POST_DEPLOY_CHECK_NGINX=true
POST_DEPLOY_CHECK_SYSTEMD=true
POST_DEPLOY_CHECK_PORTS=true
POST_DEPLOY_REQUIRE_HTTPS=false
PYPI_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
NPM_CONFIG_REGISTRY=https://registry.npmmirror.com
UV_RELOCK_FOR_INDEX=true
WEREWOLF_LLM_TIMEOUT=60
WEREWOLF_GAME_TIMEOUT=900
LANGFUSE_TRACING_ENABLED=false
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

Keep CD restricted to `main` and the protected `production` environment.
