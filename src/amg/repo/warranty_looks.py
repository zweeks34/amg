"""The look through receipts read before AMG kept warranties: which are waiting, the queue, and what it found.

A receipt read since has ``warranties`` in its extraction; one read before
doesn't, and is waiting until it's been looked at. What a look finds goes
into the receipt's draft, each row marked ``found`` with the day, and counts
for nothing until you check it and save the receipt.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field

from ..db import now_iso, transaction
from ..ingest import claude
from ..ingest.claude import Usage
from ..ingest.drafts import phrase
from . import jobs

# What a look costs beyond the pages and prompt it's sent: a short answer, and some thinking at low effort.
OUTPUT_TOKENS = 1_000
# A receipt with no token count from its first reading: about this much a page, prompt included.
TOKENS_A_PAGE = 6_000

_WAITING = (
    "SELECT r.id FROM receipts r LEFT JOIN warranty_looks l ON l.receipt_id = r.id"
    " WHERE r.status = 'confirmed' AND r.extraction_json IS NOT NULL"
    "   AND json_type(r.extraction_json, '$.warranties') IS NULL AND l.receipt_id IS NULL"
    " ORDER BY r.id"
)
_DESCRIBED = (
    "SELECT r.id, r.draft_json, e.performed_on, e.shop, v.name AS car_name, l.error"
    "  FROM receipts r LEFT JOIN service_events e ON e.id = r.service_event_id"
    "  LEFT JOIN vehicles v ON v.id = r.vehicle_id LEFT JOIN warranty_looks l ON l.receipt_id = r.id"
)


@dataclass
class Progress:
    waiting: list[int] = field(default_factory=list)    # receipts never looked at
    failed: list[dict] = field(default_factory=list)    # {id, performed_on, shop, car_name, error}
    found: list[dict] = field(default_factory=list)     # receipts with finds to check: {id, …, count}
    job_id: int | None = None                           # the look running now, if one is
    total: int = 0                                      # in the running look
    done: int = 0
    stalled: bool = False

    @property
    def running(self) -> bool:
        return self.job_id is not None

    def __bool__(self) -> bool:
        return bool(self.waiting or self.failed or self.found or self.running)


def waiting(conn: sqlite3.Connection) -> list[int]:
    return [row[0] for row in conn.execute(_WAITING)]


def failed(conn: sqlite3.Connection) -> list[int]:
    return [row[0] for row in conn.execute("SELECT receipt_id FROM warranty_looks WHERE status = 'failed'"
                                           " ORDER BY receipt_id")]


def estimate(conn: sqlite3.Connection, receipt_ids: Sequence[int]) -> int:
    """About what looking at these costs, in cents: each one's own first reading, as a guide."""
    if not receipt_ids:
        return 0
    per_in, per_out, _ = claude.PRICES.get(claude.model(), claude.PRICES[claude.DEFAULT_MODEL])
    marks = ", ".join("?" * len(receipt_ids))
    spend = sum(     # dollars a million tokens, times tokens
        (row["input_tokens"] or row["page_count"] * TOKENS_A_PAGE) * per_in + OUTPUT_TOKENS * per_out
        for row in conn.execute(
            f"SELECT r.input_tokens, d.page_count FROM receipts r JOIN documents d ON d.id = r.document_id"
            f" WHERE r.id IN ({marks})", list(receipt_ids))
    )
    return round(spend / 1_000_000 * 100)


# ---------- The queue ----------


def queue(conn: sqlite3.Connection, receipt_ids: Sequence[int], job_id: int) -> None:
    now = now_iso()
    conn.executemany(
        "INSERT INTO warranty_looks (receipt_id, job_id, status, created_at, updated_at) VALUES (?, ?, 'queued', ?, ?)"
        " ON CONFLICT (receipt_id) DO UPDATE SET job_id = excluded.job_id, status = 'queued', error = '',"
        " updated_at = excluded.updated_at",
        [(receipt_id, job_id, now, now) for receipt_id in receipt_ids],
    )


def claim_next(conn: sqlite3.Connection, job_id: int) -> int | None:
    """Take the job's next queued receipt; atomic, so two threads never look at the same one."""
    row = conn.execute(
        "UPDATE warranty_looks SET status = 'looking', updated_at = ?"
        " WHERE receipt_id = (SELECT receipt_id FROM warranty_looks WHERE job_id = ? AND status = 'queued'"
        "                      ORDER BY receipt_id LIMIT 1)"
        " RETURNING receipt_id",
        (now_iso(), job_id),
    ).fetchone()
    return row[0] if row else None


def mark_done(conn: sqlite3.Connection, receipt_id: int, found: int, usage: Usage | None) -> None:
    now = now_iso()
    conn.execute(
        "UPDATE warranty_looks SET status = 'done', found = ?, error = '', model = ?, input_tokens = ?,"
        " output_tokens = ?, cost_usd = ?, looked_at = ?, updated_at = ? WHERE receipt_id = ?",
        (found, usage.model if usage else None,
         usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens if usage else None,
         usage.output_tokens if usage else None, usage.cost_usd if usage else None, now, now, receipt_id),
    )


def mark_failed(conn: sqlite3.Connection, receipt_id: int, error: str) -> None:
    conn.execute("UPDATE warranty_looks SET status = 'failed', error = ?, updated_at = ? WHERE receipt_id = ?",
                 (error, now_iso(), receipt_id))


def add_found(conn: sqlite3.Connection, receipt_id: int, rows: Sequence[dict]) -> int:
    """Add a look's finds to the receipt's draft, leaving out any worded as one it has; returns how many."""
    with transaction(conn):
        row = conn.execute("SELECT draft_json FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
        draft = json.loads(row["draft_json"] or "{}")
        held = draft.get("warranties") or []
        have = {phrase(w.get("description") or "") for w in held}
        new = []
        for found in rows:
            key = phrase(found["description"])
            if key not in have:
                have.add(key)
                new.append(found)
        if new:
            draft["warranties"] = held + new
            conn.execute("UPDATE receipts SET draft_json = ?, updated_at = ? WHERE id = ?",
                         (json.dumps(draft), now_iso(), receipt_id))
    return len(new)


# ---------- How it's going ----------


def to_check(conn: sqlite3.Connection, vehicle_id: int | None = None) -> list[dict]:
    """Confirmed receipts holding finds you haven't checked, oldest visit first.

    Each is {id, performed_on, shop, car_name, error, count}.
    """
    where = " AND r.vehicle_id = ?" if vehicle_id is not None else ""
    found = []
    for row in conn.execute(f"{_DESCRIBED} WHERE r.status = 'confirmed'{where} ORDER BY e.performed_on, r.id",
                            (vehicle_id,) if vehicle_id is not None else ()):
        count = sum(1 for w in json.loads(row["draft_json"] or "{}").get("warranties") or [] if w.get("found"))
        if count:
            found.append({**_described(row), "count": count})
    return found


def progress(conn: sqlite3.Connection) -> Progress:
    found = Progress(waiting=waiting(conn), found=to_check(conn))
    found.failed = [_described(row) for row in conn.execute(
        f"{_DESCRIBED} WHERE l.status = 'failed' ORDER BY e.performed_on, r.id")]
    busy = conn.execute(
        "SELECT job_id FROM warranty_looks WHERE status IN ('queued', 'looking') AND job_id IS NOT NULL"
        " ORDER BY job_id DESC LIMIT 1").fetchone()
    if busy:
        job = jobs.get(conn, busy["job_id"])
        counts = conn.execute(
            "SELECT count(*) AS total, sum(status IN ('done', 'failed')) AS done FROM warranty_looks WHERE job_id = ?",
            (busy["job_id"],)).fetchone()
        found.job_id, found.total, found.done = busy["job_id"], counts["total"], counts["done"] or 0
        found.stalled = job is None or jobs.is_stalled(job)
    return found


def _described(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "performed_on": row["performed_on"], "shop": row["shop"], "car_name": row["car_name"],
            "error": row["error"] or ""}
