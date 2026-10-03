"""Reading receipts and schedules in a background thread, so an upload answers straight away.

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

from .. import db
from ..repo import documents, jobs, receipts, schedules, services, vehicles
from . import claude, drafts, manuals, schedule_drafts
from . import receipts as reader

log = logging.getLogger(__name__)

JOB_KIND = "read_receipts"
SCHEDULE_JOB = "read_schedule"


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
