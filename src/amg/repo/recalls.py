"""Recalls: what NHTSA lists for each car, what you said about each, and when each car was last checked."""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from ..db import now_iso, transaction
from ..ingest.recalls import Lookup

CHECK_DAYS = 7   # a car is checked once a week
STATUSES = ("open", "done", "not_mine")


def due_for_check(conn: sqlite3.Connection, today: date) -> list[dict]:
    """Cars in the garage with a year, make and model, not checked in the last week."""
    since = (today - timedelta(days=CHECK_DAYS)).isoformat()
    return [dict(row) for row in conn.execute(
        "SELECT * FROM vehicles WHERE archived_at IS NULL AND year IS NOT NULL AND make != '' AND model != ''"
        "   AND (recalls_checked_on IS NULL OR recalls_checked_on <= ?)"
        " ORDER BY name COLLATE NOCASE, id",
        (since,),
    )]


def record(conn: sqlite3.Connection, vehicle_id: int, lookup: Lookup, today: date) -> list[str]:
    """Store a check's answer; returns the campaigns new to this car.

    Known recalls keep what you said about them, and take NHTSA's latest
    wording. An open one NHTSA no longer lists is dropped.
    """
    now = now_iso()
    with transaction(conn):
        known = {row["campaign"]: row["status"] for row in conn.execute(
            "SELECT campaign, status FROM recalls WHERE vehicle_id = ?", (vehicle_id,))}
        listed = {recall.campaign for recall in lookup.recalls}
        for campaign, status in known.items():
            if campaign not in listed and status == "open":
                conn.execute("DELETE FROM recalls WHERE vehicle_id = ? AND campaign = ?", (vehicle_id, campaign))
        for recall in lookup.recalls:
            conn.execute(
                "INSERT INTO recalls (vehicle_id, campaign, reported_on, component, summary, consequence, remedy,"
                "                     park_it, park_outside, found_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT (vehicle_id, campaign) DO UPDATE SET reported_on = excluded.reported_on,"
                "   component = excluded.component, summary = excluded.summary, consequence = excluded.consequence,"
                "   remedy = excluded.remedy, park_it = excluded.park_it, park_outside = excluded.park_outside",
                (vehicle_id, recall.campaign, recall.reported_on, recall.component, recall.summary,
                 recall.consequence, recall.remedy, int(recall.park_it), int(recall.park_outside), now, now),
            )
        conn.execute(
            "UPDATE vehicles SET recalls_checked_on = ?, recalls_model = ?, recalls_listed = ?, recalls_error = ''"
            " WHERE id = ?",
            (today.isoformat(), lookup.model, ",".join(lookup.listed), vehicle_id),
        )
    return [recall.campaign for recall in lookup.recalls if recall.campaign not in known]


def failed(conn: sqlite3.Connection, vehicle_id: int, error: str) -> None:
    """A check that didn't get an answer: said on the car's page, and tried again on the next run."""
    conn.execute("UPDATE vehicles SET recalls_error = ? WHERE id = ?", (error, vehicle_id))


def for_car(conn: sqlite3.Connection, vehicle_id: int) -> list[sqlite3.Row]:
    """Every recall for a car, with the service it was done on if you said: open ones first, newest report
    first within each."""
    return conn.execute(
        "SELECT r.*, e.performed_on AS service_on, e.shop AS service_shop"
        "  FROM recalls r LEFT JOIN service_events e ON e.id = r.service_event_id"
        " WHERE r.vehicle_id = ?"
        " ORDER BY r.status != 'open', r.reported_on IS NULL, r.reported_on DESC, r.campaign",
        (vehicle_id,),
    ).fetchall()


def open_for(conn: sqlite3.Connection, vehicle_id: int) -> list[sqlite3.Row]:
    return [row for row in for_car(conn, vehicle_id) if row["status"] == "open"]


def get(conn: sqlite3.Connection, recall_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM recalls WHERE id = ?", (recall_id,)).fetchone()


def close(conn: sqlite3.Connection, recall_id: int, status: str, closed_on: str | None = None,
          service_event_id: int | None = None) -> None:
    if status not in ("done", "not_mine"):
        raise ValueError(f"Unknown status {status!r}.")
    conn.execute(
        "UPDATE recalls SET status = ?, closed_on = ?, service_event_id = ?, updated_at = ? WHERE id = ?",
        (status, closed_on, service_event_id, now_iso(), recall_id),
    )


def reopen(conn: sqlite3.Connection, recall_id: int) -> None:
    conn.execute(
        "UPDATE recalls SET status = 'open', closed_on = NULL, service_event_id = NULL, updated_at = ? WHERE id = ?",
        (now_iso(), recall_id),
    )


def recall_visits(conn: sqlite3.Connection, vehicle_id: int, since: str | None) -> list[sqlite3.Row]:
    """The car's confirmed services with a recall line, on or after ``since``: the ones a recall may have been."""
    return conn.execute(
        "SELECT DISTINCT e.id, e.performed_on, e.shop FROM service_events e"
        "  JOIN line_items li ON li.service_event_id = e.id"
        "  JOIN line_item_services lis ON lis.line_item_id = li.id"
        "  JOIN service_types st ON st.id = lis.service_type_id"
        " WHERE e.vehicle_id = ? AND e.confirmed = 1 AND st.code = 'recall' AND e.performed_on >= ?"
        " ORDER BY e.performed_on DESC, e.id DESC",
        (vehicle_id, since or ""),
    ).fetchall()


def everything(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every recall on every car, for the data export."""
    return conn.execute(
        "SELECT r.*, v.name AS car_name, e.performed_on AS service_on, e.shop AS service_shop"
        "  FROM recalls r JOIN vehicles v ON v.id = r.vehicle_id"
        "  LEFT JOIN service_events e ON e.id = r.service_event_id"
        " ORDER BY v.archived_at IS NOT NULL, v.name COLLATE NOCASE, v.id, r.reported_on, r.campaign"
    ).fetchall()
