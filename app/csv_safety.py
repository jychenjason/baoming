"""Helpers for writing untrusted text safely to spreadsheet-readable CSV."""

from __future__ import annotations


def spreadsheet_safe(value: object) -> str:
    text = "" if value is None else str(value)
    probe = text
    while probe and (probe[0].isspace() or ord(probe[0]) < 32):
        probe = probe[1:]
    if probe.startswith(("=", "+", "-", "@")):
        return "'" + text
    return text
