"""Specs cards: each car's values, the receipt lines that suggest them, and Claude's readings of them.

A reading runs queued → reading → read → used, with failed and discarded to
the side, as a schedule draft does. Using one replaces the car's specs with
what was checked on the review, in the same transaction.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from ..db import now_iso, transaction
from ..engine.specs import CUSTOM, FIELDS
from ..ingest.claude import Usage
from . import jobs

SOURCES = ("you", "read")


@dataclass
class SpecInput:
    key: str                         # a catalogue key, or CUSTOM
    value: str
    label: str = ""                  # a custom line's name
    source: str = "you"
    document_id: int | None = None   # source read: the file it was read from
    page: int | None = None


def values(conn: sqlite3.Connection, vehicle_id: int) -> list[dict]:
    """A car's specs in card order, each with the file it was read from (filename, sha256), if any."""
    rows = conn.execute(
        "SELECT s.*, d.filename, d.sha256, d.page_count FROM vehicle_specs s"
        "  LEFT JOIN documents d ON d.id = s.document_id"
        " WHERE s.vehicle_id = ? ORDER BY s.position, s.id",
        (vehicle_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def save(conn: sqlite3.Connection, vehicle_id: int, specs: Sequence[SpecInput]) -> None:
    """Replace a car's specs with these, in this order."""
    seen: set[str] = set()
    for spec in specs:
        if spec.key != CUSTOM and spec.key not in FIELDS:
            raise ValueError(f"No spec is called {spec.key!r}.")
        if spec.key != CUSTOM and spec.key in seen:
            raise ValueError(f"{spec.key!r} is given twice.")
        if not spec.value.strip() or (spec.key == CUSTOM and not spec.label.strip()):
            raise ValueError("A spec needs a value, and a line of your own a name.")
        if spec.source not in SOURCES:
            raise ValueError(f"Unknown source {spec.source!r}.")
        seen.add(spec.key)
    now = now_iso()
    with transaction(conn):
        conn.execute("DELETE FROM vehicle_specs WHERE vehicle_id = ?", (vehicle_id,))
        for position, spec in enumerate(specs):
            conn.execute(
                "INSERT INTO vehicle_specs (vehicle_id, key, label, value, source, document_id, page, position,"
                " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (vehicle_id, spec.key, spec.label.strip() if spec.key == CUSTOM else "", spec.value.strip(),
                 spec.source, spec.document_id if spec.source == "read" else None,
                 spec.page if spec.source == "read" else None, position, now),
            )


def fitted_lines(conn: sqlite3.Connection, vehicle_id: int, codes: Sequence[str]) -> list[dict]:
    """Lines of the car's confirmed services that replaced one of these service types, newest visit first.

    A line covering two of them comes once for each, with its ``code``.
    """
    if not codes:
        return []
    marks = ", ".join("?" * len(codes))
    rows = conn.execute(
        "SELECT st.code, e.id AS event_id, e.performed_on, e.shop, e.source, li.id AS line_id, li.description,"
        "       li.part_number, li.quantity, li.kind"
        "  FROM line_items li"
        "  JOIN line_item_services lis ON lis.line_item_id = li.id"
        "  JOIN service_types st ON st.id = lis.service_type_id"
        "  JOIN service_events e ON e.id = li.service_event_id"
        f" WHERE e.vehicle_id = ? AND e.confirmed = 1 AND lis.action = 'replace' AND st.code IN ({marks})"
        " ORDER BY e.performed_on DESC, e.id DESC, li.position",
        (vehicle_id, *codes),
    ).fetchall()
    return [dict(row) for row in rows]


def everything(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every car's specs, for Download your data."""
    return conn.execute(
        "SELECT s.*, v.name AS car, d.filename FROM vehicle_specs s"
        "  JOIN vehicles v ON v.id = s.vehicle_id"
        "  LEFT JOIN documents d ON d.id = s.document_id"
        " ORDER BY v.name, v.id, s.position, s.id"
    ).fetchall()


# ---------- Readings ----------


def create_read(conn: sqlite3.Connection, vehicle_id: int, document_id: int, requested_pages: str, job_id: int) -> int:
    now = now_iso()
    cursor = conn.execute(
        "INSERT INTO spec_reads (vehicle_id, document_id, requested_pages, job_id, status, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, 'queued', ?, ?)",
        (vehicle_id, document_id, requested_pages, job_id, now, now),
    )
    return cursor.lastrowid  # type: ignore[return-value]


def claim_next(conn: sqlite3.Connection, job_id: int) -> int | None:
    row = conn.execute(
        "UPDATE spec_reads SET status = 'reading', updated_at = ?"
        " WHERE id = (SELECT id FROM spec_reads WHERE job_id = ? AND status = 'queued' ORDER BY id LIMIT 1)"
        " RETURNING id",
        (now_iso(), job_id),
    ).fetchone()
    return row[0] if row else None


def mark_read(conn: sqlite3.Connection, read_id: int, extraction: dict, values: dict, warnings: list[str],
              pages: list[int], usage: Usage) -> None:
    now = now_iso()
    conn.execute(
        "UPDATE spec_reads SET status = 'read', extraction_json = ?, values_json = ?, warnings_json = ?, pages_json = ?,"
        " error = '', model = ?, input_tokens = ?, output_tokens = ?, cost_usd = ?, read_seconds = ?, request_id = ?,"
        " read_at = ?, updated_at = ? WHERE id = ?",
        (
            json.dumps(extraction), json.dumps(values), json.dumps(warnings), json.dumps(pages), usage.model,
            usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens, usage.output_tokens,
            usage.cost_usd, usage.seconds, usage.request_id, now, now, read_id,
        ),
    )


def mark_failed(conn: sqlite3.Connection, read_id: int, error: str) -> None:
    conn.execute("UPDATE spec_reads SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                 (error, now_iso(), read_id))


def requeue(conn: sqlite3.Connection, read_id: int, job_id: int, requested_pages: str | None = None) -> None:
    """Read again — after a failure, or with other pages."""
    conn.execute(
        "UPDATE spec_reads SET status = 'queued', job_id = ?, error = '', updated_at = ?,"
        " requested_pages = coalesce(?, requested_pages) WHERE id = ? AND status IN ('read', 'failed')",
        (job_id, now_iso(), requested_pages, read_id),
    )


def get_read(conn: sqlite3.Connection, read_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM spec_reads WHERE id = ?", (read_id,)).fetchone()
    if row is None:
        return None
    read = dict(row)
    document = None
    if row["document_id"]:
        document = conn.execute("SELECT * FROM documents WHERE id = ?", (row["document_id"],)).fetchone()
    read["document"] = dict(document) if document else None
    read["vehicle"] = dict(conn.execute("SELECT * FROM vehicles WHERE id = ?", (row["vehicle_id"],)).fetchone())
    read["extraction"] = json.loads(row["extraction_json"]) if row["extraction_json"] else None
    read["values"] = json.loads(row["values_json"]) if row["values_json"] else {}
    read["warnings"] = json.loads(row["warnings_json"] or "[]")
    read["pages"] = json.loads(row["pages_json"] or "[]")
    job = jobs.get(conn, row["job_id"]) if row["job_id"] else None
    read["stalled"] = bool(row["status"] in ("queued", "reading") and (job is None or jobs.is_stalled(job)))
    return read


def open_reads(conn: sqlite3.Connection, vehicle_id: int) -> list[dict]:
    """Readings still going, waiting to be checked, or failed, newest first."""
    rows = conn.execute(
        "SELECT r.id, r.status, r.created_at, r.error, d.filename FROM spec_reads r"
        "  LEFT JOIN documents d ON d.id = r.document_id"
        " WHERE r.vehicle_id = ? AND r.status IN ('queued', 'reading', 'read', 'failed') ORDER BY r.id DESC",
        (vehicle_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def use_read(conn: sqlite3.Connection, read_id: int, vehicle_id: int, specs: Sequence[SpecInput]) -> None:
    """The checked reading becomes the car's specs."""
    with transaction(conn):
        save(conn, vehicle_id, specs)
        now = now_iso()
        conn.execute("UPDATE spec_reads SET status = 'used', used_at = ?, updated_at = ? WHERE id = ?",
                     (now, now, read_id))


def discard(conn: sqlite3.Connection, read_id: int) -> None:
    conn.execute("UPDATE spec_reads SET status = 'discarded', updated_at = ? WHERE id = ? AND status IN ('read', 'failed')",
                 (now_iso(), read_id))


def car_files(conn: sqlite3.Connection, vehicle_id: int) -> list[dict]:
    """Files AMG already has for a car that could hold its specs: the ones its schedules and specs were read from."""
    rows = conn.execute(
        "SELECT d.id, d.filename, d.page_count FROM documents d WHERE d.id IN ("
        "  SELECT document_id FROM schedule_drafts WHERE vehicle_id = ? AND origin = 'manual'"
        "  UNION SELECT document_id FROM spec_reads WHERE vehicle_id = ?"
        ") ORDER BY d.page_count DESC, d.id DESC",
        (vehicle_id, vehicle_id),
    ).fetchall()
    return [dict(row) for row in rows]
