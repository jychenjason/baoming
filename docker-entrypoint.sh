#!/bin/sh
set -eu

# Docker creates the bind-mounted data directory as root. Fix ownership before
# dropping privileges so the server itself never runs as root.
mkdir -p /app/data
chown -R appuser:appuser /app/data

exec setpriv --reuid=appuser --regid=appuser --init-groups "$@"
