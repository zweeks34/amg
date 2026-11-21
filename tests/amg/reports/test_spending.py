"""The Spending report: every year's column adds up to what you paid."""

from __future__ import annotations

from datetime import date

import report_fixtures as rf  # tests/ is on pytest's path

from amg.reports import history, spending
from amg.reports.filters import Filters
from amg.repo import odometer, reports


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


# ---------- Around the table ----------


def test_the_latest_year_against_the_one_before(conn):
    rf.garage(conn)
    found = spending.latest(table(conn), today=date(2026, 11, 21))
    assert found == {"year": 2024, "cents": 0, "words": "2024", "change": "▼ 100% on 2023", "up": False}
    up = spending.latest(spending.Spending([2025, 2026], [], {2025: 10_000, 2026: 11_200}, 21_200), today=date(2026, 3, 1))
    assert up["words"] == "2026 so far" and up["change"] == "▲ 12% on 2025" and up["up"]
    nothing_before = spending.latest(spending.Spending([2025, 2026], [], {2025: 0, 2026: 100}, 100), today=date(2026, 3, 1))
    assert nothing_before["change"] == ""
    assert spending.latest(spending.Spending([2026], [], {2026: 100}, 100)) is None


def test_the_year_bars_stack_each_category(conn):
    rf.garage(conn)
    found = spending.bars(table(conn))
    assert [bar["label"] for bar in found["bars"]] == ["2019", "2020", "2021", "2022", "2023", "2024"]
    first = found["bars"][0]                                         # $270: engine, brakes, then other and tax
    assert [(seg["type"], seg["colour"], seg["cents"]) for seg in first["segs"]] == [
        ("Engine", "1", 5_000), ("Brakes", "2", 20_000), ("Other", "other", 750), ("Tax", "other", 1_250)]
    heights = {bar["label"]: bar["h"] for bar in found["bars"]}
    assert heights["2021"] == 85.0 and heights["2020"] == 0          # $340 on a $400 scale
    assert found["line"] is None and found["per_month"] is None      # no put-aside tape
    assert found["types"][0] == {"label": "Brakes", "total": 50_000, "colour": "2"}
    single = spending.Spending([2026], [{"label": "Engine", "cells": {2026: 100}, "total": 100}], {2026: 100}, 100)
    assert spending.bars(single) is None


def test_each_cell_shaded_against_the_biggest(conn):
    rf.garage(conn)
    result = table(conn)
    assert result.top_cell == 30_000 and result.heat(30_000) == 1.0 and result.heat(3_000) == 0.1
    assert result.heat(None) == 0.0 and result.share(32_000) == 50.0


def test_labor_parts_and_fees_add_up_to_what_was_paid(conn):
    rf.garage(conn)
    found = spending.kinds(history.load(conn, Filters()))
    assert [(row["label"], row["cents"]) for row in found] == [
        ("Labor", 58_000), ("Parts", 4_000), ("Other", 750), ("Tax", 1_250)]
    assert sum(row["cents"] for row in found) == 64_000
    assert [row["share"] for row in found] == [91, 6, 1, 2] and found[0]["bar"] == 100


def test_narrowed_only_the_matching_lines_by_kind(conn):
    rf.garage(conn)
    assert spending.kinds(history.load(conn, Filters(service="category:Brakes"))) == []   # all labor: one kind


def test_who_did_the_work_most_spent_first(conn):
    rf.garage(conn)
    found = spending.shops(history.load(conn, Filters()))
    assert [(row["who"], row["cents"], row["visits"]) for row in found["rows"]] == [
        ("MIDAS Auto", 30_000, 1), ("Midas #1234", 27_000, 1), ("Your own work", 4_000, 1),
        ("Corner Garage", 3_000, 1), ("Done, no receipt", 0, 1)]
    assert found["rows"][2]["diy"] and found["more"] == 0
    assert spending.shops(history.load(conn, Filters()), limit=2)["more"] == 3


def test_a_shop_spelled_two_ways_is_one(conn):
    car = rf.car(conn, "Outback")
    rf.visit(conn, car, "2025-01-01", shop="Corner Garage", lines=[rf.line("Oil", 5_000, "engine_oil")])
    rf.visit(conn, car, "2025-06-01", shop="corner garage ", lines=[rf.line("Oil", 6_000, "engine_oil")])
    (row,) = spending.shops(history.load(conn, Filters()))["rows"]
    assert row["visits"] == 2 and row["cents"] == 11_000


def test_by_car_with_its_cost_a_mile(conn):
    ids = rf.garage(conn)
    found = spending.by_car(history.load(conn, Filters()), {ids["outback"]: 10_000.0, ids["civic"]: 300.0})
    assert [(row["label"], row["total"], row["cells"]) for row in found] == [
        ("Outback", 34_000, {2019: 27_000, 2021: 4_000, 2023: 3_000, 2024: 0}), ("Civic", 30_000, {2021: 30_000})]
    assert found[0]["per_mile"] == 3.4 and found[1]["per_mile"] is None    # 300 miles is too few to say
    assert spending.by_car(history.load(conn, Filters(car=ids["civic"]))) == []


def test_the_miles_each_car_went_in_the_dates(conn):
    outback = rf.car(conn, "Outback", acquired_date="2024-01-01")
    civic = rf.car(conn, "Civic")
    for day, miles in (("2024-01-01", 10_000), ("2025-01-01", 22_000)):
        odometer.add(conn, outback, day, miles)
    cars = reports.cars(conn)
    found = spending.miles(conn, cars, Filters(start="2024-07-01", end="2025-01-01"), today=date(2026, 1, 1))
    assert set(found) == {outback} and round(found[outback]) == 6_033    # 184 of 2024's 366 days at 12,000 a year
    assert civic not in spending.miles(conn, cars, Filters(), today=date(2026, 1, 1))   # no readings to go on
    assert spending.miles(conn, cars, Filters(car=civic), today=date(2026, 1, 1)) == {}
