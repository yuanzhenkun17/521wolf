#!/usr/bin/env bash
set -euo pipefail

SERVER_NAME="${SERVER_NAME:-117.72.217.45}"
APP_ROOT="${APP_ROOT:-/opt/521wolf/app/ui/frontend/dist}"
API_UPSTREAM="${API_UPSTREAM:-http://127.0.0.1:8000}"
APP_DIR="${APP_DIR:-/opt/521wolf/app}"
CERT_DIR="${CERT_DIR:-/etc/nginx/ssl/521wolf}"
CERT_DAYS="${CERT_DAYS:-3650}"
NGINX_TEMPLATE="${NGINX_TEMPLATE:-$APP_DIR/deploy/nginx/521wolf.ssl.conf.example}"
NGINX_SITE_NAME="${NGINX_SITE_NAME:-521wolf}"
INSTALL_NGINX_CONFIG="${INSTALL_NGINX_CONFIG:-true}"
RELOAD_NGINX="${RELOAD_NGINX:-true}"

CERT_PATH="${CERT_PATH:-$CERT_DIR/$NGINX_SITE_NAME.crt}"
KEY_PATH="${KEY_PATH:-$CERT_DIR/$NGINX_SITE_NAME.key}"

sudo_if_available() {
  if command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    sudo -n "$@"
  else
    "$@"
  fi
}

escape_sed_replacement() {
  printf '%s' "$1" | sed -e 's/[\/&]/\\&/g'
}

if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required" >&2
  exit 1
fi

if [ "$INSTALL_NGINX_CONFIG" = "true" ] && [ ! -f "$NGINX_TEMPLATE" ]; then
  echo "nginx template not found: $NGINX_TEMPLATE" >&2
  exit 1
fi

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

openssl_conf="$tmp_dir/openssl.cnf"
{
  cat <<EOF
[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_req
prompt = no

[req_distinguished_name]
CN = $SERVER_NAME

[v3_req]
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[alt_names]
EOF
  if printf '%s' "$SERVER_NAME" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}$'; then
    echo "IP.1 = $SERVER_NAME"
  else
    echo "DNS.1 = $SERVER_NAME"
  fi
  echo "IP.2 = 127.0.0.1"
  echo "DNS.2 = localhost"
} > "$openssl_conf"

sudo_if_available mkdir -p "$CERT_DIR"
sudo_if_available openssl req \
  -x509 \
  -nodes \
  -newkey rsa:2048 \
  -sha256 \
  -days "$CERT_DAYS" \
  -keyout "$KEY_PATH" \
  -out "$CERT_PATH" \
  -config "$openssl_conf"
sudo_if_available chmod 600 "$KEY_PATH"
sudo_if_available chmod 644 "$CERT_PATH"

if [ "$INSTALL_NGINX_CONFIG" = "true" ]; then
  rendered="$tmp_dir/$NGINX_SITE_NAME.conf"
  sed \
    -e "s/__SERVER_NAME__/$(escape_sed_replacement "$SERVER_NAME")/g" \
    -e "s/__CERT_PATH__/$(escape_sed_replacement "$CERT_PATH")/g" \
    -e "s/__KEY_PATH__/$(escape_sed_replacement "$KEY_PATH")/g" \
    -e "s/__APP_ROOT__/$(escape_sed_replacement "$APP_ROOT")/g" \
    -e "s/__API_UPSTREAM__/$(escape_sed_replacement "${API_UPSTREAM%/}")/g" \
    "$NGINX_TEMPLATE" > "$rendered"

  if [ -d /etc/nginx/sites-available ]; then
    site_available="/etc/nginx/sites-available/$NGINX_SITE_NAME"
    site_enabled="/etc/nginx/sites-enabled/$NGINX_SITE_NAME"
    sudo_if_available cp "$rendered" "$site_available"
    sudo_if_available ln -sfn "$site_available" "$site_enabled"
  else
    sudo_if_available mkdir -p /etc/nginx/conf.d
    sudo_if_available cp "$rendered" "/etc/nginx/conf.d/$NGINX_SITE_NAME.conf"
  fi
fi

if command -v nginx >/dev/null 2>&1; then
  sudo_if_available nginx -t
  if [ "$RELOAD_NGINX" = "true" ]; then
    if command -v systemctl >/dev/null 2>&1; then
      sudo_if_available systemctl reload nginx
    else
      sudo_if_available nginx -s reload
    fi
  fi
fi

echo "self-signed SSL installed"
echo "certificate: $CERT_PATH"
echo "private key: $KEY_PATH"
echo "url: https://$SERVER_NAME"
