"""Alerts: the per-car switch, the log of what was sent, and the last run.

Every alert is claimed in the log before it goes out, and the log's
UNIQUE (channel, subject, level) means an alert can only be claimed once — by
this run or any other. A failed send gives the claim back for the next run.
"""

from __future__ import annotations

import json
import sqlite3

from ..db import now_iso
from . import settings

LAST_RUN = "alerts_last_run"


# ---------- The switch ----------


def cars_on(conn: sqlite3.Connection) -> list[dict]:
    """Cars sending alerts: switched on, and not archived."""
    return [dict(row) for row in conn.execute(
        "SELECT * FROM vehicles WHERE alerts = 1 AND archived_at IS NULL ORDER BY name COLLATE NOCASE, id")]


def cars_watched(conn: sqlite3.Connection) -> list[dict]:
    """Cars the daily run looks at: alerts on, an inspection or registration date to remind of, or an open
    recall; not archived."""
    return [dict(row) for row in conn.execute(
        "SELECT * FROM vehicles v WHERE archived_at IS NULL"
        "   AND (alerts = 1 OR EXISTS (SELECT 1 FROM renewals r WHERE r.vehicle_id = v.id)"
        "        OR EXISTS (SELECT 1 FROM recalls rc WHERE rc.vehicle_id = v.id AND rc.status = 'open'))"
        " ORDER BY name COLLATE NOCASE, id")]


def cars_with_warranties(conn: sqlite3.Connection) -> list[dict]:
    """Cars with a warranty that can end (not lifetime); not archived. The run sees whether one is ending."""
    return [dict(row) for row in conn.execute(
        "SELECT * FROM vehicles v WHERE archived_at IS NULL"
        "   AND EXISTS (SELECT 1 FROM warranties w WHERE w.vehicle_id = v.id"
        "               AND (w.months IS NOT NULL OR w.miles IS NOT NULL))"
        " ORDER BY name COLLATE NOCASE, id")]


def switch(conn: sqlite3.Connection, vehicle_id: int, on: bool) -> None:
    conn.execute("UPDATE vehicles SET alerts = ?, updated_at = ? WHERE id = ?", (int(on), now_iso(), vehicle_id))


# ---------- The log ----------


def logged(conn: sqlite3.Connection, channel: str) -> set[tuple[str, str]]:
    """(subject, level) of every alert sent, going out, or held back: everything but failures."""
    return {(row[0], row[1]) for row in conn.execute(
        "SELECT subject, level FROM alert_log WHERE channel = ? AND outcome != 'failed'", (channel,))}


def claim(conn: sqlite3.Connection, channel: str, subject: str, level: str, vehicle_id: int | None,
          title: str, body: str = "") -> int | None:
    """Take an alert to send; its log id, or None if it's already been sent or is going out."""
    now = now_iso()
    row = conn.execute(
        "INSERT INTO alert_log (channel, subject, level, vehicle_id, title, body, outcome, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, 'sending', ?, ?)"
        " ON CONFLICT (channel, subject, level) DO UPDATE SET outcome = 'sending', title = excluded.title,"
        "   body = excluded.body, error = '', updated_at = excluded.updated_at"
        " WHERE alert_log.outcome = 'failed'"
        " RETURNING id",
        (channel, subject, level, vehicle_id, title, body, now, now),
    ).fetchone()
    return row[0] if row else None


def mark(conn: sqlite3.Connection, alert_id: int, outcome: str, error: str = "") -> None:
    conn.execute("UPDATE alert_log SET outcome = ?, error = ?, updated_at = ? WHERE id = ?",
                 (outcome, error, now_iso(), alert_id))


def known(conn: sqlite3.Connection, channel: str, subject: str, level: str, vehicle_id: int, title: str) -> None:
    """Log an alert as held back — already true when the car's alerts were turned on."""
    now = now_iso()
    conn.execute(
        "INSERT INTO alert_log (channel, subject, level, vehicle_id, title, outcome, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, 'known', ?, ?) ON CONFLICT (channel, subject, level) DO NOTHING",
        (channel, subject, level, vehicle_id, title, now, now),
    )


def recent(conn: sqlite3.Connection, limit: int = 20) -> list[dict]:
    """The latest alerts sent or tried, newest first; held-back ones aren't news."""
    return [dict(row) for row in conn.execute(
        "SELECT a.*, v.name AS vehicle_name FROM alert_log a LEFT JOIN vehicles v ON v.id = a.vehicle_id"
        " WHERE a.outcome != 'known' ORDER BY a.updated_at DESC, a.id DESC LIMIT ?", (limit,))]


# ---------- The last run ----------


def last_run(conn: sqlite3.Connection) -> dict | None:
    """When the daily run last ran and what it did: {"at": ISO time, "summary": words, "ok": bool}."""
    value = settings.get(conn, LAST_RUN)
    return json.loads(value) if value else None


def set_last_run(conn: sqlite3.Connection, at: str, summary: str, ok: bool) -> None:
    settings.put(conn, LAST_RUN, json.dumps({"at": at, "summary": summary, "ok": ok}))
