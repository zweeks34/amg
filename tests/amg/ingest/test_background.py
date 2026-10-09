from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pymupdf
import pytest
import receipt_fixtures as fx  # tests/ is on pytest's path
import schedule_fixtures as sfx

from amg.ingest import background, claude, manuals
from amg.ingest import receipts as reader
from amg.ingest import specs as spec_reader
from amg.ingest import warranties as warranty_reader
from amg.repo import documents, jobs, receipts, schedules, specs, vehicles, warranty_looks


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


def _fake_specs_read(outcomes):
    def read(path, car, pages=""):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return spec_reader.SpecsRead([35, 36], outcome, fx.USAGE)
    return read


SPEC_READING = spec_reader.SpecsExtraction(printed_for="2016 Outback", uncertain="", specs=[
    spec_reader.SpecValue(key="oil_grade", value="0W-20", page=35, note="")])


def test_specs_are_read_into_a_reading(conn, car, inline_jobs, monkeypatch):
    monkeypatch.setattr(spec_reader, "read_specs", _fake_specs_read([SPEC_READING]))
    row = specs.get_read(conn, background.read_specs(conn, car, _document(conn, "manual")))
    assert (row["status"], row["pages"], row["values"]) == ("read", [35, 36], {"oil_grade": {"value": "0W-20", "page": 35}})
    assert row["extraction"]["printed_for"] == "2016 Outback" and jobs.get(conn, row["job_id"])["status"] == "done"


def test_a_failed_specs_read_says_why_and_can_be_read_again(conn, car, inline_jobs, monkeypatch):
    monkeypatch.setattr(spec_reader, "read_specs", _fake_specs_read([
        manuals.ManualError("AMG couldn't find the specifications in this document."), SPEC_READING]))
    read_id = background.read_specs(conn, car, _document(conn, "manual"))
    assert specs.get_read(conn, read_id)["error"] == "AMG couldn't find the specifications in this document."
    background.read_specs_again(conn, read_id, "35-36")
    row = specs.get_read(conn, read_id)
    assert (row["status"], row["requested_pages"]) == ("read", "35-36")


def test_carry_on_finishes_a_stalled_specs_read(conn, car, monkeypatch):
    monkeypatch.setattr(background, "spawn", lambda job_id: None)
    read_id = background.read_specs(conn, car, _document(conn, "manual"))
    job_id = specs.get_read(conn, read_id)["job_id"]
    specs.claim_next(conn, job_id)
    monkeypatch.setattr(spec_reader, "read_specs", _fake_specs_read([SPEC_READING]))
    monkeypatch.setattr(background, "spawn", background.run)
    background.carry_on(conn, job_id)
    assert specs.get_read(conn, read_id)["status"] == "read"


# ---------- Looking through older receipts for warranties ----------


def _older(conn, car, text="Costco", **fields):
    """A receipt confirmed before AMG kept warranties: its extraction has none."""
    import report_fixtures as rf

    receipt_id, _ = rf.receipt(conn, car, rf.pdf_bytes(text), f"{text}.pdf", shop_name=text, date="2025-03-01",
                               lines=[fx.line("Interstate battery", 180.0, ["battery_12v"])], **fields)
    extraction = json.loads(conn.execute("SELECT extraction_json FROM receipts WHERE id = ?",
                                         (receipt_id,)).fetchone()[0])
    del extraction["warranties"]
    conn.execute("UPDATE receipts SET extraction_json = ?, input_tokens = 7000 WHERE id = ?",
                 (json.dumps(extraction), receipt_id))
    return receipt_id


def _answers(monkeypatch, outcomes):
    """claude.parse stand-in for the look: each call takes the next outcome (a list of warranties, or an exception)."""
    asked = []

    def parse(schema, system, content, effort="medium", **_):
        asked.append({"schema": schema, "system": system, "content": content, "effort": effort})
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return schema(warranties=outcome), fx.USAGE
    monkeypatch.setattr(warranty_reader.claude, "parse", parse)
    return asked


def test_only_confirmed_receipts_read_before_warranties_wait(conn, car):
    older = _older(conn, car)
    import report_fixtures as rf

    rf.receipt(conn, car, rf.pdf_bytes("New"), "new.pdf", shop_name="New", date="2026-01-01")
    unconfirmed = _older(conn, car, "Draft")
    receipts.release_event(conn, receipts.get(conn, unconfirmed)["service_event_id"])
    assert warranty_looks.waiting(conn) == [older]


def test_a_look_puts_its_finds_in_the_draft_to_be_checked(conn, car, inline_jobs, monkeypatch):
    receipt_id = _older(conn, car)
    asked = _answers(monkeypatch, [[fx.warranty(codes=[]), fx.warranty("Lifetime", months=None, lifetime=True,
                                                                        codes=["blinker_fluid", "battery_12v"])]])
    background.look_for_warranties(conn, warranty_looks.waiting(conn))
    [request] = asked
    assert request["effort"] == "low" and "List in `warranties`" in request["system"]
    assert any(block["type"] == "image" for block in request["content"])
    assert "- Interstate battery: battery_12v (replace)" in request["content"][-1]["text"]

    draft = receipts.get(conn, receipt_id)["draft"]
    today = date.today().isoformat()
    assert [(w["description"], w["codes"], w["found"]) for w in draft.warranties] == [
        ("36-month free replacement", ["battery_12v"], today), ("Lifetime", ["battery_12v"], today)]
    assert conn.execute("SELECT count(*) FROM warranties").fetchone()[0] == 0      # not until it's checked
    look = conn.execute("SELECT * FROM warranty_looks WHERE receipt_id = ?", (receipt_id,)).fetchone()
    assert (look["status"], look["found"], look["model"]) == ("done", 2, fx.USAGE.model)
    assert warranty_looks.waiting(conn) == [] and warranty_looks.to_check(conn)[0]["count"] == 2


def test_nothing_twice_by_wording(conn, car, inline_jobs, monkeypatch):
    receipt_id = _older(conn, car)
    draft = receipts.get(conn, receipt_id)["draft"]
    draft.warranties = [{"description": "36 month free replacement", "provider": "", "months": 36, "miles": None,
                         "lifetime": False, "codes": ["battery_12v"], "found": ""}]
    receipts.save_draft(conn, receipt_id, draft, car)
    _answers(monkeypatch, [[fx.warranty("36-MONTH FREE REPLACEMENT"), fx.warranty("Road hazard", codes=["tires"]),
                            fx.warranty("Road hazard!", codes=["tires"])]])
    background.look_for_warranties(conn, [receipt_id])
    assert [w["description"] for w in receipts.get(conn, receipt_id)["draft"].warranties] == [
        "36 month free replacement", "Road hazard"]


def test_a_failure_says_why_and_can_be_tried_again(conn, car, inline_jobs, monkeypatch):
    receipt_id = _older(conn, car)
    _answers(monkeypatch, [claude.ClaudeError("Claude took too long to answer. Try reading it again."), []])
    background.look_for_warranties(conn, [receipt_id])
    assert warranty_looks.failed(conn) == [receipt_id] and warranty_looks.waiting(conn) == []
    assert warranty_looks.progress(conn).failed[0]["error"].startswith("Claude took too long")
    background.look_for_warranties(conn, warranty_looks.failed(conn))
    assert warranty_looks.failed(conn) == [] and not warranty_looks.progress(conn)


def test_carry_on_finishes_a_stalled_look(conn, car, monkeypatch):
    receipt_id = _older(conn, car)
    monkeypatch.setattr(background, "spawn", lambda job_id: None)       # the thread dies at once
    job_id = background.look_for_warranties(conn, [receipt_id])
    warranty_looks.claim_next(conn, job_id)
    conn.execute("UPDATE jobs SET heartbeat_at = '2020-01-01T00:00:00Z' WHERE id = ?", (job_id,))
    progress = warranty_looks.progress(conn)
    assert progress.running and progress.stalled and (progress.done, progress.total) == (0, 1)
    _answers(monkeypatch, [[]])
    monkeypatch.setattr(background, "spawn", background.run)
    background.carry_on(conn, job_id)
    assert conn.execute("SELECT status FROM warranty_looks").fetchone()[0] == "done"
    assert jobs.get(conn, job_id)["status"] == "done"


def test_the_estimate(conn, car):
    first = _older(conn, car)
    second = _older(conn, car, "Midas")
    conn.execute("UPDATE receipts SET input_tokens = NULL WHERE id = ?", (second,))
    per_in, per_out, _ = claude.PRICES.get(claude.model(), claude.PRICES[claude.DEFAULT_MODEL])
    expected = (7000 * per_in + 1000 * per_out) + (warranty_looks.TOKENS_A_PAGE * per_in + 1000 * per_out)
    assert warranty_looks.estimate(conn, [first, second]) == round(expected / 1_000_000 * 100)
    assert warranty_looks.estimate(conn, []) == 0
