"""Shop recommendations: reading them from confirmed receipts, and what you decided about each.

They live in each receipt's draft_json, the editable record; an outcome is
keyed by the receipt and the recommendation's normalised wording. Whether one
is still open is the engine's call (engine/follow_ups.py).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date

from ..db import now_iso
from ..engine.follow_ups import Outcome, Recommendation
from ..ingest.drafts import phrase


def recommendations(conn: sqlite3.Connection, vehicle_id: int) -> list[Recommendation]:
    """Every recommendation on a car's confirmed receipts, oldest visit first."""
    found = []
    for row in conn.execute(
        "SELECT r.id, r.draft_json, e.id AS event_id, e.performed_on, e.shop"
        "  FROM receipts r JOIN service_events e ON e.id = r.service_event_id"
        " WHERE r.status = 'confirmed' AND e.confirmed = 1 AND e.vehicle_id = ?"
        " ORDER BY e.performed_on, e.id",
        (vehicle_id,),
    ):
        draft = json.loads(row["draft_json"] or "{}")
        for rec in draft.get("recommendations") or []:
            description = (rec.get("description") or "").strip()
            found.append(Recommendation(
                receipt_id=row["id"], event_id=row["event_id"], day=date.fromisoformat(row["performed_on"]),
                shop=row["shop"], description=description, codes=tuple(rec.get("codes") or ()),
                quoted_cents=rec.get("quoted_cents"), key=phrase(description),
            ))
    return found


def find(conn: sqlite3.Connection, receipt_id: int, key: str) -> tuple[Recommendation, int] | None:
    """One recommendation by its receipt and key, with the car it's for; None if there's no such one."""
    row = conn.execute(
        "SELECT e.vehicle_id FROM receipts r JOIN service_events e ON e.id = r.service_event_id"
        " WHERE r.id = ? AND r.status = 'confirmed'",
        (receipt_id,),
    ).fetchone()
    if row is None:
        return None
    rec = next((r for r in recommendations(conn, row["vehicle_id"]) if r.receipt_id == receipt_id and r.key == key),
               None)
    return (rec, row["vehicle_id"]) if rec else None


def outcomes(conn: sqlite3.Connection, vehicle_id: int) -> dict[tuple[int, str], Outcome]:
    return {
        (row["receipt_id"], row["phrase"]): Outcome(row["outcome"], row["service_event_id"])
        for row in conn.execute(
            "SELECT o.* FROM recommendation_outcomes o"
            "  JOIN receipts r ON r.id = o.receipt_id JOIN service_events e ON e.id = r.service_event_id"
            " WHERE e.vehicle_id = ?",
            (vehicle_id,),
        )
    }


def skip(conn: sqlite3.Connection, receipt_id: int, key: str) -> None:
    """You're not doing it."""
    _set(conn, receipt_id, key, "skipped", None)


def done(conn: sqlite3.Connection, receipt_id: int, key: str, event_id: int) -> None:
    """Logged as a service from the recommendation."""
    _set(conn, receipt_id, key, "done", event_id)


def undo(conn: sqlite3.Connection, receipt_id: int, key: str) -> None:
    conn.execute("DELETE FROM recommendation_outcomes WHERE receipt_id = ? AND phrase = ?", (receipt_id, key))


def _set(conn: sqlite3.Connection, receipt_id: int, key: str, outcome: str, event_id: int | None) -> None:
    conn.execute(
        "INSERT INTO recommendation_outcomes (receipt_id, phrase, outcome, service_event_id, created_at)"
        " VALUES (?, ?, ?, ?, ?)"
        " ON CONFLICT (receipt_id, phrase) DO UPDATE SET outcome = excluded.outcome,"
        "   service_event_id = excluded.service_event_id, created_at = excluded.created_at",
        (receipt_id, key, outcome, event_id, now_iso()),
    )
