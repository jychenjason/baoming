"""Administrator exports for complete event and registration data."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app import db
from app.csv_safety import spreadsheet_safe
from app.timeutil import format_local_datetime


def _localize_timestamp(value: object, timezone_name: str) -> object:
    if not isinstance(value, str) or not value:
        return value
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(ZoneInfo(timezone_name)).isoformat(timespec="seconds")


def _localize_datetime_fields(value: object, timezone_name: str) -> object:
    if isinstance(value, list):
        return [_localize_datetime_fields(item, timezone_name) for item in value]
    if isinstance(value, dict):
        return {
            key: _localize_timestamp(item, timezone_name)
            if key.endswith("_at") or key in {"created_at", "updated_at"}
            else _localize_datetime_fields(item, timezone_name)
            for key, item in value.items()
        }
    return value


def csv_export(db_path: str, event_id: int, timezone_name: str) -> bytes | None:
    with db.open_db(db_path) as conn:
        event = conn.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone()
        if event is None:
            return None
        groups = conn.execute(
            "SELECT id, title FROM option_groups WHERE event_id = ? AND kind = 'custom' ORDER BY sort_order, id",
            (event_id,),
        ).fetchall()
        rows = conn.execute(
            """SELECT r.id, r.name, r.attendance, r.note, r.created_at, r.updated_at,
                      rc.group_id, rc.option_label, rc.option_price, rc.option_id, o.is_active
               FROM registrations r
               LEFT JOIN registration_choices rc ON rc.registration_id = r.id
               LEFT JOIN options o ON o.id = rc.option_id
               WHERE r.event_id = ?
               ORDER BY r.created_at, r.id""",
            (event_id,),
        ).fetchall()

    answers: dict[tuple[int, int], tuple[str, int, bool]] = {}
    registrations: dict[int, dict] = {}
    for row in rows:
        rid = int(row["id"])
        if rid not in registrations:
            registrations[rid] = {
                "name": row["name"],
                "attendance": "出席" if row["attendance"] == "attending" else "不出席",
                "note": row["note"] or "",
                "created": format_local_datetime(row["created_at"], timezone_name),
                "updated": format_local_datetime(row["updated_at"], timezone_name),
            }
        if row["group_id"] is not None:
            answers[(rid, int(row["group_id"]))] = (
                str(row["option_label"]), int(row["option_price"]), bool(row["is_active"])
            )

    output = io.StringIO(newline="")
    writer = csv.writer(output, dialect="excel", lineterminator="\r\n")
    headers = ["姓名", "出席狀態", "備註", "建立時間", "最後更新時間"]
    headers.extend(group["title"] for group in groups)
    writer.writerow([spreadsheet_safe(value) for value in headers])
    for rid, registration in registrations.items():
        values = [registration[key] for key in ("name", "attendance", "note", "created", "updated")]
        for group in groups:
            answer = answers.get((rid, int(group["id"])))
            values.append(
                f"{answer[0]}（NT$ {answer[1]}）" + ("（已停用）" if not answer[2] else "")
                if answer else ""
            )
        writer.writerow([spreadsheet_safe(value) for value in values])
    return b"\xef\xbb\xbf" + output.getvalue().encode("utf-8")


def json_export(db_path: str, event_id: int, timezone_name: str = "Asia/Taipei") -> bytes | None:
    with db.open_db(db_path) as conn:
        event = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if event is None:
            return None
        groups = conn.execute(
            "SELECT * FROM option_groups WHERE event_id = ? ORDER BY sort_order, id",
            (event_id,),
        ).fetchall()
        group_data = []
        for group in groups:
            options = conn.execute(
                "SELECT * FROM options WHERE group_id = ? ORDER BY sort_order, id",
                (group["id"],),
            ).fetchall()
            group_data.append({**dict(group), "options": [dict(option) for option in options]})
        registrations = conn.execute(
            "SELECT * FROM registrations WHERE event_id = ? ORDER BY created_at, id",
            (event_id,),
        ).fetchall()
        registration_data = []
        for registration in registrations:
            choices = conn.execute(
                "SELECT * FROM registration_choices WHERE registration_id = ? ORDER BY group_id",
                (registration["id"],),
            ).fetchall()
            registration_data.append({**dict(registration), "choices": [dict(choice) for choice in choices]})

    payload = {
        "event": dict(event),
        "groups": group_data,
        "registrations": registration_data,
    }
    localized = _localize_datetime_fields(payload, timezone_name)
    return json.dumps(localized, ensure_ascii=False, indent=2).encode("utf-8")
