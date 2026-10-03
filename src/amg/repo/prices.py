"""Prices for the budget: the ones you set, Claude's estimates, and what your receipts show.

A *job* is what a schedule item asks for: its service types and its action.
Prices are kept per car and per job (``price_book``), so they outlive the
schedule items that asked for them. What visits actually cost is read from
the confirmed services' lines (``visits``) and the prices shops quoted for
work they recommended (``quotes``); engine/forecast.py does the arithmetic.
"""

from __future__ import annotations

import json
import sqlite3

from ..db import now_iso, transaction
from ..ingest.claude import Usage
from .services import ACTIONS


def job_codes(codes) -> str:
    """A job's service types as stored: sorted, comma-separated."""
    return ",".join(sorted(set(codes)))


def _check(codes: str, action: str) -> None:
    if not codes:
        raise ValueError("A job needs at least one service type.")
    if action not in ACTIONS:
        raise ValueError(f"Unknown action {action!r}.")


# ---------- Your prices ----------


def set_yours(conn: sqlite3.Connection, vehicle_id: int, codes, action: str, name: str, cents: int) -> None:
    """Set (or change) your price for a job on a car: what one visit costs."""
    codes = job_codes(codes)
    _check(codes, action)
    if cents < 0:
        raise ValueError("A price can't be below zero.")
    now = now_iso()
    conn.execute(
        "INSERT INTO price_book (vehicle_id, codes, action, name, source, low_cents, high_cents, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, 'you', ?, ?, ?, ?)"
        " ON CONFLICT (vehicle_id, codes, action, source) DO UPDATE SET"
        "   name = excluded.name, low_cents = excluded.low_cents, high_cents = excluded.high_cents,"
        "   updated_at = excluded.updated_at",
        (vehicle_id, codes, action, name, cents, cents, now, now),
    )


def remove_yours(conn: sqlite3.Connection, vehicle_id: int, codes, action: str) -> None:
    conn.execute("DELETE FROM price_book WHERE vehicle_id = ? AND codes = ? AND action = ? AND source = 'you'",
                 (vehicle_id, job_codes(codes), action))


def for_car(conn: sqlite3.Connection, vehicle_id: int) -> list[sqlite3.Row]:
    """Every price-book row for a car — yours and Claude's, whatever state Claude's are in."""
    return conn.execute("SELECT * FROM price_book WHERE vehicle_id = ? ORDER BY name, id", (vehicle_id,)).fetchall()


# ---------- Claude's estimates ----------


def queue_claude(conn: sqlite3.Connection, vehicle_id: int, jobs: list[tuple], job_id: int) -> None:
    """Queue jobs — (codes, action, name) — for Claude to price under a background job."""
    now = now_iso()
    with transaction(conn):
        for codes, action, name in jobs:
            codes = job_codes(codes)
            _check(codes, action)
            conn.execute(
                "INSERT INTO price_book (vehicle_id, codes, action, name, source, status, job_id, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, 'claude', 'queued', ?, ?, ?)"
                " ON CONFLICT (vehicle_id, codes, action, source) DO UPDATE SET"
                "   name = excluded.name, status = 'queued', job_id = excluded.job_id, error = '',"
                "   updated_at = excluded.updated_at",
                (vehicle_id, codes, action, name, job_id, now, now),
            )


def claim(conn: sqlite3.Connection, job_id: int) -> list[sqlite3.Row]:
    """Take every queued row of a job at once: Claude prices a car's jobs in one call."""
    return conn.execute(
        "UPDATE price_book SET status = 'asking', updated_at = ? WHERE job_id = ? AND status = 'queued'"
        " RETURNING *",
        (now_iso(), job_id),
    ).fetchall()


def mark_priced(conn: sqlite3.Connection, row_id: int, low_cents: int, high_cents: int, note: str,
                usage: Usage, share: int = 1) -> None:
    """Store Claude's range; the call's cost is split across the ``share`` jobs it priced."""
    cost = None if usage.cost_usd is None else usage.cost_usd / max(share, 1)
    conn.execute(
        "UPDATE price_book SET status = 'done', low_cents = ?, high_cents = ?, note = ?, error = '', model = ?,"
        " cost_usd = ?, updated_at = ? WHERE id = ?",
        (low_cents, high_cents, note, usage.model, cost, now_iso(), row_id),
    )


def mark_failed(conn: sqlite3.Connection, row_id: int, error: str) -> None:
    conn.execute("UPDATE price_book SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                 (error, now_iso(), row_id))


# ---------- What your receipts show ----------


def visits(conn: sqlite3.Connection) -> list[dict]:
    """Every confirmed visit, all cars, oldest first: its tax and its lines, each with what it covered.

    A line's ``covers`` is {code: action}. Visits with no lines (marked done
    with no receipt) are left out: they say the work was done, not what it cost.
    """
    found: dict[int, dict] = {}
    lines: dict[int, dict] = {}
    for row in conn.execute(
        "SELECT e.id, e.vehicle_id, e.performed_on, e.tax_cents, li.id AS line_id, li.kind, li.amount_cents,"
        "       st.code, lis.action"
        "  FROM service_events e"
        "  JOIN line_items li ON li.service_event_id = e.id"
        "  LEFT JOIN line_item_services lis ON lis.line_item_id = li.id"
        "  LEFT JOIN service_types st ON st.id = lis.service_type_id"
        " WHERE e.confirmed = 1"
        " ORDER BY e.performed_on, e.id, li.position",
    ):
        visit = found.setdefault(row["id"], {
            "id": row["id"], "vehicle_id": row["vehicle_id"], "performed_on": row["performed_on"],
            "tax_cents": row["tax_cents"], "lines": [],
        })
        line = lines.get(row["line_id"])
        if line is None:
            line = lines[row["line_id"]] = {"kind": row["kind"], "amount_cents": row["amount_cents"], "covers": {}}
            visit["lines"].append(line)
        if row["code"]:
            line["covers"][row["code"]] = row["action"]
    return list(found.values())


def quotes(conn: sqlite3.Connection, vehicle_id: int) -> list[dict]:
    """Prices shops quoted for work they recommended, from a car's confirmed receipts, oldest first.

    Each is {day, codes, cents, description}; a recommendation with no price or
    no service types prices nothing and is left out.
    """
    found = []
    for row in conn.execute(
        "SELECT e.performed_on, r.draft_json FROM receipts r JOIN service_events e ON e.id = r.service_event_id"
        " WHERE r.status = 'confirmed' AND e.confirmed = 1 AND e.vehicle_id = ?"
        " ORDER BY e.performed_on, e.id",
        (vehicle_id,),
    ):
        draft = json.loads(row["draft_json"] or "{}")
        for rec in draft.get("recommendations") or []:
            cents, codes = rec.get("quoted_cents"), rec.get("codes") or []
            if cents and cents > 0 and codes:
                found.append({"day": row["performed_on"], "codes": list(codes), "cents": cents,
                              "description": rec.get("description", "")})
    return found
