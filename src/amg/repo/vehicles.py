"""Cars: add, edit, archive, and what the garage shows about each one."""

from __future__ import annotations

import sqlite3
from dataclasses import astuple, dataclass, fields

from ..db import now_iso

POWERTRAINS = ("gas", "hybrid", "ev")


@dataclass
class VehicleFields:
    name: str
    vin: str | None = None
    year: int | None = None
    make: str = ""
    model: str = ""
    trim: str = ""
    engine: str = ""
    powertrain: str = "gas"
    plate: str = ""
    in_service_date: str | None = None
    acquired_date: str | None = None
    acquired_miles: int | None = None
    notes: str = ""


_COLUMNS = tuple(f.name for f in fields(VehicleFields))

# A car with its photo's content hash, for the photo's URL: a URL that names the content can be kept for good.
_WITH_PHOTO = "SELECT v.*, d.sha256 AS photo_sha256 FROM vehicles v LEFT JOIN documents d ON d.id = v.photo_document_id"


def create(conn: sqlite3.Connection, vehicle: VehicleFields) -> int:
    now = now_iso()
    cursor = conn.execute(
        f"INSERT INTO vehicles ({', '.join(_COLUMNS)}, created_at, updated_at)"
        f" VALUES ({', '.join('?' * len(_COLUMNS))}, ?, ?)",
        (*astuple(vehicle), now, now),
    )
    return cursor.lastrowid  # type: ignore[return-value]


def update(conn: sqlite3.Connection, vehicle_id: int, vehicle: VehicleFields) -> None:
    assignments = ", ".join(f"{column} = ?" for column in _COLUMNS)
    conn.execute(
        f"UPDATE vehicles SET {assignments}, updated_at = ?,"
        # Another year, make or model may have other recalls: check on the next run. (The right side reads the
        # row as it was.)
        "   recalls_checked_on = CASE WHEN year IS ? AND make = ? AND model = ? THEN recalls_checked_on END"
        " WHERE id = ?",
        (*astuple(vehicle), now_iso(), vehicle.year, vehicle.make, vehicle.model, vehicle_id),
    )


def get(conn: sqlite3.Connection, vehicle_id: int) -> sqlite3.Row | None:
    return conn.execute(f"{_WITH_PHOTO} WHERE v.id = ?", (vehicle_id,)).fetchone()


def set_photo(conn: sqlite3.Connection, vehicle_id: int, document_id: int | None) -> None:
    """The car's photo, one of the stored files; None takes it off. The file itself stays."""
    conn.execute("UPDATE vehicles SET photo_document_id = ?, updated_at = ? WHERE id = ?",
                 (document_id, now_iso(), vehicle_id))


def fields_of(row: sqlite3.Row) -> VehicleFields:
    return VehicleFields(**{column: row[column] for column in _COLUMNS})


def vin_owner(conn: sqlite3.Connection, vin: str) -> int | None:
    """The id of the car already holding this VIN, if any."""
    row = conn.execute("SELECT id FROM vehicles WHERE vin = ?", (vin,)).fetchone()
    return row[0] if row else None


def archive(conn: sqlite3.Connection, vehicle_id: int) -> None:
    conn.execute("UPDATE vehicles SET archived_at = ?, updated_at = ? WHERE id = ?", (now_iso(), now_iso(), vehicle_id))


def restore(conn: sqlite3.Connection, vehicle_id: int) -> None:
    conn.execute("UPDATE vehicles SET archived_at = NULL, updated_at = ? WHERE id = ?", (now_iso(), vehicle_id))


def garage(conn: sqlite3.Connection) -> tuple[list[dict], list[dict]]:
    """(active, archived) cars, each with its latest odometer and last service."""
    active: list[dict] = []
    archived: list[dict] = []
    for row in conn.execute(f"{_WITH_PHOTO} ORDER BY v.name COLLATE NOCASE, v.id").fetchall():
        car = dict(row)
        car["odometer"] = latest_odometer(conn, row["id"])
        last = conn.execute(
            "SELECT id, performed_on, shop, source FROM service_events"
            " WHERE vehicle_id = ? AND confirmed = 1 ORDER BY performed_on DESC, id DESC LIMIT 1",
            (row["id"],),
        ).fetchone()
        car["last_service"] = dict(last) if last else None
        car["service_count"] = conn.execute(
            "SELECT count(*) FROM service_events WHERE vehicle_id = ? AND confirmed = 1", (row["id"],)
        ).fetchone()[0]
        (archived if row["archived_at"] else active).append(car)
    return active, archived


def names(conn: sqlite3.Connection) -> dict[int, str]:
    """Every car's name by id, archived ones included."""
    return {row["id"]: row["name"] for row in conn.execute("SELECT id, name FROM vehicles")}


def powertrains(conn: sqlite3.Connection) -> set[str]:
    """The powertrains of the cars in the garage (archived ones aside)."""
    return {row[0] for row in conn.execute("SELECT DISTINCT powertrain FROM vehicles WHERE archived_at IS NULL")}


def latest_odometer(conn: sqlite3.Connection, vehicle_id: int) -> dict | None:
    row = conn.execute(
        "SELECT read_on, miles, source FROM odometer_points WHERE vehicle_id = ?"
        " ORDER BY read_on DESC, miles DESC LIMIT 1",
        (vehicle_id,),
    ).fetchone()
    return dict(row) if row else None
