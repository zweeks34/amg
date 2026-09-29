"""FastAPI dependencies shared by the route modules."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

from .. import db


def get_conn() -> Iterator[sqlite3.Connection]:
    """One database connection per request, closed when the response is done."""
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()
