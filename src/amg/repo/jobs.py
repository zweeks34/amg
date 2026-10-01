"""Background jobs: a batch of work done by a thread, and how to tell it died.

The thread lives in whichever gunicorn worker took the upload, so a restart or
a deploy kills it mid-batch. Nothing is lost — each receipt is saved as it's
read — but the job's heartbeat stops, and a job that has been quiet longer
than any one read could take is shown as stalled, with a way to carry on.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from ..db import now_iso

# One read is at most three attempts of a three-minute timeout; ten minutes of
# silence means the thread is gone.
STALL_SECONDS = 600


def create(conn: sqlite3.Connection, kind: str) -> int:
    now = now_iso()
    cursor = conn.execute(
        "INSERT INTO jobs (kind, status, started_at, heartbeat_at) VALUES (?, 'running', ?, ?)", (kind, now, now)
    )
    return cursor.lastrowid  # type: ignore[return-value]


def get(conn: sqlite3.Connection, job_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def heartbeat(conn: sqlite3.Connection, job_id: int) -> None:
    conn.execute("UPDATE jobs SET heartbeat_at = ? WHERE id = ?", (now_iso(), job_id))


def finish(conn: sqlite3.Connection, job_id: int) -> None:
    now = now_iso()
    conn.execute("UPDATE jobs SET status = 'done', heartbeat_at = ?, finished_at = ? WHERE id = ?", (now, now, job_id))


def is_stalled(job: sqlite3.Row | dict, now: datetime | None = None) -> bool:
    if job["status"] != "running":
        return False
    beat = datetime.strptime(job["heartbeat_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - beat).total_seconds() > STALL_SECONDS


def resume(conn: sqlite3.Connection, job_id: int) -> None:
    """Put a stalled job's half-read receipt back in the queue and mark it alive."""
    conn.execute("UPDATE receipts SET status = 'queued', updated_at = ? WHERE job_id = ? AND status = 'reading'",
                 (now_iso(), job_id))
    conn.execute("UPDATE jobs SET status = 'running', heartbeat_at = ?, finished_at = NULL WHERE id = ?",
                 (now_iso(), job_id))
