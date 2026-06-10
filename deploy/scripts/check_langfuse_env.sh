#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/521wolf/.env}"
CHECK_LANGFUSE_HTTP="${CHECK_LANGFUSE_HTTP:-true}"
EXPECT_LANGFUSE_ENABLED="${EXPECT_LANGFUSE_ENABLED:-false}"
REQUIRE_LANGFUSE_CAPTURE_INPUT_OUTPUT="${REQUIRE_LANGFUSE_CAPTURE_INPUT_OUTPUT:-false}"
CURL_TIMEOUT_SECONDS="${CURL_TIMEOUT_SECONDS:-10}"

warnings=0

fail() {
  echo "langfuse check failed: $*" >&2
  exit 1
}

warn() {
  warnings=$((warnings + 1))
  echo "langfuse check warning: $*" >&2
}

info() {
  echo "langfuse check: $*"
}

is_true() {
  case "${1:-}" in
    true|True|TRUE|1|yes|YES|on|ON)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

load_env_file() {
  if [ -f "$ENV_FILE" ]; then
    info "loading $ENV_FILE"
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
  else
    warn "env file not found: $ENV_FILE"
  fi
}

require_present() {
  local name="$1"
  local value
  value="$(printenv "$name" 2>/dev/null || true)"
  if [ -z "$value" ]; then
    fail "$name is required when LANGFUSE_TRACING_ENABLED=true"
  fi
  info "$name is set"
}

load_env_file

if ! is_true "${LANGFUSE_TRACING_ENABLED:-false}"; then
  if is_true "$EXPECT_LANGFUSE_ENABLED"; then
    fail "LANGFUSE_TRACING_ENABLED is not true"
  fi
  info "tracing disabled; no Langfuse writes are expected"
  exit 0
fi

info "tracing enabled"
require_present LANGFUSE_PUBLIC_KEY
require_present LANGFUSE_SECRET_KEY
require_present LANGFUSE_BASE_URL

base_url="${LANGFUSE_BASE_URL%/}"

if is_true "${CHECK_LANGFUSE_HTTP:-true}"; then
  info "checking Langfuse base URL $base_url"
  curl -fsSL --max-time "$CURL_TIMEOUT_SECONDS" "$base_url" -o /dev/null \
    || fail "cannot reach LANGFUSE_BASE_URL=$base_url"
fi

if is_true "${LANGFUSE_CAPTURE_INPUT_OUTPUT:-false}"; then
  info "raw input/output capture enabled"
else
  message="LANGFUSE_CAPTURE_INPUT_OUTPUT is false; Langfuse traces can exist while Input is null and Output is undefined"
  if is_true "$REQUIRE_LANGFUSE_CAPTURE_INPUT_OUTPUT"; then
    fail "$message"
  fi
  warn "$message"
fi

case "${LANGFUSE_SAMPLE_RATE:-}" in
  "" )
    warn "LANGFUSE_SAMPLE_RATE is empty; SDK default will apply"
    ;;
  0|0.0|0.00 )
    warn "LANGFUSE_SAMPLE_RATE is 0; traces may be sampled out"
    ;;
  * )
    info "LANGFUSE_SAMPLE_RATE=${LANGFUSE_SAMPLE_RATE}"
    ;;
esac

if [ -z "${LANGFUSE_ENVIRONMENT:-}" ]; then
  warn "LANGFUSE_ENVIRONMENT is empty"
else
  info "LANGFUSE_ENVIRONMENT=${LANGFUSE_ENVIRONMENT}"
fi

if [ -z "${LANGFUSE_RELEASE:-}" ]; then
  warn "LANGFUSE_RELEASE is empty; traces will be harder to tie to a deploy"
else
  info "LANGFUSE_RELEASE is set"
fi

info "passed with $warnings warning(s)"
