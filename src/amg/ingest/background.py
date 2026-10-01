"""Reading receipts in a background thread, so an upload answers straight away.

The upload request stores the files, makes a job and starts a thread; the
receipts page watches the database. A file and not memory, because gunicorn
runs several workers and the page polling for progress lands on whichever one
it lands on — state held in the reading thread would be invisible to it.

Each receipt is saved the moment it's read, so a thread killed by a restart
loses at most the one it was on; ``carry_on`` picks the job up again.
"""

from __future__ import annotations

import logging
import threading

from .. import db
from ..repo import documents, jobs, receipts, services
from . import claude, drafts
from . import receipts as reader

log = logging.getLogger(__name__)

JOB_KIND = "read_receipts"


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


def carry_on(conn, job_id: int) -> None:
    jobs.resume(conn, job_id)
    spawn(job_id)


def spawn(job_id: int) -> None:
    """Run the job on a daemon thread. Tests replace this to run it inline."""
    threading.Thread(target=run, args=(job_id,), name=f"amg-job-{job_id}", daemon=True).start()


def run(job_id: int) -> None:
    conn = db.connect()
    try:
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
