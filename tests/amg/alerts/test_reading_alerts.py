"""Asking for an odometer reading: a car whose jobs fall due by mileage, once the last reading is two months old.

The alert_fixtures car, new on 2026-01-01, with one job due by mileage: a tire
rotation every 15,000 mi. A reading of 3,000 mi on 2026-03-02 makes 50 mi a
day, so the rotation isn't due till late October and nothing else is pushed.
"""

from __future__ import annotations

from datetime import date

import alert_fixtures as af  # tests/ is on pytest's path
import pytest

from amg.alerts import mail, run, watch
from amg.repo import alerts, odometer, vehicles
from amg.repo.schedules import ItemInput

TIRES = ItemInput("Tire rotation", "perform", ["tire_rotation"], interval_miles=15_000)
READ_ON = date(2026, 3, 2)
MAY_6 = date(2026, 5, 6)      # 65 days on


@pytest.fixture
def car(conn):
    car = af.make_car(conn)
    af.schedule(conn, car, [TIRES])
    odometer.add(conn, car, READ_ON.isoformat(), 3_000)
    return car


def _run(conn, day):
    return run.run(conn, day, say=lambda words: None)


def _asked(pushes):
    return [p for p in pushes if "odometer reading wanted" in p.title]


def test_an_old_reading_is_asked_for_once(conn, car, pushes):
    _run(conn, date(2026, 4, 30))                       # 59 days: not yet
    assert pushes == []
    _run(conn, MAY_6)
    _run(conn, date(2026, 5, 7))
    assert [(p.title, p.message) for p in pushes] == [
        ("Outback: odometer reading wanted", "The last was Mar 2, 2 months ago; AMG's guess is ~6,250 mi.")]
    assert pushes[0].click == f"http://amg.home.arpa/vehicles/{car}#add-reading" and pushes[0].priority == 3


def test_a_new_reading_then_two_quiet_months_asks_again(conn, car, pushes):
    _run(conn, MAY_6)
    odometer.add(conn, car, "2026-05-10", 6_400)
    _run(conn, date(2026, 6, 1))
    assert len(_asked(pushes)) == 1
    _run(conn, date(2026, 7, 15))                       # 66 days after May 10
    assert len(_asked(pushes)) == 2 and "The last was May 10, 2 months ago" in pushes[-1].message


def test_with_no_reading_at_all_one_is_asked_for(conn, pushes):
    car = af.make_car(conn, "Crosstrek")
    af.schedule(conn, car, [TIRES])
    _run(conn, MAY_6)
    assert [(p.title, p.message) for p in pushes] == [("Crosstrek: odometer reading wanted", "There's no reading yet.")]


def test_a_car_with_no_job_due_by_mileage_isnt_asked(conn, pushes):
    car = af.make_car(conn)                             # oil, wipers and cabin filter: all by months
    odometer.add(conn, car, READ_ON.isoformat(), 3_000)
    _run(conn, MAY_6)
    assert pushes == []


def test_a_car_with_alerts_off_isnt_asked(conn, car, pushes):
    alerts.switch(conn, car, False)
    _run(conn, MAY_6)
    assert pushes == []


def test_turning_alerts_on_doesnt_hold_the_question_back(conn, car, pushes):
    alerts.switch(conn, car, False)
    alerts.switch(conn, car, True)
    assert watch.take_stock(conn, vehicles.get(conn, car), MAY_6) == 0
    _run(conn, MAY_6)
    assert len(_asked(pushes)) == 1


def test_a_reading_wanted_isnt_a_job_due(conn, car):
    looked = watch.look(conn, vehicles.get(conn, car), MAY_6)
    assert looked.jobs == [] and looked.reading.subject == f"{car}:reading:2026-03-02"
    text = mail.text([looked], 0, "http://amg.home.arpa")
    assert text.startswith("AMG: nothing due this week\n")
    assert ("Nothing due or overdue.\nOdometer reading wanted: the last was Mar 2, 2 months ago; AMG's guess is "
            f"~6,250 mi. Add one: http://amg.home.arpa/vehicles/{car}#add-reading\n") in text
    html = mail.digest([looked], 0, "http://amg.home.arpa", "").get_body(("html",)).get_content()
    assert f'href="http://amg.home.arpa/vehicles/{car}#add-reading"' in html
