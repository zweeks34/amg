"""Service events, their line items, and the service-type catalogue.

A service event is one visit; its line items are what the invoice lists; each
line item *covers* zero or more service types, with an action. Coverage is
what the gap engine reads — line items without any are kept (a car wash, a
shop-supplies fee) but count towards no schedule item.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field

from ..db import now_iso, transaction

ACTIONS = ("replace", "inspect", "perform")
KINDS = ("labor", "part", "fee", "other")
SOURCES = ("diy", "shop", "receipt", "attested")


@dataclass
class Coverage:
    code: str
    action: str


@dataclass
class LineInput:
    description: str
    kind: str = "other"
    part_number: str = ""
    quantity: float | None = None
    amount_cents: int | None = None
    covers: list[Coverage] = field(default_factory=list)


@dataclass
class EventInput:
    performed_on: str
    source: str
    odometer: int | None = None
    shop: str = ""
    invoice_number: str = ""
    tax_cents: int | None = None
    total_cents: int | None = None
    notes: str = ""
    lines: list[LineInput] = field(default_factory=list)


# ---------- Service types ----------


def list_types(conn: sqlite3.Connection, powertrain: str | None = None) -> list[sqlite3.Row]:
    """The catalogue in display order; with a powertrain, only the types that apply to it."""
    rows = conn.execute("SELECT * FROM service_types ORDER BY sort, name").fetchall()
    if powertrain is None:
        return rows
    return [row for row in rows if powertrain in row["powertrains"].split(",")]


def add_custom_type(conn: sqlite3.Connection, name: str, category: str, default_action: str = "replace") -> str:
    """Add a type the standard list lacks; returns its new code."""
    name = name.strip()
    if not name:
        raise ValueError("Give the service a name.")
    if default_action not in ACTIONS:
        raise ValueError(f"Unknown action {default_action!r}.")
    if conn.execute("SELECT 1 FROM service_types WHERE name = ? COLLATE NOCASE", (name,)).fetchone():
        raise ValueError(f"There's already a service called {name!r}.")
    base = "custom_" + (re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "service")
    code, n = base, 2
    while conn.execute("SELECT 1 FROM service_types WHERE code = ?", (code,)).fetchone():
        code, n = f"{base}_{n}", n + 1
    sort = conn.execute("SELECT coalesce(max(sort), 0) + 1 FROM service_types WHERE category = ?", (category,)).fetchone()[0]
    conn.execute(
        "INSERT INTO service_types (code, name, category, default_action, sort, is_custom) VALUES (?, ?, ?, ?, ?, 1)",
        (code, name, category, default_action, sort),
    )
    return code


# ---------- Service events ----------


def create_event(conn: sqlite3.Connection, vehicle_id: int, event: EventInput, confirmed: bool = True) -> int:
    _check(event)
    now = now_iso()
    with transaction(conn):
        cursor = conn.execute(
            "INSERT INTO service_events (vehicle_id, performed_on, odometer, source, shop, invoice_number,"
            " tax_cents, total_cents, notes, confirmed, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                vehicle_id, event.performed_on, event.odometer, event.source, event.shop, event.invoice_number,
                event.tax_cents, event.total_cents, event.notes, int(confirmed), now, now,
            ),
        )
        event_id = cursor.lastrowid
        _insert_lines(conn, event_id, event.lines)  # type: ignore[arg-type]
    return event_id  # type: ignore[return-value]


def update_event(conn: sqlite3.Connection, event_id: int, event: EventInput) -> None:
    """Replace an event's fields and all its lines."""
    _check(event)
    with transaction(conn):
        conn.execute(
            "UPDATE service_events SET performed_on = ?, odometer = ?, source = ?, shop = ?, invoice_number = ?,"
            " tax_cents = ?, total_cents = ?, notes = ?, updated_at = ? WHERE id = ?",
            (
                event.performed_on, event.odometer, event.source, event.shop, event.invoice_number,
                event.tax_cents, event.total_cents, event.notes, now_iso(), event_id,
            ),
        )
        conn.execute("DELETE FROM line_items WHERE service_event_id = ?", (event_id,))
        _insert_lines(conn, event_id, event.lines)


def move_event(conn: sqlite3.Connection, event_id: int, vehicle_id: int) -> None:
    """File a service under a different car (a receipt reassigned on review)."""
    conn.execute("UPDATE service_events SET vehicle_id = ?, updated_at = ? WHERE id = ?", (vehicle_id, now_iso(), event_id))


def delete_event(conn: sqlite3.Connection, event_id: int) -> None:
    conn.execute("DELETE FROM service_events WHERE id = ?", (event_id,))


def get_event(conn: sqlite3.Connection, event_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM service_events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        return None
    event = dict(row)
    lines = [dict(r) for r in conn.execute(
        "SELECT * FROM line_items WHERE service_event_id = ? ORDER BY position", (event_id,)
    )]
    covers = _covers_for(conn, [line["id"] for line in lines])
    for line in lines:
        line["covers"] = covers.get(line["id"], [])
    event["lines"] = lines
    return event


def event_input(event: dict) -> EventInput:
    """An event as read by get_event, back in the shape create/update take."""
    return EventInput(
        performed_on=event["performed_on"],
        source=event["source"],
        odometer=event["odometer"],
        shop=event["shop"],
        invoice_number=event["invoice_number"],
        tax_cents=event["tax_cents"],
        total_cents=event["total_cents"],
        notes=event["notes"],
        lines=[
            LineInput(
                description=line["description"],
                kind=line["kind"],
                part_number=line["part_number"],
                quantity=line["quantity"],
                amount_cents=line["amount_cents"],
                covers=[Coverage(c["code"], c["action"]) for c in line["covers"]],
            )
            for line in event["lines"]
        ],
    )


def history(conn: sqlite3.Connection, vehicle_id: int) -> list[dict]:
    """A car's confirmed services, newest first, each with what it covered."""
    events = [dict(r) for r in conn.execute(
        "SELECT * FROM service_events WHERE vehicle_id = ? AND confirmed = 1 ORDER BY performed_on DESC, id DESC",
        (vehicle_id,),
    )]
    covered: dict[int, list[dict]] = {}
    for row in conn.execute(
        "SELECT li.service_event_id AS event_id, st.code, st.name, st.sort,"
        "       group_concat(DISTINCT lis.action) AS actions"
        "  FROM line_items li"
        "  JOIN line_item_services lis ON lis.line_item_id = li.id"
        "  JOIN service_types st ON st.id = lis.service_type_id"
        "  JOIN service_events e ON e.id = li.service_event_id"
        " WHERE e.vehicle_id = ?"
        " GROUP BY li.service_event_id, st.id"
        " ORDER BY st.sort",
        (vehicle_id,),
    ):
        actions = set(row["actions"].split(","))
        covered.setdefault(row["event_id"], []).append(
            # "inspected" only when nothing on the visit did more than look at it
            {"code": row["code"], "name": row["name"], "inspected_only": actions == {"inspect"}}
        )
    for event in events:
        event["covered"] = covered.get(event["id"], [])
    return events


def coverage(conn: sqlite3.Connection, vehicle_id: int) -> list[dict]:
    """A car's confirmed services, oldest first, each with {code: {actions}} — what the gap engine reads."""
    events: dict[int, dict] = {}
    for row in conn.execute(
        "SELECT e.id, e.performed_on, e.odometer, e.source, st.code, lis.action"
        "  FROM service_events e"
        "  LEFT JOIN line_items li ON li.service_event_id = e.id"
        "  LEFT JOIN line_item_services lis ON lis.line_item_id = li.id"
        "  LEFT JOIN service_types st ON st.id = lis.service_type_id"
        " WHERE e.vehicle_id = ? AND e.confirmed = 1"
        " ORDER BY e.performed_on, e.id",
        (vehicle_id,),
    ):
        event = events.setdefault(row["id"], {
            "id": row["id"], "performed_on": row["performed_on"], "odometer": row["odometer"],
            "source": row["source"], "coverage": {},
        })
        if row["code"]:
            event["coverage"].setdefault(row["code"], set()).add(row["action"])
    return list(events.values())


def _covers_for(conn: sqlite3.Connection, line_ids: list[int]) -> dict[int, list[dict]]:
    if not line_ids:
        return {}
    marks = ", ".join("?" * len(line_ids))
    result: dict[int, list[dict]] = {}
    for row in conn.execute(
        "SELECT lis.line_item_id, lis.action, st.code, st.name"
        "  FROM line_item_services lis JOIN service_types st ON st.id = lis.service_type_id"
        f" WHERE lis.line_item_id IN ({marks}) ORDER BY st.sort",
        line_ids,
    ):
        result.setdefault(row["line_item_id"], []).append(
            {"code": row["code"], "name": row["name"], "action": row["action"]}
        )
    return result


def _insert_lines(conn: sqlite3.Connection, event_id: int, lines: list[LineInput]) -> None:
    type_ids = {row["code"]: row["id"] for row in conn.execute("SELECT id, code FROM service_types")}
    for position, line in enumerate(lines):
        cursor = conn.execute(
            "INSERT INTO line_items (service_event_id, position, description, kind, part_number, quantity, amount_cents)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (event_id, position, line.description, line.kind, line.part_number, line.quantity, line.amount_cents),
        )
        for cover in line.covers:
            if cover.code not in type_ids:
                raise ValueError(f"Unknown service type {cover.code!r}.")
            conn.execute(
                "INSERT OR REPLACE INTO line_item_services (line_item_id, service_type_id, action) VALUES (?, ?, ?)",
                (cursor.lastrowid, type_ids[cover.code], cover.action),
            )


def _check(event: EventInput) -> None:
    if event.source not in SOURCES:
        raise ValueError(f"Unknown source {event.source!r}.")
    for line in event.lines:
        if line.kind not in KINDS:
            raise ValueError(f"Unknown line kind {line.kind!r}.")
        for cover in line.covers:
            if cover.action not in ACTIONS:
                raise ValueError(f"Unknown action {cover.action!r}.")
