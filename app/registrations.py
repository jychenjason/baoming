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
    choices: dict[str, str]


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
    choices = {key: value for key, value in raw.items() if key.startswith("group_")}
    return RegistrationInput(name, normalized, attendance, note or None, choices), {}


def custom_groups(db_path: str, event_id: int) -> list[dict]:
    with db.open_db(db_path) as conn:
        groups = conn.execute(
            "SELECT id, title, required FROM option_groups WHERE event_id = ? AND kind = 'custom' ORDER BY sort_order, id",
            (event_id,),
        ).fetchall()
        result = []
        for group in groups:
            options = conn.execute(
                "SELECT id, label FROM options WHERE group_id = ? AND is_active = 1 ORDER BY sort_order, id",
                (group["id"],),
            ).fetchall()
            result.append({**dict(group), "options": [dict(option) for option in options]})
    return result


def registration_for_id(db_path: str, event_id: int, registration_id: int) -> dict | None:
    with db.open_db(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM registrations WHERE id = ? AND event_id = ?",
            (registration_id, event_id),
        ).fetchone()
        if row is None:
            return None
        choices = conn.execute(
            "SELECT group_id, option_id FROM registration_choices WHERE registration_id = ?",
            (registration_id,),
        ).fetchall()
    return {**dict(row), "choices": {f"group_{choice['group_id']}": str(choice['option_id']) for choice in choices}}


def save_registration(
    db_path: str,
    event_id: int,
    data: RegistrationInput,
    now: datetime,
    *,
    authorized_registration_id: int | None = None,
    confirm_overwrite: bool = False,
) -> tuple[RegistrationOutcome | Literal["invalid"], int | None, dict | None, dict[str, str]]:
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
                return "unavailable", None, None, {}
            if event["registration_deadline_at"]:
                deadline = datetime.fromisoformat(event["registration_deadline_at"])
                checked_now = now if now.tzinfo else now.replace(tzinfo=deadline.tzinfo)
                if checked_now >= deadline:
                    conn.rollback()
                    return "unavailable", None, None, {}

            groups = conn.execute(
                "SELECT id, title, required FROM option_groups WHERE event_id = ? AND kind = 'custom' ORDER BY sort_order, id",
                (event_id,),
            ).fetchall()
            group_by_key = {f"group_{group['id']}": group for group in groups}
            choice_errors: dict[str, str] = {}
            selected: list[tuple[int, int, str, str]] = []
            if data.attendance == "attending":
                for key in data.choices:
                    if key not in group_by_key:
                        choice_errors["choices"] = "包含無效的選項群組，請重新選擇。"
                        break
                for key, group in group_by_key.items():
                    value = data.choices.get(key, "").strip()
                    if not value:
                        if group["required"]:
                            choice_errors[key] = f"請選擇「{group['title']}」。"
                        continue
                    try:
                        option_id = int(value)
                    except ValueError:
                        choice_errors[key] = f"「{group['title']}」的選項無效，請重新選擇。"
                        continue
                    option = conn.execute(
                        "SELECT label FROM options WHERE id = ? AND group_id = ? AND is_active = 1",
                        (option_id, group["id"]),
                    ).fetchone()
                    if option is None:
                        choice_errors[key] = f"「{group['title']}」的選項已失效，請重新選擇。"
                    else:
                        selected.append((int(group["id"]), option_id, str(option["label"]), str(group["title"])))
            if choice_errors:
                conn.rollback()
                return "invalid", None, None, choice_errors

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
                return "conflict", None, None, {}
            if existing or authorized:
                target = existing or authorized
                rid = int(target["id"])
                if authorized is None or int(authorized["id"]) != rid:
                    conn.rollback()
                    return "conflict", None, None, {}
                if not confirm_overwrite:
                    conn.rollback()
                    return "conflict", rid, dict(target), {}
                conn.execute(
                    "UPDATE registrations SET name = ?, name_normalized = ?, attendance = ?, note = ?, updated_at = ? WHERE id = ? AND event_id = ?",
                    (data.name, data.name_normalized, data.attendance, data.note, stamp, rid, event_id),
                )
                conn.execute("DELETE FROM registration_choices WHERE registration_id = ?", (rid,))
                conn.executemany(
                    "INSERT INTO registration_choices (registration_id, group_id, option_id, option_label, group_title) VALUES (?, ?, ?, ?, ?)",
                    [(rid, group_id, option_id, label, title) for group_id, option_id, label, title in selected],
                )
                conn.commit()
                updated = conn.execute(
                    "SELECT * FROM registrations WHERE id = ?", (rid,)
                ).fetchone()
                return "updated", rid, dict(updated), {}

            cursor = conn.execute(
                "INSERT INTO registrations (event_id, name, name_normalized, attendance, note, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (event_id, data.name, data.name_normalized, data.attendance, data.note, stamp, stamp),
            )
            rid = int(cursor.lastrowid)
            conn.executemany(
                "INSERT INTO registration_choices (registration_id, group_id, option_id, option_label, group_title) VALUES (?, ?, ?, ?, ?)",
                [(rid, group_id, option_id, label, title) for group_id, option_id, label, title in selected],
            )
            conn.commit()
            created = conn.execute(
                "SELECT * FROM registrations WHERE id = ?", (rid,)
            ).fetchone()
            return "created", rid, dict(created), {}
        except sqlite3.IntegrityError:
            conn.rollback()
            return "conflict", None, None, {}


def roster(db_path: str, event_id: int, timezone_name: str = "Asia/Taipei") -> dict:
    with db.open_db(db_path) as conn:
        rows = conn.execute(
            "SELECT id, name, attendance, note, updated_at, created_at FROM registrations WHERE event_id = ? ORDER BY created_at, id",
            (event_id,),
        ).fetchall()
        groups = conn.execute(
            "SELECT id, title FROM option_groups WHERE event_id = ? AND kind = 'custom' ORDER BY sort_order, id",
            (event_id,),
        ).fetchall()
        choices = conn.execute(
            """SELECT rc.registration_id, rc.group_id, rc.option_id, rc.option_label, rc.group_title,
                      o.is_active
               FROM registration_choices rc
               JOIN registrations r ON r.id = rc.registration_id
               LEFT JOIN options o ON o.id = rc.option_id
               WHERE r.event_id = ?""",
            (event_id,),
        ).fetchall()
    choice_index = {(int(row["registration_id"]), int(row["group_id"])): dict(row) for row in choices}
    registrations = [
        {
            **dict(row),
            "updated_label": format_local_datetime(row["updated_at"], timezone_name),
            "choices": [
                {
                    "group_title": choice_index[(int(row["id"]), int(group["id"]))]["group_title"],
                    "option_label": choice_index[(int(row["id"]), int(group["id"]))]["option_label"],
                    "disabled": not bool(choice_index[(int(row["id"]), int(group["id"]))]["is_active"]),
                }
                if (int(row["id"]), int(group["id"])) in choice_index
                else {"group_title": group["title"], "option_label": "未選", "disabled": False}
                for group in groups
            ],
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
