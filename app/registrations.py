"""Participant registrations and the basic public roster."""

from __future__ import annotations

import sqlite3
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app import db
from app.timeutil import format_local_datetime, utc_stamp

NAME_MAX = 50
NOTE_MAX = 100
RegistrationOutcome = Literal["created", "updated", "conflict", "unavailable"]


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = " ".join(normalized.split())
    return "".join(
        character.casefold()
        if "LATIN" in unicodedata.name(character, "")
        else character
        for character in normalized
    )


@dataclass(frozen=True)
class RegistrationInput:
    name: str
    name_normalized: str
    attendance: str
    note: str | None


def validate_form(raw: dict[str, str]) -> tuple[RegistrationInput | None, dict[str, str]]:
    name = raw.get("name", "").strip()
    attendance = raw.get("attendance", "")
    note = raw.get("note", "").strip()
    errors: dict[str, str] = {}
    normalized = normalize_name(name)
    if not normalized:
        errors["name"] = "請輸入姓名。"
    elif len(name) > NAME_MAX:
        errors["name"] = f"姓名不可超過 {NAME_MAX} 字。"
    if attendance not in {"attending", "not_attending"}:
        errors["attendance"] = "請選擇是否出席。"
    if len(note) > NOTE_MAX:
        errors["note"] = f"備註不可超過 {NOTE_MAX} 字。"
    if errors:
        return None, errors
    return RegistrationInput(name, normalized, attendance, note or None), {}


def registration_for_id(db_path: str, event_id: int, registration_id: int) -> dict | None:
    with db.open_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM registrations WHERE id = ? AND event_id = ?",
            (registration_id, event_id),
        ).fetchone()
    return dict(row) if row else None


def save_registration(
    db_path: str,
    event_id: int,
    data: RegistrationInput,
    now: datetime,
    *,
    authorized_registration_id: int | None = None,
    confirm_overwrite: bool = False,
) -> tuple[RegistrationOutcome, int | None, dict | None]:
    """Serialize name check and write so simultaneous duplicate creates cannot overwrite."""
    stamp = utc_stamp(now)
    with db.open_db(db_path) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            event = conn.execute(
                "SELECT status, registration_deadline_at FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()
            if event is None or event["status"] != "open":
                conn.rollback()
                return "unavailable", None, None
            if event["registration_deadline_at"]:
                deadline = datetime.fromisoformat(event["registration_deadline_at"])
                checked_now = now if now.tzinfo else now.replace(tzinfo=deadline.tzinfo)
                if checked_now >= deadline:
                    conn.rollback()
                    return "unavailable", None, None

            existing = conn.execute(
                "SELECT * FROM registrations WHERE event_id = ? AND name_normalized = ?",
                (event_id, data.name_normalized),
            ).fetchone()
            authorized = None
            if authorized_registration_id is not None:
                authorized = conn.execute(
                    "SELECT * FROM registrations WHERE id = ? AND event_id = ?",
                    (authorized_registration_id, event_id),
                ).fetchone()
            if existing and (
                authorized is None or int(existing["id"]) != int(authorized["id"])
            ):
                conn.rollback()
                return "conflict", None, None
            if existing or authorized:
                target = existing or authorized
                rid = int(target["id"])
                if authorized is None or int(authorized["id"]) != rid:
                    conn.rollback()
                    return "conflict", None, None
                if not confirm_overwrite:
                    conn.rollback()
                    return "conflict", rid, dict(target)
                conn.execute(
                    "UPDATE registrations SET name = ?, name_normalized = ?, attendance = ?, note = ?, updated_at = ? WHERE id = ? AND event_id = ?",
                    (data.name, data.name_normalized, data.attendance, data.note, stamp, rid, event_id),
                )
                conn.commit()
                updated = conn.execute(
                    "SELECT * FROM registrations WHERE id = ?", (rid,)
                ).fetchone()
                return "updated", rid, dict(updated)

            cursor = conn.execute(
                "INSERT INTO registrations (event_id, name, name_normalized, attendance, note, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (event_id, data.name, data.name_normalized, data.attendance, data.note, stamp, stamp),
            )
            rid = int(cursor.lastrowid)
            conn.commit()
            created = conn.execute(
                "SELECT * FROM registrations WHERE id = ?", (rid,)
            ).fetchone()
            return "created", rid, dict(created)
        except sqlite3.IntegrityError:
            conn.rollback()
            return "conflict", None, None


def roster(db_path: str, event_id: int, timezone_name: str = "Asia/Taipei") -> dict:
    with db.open_db(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name, attendance, updated_at, created_at FROM registrations WHERE event_id = ? ORDER BY created_at, id",
            (event_id,),
        ).fetchall()
    registrations = [
        {
            **dict(row),
            "updated_label": format_local_datetime(row["updated_at"], timezone_name),
        }
        for row in rows
    ]
    attending = sum(row["attendance"] == "attending" for row in registrations)
    return {
        "registrations": registrations,
        "total": len(registrations),
        "attending": attending,
        "not_attending": len(registrations) - attending,
    }
