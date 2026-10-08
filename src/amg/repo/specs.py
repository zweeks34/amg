"""Specs cards: each car's values, and the receipt lines that suggest them."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass

from ..db import now_iso, transaction
from ..engine.specs import CUSTOM, FIELDS

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
