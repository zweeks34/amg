from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
import receipt_fixtures as fx  # tests/ is on pytest's path

from amg.ingest import background, claude
from amg.ingest import receipts as reader
from amg.repo import documents, jobs, receipts


@pytest.fixture
def inline_jobs(monkeypatch):
    monkeypatch.setattr(background, "spawn", background.run)


def _document(conn, text):
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), text)
        document, _ = documents.store(conn, doc.tobytes(), f"{text}.pdf")
    return document["id"]


def _fake_read(outcomes):
    """read_receipt stand-in: each call takes the next outcome (an extraction or an exception)."""
    def read(path, types, mode="vision", effort="medium"):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return reader.ReceiptRead(Path(path), mode, [], outcome, fx.USAGE, [])
    return read


def test_a_job_reads_every_receipt_and_finishes(conn, inline_jobs, monkeypatch):
    monkeypatch.setattr(reader, "read_receipt", _fake_read([fx.extraction(), fx.extraction(total=10.0)]))
    job_id = background.start(conn, [_document(conn, "a"), _document(conn, "b")])
    inbox = receipts.inbox(conn)
    assert [r["total_cents"] for r in inbox["to_check"]] == [7779, 1000]
    assert jobs.get(conn, job_id)["status"] == "done"


def test_one_failure_doesnt_stop_the_batch(conn, inline_jobs, monkeypatch):
    monkeypatch.setattr(reader, "read_receipt", _fake_read([
        claude.ClaudeError("Claude took too long to answer."), RuntimeError("boom"), fx.extraction()]))
    background.start(conn, [_document(conn, "a"), _document(conn, "b"), _document(conn, "c")])
    inbox = receipts.inbox(conn)
    assert [r["error"] for r in inbox["failed"]] == [
        "Claude took too long to answer.", "Something went wrong reading this file (RuntimeError)."]
    assert len(inbox["to_check"]) == 1


def test_read_again_after_a_failure(conn, inline_jobs, monkeypatch):
    monkeypatch.setattr(reader, "read_receipt", _fake_read([claude.ClaudeError("down"), fx.extraction()]))
    background.start(conn, [_document(conn, "a")])
    receipt_id = receipts.inbox(conn)["failed"][0]["id"]
    background.read_again(conn, receipt_id)
    assert receipts.get(conn, receipt_id)["status"] == "read"


def test_carry_on_finishes_a_stalled_job(conn, monkeypatch):
    monkeypatch.setattr(background, "spawn", lambda job_id: None)   # the thread "dies" before starting
    job_id = background.start(conn, [_document(conn, "a")])
    receipts.claim_next(conn, job_id)                                # it got as far as claiming one
    monkeypatch.setattr(reader, "read_receipt", _fake_read([fx.extraction()]))
    monkeypatch.setattr(background, "spawn", background.run)
    background.carry_on(conn, job_id)
    assert len(receipts.inbox(conn)["to_check"]) == 1
