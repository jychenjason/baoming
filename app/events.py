"""Event management: validation, creation, listing, and public tokens."""

from __future__ import annotations

import secrets
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app import db
from app.timeutil import format_local_datetime, parse_local_datetime

TOKEN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ234567"
TOKEN_LENGTH = 10
TITLE_MAX = 100
DESCRIPTION_MAX = 2000
LOCATION_MAX = 200
ATTENDANCE_GROUP_TITLE = "是否出席"
ATTENDANCE_OPTIONS = ("出席", "不出席")

STATUS_LABELS = {"draft": "草稿", "open": "開放中", "closed": "已關閉"}


def generate_token() -> str:
    return "".join(secrets.choice(TOKEN_ALPHABET) for _ in range(TOKEN_LENGTH))


@dataclass(frozen=True)
class EventInput:
    title: str
    description: str | None
    location: str | None
    starts_at: str | None
    registration_deadline_at: str | None


def validate_event_form(
    raw: Mapping[str, str], timezone_name: str
) -> tuple[EventInput | None, dict[str, str]]:
    title = raw.get("title", "").strip()
    description = raw.get("description", "").strip()
    location = raw.get("location", "").strip()
    errors: dict[str, str] = {}

    if not title:
        errors["title"] = "請輸入活動標題。"
    elif len(title) > TITLE_MAX:
        errors["title"] = f"活動標題不可超過 {TITLE_MAX} 字。"

    if len(description) > DESCRIPTION_MAX:
        errors["description"] = f"說明不可超過 {DESCRIPTION_MAX} 字。"

    if len(location) > LOCATION_MAX:
        errors["location"] = f"地點不可超過 {LOCATION_MAX} 字。"

    starts_at = None
    if raw.get("starts_at", "").strip():
        try:
            starts_at = parse_local_datetime(raw["starts_at"], timezone_name)
        except ValueError:
            errors["starts_at"] = "活動時間格式不正確。"

    deadline = None
    if raw.get("registration_deadline_at", "").strip():
        try:
            deadline = parse_local_datetime(
                raw["registration_deadline_at"], timezone_name
            )
        except ValueError:
            errors["registration_deadline_at"] = "報名截止時間格式不正確。"

    if errors:
        return None, errors

    return (
        EventInput(
            title=title,
            description=description or None,
            location=location or None,
            starts_at=starts_at,
            registration_deadline_at=deadline,
        ),
        {},
    )


def _unique_token(conn: sqlite3.Connection) -> str:
    for _ in range(50):
        token = generate_token()
        exists = conn.execute(
            "SELECT 1 FROM events WHERE token = ?", (token,)
        ).fetchone()
        if not exists:
            return token
    raise RuntimeError("could not allocate a unique event token")


def create_event(
    db_path: str, data: EventInput, now: datetime
) -> int:
    stamp = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    with db.open_db(db_path) as conn:
        with conn:
            token = _unique_token(conn)
            cursor = conn.execute(
                """
                INSERT INTO events
                    (token, title, description, location, starts_at,
                     registration_deadline_at, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?)
                """,
                (
                    token,
                    data.title,
                    data.description,
                    data.location,
                    data.starts_at,
                    data.registration_deadline_at,
                    stamp,
                    stamp,
                ),
            )
            event_id = int(cursor.lastrowid)
            group = conn.execute(
                """
                INSERT INTO option_groups
                    (event_id, kind, title, required, sort_order, created_at)
                VALUES (?, 'attendance', ?, 1, 0, ?)
                """,
                (event_id, ATTENDANCE_GROUP_TITLE, stamp),
            )
            group_id = int(group.lastrowid)
            conn.executemany(
                """
                INSERT INTO options (group_id, label, is_active, sort_order, created_at)
                VALUES (?, ?, 1, ?, ?)
                """,
                [
                    (group_id, label, index, stamp)
                    for index, label in enumerate(ATTENDANCE_OPTIONS)
                ],
            )
    return event_id


def list_events(
    db_path: str, *, base_url: str = "", timezone_name: str = "Asia/Taipei"
) -> list[dict[str, Any]]:
    with db.open_db(db_path) as conn:
        rows = conn.execute(
            """
            SELECT e.*,
                   (SELECT COUNT(*) FROM registrations r
                    WHERE r.event_id = e.id) AS registration_count
            FROM events e
            ORDER BY e.created_at DESC, e.id DESC
            """
        ).fetchall()

    return [
        {
            **dict(row),
            "status_label": STATUS_LABELS.get(row["status"], row["status"]),
            "deadline_label": format_local_datetime(
                row["registration_deadline_at"], timezone_name
            ),
            "public_url": f"{base_url}/e/{row['token']}",
        }
        for row in rows
    ]


def get_event(db_path: str, event_id: int) -> dict[str, Any] | None:
    with db.open_db(db_path) as conn:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    return dict(row) if row else None


def get_event_by_token(db_path: str, token: str) -> dict[str, Any] | None:
    with db.open_db(db_path) as conn:
        row = conn.execute("SELECT * FROM events WHERE token = ?", (token,)).fetchone()
    return dict(row) if row else None


def get_event_detail(
    db_path: str, event_id: int, timezone_name: str = "Asia/Taipei"
) -> dict[str, Any] | None:
    with db.open_db(db_path) as conn:
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            return None
        groups = conn.execute(
            "SELECT * FROM option_groups WHERE event_id = ? ORDER BY sort_order, id",
            (event_id,),
        ).fetchall()
        group_rows = []
        for group in groups:
            options = conn.execute(
                "SELECT * FROM options WHERE group_id = ? ORDER BY sort_order, id",
                (group["id"],),
            ).fetchall()
            group_rows.append({**dict(group), "options": [dict(o) for o in options]})

    event = dict(row)
    event["status_label"] = STATUS_LABELS.get(event["status"], event["status"])
    event["starts_label"] = format_local_datetime(event["starts_at"], timezone_name)
    event["deadline_label"] = format_local_datetime(
        event["registration_deadline_at"], timezone_name
    )
    event["groups"] = group_rows
    return event


def rotate_token(db_path: str, event_id: int, now: datetime) -> str | None:
    stamp = now.astimezone(timezone.utc).isoformat(timespec="seconds")
    with db.open_db(db_path) as conn:
        with conn:
            exists = conn.execute(
                "SELECT 1 FROM events WHERE id = ?", (event_id,)
            ).fetchone()
            if not exists:
                return None
            token = _unique_token(conn)
            conn.execute(
                "UPDATE events SET token = ?, updated_at = ? WHERE id = ?",
                (token, stamp, event_id),
            )
    return token
