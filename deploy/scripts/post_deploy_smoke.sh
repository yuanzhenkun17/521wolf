#!/usr/bin/env bash
set -euo pipefail

APP_BASE_URL="${APP_BASE_URL:-http://127.0.0.1}"
API_HEALTH_URL="${API_HEALTH_URL:-http://127.0.0.1/api/health}"
SERVICE_NAME="${SERVICE_NAME:-521wolf}"
CHECK_NGINX="${CHECK_NGINX:-true}"
CHECK_SYSTEMD="${CHECK_SYSTEMD:-true}"
CHECK_PORTS="${CHECK_PORTS:-true}"
REQUIRE_HTTPS="${REQUIRE_HTTPS:-false}"
CURL_TIMEOUT_SECONDS="${CURL_TIMEOUT_SECONDS:-10}"
MAX_ASSET_CHECKS="${MAX_ASSET_CHECKS:-20}"

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

fail() {
  echo "post-deploy smoke failed: $*" >&2
  exit 1
}

info() {
  echo "post-deploy smoke: $*"
}

sudo_if_available() {
  if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    sudo -n "$@"
  else
    "$@"
  fi
}

fetch_to_file() {
  local url="$1"
  local output="$2"
  curl -fsS --max-time "$CURL_TIMEOUT_SECONDS" "$url" -o "$output" \
    || fail "curl failed for $url"
}

check_url() {
  local url="$1"
  curl -fsS --max-time "$CURL_TIMEOUT_SECONDS" "$url" -o /dev/null \
    || fail "curl failed for $url"
}

base_without_trailing_slash="${APP_BASE_URL%/}"

info "checking API health at $API_HEALTH_URL"
health_body="$tmp_dir/health.json"
fetch_to_file "$API_HEALTH_URL" "$health_body"
if ! grep -q "{" "$health_body"; then
  fail "API health did not return JSON-like content"
fi
if command -v python3 >/dev/null 2>&1; then
  python_bin="python3"
elif command -v python >/dev/null 2>&1; then
  python_bin="python"
else
  python_bin=""
fi
if [ -n "$python_bin" ]; then
  "$python_bin" - "$health_body" <<'PY' || fail "API health JSON reports status=error or is invalid"
import json
import sys

with open(sys.argv[1], "r", encoding="utf-8") as handle:
    payload = json.load(handle)
if payload.get("status") == "error":
    raise SystemExit(1)
PY
fi

info "checking app shell at $base_without_trailing_slash/"
html_body="$tmp_dir/index.html"
fetch_to_file "$base_without_trailing_slash/" "$html_body"
if ! grep -qi "<html" "$html_body"; then
  fail "app shell did not return HTML"
fi

asset_list="$tmp_dir/assets.txt"
grep -Eo '(src|href)="[^"]+"' "$html_body" \
  | sed -E 's/^(src|href)="([^"]+)"/\2/' \
  | grep -E '\.(js|css)(\?|$)' \
  | awk '!seen[$0]++' \
  | head -n "$MAX_ASSET_CHECKS" > "$asset_list" || true

if [ ! -s "$asset_list" ]; then
  fail "app shell did not reference any JS/CSS assets"
fi

while IFS= read -r asset_path; do
  case "$asset_path" in
    http://*|https://*)
      asset_url="$asset_path"
      ;;
    /*)
      asset_url="$base_without_trailing_slash$asset_path"
      ;;
    *)
      asset_url="$base_without_trailing_slash/$asset_path"
      ;;
  esac
  info "checking asset $asset_url"
  check_url "$asset_url"
done < "$asset_list"

if [ "$CHECK_NGINX" != "false" ] && command -v nginx >/dev/null 2>&1; then
  info "checking nginx configuration"
  sudo_if_available nginx -t >/dev/null
fi

if [ "$CHECK_SYSTEMD" != "false" ] && command -v systemctl >/dev/null 2>&1; then
  info "checking systemd service $SERVICE_NAME"
  sudo_if_available systemctl is-active --quiet "$SERVICE_NAME" \
    || fail "systemd service $SERVICE_NAME is not active"
fi

if [ "$CHECK_PORTS" != "false" ]; then
  if command -v ss >/dev/null 2>&1; then
    listeners="$(ss -ltn)"
  elif command -v netstat >/dev/null 2>&1; then
    listeners="$(netstat -ltn)"
  else
    listeners=""
  fi

  if [ -n "$listeners" ]; then
    echo "$listeners" | grep -Eq '(:|\.)80[[:space:]]' \
      || fail "port 80 is not listening"
    if [ "$REQUIRE_HTTPS" = "true" ]; then
      echo "$listeners" | grep -Eq '(:|\.)443[[:space:]]' \
        || fail "port 443 is not listening"
    fi
  fi
fi

info "passed"
