"""Download your data: every sheet, every confirmed receipt named for a person, and nothing that isn't yours to read."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import date

import report_fixtures as rf  # tests/ is on pytest's path

from amg.reports import csvs, export
from amg.repo import documents, fuel, odometer, prices, receipts, renewals, schedules, specs, vehicles
from amg.repo.renewals import RenewalInput
from amg.repo.schedules import ItemInput
from amg.repo.specs import SpecInput

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
                                                       document_id=manual["id"], page=31),
                                             ItemInput("Washer fluid", "replace", ["washer_fluid"], interval_months=3,
                                                       counts_from="2026-09-15")], {})
    prices.set_yours(conn, outback, ["engine_oil", "oil_filter"], "replace", "Oil and filter", 8_500)
    inspected = rf.visit(conn, outback, "2026-09-01", shop="Corner Garage",
                         lines=[rf.line("State inspection", 2_000, "state_inspection", action="perform")])
    renewals.create(conn, outback, RenewalInput("safety", "2027-09-30", "2026-09-01", 2_000,
                                                service_event_id=inspected))
    renewals.create(conn, outback, RenewalInput("registration", "2027-03-31", note="Online, 2 years"))
    specs.save(conn, outback, [SpecInput("oil_grade", "0W-20"), SpecInput("custom", "168", label="Trunk light")])

    zf, missing = build(conn, tmp_path)
    names = sorted(zf.namelist())
    assert names == [
        "README.txt", "cars.csv", "fuel.csv", "inspections-and-registration.csv", "manuals/2016 Outback manual.pdf",
        "odometer.csv", "prices.csv", "recalls.csv",
        "receipts/2015-11-02 Bob's - Old Tacoma.pdf",
        "receipts/2019-03-04 Midas - Outback (2).pdf",
        "receipts/2019-03-04 Midas - Outback.pdf",
        "receipts/2020-05-06 A B Best Garage - Outback.jpg",       # what a file name can't hold, taken out
        "recommendations.csv", "schedules.csv", "service-history.csv", "specs.csv",
    ] and missing == []
    assert zf.read("receipts/2019-03-04 Midas - Outback.pdf") == documents.path(
        documents.by_sha(conn, conn.execute("SELECT sha256 FROM documents WHERE filename = 'scan 1.pdf'")
                         .fetchone()[0])).read_bytes()

    cars = sheet(zf, "cars.csv")
    assert [(c["Name"], c["Archived"] != "") for c in cars] == [("Outback", False), ("Old Tacoma", True)]
    assert cars[0]["VIN"] == "4S4BSANC5G3200001" and cars[0]["Year"] == "2016" and cars[0]["Powertrain"] == "Gas"
    history = sheet(zf, "service-history.csv")
    assert {row["Date"] for row in history} == {"2015-11-02", "2019-03-04", "2020-05-06", "2021-06-01", "2026-09-01"}
    assert sheet(zf, "fuel.csv")[0] == {
        "Car": "Outback", "Date": "2026-09-01", "Odometer": "92000", "Energy": "Gas", "Quantity": "12.5",
        "Unit": "gal", "Cost": "43.75", "Full": "Yes", "Missed one before": "No", "Place": "", "Note": ""}
    readings = sheet(zf, "odometer.csv")
    assert {"Car": "Outback", "Date": "2026-09-20", "Miles": "92300", "From": "Typed in"} in readings
    assert {"Car": "Outback", "Date": "2026-09-01", "Miles": "92000", "From": "A fill-up"} in readings
    item, fluid = sheet(zf, "schedules.csv")
    assert (item["Item"], item["Every miles"], item["Every months"], item["Services"], item["From"], item["Page"],
            item["Count from"]) == ("Oil and filter", "6000", "6", "Engine oil; Oil filter", "Owner's manual", "31", "")
    assert (fluid["Item"], fluid["Every months"], fluid["Count from"]) == ("Washer fluid", "3", "2026-09-15")
    assert sheet(zf, "inspections-and-registration.csv") == [
        {"Car": "Outback", "What": "Safety inspection", "Done on": "2026-09-01", "Expires": "2027-09-30",
         "Cost": "20.00", "Note": "", "Service": "2026-09-01 Corner Garage"},
        {"Car": "Outback", "What": "Registration", "Done on": "", "Expires": "2027-03-31", "Cost": "", "Note": "Online, 2 years",
         "Service": ""},
    ]
    recommended = sheet(zf, "recommendations.csv")          # each test receipt recommends a brake fluid flush
    assert [(r["Car"], r["Date"], r["Now"]) for r in recommended] == [
        ("Outback", "2019-03-04", "Open"), ("Outback", "2019-03-04", "Open"), ("Outback", "2020-05-06", "Open"),
        ("Old Tacoma", "2015-11-02", "Open")]
    assert (recommended[0]["Shop"], recommended[0]["Recommendation"], recommended[0]["Services"],
            recommended[0]["Quoted"]) == ("Midas", "Brake fluid flush", "Brake fluid", "129.95")
    assert sheet(zf, "specs.csv") == [
        {"Car": "Outback", "Group": "Engine oil", "Spec": "Oil grade", "Value": "0W-20", "From": "You", "Page": ""},
        {"Car": "Outback", "Group": "Other", "Spec": "Trunk light", "Value": "168", "From": "You", "Page": ""},
    ]
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
    assert sheet(zf, "inspections-and-registration.csv") == []


def test_names_a_file_can_hold():
    assert export.safe('A/B: "Best" Garage?') == "A B Best Garage"
    assert export.safe("  ..Midas..  ") == "Midas"
    assert len(export.safe("x" * 300)) == 100
