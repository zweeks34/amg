"""SQLite access: one connection per unit of work, migrations applied at startup.

Connections run in autocommit mode (Python 3.12's ``autocommit=True``), so
nothing is ever left open inside an implicit transaction; a write that spans
statements says so with ``transaction(conn)``. Every connection turns foreign
keys on — SQLite leaves them off per connection — and waits for a lock rather
than failing, because gunicorn runs more than one worker against the same file.
"""

from __future__ import annotations

import itertools
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import config

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_savepoints = itertools.count()


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    # check_same_thread is off because FastAPI may open the connection in one
    # threadpool thread and run the route in another; a connection still only
    # ever serves one request at a time.
    conn = sqlite3.connect(
        path or config.db_path(),
        autocommit=True,
        timeout=5.0,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block as one write transaction; nested use becomes a savepoint.

    BEGIN IMMEDIATE takes the write lock up front. A deferred transaction that
    reads first and writes later can fail to upgrade its lock when another
    worker got there in between, and waiting does not help it.
    """
    if conn.in_transaction:
        name = f"sp{next(_savepoints)}"
        conn.execute(f"SAVEPOINT {name}")
        try:
            yield conn
        except BaseException:
            conn.execute(f"ROLLBACK TO {name}")
            conn.execute(f"RELEASE {name}")
            raise
        conn.execute(f"RELEASE {name}")
        return

    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def migrations(directory: Path | None = None) -> list[tuple[int, str, str]]:
    """(version, name, sql) for each ``NNNN_name.sql`` file, in version order."""
    found: dict[int, tuple[int, str, str]] = {}
    for path in sorted((directory or MIGRATIONS_DIR).glob("[0-9][0-9][0-9][0-9]_*.sql")):
        version = int(path.name[:4])
        if version in found:
            raise RuntimeError(f"two migrations share version {version}: {found[version][1]}, {path.stem}")
        found[version] = (version, path.stem, path.read_text(encoding="utf-8"))
    return [found[v] for v in sorted(found)]


def migrate(conn: sqlite3.Connection, directory: Path | None = None) -> list[int]:
    """Apply every migration not yet recorded; return the versions applied.

    The whole run holds the write lock, so two workers starting together cannot
    both apply the same migration: the second waits, then finds nothing to do.
    Statements run one at a time inside that transaction — executescript()
    would COMMIT first — so a failing migration leaves the database exactly as
    the run found it, earlier migrations of the same run included.
    """
    conn.execute("PRAGMA journal_mode = WAL")
    applied: list[int] = []
    with transaction(conn):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            " version INTEGER PRIMARY KEY,"
            " name TEXT NOT NULL,"
            " applied_at TEXT NOT NULL)"
        )
        done = {row[0] for row in conn.execute("SELECT version FROM schema_version")}
        for version, name, sql in migrations(directory):
            if version in done:
                continue
            for statement in _statements(sql):
                conn.execute(statement)
            conn.execute(
                "INSERT INTO schema_version (version, name, applied_at) VALUES (?, ?, ?)",
                (version, name, now_iso()),
            )
            applied.append(version)
    return applied


def _statements(sql: str) -> Iterator[str]:
    """Split a migration into statements SQLite can run one at a time.

    sqlite3.complete_statement understands string literals, comments and
    CREATE TRIGGER ... END blocks, so a semicolon in any of those does not end
    a statement early.
    """
    buffer = ""
    for line in sql.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            yield buffer
            buffer = ""
    leftover = "\n".join(
        line for line in buffer.splitlines() if line.strip() and not line.strip().startswith("--")
    )
    if leftover:
        raise ValueError(f"migration ends with an incomplete statement: {leftover[:80]!r}")


def now_iso() -> str:
    """The current UTC time as ISO-8601 with a Z, the format every timestamp column uses."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
