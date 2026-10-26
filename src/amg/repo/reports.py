"""What the reports read: confirmed services with their lines, and what the filters offer.

Only confirmed services count — a receipt waiting to be checked is in nobody's
history yet. Archived cars stay in: a car you've sold still has a past, and its
sale packet is wanted after it's gone.
"""

from __future__ import annotations

import sqlite3


def car_photos(conn: sqlite3.Connection) -> list[dict]:
    """Each car's photo (its document), with the car's name; A to Z."""
    return [dict(row) for row in conn.execute(
        "SELECT d.*, v.name AS car_name FROM vehicles v JOIN documents d ON d.id = v.photo_document_id"
        " ORDER BY v.name COLLATE NOCASE, v.id"
    )]


def cars(conn: sqlite3.Connection) -> list[dict]:
    """Every car, the ones in the garage first, then the archived ones; A to Z within each."""
    return [dict(row) for row in conn.execute(
        "SELECT * FROM vehicles ORDER BY archived_at IS NOT NULL, name COLLATE NOCASE, id"
    )]


def has_services(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM service_events WHERE confirmed = 1 LIMIT 1").fetchone() is not None


def has_fills(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM fuel_logs LIMIT 1").fetchone() is not None


def visits(conn: sqlite3.Connection, car_id: int | None = None, start: str | None = None,
           end: str | None = None) -> list[dict]:
    """Confirmed services, newest first, between two ISO dates (both included).

    Each carries its car's name and whether it's archived, and its lines in
    order; each line carries the service types it covers, in catalogue order,
    with their category.
    """
    where, args = ["e.confirmed = 1"], []
    for clause, value in (("e.vehicle_id = ?", car_id), ("e.performed_on >= ?", start), ("e.performed_on <= ?", end)):
        if value is not None:
            where.append(clause)
            args.append(value)
    within = " AND ".join(where)
    found = [dict(row) for row in conn.execute(
        "SELECT e.*, v.name AS car_name, v.archived_at IS NOT NULL AS car_archived"
        "  FROM service_events e JOIN vehicles v ON v.id = e.vehicle_id"
        f" WHERE {within} ORDER BY e.performed_on DESC, e.id DESC",
        args,
    )]
    lines: dict[int, list[dict]] = {}
    by_id: dict[int, dict] = {}
    for row in conn.execute(
        "SELECT li.* FROM line_items li JOIN service_events e ON e.id = li.service_event_id"
        f" WHERE {within} ORDER BY li.service_event_id, li.position",
        args,
    ):
        line = {**dict(row), "covers": []}
        lines.setdefault(row["service_event_id"], []).append(line)
        by_id[row["id"]] = line
    for row in conn.execute(
        "SELECT lis.line_item_id, lis.action, st.code, st.name, st.category"
        "  FROM line_item_services lis"
        "  JOIN service_types st ON st.id = lis.service_type_id"
        "  JOIN line_items li ON li.id = lis.line_item_id"
        "  JOIN service_events e ON e.id = li.service_event_id"
        f" WHERE {within} ORDER BY st.sort, st.name",
        args,
    ):
        by_id[row["line_item_id"]]["covers"].append(
            {"code": row["code"], "name": row["name"], "category": row["category"], "action": row["action"]}
        )
    for visit in found:
        visit["lines"] = lines.get(visit["id"], [])
    return found


def receipt_files(conn: sqlite3.Connection, car_id: int) -> dict[int, sqlite3.Row]:
    """The stored file behind each of a car's confirmed services that came from a receipt, by service id."""
    return {row["service_event_id"]: row for row in conn.execute(
        "SELECT r.service_event_id, d.* FROM receipts r"
        "  JOIN documents d ON d.id = r.document_id"
        "  JOIN service_events e ON e.id = r.service_event_id"
        " WHERE r.status = 'confirmed' AND e.confirmed = 1 AND e.vehicle_id = ?",
        (car_id,),
    )}


def shops(conn: sqlite3.Connection) -> list[str]:
    """The shops your confirmed services name, each once whatever its capitals, A to Z."""
    seen: dict[str, str] = {}
    for (shop,) in conn.execute(
        "SELECT shop FROM service_events WHERE confirmed = 1 AND trim(shop) != ''"
        " GROUP BY shop ORDER BY count(*) DESC, shop"
    ):
        seen.setdefault(shop.strip().lower(), shop.strip())   # the spelling used most often
    return sorted(seen.values(), key=str.lower)


def used_types(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """The service types your confirmed services cover, in catalogue order."""
    return conn.execute(
        "SELECT DISTINCT st.code, st.name, st.category, st.sort"
        "  FROM service_types st"
        "  JOIN line_item_services lis ON lis.service_type_id = st.id"
        "  JOIN line_items li ON li.id = lis.line_item_id"
        "  JOIN service_events e ON e.id = li.service_event_id"
        " WHERE e.confirmed = 1"
        " ORDER BY st.sort, st.name"
    ).fetchall()


def categories(conn: sqlite3.Connection) -> list[str]:
    """Every category, in the order the catalogue shows them."""
    return [row[0] for row in conn.execute(
        "SELECT category FROM service_types GROUP BY category ORDER BY min(sort), category"
    )]


# ---------- Download your data ----------


def fills(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every fill-up and charge, car by car, oldest first."""
    return conn.execute(
        "SELECT f.*, v.name AS car_name FROM fuel_logs f JOIN vehicles v ON v.id = f.vehicle_id"
        " ORDER BY v.name COLLATE NOCASE, v.id, f.filled_on, f.odometer, f.id"
    ).fetchall()


def odometer_points(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every odometer reading AMG knows, car by car, wherever it was recorded."""
    return conn.execute(
        "SELECT p.read_on, p.miles, p.source, v.name AS car_name"
        "  FROM odometer_points p JOIN vehicles v ON v.id = p.vehicle_id"
        " ORDER BY v.name COLLATE NOCASE, v.id, p.read_on, p.miles"
    ).fetchall()


def prices(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """The prices the budget uses — yours, and Claude's estimates that came back — car by car."""
    return conn.execute(
        "SELECT p.*, v.name AS car_name FROM price_book p JOIN vehicles v ON v.id = p.vehicle_id"
        " WHERE p.status = 'done'"
        " ORDER BY v.name COLLATE NOCASE, v.id, p.name, p.source DESC"
    ).fetchall()


def receipt_downloads(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every confirmed receipt's stored file, with the date, shop and car its service says, oldest first."""
    return conn.execute(
        "SELECT d.*, e.performed_on, e.shop, v.name AS car_name"
        "  FROM receipts r"
        "  JOIN documents d ON d.id = r.document_id"
        "  JOIN service_events e ON e.id = r.service_event_id"
        "  JOIN vehicles v ON v.id = e.vehicle_id"
        " WHERE r.status = 'confirmed' AND e.confirmed = 1"
        " ORDER BY e.performed_on, r.id"
    ).fetchall()


def manuals(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """The stored files a schedule in use, or a car's specs, were read from: owner's manuals, mostly."""
    return conn.execute(
        "SELECT * FROM documents WHERE id IN ("
        "  SELECT document_id FROM schedule_items WHERE document_id IS NOT NULL"
        "  UNION SELECT document_id FROM schedule_drafts WHERE status = 'confirmed' AND document_id IS NOT NULL"
        "  UNION SELECT document_id FROM vehicle_specs WHERE document_id IS NOT NULL"
        ") ORDER BY filename, id"
    ).fetchall()
