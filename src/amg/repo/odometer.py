"""Odometer readings, and the check that keeps them in order.

A reading can come from three places — typed in here, a service, or the
mileage when you got the car — and all three meet in the ``odometer_points``
view. ``conflict`` is how every one of them is checked before it is saved: a
reading lower than one from an earlier date (or higher than one from a later
date) is almost always a typo, and left in it would bend every projection the
odometer model makes. Readings on the same day are never compared.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..db import now_iso


@dataclass
class Conflict:
    read_on: str
    miles: int
    source: str
    later: bool  # True: the conflicting reading is from a later date

    def message(self) -> str:
        where = {"manual": "a reading", "service": "a service", "acquired": "when you got the car"}.get(self.source, "a reading")
        if self.later:
            return f"That's higher than the {self.miles:,} mi recorded later, on {self.read_on} ({where})."
        return f"That's lower than the {self.miles:,} mi recorded earlier, on {self.read_on} ({where})."


def add(conn: sqlite3.Connection, vehicle_id: int, read_on: str, miles: int, note: str = "") -> int:
    cursor = conn.execute(
        "INSERT INTO odometer_readings (vehicle_id, read_on, miles, note, created_at) VALUES (?, ?, ?, ?, ?)",
        (vehicle_id, read_on, miles, note, now_iso()),
    )
    return cursor.lastrowid  # type: ignore[return-value]


def get(conn: sqlite3.Connection, reading_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM odometer_readings WHERE id = ?", (reading_id,)).fetchone()


def delete(conn: sqlite3.Connection, reading_id: int) -> None:
    conn.execute("DELETE FROM odometer_readings WHERE id = ?", (reading_id,))


def points(conn: sqlite3.Connection, vehicle_id: int) -> list[sqlite3.Row]:
    """Every known reading for a car, oldest first."""
    return conn.execute(
        "SELECT read_on, miles, source, source_id FROM odometer_points WHERE vehicle_id = ? ORDER BY read_on, miles",
        (vehicle_id,),
    ).fetchall()


def conflict(
    conn: sqlite3.Connection,
    vehicle_id: int,
    read_on: str,
    miles: int,
    ignore: tuple[str, int] | None = None,
) -> Conflict | None:
    """The nearest reading this one would contradict, or None.

    ``ignore`` is the (source, id) of the record being edited, so a reading is
    never judged against its own previous value.
    """
    exclude = ""
    params: list = [vehicle_id, read_on, miles]
    if ignore:
        exclude = " AND NOT (source = ? AND source_id = ?)"
        params += list(ignore)

    earlier = conn.execute(
        "SELECT read_on, miles, source FROM odometer_points"
        f" WHERE vehicle_id = ? AND read_on < ? AND miles > ?{exclude}"
        " ORDER BY miles DESC LIMIT 1",
        params,
    ).fetchone()
    if earlier:
        return Conflict(earlier["read_on"], earlier["miles"], earlier["source"], later=False)

    later = conn.execute(
        "SELECT read_on, miles, source FROM odometer_points"
        f" WHERE vehicle_id = ? AND read_on > ? AND miles < ?{exclude}"
        " ORDER BY miles LIMIT 1",
        params,
    ).fetchone()
    if later:
        return Conflict(later["read_on"], later["miles"], later["source"], later=True)
    return None
