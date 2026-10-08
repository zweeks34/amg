"""Issues: what you've noticed wrong with each car, their photos, and the visits that didn't fix them.

Which visit to ask about is the engine's call (engine/issues.py); the
answers are stored here. A check is a visit you said it was still there
after; a fix may name the service that did it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from ..db import now_iso, transaction
from ..engine.issues import Visit

STATUSES = ("open", "fixed", "dropped")
MAX_PHOTOS = 10


@dataclass
class IssueInput:
    title: str
    details: str
    noticed_on: str


_SELECT = (
    "SELECT i.*, e.performed_on AS fixed_service_on, e.shop AS fixed_shop"
    "  FROM issues i LEFT JOIN service_events e ON e.id = i.fixed_by_event_id"
)


# ---------- Writing one ----------


def create(conn: sqlite3.Connection, vehicle_id: int, issue: IssueInput, photo_ids: Sequence[int] = ()) -> int:
    now = now_iso()
    with transaction(conn):
        cursor = conn.execute(
            "INSERT INTO issues (vehicle_id, title, details, noticed_on, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (vehicle_id, issue.title.strip(), issue.details.strip(), issue.noticed_on, now, now),
        )
        issue_id = cursor.lastrowid
        _set_photos(conn, issue_id, photo_ids)  # type: ignore[arg-type]
    return issue_id  # type: ignore[return-value]


def update(conn: sqlite3.Connection, issue_id: int, issue: IssueInput, photo_ids: Sequence[int]) -> None:
    """Change what it says, and replace its photos with these, in this order."""
    with transaction(conn):
        conn.execute(
            "UPDATE issues SET title = ?, details = ?, noticed_on = ?, updated_at = ? WHERE id = ?",
            (issue.title.strip(), issue.details.strip(), issue.noticed_on, now_iso(), issue_id),
        )
        _set_photos(conn, issue_id, photo_ids)


def delete(conn: sqlite3.Connection, issue_id: int) -> None:
    """The issue, its photos' places on it and its checks. The photo files stay, as discarded receipts' do."""
    conn.execute("DELETE FROM issues WHERE id = ?", (issue_id,))


def _set_photos(conn: sqlite3.Connection, issue_id: int, photo_ids: Sequence[int]) -> None:
    ids = list(dict.fromkeys(photo_ids))
    if len(ids) > MAX_PHOTOS:
        raise ValueError(f"An issue holds up to {MAX_PHOTOS} photos.")
    conn.execute("DELETE FROM issue_photos WHERE issue_id = ?", (issue_id,))
    conn.executemany("INSERT INTO issue_photos (issue_id, document_id, position) VALUES (?, ?, ?)",
                     [(issue_id, document_id, position) for position, document_id in enumerate(ids)])


# ---------- Reading them ----------


def get(conn: sqlite3.Connection, issue_id: int) -> dict | None:
    row = conn.execute(f"{_SELECT} WHERE i.id = ?", (issue_id,)).fetchone()
    return _complete(conn, [row])[0] if row else None


def for_car(conn: sqlite3.Connection, vehicle_id: int) -> list[dict]:
    """A car's issues: open ones first, newest noticed first; then the closed ones, latest closed first.

    Each has its ``photos`` (document rows) and ``checks`` (the visits you said
    it was still there after, oldest first).
    """
    rows = conn.execute(
        f"{_SELECT} WHERE i.vehicle_id = ?"
        " ORDER BY i.status != 'open', COALESCE(i.closed_on, i.noticed_on) DESC, i.id DESC",
        (vehicle_id,),
    ).fetchall()
    return _complete(conn, rows)


def fixed_by(conn: sqlite3.Connection, event_id: int) -> list[dict]:
    """The issues a service fixed."""
    rows = conn.execute(f"{_SELECT} WHERE i.fixed_by_event_id = ? ORDER BY i.noticed_on, i.id", (event_id,))
    return _complete(conn, rows.fetchall())


def open_counts(conn: sqlite3.Connection) -> dict[int, int]:
    """Open issues per car, for the garage."""
    return {row["vehicle_id"]: row["n"] for row in conn.execute(
        "SELECT vehicle_id, count(*) AS n FROM issues WHERE status = 'open' GROUP BY vehicle_id")}


def visits(conn: sqlite3.Connection, vehicle_id: int) -> list[Visit]:
    """The car's confirmed services, newest first, leaving out those marked done with no receipt: not visits."""
    return [
        Visit(row["id"], date.fromisoformat(row["performed_on"]), row["shop"])
        for row in conn.execute(
            "SELECT id, performed_on, shop FROM service_events"
            " WHERE vehicle_id = ? AND confirmed = 1 AND source != 'attested'"
            " ORDER BY performed_on DESC, id DESC",
            (vehicle_id,),
        )
    ]


def _complete(conn: sqlite3.Connection, rows: Sequence[sqlite3.Row]) -> list[dict]:
    issues = [dict(row) for row in rows]
    if not issues:
        return []
    ids = [issue["id"] for issue in issues]
    marks = ", ".join("?" * len(ids))
    photos: dict[int, list[dict]] = {}
    for row in conn.execute(
        f"SELECT p.issue_id, d.* FROM issue_photos p JOIN documents d ON d.id = p.document_id"
        f" WHERE p.issue_id IN ({marks}) ORDER BY p.position",
        ids,
    ):
        photos.setdefault(row["issue_id"], []).append(dict(row))
    checks: dict[int, list[dict]] = {}
    for row in conn.execute(
        f"SELECT c.issue_id, e.id AS event_id, e.performed_on, e.shop FROM issue_checks c"
        f"  JOIN service_events e ON e.id = c.event_id"
        f" WHERE c.issue_id IN ({marks}) ORDER BY e.performed_on, e.id",
        ids,
    ):
        checks.setdefault(row["issue_id"], []).append(dict(row))
    for issue in issues:
        issue["photos"] = photos.get(issue["id"], [])
        issue["checks"] = checks.get(issue["id"], [])
    return issues


# ---------- Closing them ----------


def fix(conn: sqlite3.Connection, issue_id: int, day: str, event_id: int | None = None) -> None:
    """Fixed on ``day``, by that service if you said which. A visit can't be both the fix and one that missed it."""
    with transaction(conn):
        conn.execute(
            "UPDATE issues SET status = 'fixed', closed_on = ?, fixed_by_event_id = ?, updated_at = ? WHERE id = ?",
            (day, event_id, now_iso(), issue_id),
        )
        if event_id is not None:
            conn.execute("DELETE FROM issue_checks WHERE issue_id = ? AND event_id = ?", (issue_id, event_id))


def drop(conn: sqlite3.Connection, issue_id: int, day: str) -> None:
    """It went away, or you'll live with it."""
    conn.execute(
        "UPDATE issues SET status = 'dropped', closed_on = ?, fixed_by_event_id = NULL, updated_at = ? WHERE id = ?",
        (day, now_iso(), issue_id),
    )


def reopen(conn: sqlite3.Connection, issue_id: int) -> None:
    conn.execute(
        "UPDATE issues SET status = 'open', closed_on = NULL, fixed_by_event_id = NULL, updated_at = ? WHERE id = ?",
        (now_iso(), issue_id),
    )


def still_there(conn: sqlite3.Connection, issue_id: int, event_id: int) -> None:
    """You said a visit didn't fix it."""
    conn.execute("INSERT OR IGNORE INTO issue_checks (issue_id, event_id, created_at) VALUES (?, ?, ?)",
                 (issue_id, event_id, now_iso()))


# ---------- The export ----------


def everything(conn: sqlite3.Connection) -> list[dict]:
    """Every issue on every car, each with its photos and checks, for the data export."""
    rows = conn.execute(
        "SELECT i.*, v.name AS car_name, e.performed_on AS fixed_service_on, e.shop AS fixed_shop"
        "  FROM issues i JOIN vehicles v ON v.id = i.vehicle_id"
        "  LEFT JOIN service_events e ON e.id = i.fixed_by_event_id"
        " ORDER BY v.archived_at IS NOT NULL, v.name COLLATE NOCASE, v.id, i.noticed_on, i.id"
    ).fetchall()
    return _complete(conn, rows)
