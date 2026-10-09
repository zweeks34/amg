"""Warranties: yours, and the ones read from receipts, with what they cover and what you said about later visits.

A receipt's warranties live in its draft, the editable record; confirming
or saving the receipt writes them here (``sync_receipt``), each found again
by its wording so what you said about it stays. Yours are written by the
warranty form. When each ends, and which visit to ask about, is the
engine's call (engine/warranties.py).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date

from ..db import now_iso, transaction
from ..engine.warranties import Visit
from ..ingest.drafts import phrase

ANSWERS = ("claimed", "paid")


@dataclass
class WarrantyInput:
    title: str
    starts_on: str
    provider: str = ""
    start_miles: int | None = None
    months: int | None = None      # months and miles both None: lifetime
    miles: int | None = None
    whole_car: bool = False
    codes: list[str] = field(default_factory=list)
    details: str = ""
    event_id: int | None = None    # the visit it came with


_SELECT = (
    "SELECT w.*, e.performed_on AS event_on, e.shop AS event_shop, e.source AS event_source"
    "  FROM warranties w LEFT JOIN service_events e ON e.id = w.service_event_id"
)


# ---------- Yours ----------


def create(conn: sqlite3.Connection, vehicle_id: int, warranty: WarrantyInput) -> int:
    now = now_iso()
    with transaction(conn):
        cursor = conn.execute(
            "INSERT INTO warranties (vehicle_id, service_event_id, title, provider, details, starts_on, start_miles,"
            " months, miles, whole_car, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (vehicle_id, warranty.event_id, *_values(warranty), now, now),
        )
        warranty_id: int = cursor.lastrowid  # type: ignore[assignment]
        _set_covers(conn, warranty_id, [] if warranty.whole_car else warranty.codes)
    return warranty_id


def update(conn: sqlite3.Connection, warranty_id: int, warranty: WarrantyInput) -> None:
    with transaction(conn):
        conn.execute(
            "UPDATE warranties SET service_event_id = ?, title = ?, provider = ?, details = ?, starts_on = ?,"
            " start_miles = ?, months = ?, miles = ?, whole_car = ?, updated_at = ? WHERE id = ?",
            (warranty.event_id, *_values(warranty), now_iso(), warranty_id),
        )
        _set_covers(conn, warranty_id, [] if warranty.whole_car else warranty.codes)


def delete(conn: sqlite3.Connection, warranty_id: int) -> None:
    conn.execute("DELETE FROM warranties WHERE id = ?", (warranty_id,))


def _values(warranty: WarrantyInput) -> tuple:
    return (warranty.title.strip(), warranty.provider.strip(), warranty.details.strip(), warranty.starts_on,
            warranty.start_miles, warranty.months, warranty.miles, int(warranty.whole_car))


def _set_covers(conn: sqlite3.Connection, warranty_id: int, codes: Iterable[str]) -> None:
    """Replace what it covers with these codes; unknown ones are left out."""
    conn.execute("DELETE FROM warranty_covers WHERE warranty_id = ?", (warranty_id,))
    conn.executemany(
        "INSERT OR IGNORE INTO warranty_covers (warranty_id, service_type_id)"
        " SELECT ?, id FROM service_types WHERE code = ?",
        [(warranty_id, code) for code in dict.fromkeys(codes)],
    )


# ---------- From a receipt ----------


def sync_receipt(conn: sqlite3.Connection, receipt_id: int, vehicle_id: int, event_id: int, performed_on: str,
                 odometer: int | None, rows: Sequence[dict]) -> None:
    """Write a confirmed receipt's warranties from its draft, keeping each one's row (and answers) by its wording.

    Rows still marked ``found`` (from the look through older receipts) wait
    until you've checked them. A wording the receipt no longer has is deleted.
    """
    now = now_iso()
    keys: list[str] = []
    with transaction(conn):
        for row in rows:
            if row.get("found"):
                continue
            key = phrase(row["description"]) or "warranty"
            key = _unique(key, keys)
            keys.append(key)
            lifetime = bool(row.get("lifetime"))
            conn.execute(
                "INSERT INTO warranties (vehicle_id, receipt_id, phrase, service_event_id, title, provider, starts_on,"
                " start_miles, months, miles, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (receipt_id, phrase) DO UPDATE SET vehicle_id = excluded.vehicle_id,"
                " service_event_id = excluded.service_event_id, title = excluded.title, provider = excluded.provider,"
                " starts_on = excluded.starts_on, start_miles = excluded.start_miles, months = excluded.months,"
                " miles = excluded.miles, updated_at = excluded.updated_at",
                (vehicle_id, receipt_id, key, event_id, row["description"].strip(), (row.get("provider") or "").strip(),
                 performed_on, odometer, None if lifetime else row.get("months"),
                 None if lifetime else row.get("miles"), now, now),
            )
            warranty_id = conn.execute("SELECT id FROM warranties WHERE receipt_id = ? AND phrase = ?",
                                       (receipt_id, key)).fetchone()["id"]
            _set_covers(conn, warranty_id, row.get("codes") or [])
        marks = ", ".join("?" * len(keys))
        conn.execute(f"DELETE FROM warranties WHERE receipt_id = ? AND phrase NOT IN ({marks})", (receipt_id, *keys))


def _unique(key: str, taken: Sequence[str]) -> str:
    """'limited warranty', then 'limited warranty 2' for a second one worded the same on one receipt."""
    if key not in taken:
        return key
    n = 2
    while f"{key} {n}" in taken:
        n += 1
    return f"{key} {n}"


def release(conn: sqlite3.Connection, event_id: int) -> None:
    """A receipt's service is being deleted, and the receipt goes back to be checked: its warranties go too."""
    conn.execute("DELETE FROM warranties WHERE receipt_id IN (SELECT id FROM receipts WHERE service_event_id = ?)",
                 (event_id,))


# ---------- Reading them ----------


def get(conn: sqlite3.Connection, warranty_id: int) -> dict | None:
    row = conn.execute(f"{_SELECT} WHERE w.id = ?", (warranty_id,)).fetchone()
    return _complete(conn, [row])[0] if row else None


def for_car(conn: sqlite3.Connection, vehicle_id: int) -> list[dict]:
    """A car's warranties, newest first, each with its ``codes`` and ``answers`` ({event_id: answer})."""
    rows = conn.execute(f"{_SELECT} WHERE w.vehicle_id = ? ORDER BY w.starts_on DESC, w.id DESC", (vehicle_id,))
    return _complete(conn, rows.fetchall())


def for_event(conn: sqlite3.Connection, event_id: int) -> list[dict]:
    """The warranties that came with a visit."""
    rows = conn.execute(f"{_SELECT} WHERE w.service_event_id = ? ORDER BY w.id", (event_id,))
    return _complete(conn, rows.fetchall())


def visits(conn: sqlite3.Connection, vehicle_id: int) -> list[Visit]:
    """The car's confirmed services, oldest first, with what each replaced; not those marked done with no receipt."""
    found: dict[int, dict] = {}
    for row in conn.execute(
        "SELECT e.id, e.performed_on, e.shop, e.odometer, st.code"
        "  FROM service_events e"
        "  LEFT JOIN line_items li ON li.service_event_id = e.id"
        "  LEFT JOIN line_item_services lis ON lis.line_item_id = li.id AND lis.action = 'replace'"
        "  LEFT JOIN service_types st ON st.id = lis.service_type_id"
        " WHERE e.vehicle_id = ? AND e.confirmed = 1 AND e.source != 'attested'"
        " ORDER BY e.performed_on, e.id",
        (vehicle_id,),
    ):
        visit = found.setdefault(row["id"], {"row": row, "codes": set()})
        if row["code"]:
            visit["codes"].add(row["code"])
    return [Visit(v["row"]["id"], date.fromisoformat(v["row"]["performed_on"]), v["row"]["shop"], v["row"]["odometer"],
                  frozenset(v["codes"])) for v in found.values()]


def _complete(conn: sqlite3.Connection, rows: Sequence[sqlite3.Row]) -> list[dict]:
    warranties = [dict(row) for row in rows]
    if not warranties:
        return []
    ids = [w["id"] for w in warranties]
    marks = ", ".join("?" * len(ids))
    codes: dict[int, list[str]] = {}
    for row in conn.execute(
        f"SELECT c.warranty_id, st.code FROM warranty_covers c JOIN service_types st ON st.id = c.service_type_id"
        f" WHERE c.warranty_id IN ({marks}) ORDER BY st.sort, st.id",
        ids,
    ):
        codes.setdefault(row["warranty_id"], []).append(row["code"])
    answers: dict[int, dict[int, str]] = {}
    for row in conn.execute(f"SELECT warranty_id, event_id, answer FROM warranty_answers WHERE warranty_id IN ({marks})",
                            ids):
        answers.setdefault(row["warranty_id"], {})[row["event_id"]] = row["answer"]
    for warranty in warranties:
        warranty["codes"] = codes.get(warranty["id"], [])
        warranty["answers"] = answers.get(warranty["id"], {})
    return warranties


# ---------- The export ----------


def everything(conn: sqlite3.Connection) -> list[dict]:
    """Every warranty on every car, with its codes and answers, for the data export."""
    rows = conn.execute(
        "SELECT w.*, v.name AS car_name, e.performed_on AS event_on, e.shop AS event_shop, e.source AS event_source"
        "  FROM warranties w JOIN vehicles v ON v.id = w.vehicle_id"
        "  LEFT JOIN service_events e ON e.id = w.service_event_id"
        " ORDER BY v.archived_at IS NOT NULL, v.name COLLATE NOCASE, v.id, w.starts_on, w.id"
    ).fetchall()
    return _complete(conn, rows)
