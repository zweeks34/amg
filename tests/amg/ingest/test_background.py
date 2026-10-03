from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
import receipt_fixtures as fx  # tests/ is on pytest's path
import schedule_fixtures as sfx

from amg.ingest import background, claude, manuals
from amg.ingest import receipts as reader
from amg.repo import documents, jobs, receipts, schedules, vehicles


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


# ---------- Schedules ----------


def _fake_schedule_read(outcomes):
    def read(path, car, types, pages=""):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return manuals.ScheduleRead([1, 2], outcome, fx.USAGE, [])
    return read


@pytest.fixture
def car(conn):
    return vehicles.create(conn, vehicles.VehicleFields(name="Outback", year=2016, make="Subaru", model="Outback"))


def test_a_manual_is_read_into_a_draft(conn, car, inline_jobs, monkeypatch):
    monkeypatch.setattr(manuals, "read_manual", _fake_schedule_read([sfx.sample()]))
    draft_id = background.read_schedule(conn, car, "manual", _document(conn, "manual"))
    draft = schedules.get_draft(conn, draft_id)
    assert (draft["status"], draft["pages"]) == ("read", [1, 2])
    names = [(item["name"], item["applies"], item["included"]) for item in draft["draft"]["items"]]
    assert ("Engine oil", "normal", True) in names and ("Timing Belt (WRX/WRX STI)", "always", False) in names
    assert jobs.get(conn, draft["job_id"])["status"] == "done"


def test_claude_drafts_a_schedule_from_the_car(conn, car, inline_jobs, monkeypatch):
    seen = []

    def draft_schedule(vehicle, types):
        seen.append(vehicle["model"])
        return manuals.ScheduleRead([], sfx.sample(), fx.USAGE, [])

    monkeypatch.setattr(manuals, "draft_schedule", draft_schedule)
    draft = schedules.get_draft(conn, background.read_schedule(conn, car, "claude"))
    assert seen == ["Outback"]
    assert {item["source"] for item in draft["draft"]["items"]} == {"claude"}


def test_a_failed_schedule_read_says_why_and_can_be_read_again(conn, car, inline_jobs, monkeypatch):
    monkeypatch.setattr(manuals, "read_manual", _fake_schedule_read([
        manuals.ManualError("Type the page numbers that hold it"), sfx.sample()]))
    draft_id = background.read_schedule(conn, car, "manual", _document(conn, "manual"))
    assert schedules.get_draft(conn, draft_id)["error"] == "Type the page numbers that hold it"
    background.read_schedule_again(conn, draft_id, "1-2")
    draft = schedules.get_draft(conn, draft_id)
    assert (draft["status"], draft["requested_pages"]) == ("read", "1-2")


def test_carry_on_finishes_a_stalled_schedule(conn, car, monkeypatch):
    monkeypatch.setattr(background, "spawn", lambda job_id: None)
    draft_id = background.read_schedule(conn, car, "claude")
    job_id = schedules.get_draft(conn, draft_id)["job_id"]
    schedules.claim_next(conn, job_id)
    monkeypatch.setattr(manuals, "draft_schedule", lambda vehicle, types: manuals.ScheduleRead([], sfx.sample(), fx.USAGE))
    monkeypatch.setattr(background, "spawn", background.run)
    background.carry_on(conn, job_id)
    assert schedules.get_draft(conn, draft_id)["status"] == "read"
