#!/bin/sh
set -eu

BASE_URL=${1:-http://127.0.0.1:${APP_PORT:-8000}}
status=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "$BASE_URL/healthz")
[ "$status" = 200 ] || { echo "/healthz returned $status (expected 200)" >&2; exit 1; }
curl --silent --show-error --fail "$BASE_URL/" | grep -q '<' || {
  echo "Homepage response did not look like HTML." >&2
  exit 1
}
status=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' "$BASE_URL/e/INVALIDTOKEN")
[ "$status" = 404 ] || { echo "Invalid event token returned $status (expected 404)" >&2; exit 1; }
echo "Smoke checks passed at $BASE_URL"
