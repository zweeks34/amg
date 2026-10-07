"""Schedules: drafts on their way to being used, and each car's own schedule.

A draft runs queued → reading → read → confirmed, with failed and discarded to
the side — the same life as a receipt. Templates and copies start at read:
there's nothing to wait for. Using a draft replaces the car's schedule items
with the draft's; after that the items are edited in place, and keep their
ids, so anything that refers to an item (the alert log, later) still finds it.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from ..db import now_iso, transaction
from ..ingest.claude import Usage
from . import jobs

APPLIES = ("always", "normal", "severe")
SOURCES = ("manual", "claude", "template", "you")


@dataclass
class ItemInput:
    name: str
    action: str
    codes: list[str] = field(default_factory=list)
    interval_miles: int | None = None
    interval_months: int | None = None
    first_miles: int | None = None
    first_months: int | None = None
    applies: str = "always"
    note: str = ""
    source: str = "you"
    document_id: int | None = None
    page: int | None = None
    counts_from: str | None = None   # ISO date its count starts on; None counts from new
    id: int | None = None    # an existing item, when saving an edited schedule


# ---------- Drafts ----------


def create_draft(
    conn: sqlite3.Connection,
    vehicle_id: int,
    origin: str,
    document_id: int | None = None,
    requested_pages: str = "",
    job_id: int | None = None,
    draft: dict | None = None,
) -> int:
    """A draft waiting to be read (``job_id``), or one ready to check (``draft``)."""
    now = now_iso()
    cursor = conn.execute(
        "INSERT INTO schedule_drafts (vehicle_id, origin, document_id, requested_pages, job_id, status, draft_json,"
        " created_at, updated_at, read_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (vehicle_id, origin, document_id, requested_pages, job_id, "queued" if draft is None else "read",
         None if draft is None else json.dumps(draft), now, now, None if draft is None else now),
    )
    return cursor.lastrowid  # type: ignore[return-value]


def claim_next(conn: sqlite3.Connection, job_id: int) -> int | None:
    row = conn.execute(
        "UPDATE schedule_drafts SET status = 'reading', updated_at = ?"
        " WHERE id = (SELECT id FROM schedule_drafts WHERE job_id = ? AND status = 'queued' ORDER BY id LIMIT 1)"
        " RETURNING id",
        (now_iso(), job_id),
    ).fetchone()
    return row[0] if row else None


def mark_read(
    conn: sqlite3.Connection,
    draft_id: int,
    extraction: dict,
    draft: dict,
    warnings: list[str],
    pages: list[int],
    usage: Usage,
) -> None:
    now = now_iso()
    conn.execute(
        "UPDATE schedule_drafts SET status = 'read', extraction_json = ?, draft_json = ?, warnings_json = ?,"
        " pages_json = ?, error = '', model = ?, input_tokens = ?, output_tokens = ?, cost_usd = ?, read_seconds = ?,"
        " request_id = ?, read_at = ?, updated_at = ? WHERE id = ?",
        (
            json.dumps(extraction), json.dumps(draft), json.dumps(warnings), json.dumps(pages), usage.model,
            usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens, usage.output_tokens,
            usage.cost_usd, usage.seconds, usage.request_id, now, now, draft_id,
        ),
    )


def mark_failed(conn: sqlite3.Connection, draft_id: int, error: str) -> None:
    conn.execute("UPDATE schedule_drafts SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                 (error, now_iso(), draft_id))


def requeue(conn: sqlite3.Connection, draft_id: int, job_id: int, requested_pages: str | None = None) -> None:
    """Read again — after a failure, to start over, or with other pages."""
    conn.execute(
        "UPDATE schedule_drafts SET status = 'queued', job_id = ?, error = '', updated_at = ?,"
        " requested_pages = coalesce(?, requested_pages)"
        " WHERE id = ? AND status IN ('read', 'failed') AND origin IN ('manual', 'claude')",
        (job_id, now_iso(), requested_pages, draft_id),
    )


def get_draft(conn: sqlite3.Connection, draft_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM schedule_drafts WHERE id = ?", (draft_id,)).fetchone()
    if row is None:
        return None
    draft = dict(row)
    document = conn.execute("SELECT * FROM documents WHERE id = ?", (row["document_id"],)).fetchone() if row["document_id"] else None
    draft["document"] = dict(document) if document else None
    draft["vehicle"] = dict(conn.execute("SELECT * FROM vehicles WHERE id = ?", (row["vehicle_id"],)).fetchone())
    draft["extraction"] = json.loads(row["extraction_json"]) if row["extraction_json"] else None
    draft["draft"] = json.loads(row["draft_json"]) if row["draft_json"] else None
    draft["warnings"] = json.loads(row["warnings_json"] or "[]")
    draft["pages"] = json.loads(row["pages_json"] or "[]")
    job = jobs.get(conn, row["job_id"]) if row["job_id"] else None
    draft["stalled"] = bool(row["status"] in ("queued", "reading") and (job is None or jobs.is_stalled(job)))
    return draft


def open_drafts(conn: sqlite3.Connection, vehicle_id: int) -> list[dict]:
    """Drafts still being read or waiting to be checked, newest first."""
    rows = conn.execute(
        "SELECT s.id, s.origin, s.status, s.created_at, s.error, d.filename FROM schedule_drafts s"
        "  LEFT JOIN documents d ON d.id = s.document_id"
        " WHERE s.vehicle_id = ? AND s.status IN ('queued', 'reading', 'read', 'failed') ORDER BY s.id DESC",
        (vehicle_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def save_draft(conn: sqlite3.Connection, draft_id: int, draft: dict) -> None:
    conn.execute("UPDATE schedule_drafts SET draft_json = ?, updated_at = ? WHERE id = ?",
                 (json.dumps(draft), now_iso(), draft_id))


def discard(conn: sqlite3.Connection, draft_id: int) -> None:
    conn.execute("UPDATE schedule_drafts SET status = 'discarded', updated_at = ? WHERE id = ? AND status IN ('read', 'failed')",
                 (now_iso(), draft_id))


def restore(conn: sqlite3.Connection, draft_id: int) -> None:
    conn.execute(
        "UPDATE schedule_drafts SET status = CASE WHEN draft_json IS NULL THEN 'failed' ELSE 'read' END, updated_at = ?"
        " WHERE id = ? AND status = 'discarded'",
        (now_iso(), draft_id),
    )


# ---------- The schedule ----------


def items(conn: sqlite3.Connection, vehicle_id: int) -> list[dict]:
    """The car's schedule in order, each item with its service codes and the category it's shown under."""
    rows = conn.execute(
        "SELECT i.*, d.sha256 AS document_sha FROM schedule_items i LEFT JOIN documents d ON d.id = i.document_id"
        " WHERE i.vehicle_id = ? ORDER BY i.position, i.id",
        (vehicle_id,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        types = conn.execute(
            "SELECT t.code, t.name, t.category, t.sort FROM schedule_item_services s"
            "  JOIN service_types t ON t.id = s.service_type_id"
            " WHERE s.schedule_item_id = ? ORDER BY t.sort, t.name",
            (row["id"],),
        ).fetchall()
        item["codes"] = [t["code"] for t in types]
        item["type_names"] = [t["name"] for t in types]
        item["category"] = types[0]["category"] if types else "Inspections and other"
        item["category_sort"] = types[0]["sort"] // 100 if types else 9
        result.append(item)
    return result


def confirm(conn: sqlite3.Connection, draft_id: int, vehicle_id: int, new_items: list[ItemInput], draft: dict) -> None:
    """Use a draft: it becomes the car's whole schedule, replacing whatever was there."""
    with transaction(conn):
        conn.execute("DELETE FROM schedule_items WHERE vehicle_id = ?", (vehicle_id,))
        for position, item in enumerate(new_items):
            _insert(conn, vehicle_id, position, item, draft_id)
        now = now_iso()
        conn.execute(
            "UPDATE schedule_drafts SET status = 'confirmed', draft_json = ?, confirmed_at = ?, updated_at = ? WHERE id = ?",
            (json.dumps(draft), now, now, draft_id),
        )


def save_items(conn: sqlite3.Connection, vehicle_id: int, new_items: list[ItemInput]) -> None:
    """Save an edited schedule: items with an id are updated, new ones added, missing ones removed."""
    with transaction(conn):
        existing = {row[0] for row in conn.execute("SELECT id FROM schedule_items WHERE vehicle_id = ?", (vehicle_id,))}
        kept: set[int] = set()
        for position, item in enumerate(new_items):
            if item.id in existing:
                conn.execute(
                    "UPDATE schedule_items SET position = ?, name = ?, action = ?, interval_miles = ?, interval_months = ?,"
                    " first_miles = ?, first_months = ?, applies = ?, note = ?, source = ?, document_id = ?, page = ?,"
                    " counts_from = ?, updated_at = ? WHERE id = ?",
                    (position, *_values(item), now_iso(), item.id),
                )
                _set_codes(conn, item.id, item.codes)  # type: ignore[arg-type]
                kept.add(item.id)  # type: ignore[arg-type]
            else:
                _insert(conn, vehicle_id, position, item, None)
        for item_id in existing - kept:
            conn.execute("DELETE FROM schedule_items WHERE id = ?", (item_id,))


def set_severe(conn: sqlite3.Connection, vehicle_id: int, severe: bool) -> None:
    conn.execute("UPDATE vehicles SET severe_service = ?, updated_at = ? WHERE id = ?", (int(severe), now_iso(), vehicle_id))


def current_draft(conn: sqlite3.Connection, vehicle_id: int) -> dict | None:
    """The draft the car's schedule was last made from: its origin, document and severe conditions."""
    row = conn.execute(
        "SELECT s.*, d.filename FROM schedule_drafts s LEFT JOIN documents d ON d.id = s.document_id"
        " WHERE s.vehicle_id = ? AND s.status = 'confirmed' ORDER BY s.confirmed_at DESC, s.id DESC LIMIT 1",
        (vehicle_id,),
    ).fetchone()
    if row is None:
        return None
    draft = dict(row)
    draft["draft"] = json.loads(row["draft_json"]) if row["draft_json"] else {}
    return draft


def count(conn: sqlite3.Connection, vehicle_id: int) -> int:
    return conn.execute("SELECT count(*) FROM schedule_items WHERE vehicle_id = ?", (vehicle_id,)).fetchone()[0]


def cars_with_schedules(conn: sqlite3.Connection, exclude: int | None = None) -> list[dict]:
    """Cars whose schedule could be copied: id, name and how many items."""
    rows = conn.execute(
        "SELECT v.id, v.name, count(i.id) AS items FROM vehicles v JOIN schedule_items i ON i.vehicle_id = v.id"
        " WHERE v.id != ? GROUP BY v.id ORDER BY v.name COLLATE NOCASE",
        (exclude or 0,),
    ).fetchall()
    return [dict(row) for row in rows]


def _values(item: ItemInput) -> tuple:
    return (item.name, item.action, item.interval_miles, item.interval_months, item.first_miles, item.first_months,
            item.applies, item.note, item.source, item.document_id, item.page, item.counts_from)


def _insert(conn: sqlite3.Connection, vehicle_id: int, position: int, item: ItemInput, draft_id: int | None) -> int:
    now = now_iso()
    cursor = conn.execute(
        "INSERT INTO schedule_items (vehicle_id, position, name, action, interval_miles, interval_months, first_miles,"
        " first_months, applies, note, source, document_id, page, counts_from, draft_id, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (vehicle_id, position, *_values(item), draft_id, now, now),
    )
    item_id: int = cursor.lastrowid  # type: ignore[assignment]
    _set_codes(conn, item_id, item.codes)
    return item_id


def _set_codes(conn: sqlite3.Connection, item_id: int, codes: list[str]) -> None:
    conn.execute("DELETE FROM schedule_item_services WHERE schedule_item_id = ?", (item_id,))
    for code in dict.fromkeys(codes):
        type_id = conn.execute("SELECT id FROM service_types WHERE code = ?", (code,)).fetchone()
        if type_id is None:
            raise ValueError(f"Unknown service type {code!r}.")
        conn.execute("INSERT INTO schedule_item_services (schedule_item_id, service_type_id) VALUES (?, ?)",
                     (item_id, type_id[0]))
