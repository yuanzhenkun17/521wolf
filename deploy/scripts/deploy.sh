#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-/opt/521wolf/app}"
BRANCH="${BRANCH:-main}"
ENV_FILE="${ENV_FILE:-/opt/521wolf/.env}"
SERVICE_NAME="${SERVICE_NAME:-521wolf}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/api/health}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-60}"
PYPI_INDEX_URL="${PYPI_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple}"
NPM_CONFIG_REGISTRY="${NPM_CONFIG_REGISTRY:-https://registry.npmmirror.com}"
UV_RELOCK_FOR_INDEX="${UV_RELOCK_FOR_INDEX:-true}"
SKIP_GIT_UPDATE="${SKIP_GIT_UPDATE:-false}"

cd "$APP_DIR"

if [ "$SKIP_GIT_UPDATE" != "true" ]; then
  git fetch origin "$BRANCH"
  git checkout "$BRANCH"
  git pull --ff-only origin "$BRANCH"
fi

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

PYPI_INDEX_URL="${PYPI_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple}"
NPM_CONFIG_REGISTRY="${NPM_CONFIG_REGISTRY:-https://registry.npmmirror.com}"
UV_RELOCK_FOR_INDEX="${UV_RELOCK_FOR_INDEX:-true}"

export UV_DEFAULT_INDEX="${UV_DEFAULT_INDEX:-$PYPI_INDEX_URL}"
export NPM_CONFIG_REGISTRY

lock_backup=""
restore_lock() {
  if [ -n "$lock_backup" ] && [ -f "$lock_backup" ]; then
    mv "$lock_backup" uv.lock
    lock_backup=""
  fi
}
trap restore_lock EXIT

if [ "$UV_RELOCK_FOR_INDEX" != "false" ] && [ -f uv.lock ]; then
  lock_backup="$(mktemp)"
  cp uv.lock "$lock_backup"
  uv lock --default-index "$UV_DEFAULT_INDEX"
fi

uv sync --frozen --dev
restore_lock
npm ci --prefix ui/frontend
npm run build --prefix ui/frontend

uv run alembic upgrade head
uv run python -m app.tools.seed_default_baseline

if command -v systemctl >/dev/null 2>&1; then
  sudo systemctl restart "$SERVICE_NAME"
fi

for _ in $(seq 1 "$HEALTH_TIMEOUT_SECONDS"); do
  if curl -fsS "$HEALTH_URL" >/dev/null; then
    echo "Deploy completed: $HEALTH_URL"
    exit 0
  fi
  sleep 1
done

curl -fsS "$HEALTH_URL" >/dev/null
echo "Deploy completed: $HEALTH_URL"
