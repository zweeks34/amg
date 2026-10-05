"""The Spending report: every year's column adds up to what you paid."""

from __future__ import annotations

import report_fixtures as rf  # tests/ is on pytest's path

from amg.reports import history, spending
from amg.reports.filters import Filters
from amg.repo import reports


def table(conn, filters=Filters()):
    return spending.table(history.load(conn, filters), filters, reports.categories(conn))


def rows(result):
    return {row["label"]: row["cells"] for row in result.rows}


def test_columns_add_up_to_what_was_paid(conn):
    rf.garage(conn)
    result = table(conn)
    assert result.years == [2019, 2020, 2021, 2022, 2023, 2024]     # every year between, spent in or not
    assert [row["label"] for row in result.rows] == ["Engine", "Brakes", "Tires and wheels", "Other", "Tax"]
    assert rows(result) == {
        "Engine": {2019: 5_000, 2021: 4_000},
        "Brakes": {2019: 20_000, 2021: 30_000},
        "Tires and wheels": {2023: 3_000},
        "Other": {2019: 750},                                       # $270 less $250 of lines and $12.50 of tax
        "Tax": {2019: 1_250},
    }
    assert result.totals == {2019: 27_000, 2020: 0, 2021: 34_000, 2022: 0, 2023: 3_000, 2024: 0}
    assert result.total == history.load(conn, Filters()).paid_cents == 64_000
    assert [row["total"] for row in result.rows] == [9_000, 50_000, 3_000, 750, 1_250]


def test_a_discount_the_invoice_didnt_itemise_comes_off_other(conn):
    car = rf.car(conn, "Outback")
    rf.visit(conn, car, "2020-01-01", lines=[rf.line("Brake pads", 10_000, "brake_pads"), rf.line("Shop supplies", 500)],
             tax=600, total=10_100)
    result = table(conn)
    assert rows(result) == {"Brakes": {2020: 10_000}, "Other": {2020: 500 - 1_000}, "Tax": {2020: 600}}
    assert result.total == 10_100


def test_a_line_in_two_categories_counts_under_the_first_or_the_one_asked_for(conn):
    car = rf.car(conn, "Outback")
    rf.visit(conn, car, "2020-01-01", lines=[rf.line("Pads and rotation", 9_000, "tire_rotation", "brake_pads")],
             total=9_000)
    assert rows(table(conn)) == {"Brakes": {2020: 9_000}}           # Brakes comes before Tires in the catalogue
    assert rows(table(conn, Filters(service="category:Tires and wheels"))) == {"Tires and wheels": {2020: 9_000}}


def test_a_service_counts_only_its_lines(conn):
    rf.garage(conn)
    result = table(conn, Filters(service="category:Brakes"))
    assert rows(result) == {"Brakes": {2019: 20_000, 2021: 30_000}}  # no tax, no leftovers, no oil
    assert result.years == [2019, 2020, 2021, 2022, 2023, 2024] and result.total == 50_000


def test_nothing_found_is_no_table(conn):
    assert table(conn) is None
