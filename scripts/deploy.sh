#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"

COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.yml}
DB_FILE=${DB_HOST_PATH:-$ROOT/data/app.db}
STATE_DIR="$ROOT/.deploy"
STATE_FILE="$STATE_DIR/current-image-tag"

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

if [ ! -f .env ]; then
  echo "Missing .env; copy .env.example and set production secrets first." >&2
  exit 2
fi
if [ ! -f "$DB_FILE" ]; then
  echo "Missing database at $DB_FILE; initialize and deploy the app once before updates." >&2
  exit 2
fi

# Preserve the live image under a stable rollback tag before fetching/building.
running_id=$(compose ps -q app)
if [ -n "$running_id" ]; then
  live_image=$(docker inspect --format '{{.Image}}' "$running_id")
  if [ -f "$STATE_FILE" ]; then
    prior_tag=$(cat "$STATE_FILE")
  else
    running_ref=$(docker inspect --format '{{.Config.Image}}' "$running_id")
    prior_tag=${running_ref##*:}
  fi
  docker image tag "$live_image" "event-registration:$prior_tag"
elif [ -f "$STATE_FILE" ]; then
  prior_tag=$(cat "$STATE_FILE")
else
  echo "No running app or recorded prior image; cannot guarantee rollback." >&2
  exit 2
fi
if ! docker image inspect "event-registration:$prior_tag" >/dev/null 2>&1; then
  echo "Prior image event-registration:$prior_tag is unavailable." >&2
  exit 2
fi

scripts/backup.sh
git pull --ff-only
new_tag=$(git rev-parse --short HEAD)
mkdir -p "$STATE_DIR"

rollback() {
  reason=$1
  echo "Deployment failed: $reason; restoring database and image $prior_tag." >&2
  if ! $COMPOSE stop app; then
    echo "Could not stop the app; refusing to replace the live database." >&2
    exit 1
  fi
  rm -f "${DB_FILE}-wal" "${DB_FILE}-shm"
  restore_tmp="${DB_FILE}.restore.$$"
  cp "$preupdate_db" "$restore_tmp"
  chmod 600 "$restore_tmp"
  mv "$restore_tmp" "$DB_FILE"
  IMAGE_TAG=$prior_tag compose up -d --no-build app
  if ! wait_healthy; then
    echo "Rollback image also failed health check; inspect Docker logs immediately." >&2
    exit 1
  fi
  printf '%s\n' "$prior_tag" > "$STATE_FILE"
  exit 1
}

wait_healthy() {
  attempt=0
  while [ "$attempt" -lt 60 ]; do
    if compose exec -T app python -c \
      'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=2)' \
      >/dev/null 2>&1; then
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 1
  done
  return 1
}

preupdate_db=$(find backups -maxdepth 1 -type f -name 'app-*.db' -printf '%T@ %p\n' | sort -nr | head -n 1 | cut -d ' ' -f 2-)
if [ -z "$preupdate_db" ] || [ ! -f "$preupdate_db" ]; then
  echo "Could not locate the pre-update database backup." >&2
  exit 1
fi

if ! IMAGE_TAG=$new_tag compose build app; then
  echo "Image build failed; the running app and database were left in place." >&2
  exit 1
fi
if ! IMAGE_TAG=$new_tag compose up -d --no-build; then
  rollback "compose up failed"
fi
if ! wait_healthy; then
  rollback "health check did not pass within 60 seconds"
fi

printf '%s\n' "$new_tag" > "$STATE_FILE"
chmod 600 "$STATE_FILE"
echo "Deployment healthy: event-registration:$new_tag"
