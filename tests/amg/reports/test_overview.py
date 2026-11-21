"""The Overview: each car as its car page counts it, the garage added up, and month by month with the gaps shown.

The worked car is the car page's (tests/amg/web/test_running_cost_pages.py): got on Jul 1, 2023 at 40,000 mi,
read each Jan 1, seen on Jul 1, 2025 at 64,000, with its visits, fees and fill-ups.
"""

from __future__ import annotations

import csv
import io
from datetime import date

import pytest
import report_fixtures as rf  # tests/ is on pytest's path

from amg.engine.running_cost import Period
from amg.reports import csvs, overview
from amg.reports.filters import Filters
from amg.repo import fuel, odometer, renewals, reports, vehicles
from amg.repo.fuel import FillInput
from amg.repo.renewals import RenewalInput
from amg.web import running_cost

TODAY = date(2025, 7, 1)


@pytest.fixture
def worked(conn):
    car = rf.car(conn, "Outback", in_service_date="2019-05-01", acquired_date="2023-07-01", acquired_miles=40_000)
    for day, miles in (("2024-01-01", 46_000), ("2025-01-01", 58_000), ("2025-07-01", 64_000)):
        odometer.add(conn, car, day, miles)
    rf.visit(conn, car, "2023-09-10", shop="Midas", total=45_000, lines=[rf.line("Brakes", 45_000, "brake_pads")])
    inspected = rf.visit(conn, car, "2024-03-02", shop="Valley", total=120_000,
                         lines=[rf.line("State inspection", 2_000, "state_inspection", action="inspect"),
                                rf.line("Timing belt", 118_000, "timing_belt")])
    renewals.create(conn, car, RenewalInput("safety", "2025-03-31", "2024-03-02", 2_000, service_event_id=inspected))
    rf.visit(conn, car, "2025-02-01", source="diy", lines=[rf.line("Pads", 30_000, "brake_pads", kind="part")])
    for day, miles, gallons, cost in (("2025-03-01", 60_000, 10.0, 4_000), ("2025-04-01", 61_000, 33.0, 12_000),
                                      ("2025-05-01", 62_000, 33.0, None), ("2025-06-01", 63_000, 34.0, 14_000)):
        fuel.create(conn, car, FillInput(day, miles, "gas", gallons, cost))
    return car


def load(conn, **filters):
    return overview.load(conn, reports.cars(conn), Filters(view="overview", **filters), today=TODAY)


def test_each_car_as_its_car_page_counts_it(conn, worked):
    found = load(conn)
    (car,) = found.cars
    page = running_cost.load(conn, vehicles.get(conn, worked), today=TODAY)
    assert car.years == page.years and car.whole == page.whole
    assert found.whole.total == pytest.approx(page.whole.total) and found.whole.miles == 24_000
    assert [row["label"] for row in found.years] == ["2025 so far", "2024", "2023"]
    assert found.years[2]["note"] == "from Jul 1"
    assert found.estimated and found.unfuelled == []


def test_the_months_add_up_to_about_the_years(conn, worked):
    found = load(conn)
    assert found.months[0]["label"] == "Jul 2025 so far" and found.months[-1]["label"] == "Jul 2023"
    assert len(found.months) == 25
    assert sum(m["period"].service + m["period"].fees for m in found.months) == (
        found.whole.service + found.whole.fees)                       # service and fees land exactly
    fuel_by_months = sum(m["period"].fuel for m in found.months)
    assert fuel_by_months == pytest.approx(found.whole.fuel, rel=0.05)  # tanks spread by day: close, not exact


def test_the_dates_narrow_each_car(conn, worked):
    found = load(conn, start="2024-06-01", end="2024-12-31")
    (car,) = found.cars
    assert (car.start, car.end) == (date(2024, 6, 1), date(2024, 12, 31))
    assert [p.start for p in car.years] == [date(2024, 6, 1)] and car.ahead is None   # an end date: no future
    assert found.months[-1]["label"] == "Jun 2024" and len(found.months) == 7


def test_a_car_with_no_readings_says_why_and_comes_last(conn, worked):
    rf.car(conn, "Civic")
    found = load(conn)
    assert [c.car["name"] for c in found.cars] == ["Outback", "Civic"]
    assert found.cars[1].reason.startswith("AMG needs two odometer readings") and found.cars[1].whole is None


def test_a_car_that_wasnt_yours_in_the_dates_is_left_out(conn, worked):
    sold = rf.car(conn, "Old Civic", acquired_date="2015-01-01")
    for day, miles in (("2015-01-01", 10_000), ("2018-01-01", 40_000)):
        odometer.add(conn, sold, day, miles)
    vehicles.archive(conn, sold)                                       # its last reading ends its span
    assert [c.car["name"] for c in load(conn, start="2024-01-01").cars] == ["Outback"]
    assert "Old Civic" in [c.car["name"] for c in load(conn).cars]


def test_cheapest_a_mile_first_and_nothing_recorded_isnt_free(conn, worked):
    nothing = rf.car(conn, "Civic", acquired_date="2024-01-01")
    for day, miles in (("2024-01-01", 10_000), ("2025-07-01", 25_000)):
        odometer.add(conn, nothing, day, miles)
    cheap = rf.car(conn, "Fit", acquired_date="2024-01-01")
    for day, miles in (("2024-01-01", 10_000), ("2025-07-01", 25_000)):
        odometer.add(conn, cheap, day, miles)
    rf.visit(conn, cheap, "2024-05-01", shop="Midas", total=15_000)
    found = load(conn)
    assert [c.car["name"] for c in found.cars] == ["Outback", "Fit", "Civic"]   # the Fit's fuel isn't counted
    assert found.cars[1].a_mile < found.cars[0].a_mile                        # so it only looks cheaper
    assert found.cars[2].a_mile is None and overview.a_mile_words(found.cars[2].whole) == "—"
    assert found.unfuelled == ["Fit", "Civic"]


# ---------- Gaps and the average month ----------


def month(year, number, total_service, miles=1_000.0, uncovered=0.0, start_day=1, end=None):
    first = date(year, number, start_day)
    last = end or overview._month_end(first)
    return Period(first, last, miles, 1_000.0, uncovered, total_service, 0)


def car_with(months, fuelled=True):
    car = overview.CarCost({"id": 1, "name": "Outback", "archived_at": None}, None)  # type: ignore[arg-type]
    car.months = months
    car.whole = Period(months[0].start, months[-1].end, 1.0, 1.0 if fuelled else None)
    return car


def test_a_month_mostly_estimated_is_a_gap_and_left_out_of_the_average():
    rows = overview._months([car_with([
        month(2026, 1, 9_000), month(2026, 2, 0, uncovered=600), month(2026, 3, 3_000), month(2026, 4, 0)])],
        today=date(2026, 6, 1))
    found = overview.Overview([], [], rows, None, None, [], False)
    overview._average(found)
    assert [(m["label"], m["gap"]) for m in rows] == [
        ("Apr 2026", False), ("Mar 2026", False), ("Feb 2026", True), ("Jan 2026", False)]
    # Jan $100, Mar $40, Apr $10 (fuel $10 each, plus service): the average is $50
    assert found.average_month == pytest.approx(5_000)
    assert [m["change"] for m in rows] == [-80, -20, None, 100]


def test_a_partial_month_is_shown_but_not_compared():
    rows = overview._months([car_with([
        month(2026, 5, 0, start_day=20), month(2026, 6, 0), month(2026, 7, 0), month(2026, 8, 0, end=date(2026, 8, 9))])],
        today=date(2026, 8, 9))
    found = overview.Overview([], [], rows, None, None, [], False)
    overview._average(found)
    assert [(m["label"], m["partial"]) for m in rows] == [
        ("Aug 2026 so far", True), ("Jul 2026", False), ("Jun 2026", False), ("May 2026", True)]
    assert [m["change"] for m in rows] == [None, 0, 0, None]


def test_a_car_whose_fuel_isnt_counted_makes_no_gap():
    rows = overview._months([car_with([month(2026, 1, 0, uncovered=1_000), month(2026, 2, 0)], fuelled=False)],
                            today=date(2026, 6, 1))
    assert not any(m["gap"] for m in rows)


def test_the_bars_hatch_a_gap_months_fuel():
    rows = overview._months([car_with([month(2026, 1, 5_000), month(2026, 2, 0, uncovered=900)])],
                            today=date(2026, 6, 1))
    chart = overview.bars(rows, "month")
    assert [[seg["colour"] for seg in bar["segs"]] for bar in chart["bars"]] == [["fuel", "service"], ["est"]]
    assert {"label": "Fuel, mostly estimated", "colour": "est"} in chart["colours"]
    assert chart["per"] == "month" and chart["line"] is None


def test_the_split_of_a_period():
    parts = overview.split(Period(date(2026, 1, 1), date(2026, 12, 31), 10_000, 30_000.0, 0, 60_000, 10_000))
    assert [(p["key"], p["share"]) for p in parts] == [("fuel", 30.0), ("service", 60.0), ("fees", 10.0)]
    assert [p["key"] for p in overview.split(Period(date(2026, 1, 1), date(2026, 1, 31), 1, None))] == [
        "fuel", "service"]                                            # no fees: not shown


# ---------- The CSV ----------


def test_the_csv_is_a_row_a_car_and_year(conn, worked):
    rows = list(csv.reader(io.StringIO(csvs.overview_csv(load(conn)).lstrip("﻿"))))
    assert rows[0] == list(csvs.OVERVIEW_COLUMNS)
    assert [row[1] for row in rows[1:]] == ["2023", "2024", "2025"]
    assert rows[1][:5] == ["Outback", "2023", "2023-07-01", "2023-12-31", "6000"]
    assert rows[1][6] == "Yes"                                        # 2023's fuel is all estimated


def test_the_next_12_months_only_when_theres_something_to_say(conn, worked):
    bare = rf.car(conn, "Civic", acquired_date="2024-01-01")
    for day, miles in (("2024-01-01", 10_000), ("2025-07-01", 25_000)):
        odometer.add(conn, bare, day, miles)
    found = {c.car["name"]: c for c in load(conn).cars}
    assert found["Outback"].ahead["label"] == "Next 12 months"                 # its fuel, at its pace
    assert found["Civic"].ahead is None                                        # no schedule, no fuel: nothing
