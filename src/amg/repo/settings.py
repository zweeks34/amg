"""Key/value settings stored in the ``settings`` table."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from ..db import now_iso


def get(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def put(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
        " ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, value, now_iso()),
    )


def get_or_create(conn: sqlite3.Connection, key: str, make: Callable[[], str]) -> str:
    """The stored value, or ``make()`` stored and returned if there is none yet.

    INSERT OR IGNORE then SELECT, so two workers racing to create the same
    value both end up reading whichever one landed first.
    """
    conn.execute(
        "INSERT OR IGNORE INTO settings (key, value, updated_at) VALUES (?, ?, ?)",
        (key, make(), now_iso()),
    )
    return get(conn, key)  # type: ignore[return-value]
