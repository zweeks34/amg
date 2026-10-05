"""Download your data: every sheet, every confirmed receipt named for a person, and nothing that isn't yours to read."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date

import report_fixtures as rf  # tests/ is on pytest's path

from amg.reports import csvs, export
from amg.repo import documents, fuel, odometer, prices, receipts, schedules, vehicles
from amg.repo.schedules import ItemInput

TODAY = date(2026, 10, 4)


def sheet(zf, name):
    text = zf.read(name).decode("utf-8")
    assert text.startswith(csvs.BOM)
    return list(csv.DictReader(io.StringIO(text[len(csvs.BOM):])))


def build(conn, tmp_path):
    path = tmp_path / "data.zip"
    missing = export.write(conn, path, TODAY)
    return zipfile.ZipFile(path), missing


def test_everything_is_there(conn, tmp_path):
    outback = rf.car(conn, "Outback", year=2016, make="Subaru", powertrain="gas", vin="4S4BSANC5G3200001")
    sold = rf.car(conn, "Old Tacoma")
    vehicles.archive(conn, sold)
    rf.receipt(conn, outback, rf.pdf_bytes("MIDAS"), "scan 1.pdf", date="2019-03-04", shop_name="Midas")
    rf.receipt(conn, outback, rf.pdf_bytes("MIDAS AGAIN"), "scan 2.pdf", date="2019-03-04", shop_name="Midas")
    rf.receipt(conn, outback, rf.image_bytes("JPEG"), "photo.jpg", date="2020-05-06", shop_name='A/B: "Best" Garage')
    rf.receipt(conn, sold, rf.pdf_bytes("TACOMA"), "t.pdf", date="2015-11-02", shop_name="Bob's")
    waiting, _ = rf.receipt(conn, outback, rf.pdf_bytes("WAITING"), "waiting.pdf", confirm=False, date="2025-01-01")
    thrown, _ = rf.receipt(conn, outback, rf.pdf_bytes("THROWN"), "thrown.pdf", confirm=False, date="2025-01-02")
    receipts.discard(conn, thrown)
    rf.visit(conn, outback, "2021-06-01", source="diy", lines=[rf.line("Oil change", 4_000, "engine_oil")])
    fuel.create(conn, outback, fuel.FillInput("2026-09-01", 92_000, "gas", 12.5, cost_cents=4_375))
    odometer.add(conn, outback, "2026-09-20", 92_300, "from the dash")
    manual, _ = documents.store(conn, rf.pdf_bytes("OWNER'S MANUAL"), "2016 Outback manual.pdf")
    draft = schedules.create_draft(conn, outback, "template", draft={"origin": "template", "items": []})
    schedules.confirm(conn, draft, outback, [ItemInput("Oil and filter", "replace", ["engine_oil", "oil_filter"],
                                                       interval_miles=6_000, interval_months=6, source="manual",
                                                       document_id=manual["id"], page=31)], {})
    prices.set_yours(conn, outback, ["engine_oil", "oil_filter"], "replace", "Oil and filter", 8_500)

    zf, missing = build(conn, tmp_path)
    names = sorted(zf.namelist())
    assert names == [
        "README.txt", "cars.csv", "fuel.csv", "manuals/2016 Outback manual.pdf", "odometer.csv", "prices.csv",
        "receipts/2015-11-02 Bob's - Old Tacoma.pdf",
        "receipts/2019-03-04 Midas - Outback (2).pdf",
        "receipts/2019-03-04 Midas - Outback.pdf",
        "receipts/2020-05-06 A B Best Garage - Outback.jpg",       # what a file name can't hold, taken out
        "schedules.csv", "service-history.csv",
    ] and missing == []
    assert zf.read("receipts/2019-03-04 Midas - Outback.pdf") == documents.path(
        documents.by_sha(conn, conn.execute("SELECT sha256 FROM documents WHERE filename = 'scan 1.pdf'")
                         .fetchone()[0])).read_bytes()

    cars = sheet(zf, "cars.csv")
    assert [(c["Name"], c["Archived"] != "") for c in cars] == [("Outback", False), ("Old Tacoma", True)]
    assert cars[0]["VIN"] == "4S4BSANC5G3200001" and cars[0]["Year"] == "2016" and cars[0]["Powertrain"] == "Gas"
    history = sheet(zf, "service-history.csv")
    assert {row["Date"] for row in history} == {"2015-11-02", "2019-03-04", "2020-05-06", "2021-06-01"}
    assert sheet(zf, "fuel.csv")[0] == {
        "Car": "Outback", "Date": "2026-09-01", "Odometer": "92000", "Energy": "Gas", "Quantity": "12.5",
        "Unit": "gal", "Cost": "43.75", "Full": "Yes", "Missed one before": "No", "Place": "", "Note": ""}
    readings = sheet(zf, "odometer.csv")
    assert {"Car": "Outback", "Date": "2026-09-20", "Miles": "92300", "From": "Typed in"} in readings
    assert {"Car": "Outback", "Date": "2026-09-01", "Miles": "92000", "From": "A fill-up"} in readings
    item = sheet(zf, "schedules.csv")[0]
    assert (item["Item"], item["Every miles"], item["Every months"], item["Services"], item["From"], item["Page"]) == (
        "Oil and filter", "6000", "6", "Engine oil; Oil filter", "Owner's manual", "31")
    price = sheet(zf, "prices.csv")[0]
    assert (price["Job"], price["From"], price["Low"], price["High"]) == ("Oil and filter", "You", "85.00", "85.00")

    readme = zf.read("README.txt").decode("utf-8")
    assert "Made October 4, 2026: 2 car(s), 4 receipt(s), 1 manual(s)." in readme
    assert "can't be put back into AMG" in readme
    everything = b"".join(zf.read(name) for name in names)
    assert b"WAITING" not in everything and b"THROWN" not in everything     # not in anyone's history yet
    assert not any(name.endswith((".sqlite3", ".env")) for name in names)


def test_a_missing_file_is_said(conn, tmp_path):
    car = rf.car(conn, "Outback")
    rf.receipt(conn, car, rf.pdf_bytes("GONE"), "gone.pdf", date="2019-03-04", shop_name="Midas")
    documents.path(conn.execute("SELECT * FROM documents").fetchone()).unlink()
    zf, missing = build(conn, tmp_path)
    assert missing == ["gone.pdf"] and not [n for n in zf.namelist() if n.startswith("receipts/")]
    assert "1 file(s) the database lists weren't on the server" in zf.read("README.txt").decode("utf-8")


def test_an_empty_garage_still_downloads(conn, tmp_path):
    zf, _ = build(conn, tmp_path)
    assert sheet(zf, "cars.csv") == [] and "0 car(s)" in zf.read("README.txt").decode("utf-8")


def test_names_a_file_can_hold():
    assert export.safe('A/B: "Best" Garage?') == "A B Best Garage"
    assert export.safe("  ..Midas..  ") == "Midas"
    assert len(export.safe("x" * 300)) == 100
