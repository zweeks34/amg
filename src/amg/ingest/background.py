"""Reading receipts and schedules, and pricing jobs, in a background thread, so a request answers straight away.

The upload request stores the files, makes a job and starts a thread; the
page watches the database. A file and not memory, because uvicorn runs
several workers and the page polling for progress lands on whichever one it
lands on — state held in the reading thread would be invisible to it.

Each receipt is saved the moment it's read, so a thread killed by a restart
loses at most the one it was on; ``carry_on`` picks the job up again.
"""

from __future__ import annotations

import logging
import threading
from datetime import date

from .. import db
from ..engine import forecast
from ..repo import documents, jobs, prices, receipts, schedules, services, vehicles
from . import claude, drafts, manuals, schedule_drafts
from . import prices as pricer
from . import receipts as reader

log = logging.getLogger(__name__)

JOB_KIND = "read_receipts"
SCHEDULE_JOB = "read_schedule"
PRICE_JOB = "price_jobs"


def start(conn, document_ids: list[int], vehicle_id: int | None = None) -> int:
    """Queue documents for reading and start a thread on them; returns the job id."""
    job_id = jobs.create(conn, JOB_KIND)
    for document_id in document_ids:
        receipts.create(conn, document_id, job_id, vehicle_id)
    spawn(job_id)
    return job_id


def read_again(conn, receipt_id: int) -> int:
    job_id = jobs.create(conn, JOB_KIND)
    receipts.requeue(conn, receipt_id, job_id)
    spawn(job_id)
    return job_id


def read_schedule(conn, vehicle_id: int, origin: str, document_id: int | None = None, pages: str = "") -> int:
    """Queue a manual (``origin`` manual) or a draft from Claude (claude) for a car; returns the draft id."""
    job_id = jobs.create(conn, SCHEDULE_JOB)
    draft_id = schedules.create_draft(conn, vehicle_id, origin, document_id, pages, job_id)
    spawn(job_id)
    return draft_id


def read_schedule_again(conn, draft_id: int, pages: str | None = None) -> None:
    job_id = jobs.create(conn, SCHEDULE_JOB)
    schedules.requeue(conn, draft_id, job_id, pages)
    spawn(job_id)


def price(conn, vehicle_id: int, wanted: list[tuple]) -> int:
    """Ask Claude to price jobs — (codes, action, name) — for a car; returns the job id."""
    job_id = jobs.create(conn, PRICE_JOB)
    prices.queue_claude(conn, vehicle_id, wanted, job_id)
    spawn(job_id)
    return job_id


def carry_on(conn, job_id: int) -> None:
    jobs.resume(conn, job_id)
    spawn(job_id)


def spawn(job_id: int) -> None:
    """Run the job on a daemon thread. Tests replace this to run it inline."""
    threading.Thread(target=run, args=(job_id,), name=f"amg-job-{job_id}", daemon=True).start()


def run(job_id: int) -> None:
    conn = db.connect()
    try:
        job = jobs.get(conn, job_id)
        if job is not None and job["kind"] == SCHEDULE_JOB:
            while (draft_id := schedules.claim_next(conn, job_id)) is not None:
                read_one_schedule(conn, draft_id)
                jobs.heartbeat(conn, job_id)
        elif job is not None and job["kind"] == PRICE_JOB:
            while rows := prices.claim(conn, job_id):
                price_rows(conn, rows)
                jobs.heartbeat(conn, job_id)
        else:
            while (receipt_id := receipts.claim_next(conn, job_id)) is not None:
                read_one(conn, receipt_id)
                jobs.heartbeat(conn, job_id)
        jobs.finish(conn, job_id)
    finally:
        conn.close()


def read_one(conn, receipt_id: int) -> None:
    row = conn.execute("SELECT document_id FROM receipts WHERE id = ?", (receipt_id,)).fetchone()
    document = documents.get(conn, row["document_id"])
    types = {r["code"]: dict(r) for r in services.list_types(conn)}
    try:
        result = reader.read_receipt(documents.path(document), list(types.values()), mode="vision")
    except (claude.ClaudeError, ValueError) as err:
        receipts.mark_failed(conn, receipt_id, str(err))
        return
    except Exception as err:  # never let one bad file stop the rest of the batch
        log.exception("reading receipt %s failed", receipt_id)
        receipts.mark_failed(conn, receipt_id, f"Something went wrong reading this file ({type(err).__name__}).")
        return
    draft = drafts.from_extraction(result.extraction, types, receipts.learned(conn))
    receipts.mark_read(conn, receipt_id, result.extraction.model_dump(), draft, result.warnings, result.usage)


def read_one_schedule(conn, draft_id: int) -> None:
    row = schedules.get_draft(conn, draft_id)
    car = vehicles.get(conn, row["vehicle_id"])
    types = {r["code"]: dict(r) for r in services.list_types(conn)}
    try:
        if row["origin"] == "manual":
            if row["document"] is None:
                raise manuals.ManualError("The manual's file is gone. Upload it again.")
            result = manuals.read_manual(documents.path(row["document"]), car, list(types.values()),
                                         pages=row["requested_pages"])
        else:
            result = manuals.draft_schedule(car, list(types.values()))
    except (claude.ClaudeError, manuals.ManualError) as err:
        schedules.mark_failed(conn, draft_id, str(err))
        return
    except Exception as err:  # a bad file must not leave the draft "reading" forever
        log.exception("reading schedule draft %s failed", draft_id)
        schedules.mark_failed(conn, draft_id, f"Something went wrong reading this ({type(err).__name__}).")
        return
    draft, warnings = schedule_drafts.from_extraction(
        result.extraction, types, row["origin"], row["document_id"], result.pages or None
    )
    schedules.mark_read(conn, draft_id, result.extraction.model_dump(), draft.to_dict(), warnings, result.pages,
                        result.usage)


def price_rows(conn, rows: list) -> None:
    """One call to Claude for a car's queued jobs; each row priced, or failed with the reason."""
    vehicle_id = rows[0]["vehicle_id"]
    car = vehicles.get(conn, vehicle_id)
    names = {r["code"]: r["name"] for r in services.list_types(conn)}
    wanted = [{"key": f"j{row['id']}", "name": row["name"], "action": row["action"],
               "types": [names.get(code, code) for code in row["codes"].split(",")]} for row in rows]
    visits = [forecast.visit_from(v) for v in prices.visits(conn) if v["vehicle_id"] == vehicle_id]
    try:
        read = pricer.ask_claude(car, wanted, pricer.anchors(schedules.items(conn, vehicle_id), visits, date.today()))
    except claude.ClaudeError as err:
        for row in rows:
            prices.mark_failed(conn, row["id"], str(err))
        return
    except Exception as err:  # never leave prices "asking" forever
        log.exception("pricing jobs for car %s failed", vehicle_id)
        for row in rows:
            prices.mark_failed(conn, row["id"], f"Something went wrong asking Claude ({type(err).__name__}).")
        return
    for row in rows:
        key = f"j{row['id']}"
        if key in read.prices:
            got = read.prices[key]
            prices.mark_priced(conn, row["id"], got.low_cents, got.high_cents, got.note, read.usage, share=len(read.prices))
        else:
            prices.mark_failed(conn, row["id"], read.missing.get(key, "Claude gave no price for this."))
