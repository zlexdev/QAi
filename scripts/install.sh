#!/usr/bin/env bash
# Installs QAi's remote FastAPI service on a fresh (or existing) Ubuntu/Debian host:
# system deps -> uv sync -> playwright browser -> systemd unit -> nginx + certbot TLS.
# Idempotent — safe to re-run; --dry-run prints every action without executing it.
set -euo pipefail

DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 1 ;;
  esac
done

RED=$'\033[0;31m'; GREEN=$'\033[0;32m'; YELLOW=$'\033[1;33m'; BLUE=$'\033[0;34m'; NC=$'\033[0m'
log_phase() { printf '\n%s==>%s %s\n' "$BLUE" "$NC" "$1"; }
log_ok()    { printf '%s  ok:%s %s\n' "$GREEN" "$NC" "$1"; }
log_warn()  { printf '%s  warn:%s %s\n' "$YELLOW" "$NC" "$1"; }
log_err()   { printf '%s  error:%s %s\n' "$RED" "$NC" "$1" >&2; }

run() {
  if [ "$DRY_RUN" = "1" ]; then
    printf '  [dry-run] %s\n' "$*"
  else
    "$@"
  fi
}

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONF_FILE="${HOME}/.qai.conf"
SERVICE_USER="${SUDO_USER:-$(whoami)}"

log_phase "Phase 1/7 — system packages"
if command -v apt-get >/dev/null 2>&1; then
  run sudo apt-get update -y
  run sudo apt-get install -y curl nginx certbot python3-certbot-nginx
else
  log_warn "non-apt system detected — install curl/nginx/certbot manually, then re-run"
fi
if ! command -v uv >/dev/null 2>&1; then
  run bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
else
  log_ok "uv already installed"
fi

log_phase "Phase 2/7 — python deps + browser"
run uv sync --project "$APP_DIR" --extra api --extra mcp
run uv run --project "$APP_DIR" playwright install --with-deps chromium

log_phase "Phase 3/7 — configuration (domain, port, API key)"
# shellcheck disable=SC1090
[ -f "$CONF_FILE" ] && source "$CONF_FILE"
if [ -z "${QAI_DOMAIN:-}" ]; then
  read -rp "Domain to bind (e.g. qai.example.com): " QAI_DOMAIN
fi
if [ -z "${QAI_PORT:-}" ]; then
  QAI_PORT=8000
fi
if [ -z "${QAI_API_KEY:-}" ]; then
  QAI_API_KEY="$(run bash -c "openssl rand -hex 32" || echo "changeme-$(date +%s)")"
  log_warn "generated a new QAI_API_KEY — save it, it will not be printed again after this run"
fi
{
  echo "QAI_DOMAIN=${QAI_DOMAIN}"
  echo "QAI_PORT=${QAI_PORT}"
  echo "QAI_API_KEY=${QAI_API_KEY}"
} > "$CONF_FILE"
log_ok "config cached at $CONF_FILE"

ENV_FILE="$APP_DIR/.env"
{
  echo "QAI_API_KEY=${QAI_API_KEY}"
  echo "QAI_HOST=127.0.0.1"
  echo "QAI_PORT=${QAI_PORT}"
} > "$ENV_FILE"
run chmod 600 "$ENV_FILE"

log_phase "Phase 4/7 — DNS check"
RESOLVED_IP="$(getent hosts "$QAI_DOMAIN" | awk '{print $1}' || true)"
if [ -z "$RESOLVED_IP" ]; then
  log_err "DNS for $QAI_DOMAIN does not resolve yet — point an A/AAAA record at this host, then re-run"
  exit 1
fi
log_ok "$QAI_DOMAIN resolves to $RESOLVED_IP"

log_phase "Phase 5/7 — systemd unit"
UV_BIN="$(command -v uv)"
UNIT_PATH="/etc/systemd/system/qai-api.service"
sed \
  -e "s#{{SERVICE_USER}}#${SERVICE_USER}#g" \
  -e "s#{{APP_DIR}}#${APP_DIR}#g" \
  -e "s#{{UV_BIN}}#${UV_BIN}#g" \
  "$APP_DIR/scripts/qai-api.service.template" > /tmp/qai-api.service
run sudo cp /tmp/qai-api.service "$UNIT_PATH"
run sudo systemctl daemon-reload
run sudo systemctl enable qai-api

log_phase "Phase 6/7 — nginx site + certbot TLS"
SITE_PATH="/etc/nginx/sites-available/qai-api.conf"
sed \
  -e "s#{{DOMAIN}}#${QAI_DOMAIN}#g" \
  -e "s#{{PORT}}#${QAI_PORT}#g" \
  "$APP_DIR/scripts/nginx-qai.conf.template" > /tmp/qai-api.conf
run sudo cp /tmp/qai-api.conf "$SITE_PATH"
run sudo ln -sf "$SITE_PATH" "/etc/nginx/sites-enabled/qai-api.conf"
run sudo nginx -t
run sudo systemctl reload nginx
run sudo certbot --nginx -d "$QAI_DOMAIN" --non-interactive --agree-tos -m "admin@${QAI_DOMAIN}" --redirect

log_phase "Phase 7/7 — start service + healthcheck"
run sudo systemctl restart qai-api
if [ "$DRY_RUN" = "1" ]; then
  log_ok "dry-run complete — no changes were made"
  exit 0
fi
sleep 2
if curl -fsS "https://${QAI_DOMAIN}/healthz" >/dev/null; then
  log_ok "https://${QAI_DOMAIN}/healthz is live"
else
  log_err "healthcheck failed — check: sudo systemctl status qai-api"
  exit 1
fi
