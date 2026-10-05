"""CSV: what you download reads back as what the report said."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

import report_fixtures as rf  # tests/ is on pytest's path

from amg.engine.fuel import Fill
from amg.reports import csvs, fuel, history, spending
from amg.reports.filters import Filters
from amg.repo import reports
from amg.web.fuel_status import UNITS


def read(text):
    assert text.startswith(csvs.BOM)                    # so Excel reads it as UTF-8
    return list(csv.DictReader(io.StringIO(text[len(csvs.BOM):])))


def cents(value):
    return int(Decimal(value) * 100) if value else None


def test_the_history_round_trips(conn):
    car = rf.car(conn, "Outback")
    rf.visit(conn, car, "2025-02-03", shop='Joe\'s "Best" Garage, Inc.', odometer=61_250, invoice="=A1", tax=412,
             total=12_345, notes="Cold start at 5 °F\nCustomer café visit",
             lines=[rf.line("Brake pads, front\nand rear", 9_999, "brake_pads"),
                    rf.line("-Oil filter", 1_234, "oil_filter", kind="part"),
                    rf.line("Discount", -500, kind="other"),
                    rf.line("Brake fluid check", 0, "brake_fluid", action="inspect")])
    report = history.load(conn, Filters())
    rows = read(csvs.history_csv(report, Filters()))
    assert list(rows[0]) == list(csvs.HISTORY_COLUMNS)
    assert [row["Line"] for row in rows] == ["Brake pads, front\nand rear", "'-Oil filter", "Discount",
                                             "Brake fluid check"]
    assert [cents(row["Amount"]) for row in rows] == [9_999, 1_234, -500, 0]
    first = rows[0]
    assert (first["Car"], first["Date"], first["Odometer"], first["Where"]) == ("Outback", "2025-02-03", "61250",
                                                                               'Joe\'s "Best" Garage, Inc.')
    assert (first["Invoice"], first["Source"], first["Kind"]) == ("'=A1", "Shop", "Labor")
    assert (first["Services"], first["Category"]) == ("Brake pads", "Brakes")
    assert (cents(first["Visit total"]), cents(first["Visit tax"])) == (12_345, 412)
    assert first["Notes"] == "Cold start at 5 °F\nCustomer café visit"
    assert rows[2]["Services"] == rows[2]["Category"] == ""
    assert rows[3]["Services"] == "Brake fluid (inspected)"
    assert len({row["Visit #"] for row in rows}) == 1
    assert sum(cents(row["Amount"]) for row in rows) == report.matched_cents


def test_a_filtered_history_has_only_the_lines_shown(conn):
    rf.garage(conn)
    filters = Filters(service="category:Brakes")
    report = history.load(conn, filters)
    rows = read(csvs.history_csv(report, filters))
    assert [row["Line"] for row in rows] == ["Brake fluid", "Brake rotors", "Front brake pads"]
    assert sum(cents(row["Amount"]) or 0 for row in rows) == report.matched_cents
    assert rows[0]["Source"] == "Done, no receipt" and rows[0]["Amount"] == ""


def test_a_visit_with_no_lines_still_has_a_row(conn):
    car = rf.car(conn, "Outback")
    rf.visit(conn, car, "2025-01-01", source="attested")
    rows = read(csvs.history_csv(history.load(conn, Filters()), Filters()))
    assert len(rows) == 1 and rows[0]["Line"] == "" and rows[0]["Where"] == "Done, no receipt"


def test_spending_round_trips(conn):
    rf.garage(conn)
    table = spending.table(history.load(conn, Filters()), Filters(), reports.categories(conn))
    rows = read(csvs.spending_csv(table))
    assert list(rows[0]) == ["Category", "2019", "2020", "2021", "2022", "2023", "2024", "Total"]
    assert [row["Category"] for row in rows] == ["Engine", "Brakes", "Tires and wheels", "Other", "Tax", "Total"]
    assert (rows[1]["2019"], rows[1]["2020"], rows[1]["Total"]) == ("200.00", "", "500.00")
    assert cents(rows[-1]["Total"]) == table.total == 64_000
    assert csvs.spending_csv(None) == csvs.BOM + "Category,Total\r\n"


def test_fuel_round_trips():
    fills = [Fill(1, date(2026, 1, 2), 1_000, 12.0, 3_600), Fill(2, date(2026, 1, 12), 1_300, 10.0, 3_000)]
    section = fuel.build({"id": 1, "name": "Outback"}, UNITS["gas"], fills, Filters(view="fuel"))
    rows = read(csvs.fuel_csv([section]))
    assert rows == [{"Car": "Outback", "Month": "2026-01", "Fill-ups": "2", "Miles": "300", "Quantity": "10.000",
                     "Unit": "gal", "Economy": "30.0", "Economy unit": "mpg", "Cents a mile": "10.0",
                     "Spent": "66.00", "Price per unit": "3.000"}]


def test_amounts_are_exact():
    assert [csvs.amount(c) for c in (123_450, -1_200, 5, -5, 0, None)] == ["1234.50", "-12.00", "0.05", "-0.05",
                                                                           "0.00", ""]
    assert [csvs.number(q) for q in (5.0, 4.5, 0.25, 3, None)] == ["5", "4.5", "0.25", "3", ""]
