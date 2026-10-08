"""Shop recommendations, read from confirmed receipts, and what you decided about each.

Every test receipt (receipt_fixtures) recommends a brake fluid flush, quoted $129.95.
"""

from __future__ import annotations

import report_fixtures as rf  # tests/ is on pytest's path

from amg.repo import follow_ups, receipts
from amg.web import follow_ups as follow_up_words


def test_only_confirmed_receipts_count(conn):
    car = rf.car(conn, "Outback")
    confirmed, event = rf.receipt(conn, car, rf.pdf_bytes("ONE"), "one.pdf", date="2026-03-03", shop_name="Midas")
    rf.receipt(conn, car, rf.pdf_bytes("TWO"), "two.pdf", confirm=False, date="2026-04-04")
    (rec,) = follow_ups.recommendations(conn, car)
    assert (rec.receipt_id, rec.event_id, rec.shop, rec.description, rec.codes, rec.quoted_cents, rec.key) == (
        confirmed, event, "Midas", "Brake fluid flush", ("brake_fluid",), 12_995, "brake fluid flush")
    assert follow_ups.find(conn, confirmed, "brake fluid flush") == (rec, car)
    assert follow_ups.find(conn, confirmed, "something else") is None


def test_skip_and_undo(conn):
    car = rf.car(conn, "Outback")
    receipt, _ = rf.receipt(conn, car, rf.pdf_bytes("ONE"), "one.pdf", date="2026-03-03")
    follow_ups.skip(conn, receipt, "brake fluid flush")
    loaded = follow_up_words.load(conn, {"id": car})
    assert loaded.open == [] and [f.rec.receipt_id for f in loaded.skipped] == [receipt]
    follow_ups.undo(conn, receipt, "brake fluid flush")
    assert len(follow_up_words.load(conn, {"id": car}).open) == 1


def test_rewording_a_recommendation_reopens_it(conn):
    car = rf.car(conn, "Outback")
    receipt, _ = rf.receipt(conn, car, rf.pdf_bytes("ONE"), "one.pdf", date="2026-03-03")
    follow_ups.skip(conn, receipt, "brake fluid flush")
    draft = receipts.get(conn, receipt)["draft"]
    draft.recommendations[0]["description"] = "Flush the brake fluid"
    receipts.confirm(conn, receipt, draft, car)
    (reopened,) = follow_up_words.load(conn, {"id": car}).open
    assert reopened.rec.key == "flush the brake fluid"
