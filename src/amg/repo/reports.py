"""What the reports read: confirmed services with their lines, and what the filters offer.

Only confirmed services count — a receipt waiting to be checked is in nobody's
history yet. Archived cars stay in: a car you've sold still has a past, and its
sale packet is wanted after it's gone.
"""

from __future__ import annotations

import sqlite3


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
