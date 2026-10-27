"""Fill-ups and charges.

A gas or hybrid car is *filled* (US gallons); an electric car is *charged*
(kWh). Every one is also an odometer reading: the ``odometer_points`` view
lists it, so the odometer model, today's estimate and the conflict check see
it with nothing more to do here.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from ..db import now_iso

ENERGIES = ("gas", "electric")
PLACES = ("home", "public")


def energy_for(powertrain: str) -> str:
    """What a car runs on, for its log: electric cars charge, the rest fill up."""
    return "electric" if powertrain == "ev" else "gas"


def point_source(energy: str) -> str:
    """The source name a fill or charge has in ``odometer_points``."""
    return "charge" if energy == "electric" else "fill"


@dataclass
class FillInput:
    filled_on: str
    odometer: int
    energy: str
    quantity: float                 # US gallons or kWh
    cost_cents: int | None = None
    full: bool = True               # filled the tank / charged to the usual limit
    missed_before: bool = False     # a fill since the last one logged wasn't logged
    place: str | None = None        # home or public; charges only
    note: str = ""
    station: str = ""               # where: "Shell", "Wawa on Route 9"


def _check(fill: FillInput) -> None:
    if fill.energy not in ENERGIES:
        raise ValueError(f"Unknown energy {fill.energy!r}.")
    if fill.place is not None and (fill.energy != "electric" or fill.place not in PLACES):
        raise ValueError(f"A {fill.energy} fill can't be at {fill.place!r}.")
    if not fill.quantity > 0:
        raise ValueError("A fill needs a quantity above zero.")


def _values(fill: FillInput) -> tuple:
    return (fill.filled_on, fill.odometer, fill.energy, fill.quantity, fill.cost_cents, int(fill.full),
            int(fill.missed_before), fill.place, fill.note, fill.station)


def create(conn: sqlite3.Connection, vehicle_id: int, fill: FillInput) -> int:
    _check(fill)
    now = now_iso()
    cursor = conn.execute(
        "INSERT INTO fuel_logs (filled_on, odometer, energy, quantity, cost_cents, full, missed_before, place, note,"
        " station, vehicle_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (*_values(fill), vehicle_id, now, now),
    )
    return cursor.lastrowid  # type: ignore[return-value]


def update(conn: sqlite3.Connection, fill_id: int, fill: FillInput) -> None:
    _check(fill)
    conn.execute(
        "UPDATE fuel_logs SET filled_on = ?, odometer = ?, energy = ?, quantity = ?, cost_cents = ?, full = ?,"
        " missed_before = ?, place = ?, note = ?, station = ?, updated_at = ? WHERE id = ?",
        (*_values(fill), now_iso(), fill_id),
    )


def get(conn: sqlite3.Connection, fill_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM fuel_logs WHERE id = ?", (fill_id,)).fetchone()


def delete(conn: sqlite3.Connection, fill_id: int) -> None:
    conn.execute("DELETE FROM fuel_logs WHERE id = ?", (fill_id,))


def log(conn: sqlite3.Connection, vehicle_id: int) -> list[sqlite3.Row]:
    """A car's fills and charges, newest first."""
    return conn.execute(
        "SELECT * FROM fuel_logs WHERE vehicle_id = ? ORDER BY filled_on DESC, odometer DESC, id DESC",
        (vehicle_id,),
    ).fetchall()


def last(conn: sqlite3.Connection, vehicle_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM fuel_logs WHERE vehicle_id = ? ORDER BY filled_on DESC, odometer DESC, id DESC LIMIT 1",
        (vehicle_id,),
    ).fetchone()


def stations(conn: sqlite3.Connection) -> list[str]:
    """Every station on the log, any car's, most recently used first; each once whatever its capitals, as it was
    last typed."""
    return [row["station"] for row in conn.execute(
        "SELECT station FROM (SELECT station, filled_on, id, row_number() OVER"
        " (PARTITION BY station COLLATE NOCASE ORDER BY filled_on DESC, id DESC) AS n"
        " FROM fuel_logs WHERE station <> '') WHERE n = 1 ORDER BY filled_on DESC, id DESC"
    )]


def cars_by_last_fill(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """The cars in the garage, the one filled most recently first; cars never filled after, by name."""
    return conn.execute(
        "SELECT v.*, d.sha256 AS photo_sha256, max(f.filled_on) AS last_filled"
        " FROM vehicles v LEFT JOIN fuel_logs f ON f.vehicle_id = v.id LEFT JOIN documents d ON d.id = v.photo_document_id"
        " WHERE v.archived_at IS NULL GROUP BY v.id"
        " ORDER BY last_filled IS NULL, last_filled DESC, v.name COLLATE NOCASE, v.id"
    ).fetchall()
