"""The car page's Running cost: what's counted, its words, and when there isn't enough to go on.

The worked car is the engine test's (tests/amg/engine/test_running_cost.py)
with its records in the database: got on Jul 1, 2023 at 40,000 mi, read each
Jan 1, and seen on Jul 1, 2025 at 64,000. Its $1,200 visit in 2024 included
the $20 safety inspection logged from it, which moves to Fees; a $500 visit
the week before you got it, a receipt not yet confirmed and a job done with no
receipt add nothing; the $85 registration has no day done, so it's counted a
year before it expires.
"""

from __future__ import annotations

import html
import re
from datetime import date

import pytest
import report_fixtures as rf  # tests/ is on pytest's path

from amg.engine.odometer import Odometer
from amg.engine.running_cost import Spend
from amg.repo import fuel, odometer, prices, renewals, schedules, vehicles
from amg.repo.fuel import FillInput
from amg.repo.renewals import RenewalInput
from amg.repo.schedules import ItemInput
from amg.web import budget, running_cost

TODAY = date(2025, 7, 1)


def page(signed_in, url):
    return " ".join(html.unescape(signed_in.get(url).text).split())


@pytest.fixture
def worked(conn):
    car = rf.car(conn, "Outback", in_service_date="2019-05-01", acquired_date="2023-07-01", acquired_miles=40_000)
    for day, miles in (("2024-01-01", 46_000), ("2025-01-01", 58_000), ("2025-07-01", 64_000)):
        odometer.add(conn, car, day, miles)
    rf.visit(conn, car, "2023-06-24", shop="Seller's garage", total=50_000)
    rf.visit(conn, car, "2023-09-10", shop="Midas", total=45_000, lines=[rf.line("Brakes", 45_000, "brake_pads")])
    inspected = rf.visit(conn, car, "2024-03-02", shop="Valley", total=120_000,
                         lines=[rf.line("State inspection", 2_000, "state_inspection", action="inspect"),
                                rf.line("Timing belt", 118_000, "timing_belt")])
    renewals.create(conn, car, RenewalInput("safety", "2025-03-31", "2024-03-02", 2_000, service_event_id=inspected))
    renewals.create(conn, car, RenewalInput("registration", "2025-11-30", None, 8_500))
    rf.visit(conn, car, "2024-05-05", shop="Midas", total=99_900, confirmed=False)
    rf.visit(conn, car, "2025-02-01", source="diy", lines=[rf.line("Pads", 30_000, "brake_pads", kind="part")])
    rf.visit(conn, car, "2025-03-15", source="attested", lines=[rf.line("Brake fluid", None, "brake_fluid")])
    for day, miles, gallons, cost in (("2025-03-01", 60_000, 10.0, 4_000), ("2025-04-01", 61_000, 33.0, 12_000),
                                      ("2025-05-01", 62_000, 33.0, None), ("2025-06-01", 63_000, 34.0, 14_000)):
        fuel.create(conn, car, FillInput(day, miles, "gas", gallons, cost))
    return car


def _load(conn, car, today=TODAY):
    return running_cost.load(conn, vehicles.get(conn, car), today=today)


# ---------- What's counted ----------


def test_what_each_visit_and_fee_counts_for(conn, worked):
    found = sorted(running_cost.spends(conn, vehicles.get(conn, worked), date(2023, 7, 1), TODAY),
                   key=lambda s: (s.day, s.part, s.cents))
    assert found == [
        Spend(date(2023, 9, 10), "service", 45_000),
        Spend(date(2024, 3, 2), "fees", 2_000),
        Spend(date(2024, 3, 2), "service", -2_000),    # the inspection, moved off its visit
        Spend(date(2024, 3, 2), "service", 120_000),
        Spend(date(2024, 11, 30), "fees", 8_500),      # no day done: a year before it expires
        Spend(date(2025, 2, 1), "service", 30_000),    # your own work, no total: its lines
    ]


def test_a_fee_never_takes_more_off_a_visit_than_it_cost(conn):
    car = rf.car(conn, "Civic")
    visit = rf.visit(conn, car, "2024-03-02", total=3_000, lines=[rf.line("Inspections", 3_000, "state_inspection")])
    renewals.create(conn, car, RenewalInput("safety", "2025-03-31", "2024-03-02", 2_000, service_event_id=visit))
    renewals.create(conn, car, RenewalInput("emissions", "2026-03-31", "2024-03-02", 2_500, service_event_id=visit))
    found = running_cost.spends(conn, vehicles.get(conn, car), date(2024, 1, 1), TODAY)
    assert sum(s.cents for s in found if s.part == "service") == 0
    assert sum(s.cents for s in found if s.part == "fees") == 4_500


def test_the_worked_car(conn, worked):
    found = _load(conn, worked)
    assert found.since == "since you got it" and found.start == date(2023, 7, 1)
    assert (found.rate, found.rate_span) == (13.0, "last 12 months")
    assert [(p.fuel, p.service, p.fees) for p in found.years] == [(78_000, 45_000, 0), (156_000, 118_000, 10_500),
                                                                 (78_000, 30_000, 0)]
    assert found.whole.total == 515_500 and found.whole.miles == 24_000


# ---------- Its words ----------


def test_the_headline_and_its_parts(conn, worked):
    shown = running_cost.block(_load(conn, worked))
    head = shown["headline"]
    assert (head["label"], head["value"]) == ("Since you got it", "21.5¢")
    assert head["note"] == "$5,155 over 24,000 mi from Jul 1, 2023"
    assert head["parts"] == [{"label": "Fuel", "value": "13.0¢", "estimated": True},
                             {"label": "Service and repairs", "value": "8.0¢", "estimated": False},
                             {"label": "Fees", "value": "0.4¢", "estimated": False}]


def test_a_row_a_year_newest_first_and_the_total(conn, worked):
    shown = running_cost.block(_load(conn, worked))
    assert [(r["label"], r["note"], r["miles"], r["fuel"], r["estimated"], r["service"], r["fees"], r["a_mile"])
            for r in shown["rows"]] == [
        ("2025 so far", "", "6,000", "$780", True, "$300", "", "18.0¢"),
        ("2024", "", "12,000", "$1,560", True, "$1,180", "$105", "23.7¢"),
        ("2023", "from Jul 1", "6,000", "$780", True, "$450", "", "20.5¢"),
    ]
    total = shown["total"]
    assert (total["label"], total["miles"], total["fuel"], total["service"], total["fees"], total["a_mile"]) == (
        "In all", "24,000", "$3,120", "$1,930", "$105", "21.5¢")


def test_how_fuel_was_counted(conn, worked):
    note = running_cost.block(_load(conn, worked))["fuel_note"]
    assert note.startswith("Fuel marked est. is at 13.0¢ a mile, what your fill-ups have cost over the last 12 months,"
                           " for the miles no logged fill-up measured.")


def test_with_no_fill_up_costs_fuel_isnt_counted(conn, worked):
    conn.execute("UPDATE fuel_logs SET cost_cents = NULL")
    shown = running_cost.block(_load(conn, worked))
    assert shown["headline"]["note"].endswith(", not counting fuel")
    assert [p["label"] for p in shown["headline"]["parts"]] == ["Service and repairs", "Fees"]
    assert shown["fuel_note"] == "Fuel isn't counted: log fill-ups with their cost and it will be."
    assert shown["total"]["fuel"] == ""


def test_a_year_with_nothing_recorded_has_no_figure(conn, worked):
    conn.execute("UPDATE fuel_logs SET cost_cents = NULL")
    conn.execute("UPDATE line_items SET amount_cents = NULL WHERE description = 'Pads'")
    [current, *_] = running_cost.block(_load(conn, worked))["rows"]
    assert (current["label"], current["service"], current["a_mile"]) == ("2025 so far", "", "—")


def test_where_it_starts():
    odo = Odometer([(date(2020, 6, 3), 30_000), (date(2021, 6, 3), 40_000)])
    car = {"acquired_date": None, "in_service_date": "2015-03-01", "archived_at": None}
    assert running_cost.start_of(car, odo) == (date(2015, 3, 1), "since it was new")
    assert running_cost.start_of({**car, "in_service_date": None}, odo) == (date(2020, 6, 3), "since your first record")
    assert running_cost.start_of({**car, "acquired_date": "2020-01-02"}, odo) == (date(2020, 1, 2), "since you got it")


def test_an_archived_car_ends_at_its_last_reading(conn, worked):
    vehicles.archive(conn, worked)
    found = _load(conn, worked, today=date(2026, 3, 1))
    assert found.years[-1].end == TODAY
    assert [r["label"] for r in running_cost.block(found)["rows"]][:1] == ["2025"]
    assert running_cost.block(found)["rows"][0]["note"] == "to Jul 1"


def test_an_electric_car_says_charging(conn):
    car = rf.car(conn, "Leaf", powertrain="ev", acquired_date="2024-01-01", acquired_miles=1_000)
    odometer.add(conn, car, "2025-01-01", 9_000)
    for day, miles, kwh, cost in (("2024-06-01", 4_000, 30.0, 600), ("2024-07-01", 5_000, 30.0, 3_000)):
        fuel.create(conn, car, FillInput(day, miles, "electric", kwh, cost, place="home"))
    shown = running_cost.block(_load(conn, car, today=date(2025, 1, 1)))
    assert shown["headline"]["parts"][0]["label"] == "Charging"
    assert shown["fuel_note"].startswith("Charging marked est. is at 3.0¢ a mile, what your charges have cost")


# ---------- When there isn't enough ----------


def test_too_few_miles_yet(conn):
    car = rf.car(conn, "New", acquired_date="2025-06-01", acquired_miles=10)
    odometer.add(conn, car, "2025-06-30", 330)
    assert running_cost.block(_load(conn, car, today=date(2025, 6, 30))) == {"reason": "Too few miles yet: 320 mi since you got it."}


def test_one_reading_isnt_enough(conn):
    car = rf.car(conn, "Unknown")
    odometer.add(conn, car, "2025-06-30", 30_000)
    assert running_cost.block(_load(conn, car))["reason"] == running_cost.NO_ODOMETER


# ---------- On the page ----------


def test_the_block_on_the_car_page(signed_in, conn, worked):
    text = page(signed_in, f"/vehicles/{worked}")
    assert 'id="running-cost"' in text and "Running cost" in text and "Since you got it" in text
    assert re.search(r'[\d.]+¢<span class="figure__unit"> a mile', text)
    assert "Service and repairs" in text and "In all" in text
    assert "Fuel marked est. is at" in text


def test_the_page_says_why_when_it_cant_tell(signed_in, conn):
    car = rf.car(conn, "Unknown")
    assert running_cost.NO_ODOMETER in page(signed_in, f"/vehicles/{car}")


# ---------- The next 12 months, and the garage ----------


def _schedule(conn, car, items):
    draft_id = schedules.create_draft(conn, car, "template", draft={"origin": "template", "items": []})
    schedules.confirm(conn, draft_id, car, items, {"origin": "template", "items": []})


def _ahead(conn, car):
    return running_cost.ahead_words(budget.load(conn, vehicles.get(conn, car), 12, today=TODAY))


def test_the_next_12_months(conn, worked):
    _schedule(conn, worked, [ItemInput("Oil and filter", "replace", ["engine_oil", "oil_filter"], interval_miles=6_000),
                             ItemInput("Cabin air filter", "replace", ["cabin_air_filter"], interval_months=12)])
    prices.set_yours(conn, worked, ["engine_oil", "oil_filter"], "replace", "Oil and filter", 6_000)
    found = _ahead(conn, worked)
    assert found["label"] == "Next 12 months" and re.fullmatch(r"~[\d.]+¢", found["value"])
    assert re.fullmatch(r"~\$[\d,]+ for ~12,100 mi: fuel ~\$1,573, maintenance ~\$120, fees ~\$85",
                        found["note"]), found["note"]
    assert "Not counting $80 due now." in found["extras"]      # the oil change overdue, and the expired sticker
    assert "2 jobs not priced yet." in found["extras"]          # the cabin filter, overdue and again in May


def test_the_next_12_months_with_no_schedule(conn, worked):
    found = _ahead(conn, worked)
    assert found["note"].startswith("~$") and "maintenance" not in found["note"]
    assert found["extras"] == ["Not counting $20 due now.",
                               "Fuel and fees only: with a maintenance schedule, AMG counts its jobs too."]


def test_the_block_shows_the_next_12_months_but_not_for_an_archived_car(signed_in, conn, worked):
    text = page(signed_in, f"/vehicles/{worked}")
    assert "Next 12 months" in text and f'href="/vehicles/{worked}/budget"' in text
    vehicles.archive(conn, worked)
    text = page(signed_in, f"/vehicles/{worked}")
    assert "Running cost" in text and "Next 12 months" not in text


def test_the_garage_figure(signed_in, conn, worked):
    assert running_cost.figure(_load(conn, worked)) == {"value": "21.5¢", "unit": "a mile"}
    text = page(signed_in, "/")
    assert re.search(r"<dt>Running cost</dt> <dd class=\"mono\">[\d.]+¢ <span class=\"muted\">a mile</span>", text)


def test_the_garage_figure_says_when_fuel_isnt_in_it(signed_in, conn, worked):
    conn.execute("UPDATE fuel_logs SET cost_cents = NULL")
    assert running_cost.figure(_load(conn, worked)) == {"value": "8.5¢", "unit": "a mile, not counting fuel"}
    assert "a mile, not counting fuel</span>" in page(signed_in, "/")


def test_no_garage_figure_with_nothing_to_go_on(signed_in, conn):
    car = rf.car(conn, "Unknown")
    assert running_cost.figure(_load(conn, car)) is None
    assert "Running cost" not in page(signed_in, "/")
