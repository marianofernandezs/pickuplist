#!/usr/bin/env sh
set -e

HOST="${APP_HOST:-0.0.0.0}"
PORT_TO_USE="${PORT:-${APP_PORT:-8000}}"

exec uvicorn app.main:app \
  --host "$HOST" \
  --port "$PORT_TO_USE" \
  --proxy-headers \
  --forwarded-allow-ips="*"
