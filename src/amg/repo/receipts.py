"""Receipts: from an uploaded file, through a reading, to a confirmed service.

Status runs queued → reading → read → confirmed, with failed and discarded to
the side. Confirming writes the service event from the draft; the receipt
keeps its draft afterwards and can be corrected and confirmed again, which
rewrites the same event.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter

from ..db import now_iso, transaction
from ..ingest import drafts, vin as vins
from ..ingest.claude import Usage
from ..ingest.drafts import Draft
from . import jobs, services, warranties

# The suggestion reason when you picked the car yourself while uploading.
CHOSEN = "You chose this car when uploading."


# ---------- Creating and reading ----------


def create(conn: sqlite3.Connection, document_id: int, job_id: int, vehicle_id: int | None = None) -> int:
    now = now_iso()
    cursor = conn.execute(
        "INSERT INTO receipts (document_id, job_id, status, vehicle_id, vehicle_reason, created_at, updated_at)"
        " VALUES (?, ?, 'queued', ?, ?, ?, ?)",
        (document_id, job_id, vehicle_id, CHOSEN if vehicle_id else "", now, now),
    )
    return cursor.lastrowid  # type: ignore[return-value]


def for_document(conn: sqlite3.Connection, document_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM receipts WHERE document_id = ?", (document_id,)).fetchone()


def claim_next(conn: sqlite3.Connection, job_id: int) -> int | None:
    """Take the job's next queued receipt; atomic, so two threads never read the same one."""
    row = conn.execute(
        "UPDATE receipts SET status = 'reading', updated_at = ?"
        " WHERE id = (SELECT id FROM receipts WHERE job_id = ? AND status = 'queued' ORDER BY id LIMIT 1)"
        " RETURNING id",
        (now_iso(), job_id),
    ).fetchone()
    return row[0] if row else None


def mark_read(
    conn: sqlite3.Connection,
    receipt_id: int,
    extraction: dict,
    draft: Draft,
    warnings: list[str],
    usage: Usage,
) -> None:
    with transaction(conn):
        row = conn.execute("SELECT vehicle_id, vehicle_reason FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
        if row["vehicle_reason"] == CHOSEN and row["vehicle_id"]:
            vehicle_id, reason = row["vehicle_id"], CHOSEN
        else:
            vehicle_id, reason = suggest_vehicle(conn, draft)
        conn.execute(
            "UPDATE receipts SET status = 'read', vehicle_id = ?, vehicle_reason = ?, extraction_json = ?,"
            " draft_json = ?, warnings_json = ?, error = '', model = ?, input_tokens = ?, output_tokens = ?,"
            " cost_usd = ?, read_seconds = ?, request_id = ?, read_at = ?, updated_at = ? WHERE id = ?",
            (
                vehicle_id, reason, json.dumps(extraction), json.dumps(draft.to_dict()), json.dumps(warnings),
                usage.model, usage.input_tokens + usage.cache_read_tokens + usage.cache_write_tokens,
                usage.output_tokens, usage.cost_usd, usage.seconds, usage.request_id, now_iso(), now_iso(), receipt_id,
            ),
        )


def mark_failed(conn: sqlite3.Connection, receipt_id: int, error: str) -> None:
    conn.execute("UPDATE receipts SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
                 (error, now_iso(), receipt_id))


def requeue(conn: sqlite3.Connection, receipt_id: int, job_id: int) -> None:
    """Read again (after a failure, or to start over); a car you chose is kept."""
    conn.execute(
        "UPDATE receipts SET status = 'queued', job_id = ?, error = '', updated_at = ?,"
        " vehicle_id = CASE WHEN vehicle_reason = ? THEN vehicle_id END,"
        " vehicle_reason = CASE WHEN vehicle_reason = ? THEN vehicle_reason ELSE '' END"
        " WHERE id = ? AND status IN ('read', 'failed')",
        (job_id, now_iso(), CHOSEN, CHOSEN, receipt_id),
    )


# ---------- Looking ----------


def get(conn: sqlite3.Connection, receipt_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
    if row is None:
        return None
    receipt = dict(row)
    receipt["document"] = dict(conn.execute("SELECT * FROM documents WHERE id = ?", (row["document_id"],)).fetchone())
    receipt["extraction"] = json.loads(row["extraction_json"]) if row["extraction_json"] else None
    receipt["draft"] = Draft.from_dict(json.loads(row["draft_json"])) if row["draft_json"] else None
    receipt["warnings"] = json.loads(row["warnings_json"] or "[]")
    vehicle = conn.execute("SELECT * FROM vehicles WHERE id = ?", (row["vehicle_id"],)).fetchone() if row["vehicle_id"] else None
    receipt["vehicle"] = dict(vehicle) if vehicle else None
    job = jobs.get(conn, row["job_id"]) if row["job_id"] else None
    receipt["stalled"] = bool(job and row["status"] in ("queued", "reading") and jobs.is_stalled(job))
    return receipt


def for_event(conn: sqlite3.Connection, event_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM receipts WHERE service_event_id = ?", (event_id,)).fetchone()


def count_to_check(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT count(*) FROM receipts WHERE status = 'read'").fetchone()[0]


def inbox(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """Every receipt, grouped the way the receipts page shows them."""
    groups: dict[str, list[dict]] = {"reading": [], "to_check": [], "failed": [], "confirmed": [], "discarded": []}
    stalled_jobs: dict[int, bool] = {}
    rows = conn.execute(
        "SELECT r.*, d.filename, d.page_count, d.uploaded_at, v.name AS vehicle_name,"
        "       v.archived_at IS NOT NULL AS vehicle_archived"
        "  FROM receipts r JOIN documents d ON d.id = r.document_id"
        "  LEFT JOIN vehicles v ON v.id = r.vehicle_id"
        " ORDER BY r.id"
    ).fetchall()
    for row in rows:
        item = dict(row)
        draft = json.loads(row["draft_json"]) if row["draft_json"] else {}
        item.update(
            performed_on=draft.get("performed_on"),
            shop=draft.get("shop", ""),
            total_cents=draft.get("total_cents"),
            document_kind=draft.get("document_kind", "invoice"),
            warning_count=len(json.loads(row["warnings_json"] or "[]")),
            # What searching the confirmed receipts reads.
            invoice_number=draft.get("invoice_number", ""),
            lines=draft.get("lines", []),
            recommendations=draft.get("recommendations", []),
            notes=draft.get("notes", ""),
        )
        if row["status"] in ("queued", "reading"):
            if row["job_id"] not in stalled_jobs:
                job = jobs.get(conn, row["job_id"]) if row["job_id"] else None
                stalled_jobs[row["job_id"]] = bool(job is None or jobs.is_stalled(job))
            item["stalled"] = stalled_jobs[row["job_id"]]
            groups["reading"].append(item)
        elif row["status"] == "read":
            groups["to_check"].append(item)
        else:
            groups[row["status"]].append(item)
    # Newest receipt date first; on the same day, the one added last.
    groups["confirmed"].sort(key=lambda r: (r["performed_on"] or "", r["id"]), reverse=True)
    return groups


def next_to_check(conn: sqlite3.Connection, after_id: int | None = None) -> int | None:
    row = conn.execute(
        "SELECT id FROM receipts WHERE status = 'read' AND id != ? ORDER BY id LIMIT 1", (after_id or 0,)
    ).fetchone()
    return row[0] if row else None


def possible_duplicates(conn: sqlite3.Connection, receipt_id: int, draft: Draft) -> list[dict]:
    """Other receipts with the same date and total — the same paper, scanned twice?"""
    if not draft.performed_on or draft.total_cents is None:
        return []
    rows = conn.execute(
        "SELECT r.id, r.status, d.filename FROM receipts r JOIN documents d ON d.id = r.document_id"
        " WHERE r.id != ? AND r.status != 'discarded'"
        "   AND json_extract(r.draft_json, '$.performed_on') = ?"
        "   AND json_extract(r.draft_json, '$.total_cents') = ?",
        (receipt_id, draft.performed_on, draft.total_cents),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------- Which car ----------


def suggest_vehicle(conn: sqlite3.Connection, draft: Draft) -> tuple[int | None, str]:
    """The car this receipt is most likely for, and why — a suggestion, never a decision.

    Tried in order: the car's own VIN, its plate, a VIN or plate printed on
    receipts already confirmed for a car (so a shop that keeps printing the
    wrong car is recognised), year/make/model, and finally the only car there is.
    """
    cars = [dict(r) for r in conn.execute("SELECT * FROM vehicles ORDER BY archived_at IS NOT NULL, id")]
    vin = vins.normalize(draft.printed_vin)
    plate = drafts.normalize_plate(draft.printed_plate)

    if vin:
        for car in cars:
            if car["vin"] == vin:
                return car["id"], "The VIN matches."
    if plate:
        for car in cars:
            if car["plate"] and drafts.normalize_plate(car["plate"]) == plate:
                return car["id"], "The plate matches."
    for field, value, label in (("printed_vin", vin, "VIN"), ("printed_plate", plate, "plate")):
        if not value:
            continue
        seen = Counter(
            row[0] for row in conn.execute(
                "SELECT vehicle_id FROM receipts WHERE status = 'confirmed' AND vehicle_id IS NOT NULL"
                f" AND json_extract(draft_json, '$.{field}') = ?",
                (value,),
            )
        )
        if seen:
            car_id = seen.most_common(1)[0][0]
            name = next((c["name"] for c in cars if c["id"] == car_id), "that car")
            return car_id, f"Earlier receipts with this {label} were for {name}."
    printed = draft.printed_vehicle.lower()
    if printed:
        fits = [
            car for car in cars
            if car["make"] and car["model"]
            and car["make"].lower() in printed and car["model"].lower() in printed
            and (not car["year"] or str(car["year"]) in printed or str(car["year"])[2:] in printed)
        ]
        if len(fits) == 1:
            return fits[0]["id"], "The year, make and model match."
    active = [car for car in cars if not car["archived_at"]]
    if len(active) == 1:
        return active[0]["id"], "It's your only car."
    return None, ""


# ---------- Reviewing ----------


def save_draft(conn: sqlite3.Connection, receipt_id: int, draft: Draft, vehicle_id: int | None) -> None:
    conn.execute(
        "UPDATE receipts SET draft_json = ?, vehicle_id = ?, updated_at = ? WHERE id = ?",
        (json.dumps(draft.to_dict()), vehicle_id, now_iso(), receipt_id),
    )


def confirm(
    conn: sqlite3.Connection,
    receipt_id: int,
    draft: Draft,
    vehicle_id: int,
    car_updates: dict[str, str] | None = None,
) -> int:
    """Write (or rewrite) the service event from the draft; returns its id.

    ``car_updates`` may set the car's plate, vin or in_service_date — only
    where the car doesn't have one yet; a car's details are never overwritten
    from a receipt.
    """
    with transaction(conn):
        row = conn.execute("SELECT service_event_id, confirmed_at FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
        event = drafts.to_event(draft)
        event_id = row["service_event_id"]
        if event_id:
            services.update_event(conn, event_id, event)
            services.move_event(conn, event_id, vehicle_id)
        else:
            event_id = services.create_event(conn, vehicle_id, event)
        now = now_iso()
        conn.execute(
            "UPDATE receipts SET status = 'confirmed', draft_json = ?, vehicle_id = ?, service_event_id = ?,"
            " confirmed_at = coalesce(confirmed_at, ?), updated_at = ? WHERE id = ?",
            (json.dumps(draft.to_dict()), vehicle_id, event_id, now, now, receipt_id),
        )
        warranties.sync_receipt(conn, receipt_id, vehicle_id, event_id, draft.performed_on or "", draft.odometer,
                                draft.warranties)
        for phrase, covers in drafts.learnable(draft).items():
            conn.execute(
                "INSERT INTO service_aliases (phrase, covers_json, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT (phrase) DO UPDATE SET covers_json = excluded.covers_json, updated_at = excluded.updated_at",
                (phrase, json.dumps(covers), now),
            )
        for column, value in (car_updates or {}).items():
            if column in ("plate", "vin", "in_service_date") and value:
                conn.execute(
                    f"UPDATE vehicles SET {column} = ?, updated_at = ? WHERE id = ? AND ({column} IS NULL OR {column} = '')",
                    (value, now, vehicle_id),
                )
    return event_id


def discard(conn: sqlite3.Connection, receipt_id: int) -> None:
    conn.execute("UPDATE receipts SET status = 'discarded', updated_at = ? WHERE id = ? AND status IN ('read', 'failed')",
                 (now_iso(), receipt_id))


def restore(conn: sqlite3.Connection, receipt_id: int) -> None:
    conn.execute(
        "UPDATE receipts SET status = CASE WHEN draft_json IS NULL THEN 'failed' ELSE 'read' END, updated_at = ?"
        " WHERE id = ? AND status = 'discarded'",
        (now_iso(), receipt_id),
    )


def release_event(conn: sqlite3.Connection, event_id: int) -> None:
    """A receipt's service is being deleted: the receipt goes back to be checked, and its warranties stop counting."""
    warranties.release(conn, event_id)
    conn.execute(
        "UPDATE receipts SET status = 'read', service_event_id = NULL, updated_at = ? WHERE service_event_id = ?",
        (now_iso(), event_id),
    )


def learned(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    return {row[0]: json.loads(row[1]) for row in conn.execute("SELECT phrase, covers_json FROM service_aliases")}
