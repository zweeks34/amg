"""Warranties ending in the daily run: pushed once 60 days before, whatever the alerts switch says, in the weekly
email, and counted on the garage card.

The car is an Outback with its alerts off and a powertrain warranty that ends on Nov 1, 2026.
"""

from __future__ import annotations

import html
from datetime import date, timedelta

import pytest

from amg.alerts import mail, run, watch
from amg.engine.schedule import add_months
from amg.repo import odometer, vehicles, warranties
from amg.repo.warranties import WarrantyInput

OCT_9 = date(2026, 10, 9)
LINE = "Powertrain · Subaru: ends in 23 days, Nov 1"


@pytest.fixture
def car(conn):
    return vehicles.create(conn, vehicles.VehicleFields(name="Outback", year=2016, make="Subaru", model="Outback"))


@pytest.fixture
def powertrain(conn, car):
    return warranties.create(conn, car, WarrantyInput("Powertrain", "2023-11-01", provider="Subaru", months=36,
                                                      whole_car=True))


def _run(conn, day, said=None):
    return run.run(conn, day, say=(said.append if said is not None else lambda words: None))


def test_pushed_once_with_the_cars_alerts_off(conn, car, powertrain, pushes):
    assert not vehicles.get(conn, car)["alerts"]
    _run(conn, OCT_9)
    assert [(p.title, p.message, p.priority) for p in pushes] == [("Outback: warranty ending", f"{LINE}.", 3)]
    assert pushes[0].click == f"http://amg.home.arpa/vehicles/{car}#warranties"
    _run(conn, OCT_9 + timedelta(days=1))
    assert len(pushes) == 1


def test_not_before_sixty_days(conn, car, powertrain, pushes):
    said: list[str] = []
    _run(conn, date(2026, 9, 1), said)                       # 61 days before
    assert pushes == [] and any(words.startswith("No car has alerts turned on") for words in said)
    _run(conn, date(2026, 9, 2))
    assert len(pushes) == 1


def test_a_new_end_warns_again(conn, car, powertrain, pushes):
    _run(conn, OCT_9)
    warranties.update(conn, powertrain, WarrantyInput("Powertrain", "2023-11-01", provider="Subaru", months=37,
                                                      whole_car=True))
    _run(conn, OCT_9 + timedelta(days=1))
    assert [p.message for p in pushes] == [f"{LINE}.", "Powertrain · Subaru: ends in 52 days, Dec 1."]


def test_lifetime_and_ended_ones_never_warn(conn, car, pushes):
    warranties.create(conn, car, WarrantyInput("Pads", "2020-01-01", codes=["brake_pads"]))
    warranties.create(conn, car, WarrantyInput("Old", "2020-01-01", months=12, whole_car=True))
    _run(conn, OCT_9)
    assert pushes == []


def test_one_ending_by_miles_is_keyed_by_its_miles(conn, car, pushes):
    odometer.add(conn, car, "2026-04-09", 40_000)
    odometer.add(conn, car, "2026-10-09", 46_000)            # 1,000 mi a month
    made = warranties.create(conn, car, WarrantyInput("Tires", "2024-10-09", start_miles=27_000, miles=20_000,
                                                      codes=["tires"]))
    looked = watch.look(conn, vehicles.get(conn, car), OCT_9)
    [notice] = looked.warranties
    assert notice.subject == f"{car}:warranty:{made}:47000mi"
    assert notice.when.startswith("ends in about 1,000 mi, around ")


def test_several_go_in_one_push_with_a_count(conn, car, powertrain, pushes):
    warranties.create(conn, car, WarrantyInput("Battery", "2023-11-15", months=36, codes=["battery_12v"]))
    _run(conn, OCT_9)
    assert [(p.title, p.message) for p in pushes] == [
        ("Outback: 2 warranties ending", f"{LINE}\nBattery: ends in 37 days, Nov 15")]


def test_the_weekly_email_lists_them(conn, car, powertrain):
    looked = watch.look(conn, vehicles.get(conn, car), OCT_9)
    assert mail.subject([looked]) == "AMG: 1 warranty ending"
    text = mail.text([looked], 0, "http://amg.home.arpa")
    assert f"OUTBACK\nWarranties ending\n  • {LINE}\n" in text
    body = mail.digest([looked], 0, "http://amg.home.arpa", "").get_body(("html",)).get_content()
    assert "Warranties ending" in body and "Powertrain · Subaru" in html.unescape(body)


def test_the_garage_card_counts_them(signed_in, conn, car):
    today = date.today()
    warranties.create(conn, car, WarrantyInput("Powertrain", (add_months(today, -36) + timedelta(days=20)).isoformat(),
                                               months=36, whole_car=True))
    assert "1 warranty ending" in html.unescape(signed_in.get("/").text)
