#!/usr/bin/env python3
"""Create a consistent SQLite snapshot and per-event CSV roster exports."""

import csv
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.csv_safety import spreadsheet_safe


DB = Path(os.environ.get("DB_HOST_PATH", ROOT / "data/app.db"))
BACKUPS = Path(os.environ.get("BACKUP_DIR", ROOT / "backups"))
TZ = ZoneInfo(os.environ.get("TZ", "Asia/Taipei"))
RETENTION_DAYS = int(os.environ.get("BACKUP_RETENTION_DAYS", "30"))


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-_")[:48]
    return slug or "event"


def local_datetime(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(TZ).strftime("%Y-%m-%d %H:%M")


def main() -> int:
    if not DB.is_file():
        print(f"Database does not exist: {DB}", file=sys.stderr)
        return 1
    if RETENTION_DAYS < 1:
        print("BACKUP_RETENTION_DAYS must be positive", file=sys.stderr)
        return 2

    os.umask(0o077)
    BACKUPS.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(BACKUPS, 0o700)
    now = datetime.now(timezone.utc)
    stamp = now.astimezone(TZ).strftime("%Y%m%d-%H%M%S")
    snapshot = BACKUPS / f"app-{stamp}.db"
    csv_dir = BACKUPS / f"csv-{stamp}"
    csv_dir.mkdir(mode=0o700)

    try:
        with sqlite3.connect(f"file:{DB}?mode=ro", uri=True) as source:
            with sqlite3.connect(snapshot) as target:
                source.backup(target)
        os.chmod(snapshot, 0o600)

        with sqlite3.connect(f"file:{snapshot}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            events = conn.execute("SELECT id, title FROM events ORDER BY id").fetchall()
            for event in events:
                groups = conn.execute(
                    "SELECT id, title FROM option_groups "
                    "WHERE event_id = ? AND kind = 'custom' ORDER BY sort_order, id",
                    (event["id"],),
                ).fetchall()
                headers = ["姓名", "出席狀態", "備註", "建立時間", "最後更新時間"]
                headers.extend(group["title"] for group in groups)
                path = csv_dir / f"event-{event['id']}-{safe_slug(event['title'])}.csv"
                with path.open("w", encoding="utf-8-sig", newline="") as stream:
                    writer = csv.writer(stream)
                    writer.writerow([spreadsheet_safe(value) for value in headers])
                    registrations = conn.execute(
                        "SELECT id, name, attendance, note, created_at, updated_at "
                        "FROM registrations WHERE event_id = ? ORDER BY created_at, id",
                        (event["id"],),
                    ).fetchall()
                    for registration in registrations:
                        choices = conn.execute(
                            "SELECT group_id, option_id, option_label FROM registration_choices "
                            "WHERE registration_id = ?",
                            (registration["id"],),
                        ).fetchall()
                        by_group = {choice["group_id"]: choice for choice in choices}
                        values = [
                            registration["name"],
                            "出席" if registration["attendance"] == "attending" else "不出席",
                            registration["note"] or "",
                            local_datetime(registration["created_at"]),
                            local_datetime(registration["updated_at"]),
                        ]
                        for group in groups:
                            choice = by_group.get(group["id"])
                            if choice is None:
                                values.append("")
                                continue
                            active = conn.execute(
                                "SELECT is_active FROM options WHERE id = ?",
                                (choice["option_id"],),
                            ).fetchone()
                            label = choice["option_label"]
                            if active is None or not active["is_active"]:
                                label += "（已停用）"
                            values.append(label)
                        writer.writerow([spreadsheet_safe(value) for value in values])
                os.chmod(path, 0o600)

        cutoff = now - timedelta(days=RETENTION_DAYS)
        for path in BACKUPS.iterdir():
            if not (path.name.startswith("app-") and path.suffix == ".db") and not path.name.startswith("csv-"):
                continue
            if datetime.fromtimestamp(path.stat().st_mtime, timezone.utc) < cutoff:
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
        print(f"SQLite snapshot: {snapshot}\nCSV exports: {csv_dir}")
    except Exception:
        snapshot.unlink(missing_ok=True)
        shutil.rmtree(csv_dir, ignore_errors=True)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
