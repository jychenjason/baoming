"""Event management: validation, creation, listing, and public tokens."""

from __future__ import annotations

import secrets
import sqlite3
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime
from typing import Any

from app import db
from app.timeutil import format_local_datetime, local_datetime_input, parse_local_datetime, utc_stamp

TOKEN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ234567"
TOKEN_LENGTH = 10
TITLE_MAX = 100
DESCRIPTION_MAX = 2000
LOCATION_MAX = 200
GROUP_TITLE_MAX = 50
OPTION_LABEL_MAX = 50
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


FORM_FIELDS = tuple(field.name for field in fields(EventInput))


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
    stamp = utc_stamp(now)
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


def present_event(
    row: Mapping[str, Any], timezone_name: str, now: datetime
) -> dict[str, Any]:
    """Attach the labels every admin/public view renders for an event."""
    event = dict(row)
    event["status_label"] = STATUS_LABELS.get(event["status"], event["status"])
    event["starts_label"] = format_local_datetime(event["starts_at"], timezone_name)
    event["deadline_label"] = format_local_datetime(
        event["registration_deadline_at"], timezone_name
    )
    event["effective_status"] = effective_status(event, now)
    event["effective_status_label"] = STATUS_LABELS.get(
        event["effective_status"], event["effective_status"]
    )
    event["starts_input"] = local_datetime_input(event["starts_at"], timezone_name)
    event["deadline_input"] = local_datetime_input(
        event["registration_deadline_at"], timezone_name
    )
    return event


def effective_status(row: Mapping[str, Any], now: datetime) -> str:
    if row["status"] == "open" and row["registration_deadline_at"]:
        deadline = datetime.fromisoformat(row["registration_deadline_at"])
        checked_now = now if now.tzinfo else now.replace(tzinfo=deadline.tzinfo)
        if checked_now >= deadline:
            return "closed"
    return str(row["status"])


def list_events(
    db_path: str, *, base_url: str = "", timezone_name: str = "Asia/Taipei",
    now: datetime,
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
            **present_event(row, timezone_name, now),
            "public_url": f"{base_url}/e/{row['token']}",
        }
        for row in rows
    ]


def get_event_by_token(db_path: str, token: str) -> dict[str, Any] | None:
    with db.open_db(db_path) as conn:
        row = conn.execute("SELECT * FROM events WHERE token = ?", (token,)).fetchone()
    return dict(row) if row else None


def get_event_detail(
    db_path: str, event_id: int, timezone_name: str, now: datetime
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

    event = present_event(row, timezone_name, now)
    event["groups"] = group_rows
    return event


def update_event(db_path: str, event_id: int, data: EventInput, now: datetime) -> bool:
    stamp = utc_stamp(now)
    with db.open_db(db_path) as conn, conn:
        cursor = conn.execute(
            """UPDATE events SET title = ?, description = ?, location = ?, starts_at = ?,
               registration_deadline_at = ?, updated_at = ? WHERE id = ?""",
            (data.title, data.description, data.location, data.starts_at,
             data.registration_deadline_at, stamp, event_id),
        )
        return cursor.rowcount == 1


def set_event_status(db_path: str, event_id: int, status: str, now: datetime) -> str | None:
    if status not in {"open", "closed"}:
        return "無效的活動狀態。"
    stamp = utc_stamp(now)
    with db.open_db(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        event = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if event is None:
            return "找不到活動。"
        if status == "closed" and event["status"] != "open":
            return "草稿活動尚未開放，無法關閉。"
        if status == "open":
            if event["registration_deadline_at"]:
                deadline = datetime.fromisoformat(event["registration_deadline_at"])
                checked_now = now if now.tzinfo else now.replace(tzinfo=deadline.tzinfo)
                if checked_now >= deadline:
                    return "報名截止時間已過，請先修改截止時間再重新開放。"
            groups = conn.execute(
                """SELECT g.id, g.title, g.required,
                          COUNT(CASE WHEN o.is_active = 1 THEN 1 END) AS active_count
                   FROM option_groups g LEFT JOIN options o ON o.group_id = g.id
                   WHERE g.event_id = ? AND g.kind = 'custom'
                   GROUP BY g.id ORDER BY g.sort_order, g.id""",
                (event_id,),
            ).fetchall()
            for group in groups:
                if int(group["active_count"]) < 2:
                    return f"群組「{group['title']}」至少需要兩個啟用選項才能開放。"
                if group["required"] and int(group["active_count"]) < 1:
                    return f"必填群組「{group['title']}」需要至少一個可選答案。"
        conn.execute(
            "UPDATE events SET status = ?, updated_at = ? WHERE id = ?",
            (status, stamp, event_id),
        )
    return None


def normalize_group_title(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return " ".join(normalized.split()).casefold()


def _event_exists(conn: sqlite3.Connection, event_id: int) -> bool:
    return conn.execute("SELECT 1 FROM events WHERE id = ?", (event_id,)).fetchone() is not None


def _custom_group(conn: sqlite3.Connection, event_id: int, group_id: int):
    return conn.execute(
        "SELECT id FROM option_groups WHERE id = ? AND event_id = ? AND kind = 'custom'",
        (group_id, event_id),
    ).fetchone()


def save_group(db_path: str, event_id: int, group_id: int | None,
               title: str, required: bool, now: datetime) -> tuple[str | None, int | None]:
    title = title.strip()
    if not title:
        return "請輸入群組標題。", None
    if len(title) > GROUP_TITLE_MAX:
        return f"群組標題不可超過 {GROUP_TITLE_MAX} 字。", None
    normalized = normalize_group_title(title)
    stamp = utc_stamp(now)
    with db.open_db(db_path) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if not _event_exists(conn, event_id):
            return "找不到活動。", None
        if group_id is not None and _custom_group(conn, event_id, group_id) is None:
            return "找不到自訂群組。", None
        duplicates = conn.execute(
            "SELECT id, title FROM option_groups WHERE event_id = ?",
            (event_id,),
        ).fetchall()
        if any(normalize_group_title(row["title"]) == normalized
               and (group_id is None or int(row["id"]) != group_id) for row in duplicates):
            return "群組標題不可與其他群組重複。", None
        if group_id is None:
            order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM option_groups WHERE event_id = ?",
                (event_id,),
            ).fetchone()[0]
            cursor = conn.execute(
                "INSERT INTO option_groups (event_id, kind, title, required, sort_order, created_at) VALUES (?, 'custom', ?, ?, ?, ?)",
                (event_id, title, int(required), order, stamp),
            )
            result_id = int(cursor.lastrowid)
        else:
            conn.execute(
                "UPDATE option_groups SET title = ?, required = ? WHERE id = ? AND event_id = ? AND kind = 'custom'",
                (title, int(required), group_id, event_id),
            )
            result_id = group_id
        conn.execute("UPDATE events SET updated_at = ? WHERE id = ?", (stamp, event_id))
    return None, result_id


def save_option(db_path: str, event_id: int, group_id: int, option_id: int | None,
                label: str, now: datetime) -> str | None:
    label = label.strip()
    if not label:
        return "請輸入選項文字。"
    if len(label) > OPTION_LABEL_MAX:
        return f"選項文字不可超過 {OPTION_LABEL_MAX} 字。"
    stamp = utc_stamp(now)
    with db.open_db(db_path) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if _custom_group(conn, event_id, group_id) is None:
            return "找不到自訂群組。"
        if option_id is None:
            order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM options WHERE group_id = ?",
                (group_id,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO options (group_id, label, is_active, sort_order, created_at) VALUES (?, ?, 1, ?, ?)",
                (group_id, label, order, stamp),
            )
        else:
            exists = conn.execute(
                "SELECT 1 FROM options WHERE id = ? AND group_id = ?",
                (option_id, group_id),
            ).fetchone()
            if exists is None:
                return "找不到自訂選項。"
            conn.execute("UPDATE options SET label = ? WHERE id = ?", (label, option_id))
        conn.execute("UPDATE events SET updated_at = ? WHERE id = ?", (stamp, event_id))
    return None


def disable_option(db_path: str, event_id: int, group_id: int,
                   option_id: int, now: datetime, *, confirmed: bool = False) -> tuple[bool, int, bool]:
    stamp = utc_stamp(now)
    with db.open_db(db_path) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if _custom_group(conn, event_id, group_id) is None:
            return False, 0, False
        option = conn.execute(
            "SELECT is_active FROM options WHERE id = ? AND group_id = ?",
            (option_id, group_id),
        ).fetchone()
        if option is None:
            return False, 0, False
        uses = conn.execute(
            "SELECT COUNT(*) FROM registration_choices WHERE option_id = ?", (option_id,)
        ).fetchone()[0]
        if not confirmed:
            return True, int(uses), False
        conn.execute("UPDATE options SET is_active = 0 WHERE id = ?", (option_id,))
        conn.execute("UPDATE events SET updated_at = ? WHERE id = ?", (stamp, event_id))
    return True, int(uses), True


def reorder_item(db_path: str, event_id: int, group_id: int | None,
                 item_id: int, direction: str, now: datetime) -> bool:
    if direction not in {"up", "down"}:
        return False
    with db.open_db(db_path) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        if group_id is None:
            rows = conn.execute(
                "SELECT id, sort_order FROM option_groups WHERE event_id = ? AND kind = 'custom' ORDER BY sort_order, id",
                (event_id,),
            ).fetchall()
        else:
            if _custom_group(conn, event_id, group_id) is None:
                return False
            rows = conn.execute(
                "SELECT id, sort_order FROM options WHERE group_id = ? ORDER BY sort_order, id",
                (group_id,),
            ).fetchall()
        ids = [int(row["id"]) for row in rows]
        if item_id not in ids:
            return False
        index = ids.index(item_id)
        other = index - 1 if direction == "up" else index + 1
        if not 0 <= other < len(ids):
            return True
        ids[index], ids[other] = ids[other], ids[index]
        table = "option_groups" if group_id is None else "options"
        stamp = utc_stamp(now)
        for order, current_id in enumerate(ids):
            conn.execute(f"UPDATE {table} SET sort_order = ? WHERE id = ?", (order, current_id))
        conn.execute("UPDATE events SET updated_at = ? WHERE id = ?", (stamp, event_id))
    return True


def duplicate_event(db_path: str, event_id: int, now: datetime) -> int | None:
    stamp = utc_stamp(now)
    with db.open_db(db_path) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        source = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if source is None:
            return None
        token = _unique_token(conn)
        title = source["title"]
        suffix = "（複本）"
        title = title[: TITLE_MAX - len(suffix)] + suffix
        cursor = conn.execute(
            "INSERT INTO events (token, title, description, location, starts_at, registration_deadline_at, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?)",
            (token, title, source["description"], source["location"], source["starts_at"],
             source["registration_deadline_at"], stamp, stamp),
        )
        new_event_id = int(cursor.lastrowid)
        groups = conn.execute(
            "SELECT * FROM option_groups WHERE event_id = ? ORDER BY sort_order, id", (event_id,)
        ).fetchall()
        for group in groups:
            cursor = conn.execute(
                "INSERT INTO option_groups (event_id, kind, title, required, sort_order, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (new_event_id, group["kind"], group["title"], group["required"], group["sort_order"], stamp),
            )
            new_group_id = int(cursor.lastrowid)
            options = conn.execute(
                "SELECT * FROM options WHERE group_id = ? ORDER BY sort_order, id", (group["id"],)
            ).fetchall()
            conn.executemany(
                "INSERT INTO options (group_id, label, is_active, sort_order, created_at) VALUES (?, ?, ?, ?, ?)",
                [(new_group_id, option["label"], option["is_active"], option["sort_order"], stamp)
                 for option in options],
            )
    return new_event_id


def rotate_token(db_path: str, event_id: int, now: datetime) -> str | None:
    stamp = utc_stamp(now)
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
