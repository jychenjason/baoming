# VPS deployment and operations

This deployment runs one Uvicorn worker with SQLite. The database, SQLite snapshots, CSV roster exports, and Caddy certificates are persistent data. Names and notes are personal data: keep `data/`, `backups/`, `.env`, and downloaded exports private. The backup script uses owner-only directory/file permissions and retains snapshots for 30 days. A deleted online record can remain in backups until that retention period expires.

## Requirements

- Docker Engine with the Docker Compose v2 plugin
- Git, curl, and Python 3.12+ on the VPS (the backup utility uses Python's SQLite online-backup API)
- A DNS `A`/`AAAA` record for `DOMAIN` pointing to this VPS for the bundled Caddy setup

Copy `.env.example` to `.env`, set a unique `ADMIN_PASSWORD`, generate `SESSION_SECRET` with `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'`, and set `DOMAIN`. Restrict `.env` to the deployment owner (`chmod 600 .env`). The checked-in `.env.example` is not a production secret file.

## Default: app with automatic HTTPS

Allow inbound TCP ports 80 and 443 (and UDP 443 for HTTP/3), then run:

```sh
docker compose up -d --build
scripts/smoke.sh "https://${DOMAIN}"
```

Caddy obtains and renews the certificate and proxies to the app over a private Compose network. Caddy has the fixed address `172.28.0.3`; Uvicorn accepts forwarded headers only from that address. Do not attach untrusted containers to the `web` network.

## Existing host nginx or Caddy

Use the alternate compose file as the complete app-only stack:

```sh
docker compose -f docker-compose.proxy.yml up -d --build
```

The app is published only on `127.0.0.1:${APP_PORT:-8000}`. Configure the host proxy to send these headers:

```text
Host: original public host
X-Forwarded-For: client address (append/replace according to the proxy's trusted-client policy)
X-Forwarded-Proto: https
```

The app trusts forwarded headers only from `172.29.0.1`, the gateway of the fixed Compose network in `docker-compose.proxy.yml`. Requests must reach the published port through that host gateway. Confirm the source address seen inside the container on your Docker host before relying on proxy-derived rate-limit IPs. If the host's routing changes the source address or the subnet conflicts with local networks, adjust the Compose subnet and the matching `--forwarded-allow-ips` value together. Never set the allow-list to `*` and do not pass client-supplied forwarding headers through unchanged. `COOKIE_SECURE=1` is set because this mode is intended to terminate HTTPS at the host proxy.

Smoke-check through the public HTTPS proxy with `scripts/smoke.sh https://your-domain`. `APP_PORT` changes the loopback published port; the proxy backend must use the same port.

## Updates and rollback

Run `scripts/deploy.sh` from the VPS checkout. Set `COMPOSE_FILE=docker-compose.proxy.yml` when using the existing-proxy stack. The script:

1. Confirms the `.env`, database, and currently running/recorded image exist.
2. Creates a consistent pre-update SQLite snapshot and CSV exports before `git pull`.
3. Pulls fast-forward-only changes, builds an image tagged with the resulting short commit SHA, and updates Compose.
4. Polls the app's `/healthz` for up to 60 seconds.
5. On a failed update health check, stops the app, restores the pre-update database snapshot, starts the prior local image tag, and checks health again.

The rollback image is kept locally; this flow uses no image registry. Preserve the `.deploy/current-image-tag` state and local Docker images. If rollback health also fails, the script reports that condition; inspect `docker compose logs app` and restore the backup manually. Keep schema changes backward-compatible where possible; the database snapshot is the recovery point for changes that are not.

On the first deployment, use `docker compose up -d --build` to establish the running image before using `scripts/deploy.sh`. Updates are performed only via `deploy.sh`; a bare `docker compose up --build` after an update uses the default `local` tag.

## Daily backups

Install a cron entry under the deployment owner (the working directory is derived from the script path):

```cron
30 3 * * * /absolute/path/to/baoming/scripts/backup.sh >> /absolute/path/to/baoming/backups/backup.log 2>&1
```

Each run makes an online SQLite snapshot (`backups/app-YYYYMMDD-HHMMSS.db`) and one UTF-8-with-BOM CSV per event under a timestamped `backups/csv-*` directory. The CSV contains names, notes, attendance, timestamps, and custom answers; disabled answers are marked. Files older than 30 days are removed. Backups are not encrypted or copied off-site by this app; use private filesystem permissions and arrange your own encrypted `rsync`/`rclone` copy if needed. Do not expose `backups/` through the web server.

## Restore a database snapshot

Choose a snapshot and stop the app first. Keep a copy of the current database before replacing it:

```sh
docker compose stop app
cp data/app.db "data/app.db.before-restore.$(date +%Y%m%d-%H%M%S)"
cp backups/app-YYYYMMDD-HHMMSS.db data/app.db
docker compose up -d app
scripts/smoke.sh "https://${DOMAIN}"
```

For the existing-proxy stack, add `-f docker-compose.proxy.yml` to each Compose command and smoke-check its public HTTPS URL. Verify the event roster in the admin UI as well. Do not copy a live SQLite database file without first stopping the app; WAL state may otherwise be omitted.

## Rotate the administrator password

Edit `ADMIN_PASSWORD` in the private `.env`, then recreate the app with `docker compose up -d --force-recreate app` (include `-f docker-compose.proxy.yml` if applicable). Password-bound session validation makes old admin sessions invalid after the restart. Participants' data and cookies are unaffected.
