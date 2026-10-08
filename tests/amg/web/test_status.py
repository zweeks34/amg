"""The hand-checked car: every mark on its chart worked out on paper, then compared.

Driven 30 mi a day from new (2020-01-01), so day n is n × 30 miles. Today is
day 1000 (2022-09-27): 30,000 mi. Services, by day:

    190 (5,700)   oil, tire rotation, multi-point inspection
    380 (11,400)  cabin air filter
    400 (12,000)  oil
    640 (19,200)  oil, tire rotation
    900 (27,000)  tire rotation, brake pads inspected

Oil and filter, every 6,000 mi or 12 months (miles come first at 30 mi a day):
    due 6,000 (day 200)   ← done at 5,700, early
    due 11,700 (day 390)  ← done at 12,000, within a tenth of 200 days
    due 18,000 (day 600)  ← done at 19,200, 40 days on: late
    due 25,200 (day 840)  nothing, and 31,200 not due till day 1040: overdue
    then 31,200, 37,200, 43,200, 49,200 later (55,200 is past the chart)
Engine coolant, first at 50,000 mi or 60 months, then 30,000 / 36 months:
    due 50,000 (day 1667) later — at the chart's edge
Brake inspection, every 12,000 mi or 12 months (months come first):
    due 2021-01-01 (10,980)  ← the multi-point at 5,700 meets it, early
    due 2021-07-09 (16,650)  ← brake pads inspected at 27,000: late, but before 2022-07-09
    then 2023-06-19 (37,950), 2024-06-19 (48,930) later
Tire rotation, every 6,000 mi:
    due 6,000   ← done at 5,700
    due 11,700  nothing before 17,700 fell due too: missed
    due 17,700  ← done at 19,200, late
    due 25,200  ← done at 27,000, late
    then 33,000, 39,000, 45,000 later
Cabin air filter, every 12 months:
    due 2021-01-01 (10,980)  ← done 2021-01-15, within a tenth of a year
    due 2022-01-15 (22,350)  nothing, 2023-01-15 not yet: overdue
    then 2023-01-15 (33,300), 2024-01-15 (44,250) later
"""

from __future__ import annotations

from datetime import date

import pytest
from schedule_fixtures import steady_car  # tests/ is on pytest's path

from amg.repo import schedules, vehicles
from amg.web import status

NEW = date(2020, 1, 1)
TODAY = date(2022, 9, 27)    # day 1000


@pytest.fixture
def steady(conn):
    car, day, visits = steady_car(conn, NEW)
    assert day(1000) == TODAY
    return status.load(conn, vehicles.get(conn, car), today=TODAY), visits


def _rows(chart):
    return {row["name"]: [(m["status"], m["miles"], m["late"]) for m in row["marks"]]
            for group in chart["groups"] for row in group["rows"]}


def test_the_chart_matches_the_hand_check(steady):
    state, _ = steady
    chart = status.chart(state, "Steady")
    assert (chart["here"], chart["span"], chart["ticks"]) == (30_000, 50_000, [0, 10_000, 20_000, 30_000, 40_000, 50_000])
    assert [group["label"] for group in chart["groups"]] == ["Engine", "Brakes", "Tires and wheels", "Cabin"]
    assert _rows(chart) == {
        "Engine oil and filter": [
            ("done", 5_700, False), ("done", 12_000, False), ("done", 19_200, True), ("overdue", 25_200, False),
            ("later", 31_200, False), ("later", 37_200, False), ("later", 43_200, False), ("later", 49_200, False),
        ],
        "Engine coolant": [("later", 50_000, False)],
        "Brake inspection": [("done", 5_700, False), ("done", 27_000, True), ("later", 37_950, False),
                             ("later", 48_930, False)],
        "Tire rotation": [
            ("done", 5_700, False), ("gap", 11_700, False), ("done", 19_200, True), ("done", 27_000, True),
            ("later", 33_000, False), ("later", 39_000, False), ("later", 45_000, False),
        ],
        "Cabin air filter": [("done", 11_400, False), ("overdue", 22_350, False), ("later", 33_300, False),
                             ("later", 44_250, False)],
    }


def test_done_marks_link_to_their_service_and_missed_ones_to_mark_as_done(steady):
    state, visits = steady
    rows = {row["name"]: row["marks"] for group in status.chart(state, "Steady")["groups"] for row in group["rows"]}
    rotation = rows["Tire rotation"]
    assert rotation[0]["href"] == f"/services/{visits[190]}"
    tire_item = next(i for i in state.items.values() if i["name"] == "Tire rotation")
    assert rotation[1]["href"] == f"/vehicles/{state.vehicle_id}/schedule-items/{tire_item['id']}/done?due=2021-01-25"
    assert rotation[4]["href"] is None      # later: nothing to do yet


def test_next_up_is_overdue_first_then_soonest(steady):
    state, _ = steady
    assert [(row["name"], row["status"], row["when"]) for row in status.next_up(state)] == [
        ("Cabin air filter", "overdue", "7,650 mi overdue · due Jan 15"),
        ("Engine oil and filter", "overdue", "4,800 mi overdue · due Apr 20"),
        ("Tire rotation", "later", "in 3,000 mi · ~Jan 2023"),
        ("Brake inspection", "later", "in 7,950 mi · ~Jun 2023"),
        ("Engine coolant", "later", "in 20,000 mi · ~Jul 2024"),
    ]
    assert all(row["attest_url"] for row in status.next_up(state) if row["status"] == "overdue")


def test_missed_and_the_garage_line(steady):
    state, _ = steady
    assert [(row["name"], row["when"]) for row in status.missed(state)] == [
        ("Tire rotation", "missed at 11,700 mi · Jan 2021")]
    line = status.summary(state)
    assert (line["overdue"], line["due"], line["missed"], line["next"]["name"]) == (2, 0, 1, "Cabin air filter")


def test_no_readings_means_no_chart_but_months_still_count(conn):
    car = vehicles.create(conn, vehicles.VehicleFields(name="New", in_service_date="2021-01-01"))
    from amg.repo import schedules
    from amg.repo.schedules import ItemInput

    draft = schedules.create_draft(conn, car, "template", draft={"origin": "template", "items": []})
    schedules.confirm(conn, draft, car, [
        ItemInput("Cabin air filter", "replace", ["cabin_air_filter"], interval_months=12),
        ItemInput("Tire rotation", "perform", ["tire_rotation"], interval_miles=6000),
    ], {})
    state = status.load(conn, vehicles.get(conn, car), today=TODAY)
    assert status.chart(state, "New") is None
    assert [(row["name"], row["status"]) for row in status.next_up(state)] == [("Cabin air filter", "overdue")]
    assert state.needs_reading == ["Tire rotation"]


@pytest.mark.parametrize(("here", "span", "step"), [(30_000, 50_000, 10_000), (64_300, 80_000, 10_000),
                                                     (96_987, 120_000, 15_000), (2_000, 15_000, 5_000)])
def test_the_chart_reaches_past_today(here, span, step):
    assert status._span(here) == (span, step)


@pytest.mark.parametrize(("days", "words"), [(61, "2 months ago"), (100, "3 months ago"), (700, "23 months ago"),
                                             (800, "2 years ago")])
def test_how_long_ago_a_reading_was(days, words):
    assert status.ago(days) == words


def test_the_in_service_date_isnt_a_reading(conn):
    car = vehicles.create(conn, vehicles.VehicleFields(name="New", in_service_date="2026-01-01"))
    draft = schedules.create_draft(conn, car, "template", draft={"origin": "template", "items": []})
    schedules.confirm(conn, draft, car, [schedules.ItemInput("Tire rotation", "perform", ["tire_rotation"],
                                                             interval_miles=7_500)], {})
    stale = status.stale_reading(status.load(conn, vehicles.get(conn, car), today=date(2026, 1, 20)))
    assert stale == status.StaleReading(None, None, None)
