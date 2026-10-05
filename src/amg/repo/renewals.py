"""Inspections and registration: each one logged, and the receipts that show an inspection.

A kind's records come newest first — the latest expiry, then the latest
logged — so the first is the one in force.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..db import now_iso
from ..engine.renewals import KINDS


@dataclass
class RenewalInput:
    kind: str
    expires_on: str
    done_on: str | None = None
    cost_cents: int | None = None
    note: str = ""
    service_event_id: int | None = None


def _check(renewal: RenewalInput) -> None:
    if renewal.kind not in KINDS:
        raise ValueError(f"Unknown kind {renewal.kind!r}.")
    if renewal.done_on is not None and renewal.done_on > renewal.expires_on:
        raise ValueError("It can't expire before it was done.")


def create(conn: sqlite3.Connection, vehicle_id: int, renewal: RenewalInput) -> int:
    _check(renewal)
    now = now_iso()
    cursor = conn.execute(
        "INSERT INTO renewals (vehicle_id, kind, done_on, expires_on, cost_cents, note, service_event_id,"
        " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (vehicle_id, renewal.kind, renewal.done_on, renewal.expires_on, renewal.cost_cents, renewal.note,
         renewal.service_event_id, now, now),
    )
    return cursor.lastrowid  # type: ignore[return-value]


def update(conn: sqlite3.Connection, renewal_id: int, renewal: RenewalInput) -> None:
    """Change what was logged; the car and the kind stay."""
    _check(renewal)
    conn.execute(
        "UPDATE renewals SET done_on = ?, expires_on = ?, cost_cents = ?, note = ?, service_event_id = ?,"
        " updated_at = ? WHERE id = ?",
        (renewal.done_on, renewal.expires_on, renewal.cost_cents, renewal.note, renewal.service_event_id, now_iso(),
         renewal_id),
    )


def get(conn: sqlite3.Connection, renewal_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM renewals WHERE id = ?", (renewal_id,)).fetchone()


def delete(conn: sqlite3.Connection, renewal_id: int) -> None:
    conn.execute("DELETE FROM renewals WHERE id = ?", (renewal_id,))


def for_car(conn: sqlite3.Connection, vehicle_id: int) -> dict[str, list[sqlite3.Row]]:
    """A car's records by kind, newest first; a kind with none is absent."""
    found: dict[str, list[sqlite3.Row]] = {}
    for row in conn.execute(
        "SELECT * FROM renewals WHERE vehicle_id = ? ORDER BY expires_on DESC, id DESC", (vehicle_id,)
    ):
        found.setdefault(row["kind"], []).append(row)
    return found


def latest_service(conn: sqlite3.Connection, vehicle_id: int, code: str) -> dict | None:
    """The car's newest confirmed service covering a service type, with its shop and what its lines for it cost.

    ``cost_cents`` is None when none of those lines has an amount.
    """
    row = conn.execute(
        "SELECT e.id, e.performed_on, e.shop, e.source, sum(li.amount_cents) AS cost_cents"
        "  FROM service_events e"
        "  JOIN line_items li ON li.service_event_id = e.id"
        "  JOIN line_item_services lis ON lis.line_item_id = li.id"
        "  JOIN service_types st ON st.id = lis.service_type_id"
        " WHERE e.vehicle_id = ? AND e.confirmed = 1 AND st.code = ?"
        " GROUP BY e.id ORDER BY e.performed_on DESC, e.id DESC LIMIT 1",
        (vehicle_id, code),
    ).fetchone()
    return dict(row) if row else None


def everything(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every record, car by car, each kind oldest first: for Download your data."""
    return conn.execute(
        "SELECT r.*, v.name AS car_name, e.performed_on AS service_on, e.shop AS service_shop"
        "  FROM renewals r JOIN vehicles v ON v.id = r.vehicle_id"
        "  LEFT JOIN service_events e ON e.id = r.service_event_id"
        " ORDER BY v.name COLLATE NOCASE, v.id,"
        "   CASE r.kind WHEN 'safety' THEN 0 WHEN 'emissions' THEN 1 ELSE 2 END, r.expires_on, r.id"
    ).fetchall()
