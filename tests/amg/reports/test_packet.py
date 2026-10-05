"""The sale packet: the history, then every confirmed receipt for the car and nothing else."""

from __future__ import annotations

from datetime import date

import pymupdf
import pytest
import report_fixtures as rf  # tests/ is on pytest's path

from amg.repo import documents, vehicles
from amg.reports import packet

TODAY = date(2026, 10, 4)


def text(page):
    return page.get_text(flags=0)        # ligatures spelled out: "fi", not "ﬁ"


@pytest.fixture
def outback(conn):
    car = rf.car(conn, "Outback", year=2016, make="Subaru", model="Outback", trim="2.5i Premium",
                 vin="4S4BSANC5G3200001", in_service_date="2016-03-12")
    rf.receipt(conn, car, rf.pdf_bytes("MIDAS PAGE ONE", "MIDAS PAGE TWO"), "midas.pdf",
               date="2017-08-09", shop_name="Midas", odometer=15_900)
    rf.receipt(conn, car, rf.image_bytes("PNG"), "corner.png", date="2019-11-30", shop_name="Corner Garage",
               odometer=33_800)
    rf.receipt(conn, car, rf.image_bytes("JPEG"), "dealer.jpg", date="2024-10-02", shop_name="Subaru of Springfield",
               odometer=None)
    rf.receipt(conn, car, rf.pdf_bytes("STILL WAITING"), "waiting.pdf", confirm=False, date="2025-01-01")
    rf.visit(conn, car, "2019-06-08", source="diy", odometer=30_210, notes="Kept the old filter, it was fine",
             lines=[rf.line("Engine air filter", 1_899, "engine_air_filter", kind="part"),
                    rf.line("Shop rags", 500, kind="fee")])
    other = rf.car(conn, "Civic")
    rf.receipt(conn, other, rf.pdf_bytes("THE CIVIC'S RECEIPT"), "civic.pdf", date="2020-01-01")
    return vehicles.get(conn, car)


def build(conn, car, tmp_path):
    path = tmp_path / "packet.pdf"
    count = packet.write(conn, car, path, TODAY)
    doc = pymupdf.open(path)
    assert doc.page_count == count
    return doc


def test_the_packet_holds_every_confirmed_receipt_for_the_car(conn, outback, tmp_path):
    doc = build(conn, outback, tmp_path)
    toc = doc.get_toc()
    front = toc[1][2] - 1
    assert doc.page_count == front + 2 + 1 + 1                       # the 2-page PDF, the PNG, the JPG
    assert [entry[1] for entry in toc] == [
        "Service history",
        "2017-08-09 · Midas · 15,900 mi",
        "2019-11-30 · Corner Garage · 33,800 mi",
        "2024-10-02 · Subaru of Springfield",
    ]
    assert [entry[2] for entry in toc] == [1, front + 1, front + 3, front + 4]
    assert "MIDAS PAGE ONE" in text(doc[front]) and "MIDAS PAGE TWO" in text(doc[front + 1])
    everything = "".join(text(page) for page in doc)
    assert "STILL WAITING" not in everything and "CIVIC" not in everything


def test_the_history_is_for_a_buyer(conn, outback, tmp_path):
    doc = build(conn, outback, tmp_path)
    history = text(doc[0])
    assert "2016 Subaru Outback 2.5i Premium" in history and "4S4BSANC5G3200001" in history
    assert "prepared October 4, 2026 from the owner's records" in history
    assert "4 services, Aug 2017 to Oct 2024." in history
    assert "The receipt for 3 of them follows this" in history
    assert "Owner's own work" in history and "Engine air filter" in history
    assert "Shop rags" not in history                               # a fee isn't work
    assert "Kept the old filter" not in history                     # notes are yours
    for _, _, start in doc.get_toc()[1:]:
        assert f"p. {start}" in history                               # the table points at the right pages
    assert f"page 1 of {doc.page_count}" in history


def test_a_missing_file_is_said_and_the_rest_still_go_in(conn, outback, tmp_path):
    lost = documents.by_sha(conn, conn.execute(
        "SELECT d.sha256 FROM documents d WHERE d.filename = 'corner.png'").fetchone()[0])
    documents.path(lost).unlink()
    doc = build(conn, outback, tmp_path)
    assert len(doc.get_toc()) == 3 and "file missing" in text(doc[0])


def test_a_car_with_nothing_on_file(conn, tmp_path):
    car = vehicles.get(conn, rf.car(conn, "Bare"))
    doc = build(conn, car, tmp_path)
    assert doc.page_count == 1 and "No services are on file for this car yet." in text(doc[0])
    assert packet.title(car) == "Bare"


def test_work_is_said_in_sentence_case():
    visit = {"lines": [
        {"covers": [{"name": "Engine oil"}, {"name": "Oil filter"}], "kind": "labor", "description": ""},
        {"covers": [{"name": "Oil filter"}, {"name": "12-volt battery"}], "kind": "part", "description": ""},
        {"covers": [], "kind": "labor", "description": "Diagnose rattle"},
        {"covers": [], "kind": "other", "description": "Coupon"},
    ]}
    assert packet.work(visit) == "Engine oil, oil filter, 12-volt battery, diagnose rattle"
