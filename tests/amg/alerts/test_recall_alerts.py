"""Recalls in the daily run: checked weekly, each pushed once whatever the alerts switch says, and in the email.

The car is a 2016 Subaru Outback with its alerts off; NHTSA is recall_fixtures'
stand-in: an air bag recall, and a steering one that says not to drive it.
"""

from __future__ import annotations

from datetime import date

import recall_fixtures as nf  # tests/ is on pytest's path
import pytest

from amg.alerts import mail, run, watch
from amg.repo import alerts, recalls, vehicles

OCT_7 = date(2026, 10, 7)
AIR_BAG = "Air bags: air bag/restraint control module: NHTSA 19V-910 · reported Dec 19, 2019"
STEERING = "Steering: column: NHTSA 16V-292 · reported May 11, 2016"


@pytest.fixture
def car(conn):
    return vehicles.create(conn, vehicles.VehicleFields(name="Outback", year=2016, make="Subaru", model="Outback"))


def _run(conn, day, said=None, dry_run=False):
    return run.run(conn, day, dry_run=dry_run, say=(said.append if said is not None else lambda words: None))


def test_a_check_pushes_what_it_found_once(conn, car, pushes, monkeypatch):
    nf.nhtsa(monkeypatch)
    said: list[str] = []
    result = _run(conn, OCT_7, said)
    assert "Outback: 2 new recalls from NHTSA." in said and "recalls checked for 1 car" in result.summary()
    assert [(p.title, p.message, p.priority) for p in pushes] == [
        ("Outback: 2 recalls to check", f"{AIR_BAG}\n{STEERING}", 5)]          # the steering one says park it
    assert pushes[0].click == f"http://amg.home.arpa/vehicles/{car}#recalls"
    _run(conn, date(2026, 10, 8))
    _run(conn, date(2026, 10, 14))                                           # checked again: nothing new
    assert len(pushes) == 1


def test_one_recall_is_pushed_by_name(conn, car, pushes, monkeypatch):
    nf.nhtsa(monkeypatch, found={"results": [nf.AIR_BAG]})
    _run(conn, OCT_7)
    assert [(p.title, p.message, p.priority) for p in pushes] == [("Outback: recall to check", AIR_BAG, 4)]


def test_one_that_says_not_to_drive_says_so(conn, car, pushes, monkeypatch):
    nf.nhtsa(monkeypatch, found={"results": [nf.STEERING]})
    _run(conn, OCT_7)
    assert [(p.title, p.priority) for p in pushes] == [("Outback: recall, don't drive it", 5)]


def test_a_dry_run_asks_nhtsa_nothing(conn, car, monkeypatch):
    asked = nf.nhtsa(monkeypatch)
    _run(conn, OCT_7, dry_run=True)
    assert asked == [] and vehicles.get(conn, car)["recalls_checked_on"] is None


def test_nhtsa_being_down_doesnt_fail_the_run(conn, car, monkeypatch):
    nf.down(monkeypatch)
    said: list[str] = []
    result = _run(conn, OCT_7, said)
    assert result.ok and "Couldn't check recalls for Outback; trying again tomorrow." in said
    assert vehicles.get(conn, car)["recalls_error"] == "Couldn't reach NHTSA's recall service."


def test_the_email_counts_and_lists_open_recalls(conn, car, monkeypatch):
    nf.nhtsa(monkeypatch)
    _run(conn, OCT_7)
    looked = watch.look(conn, vehicles.get(conn, car), OCT_7)
    assert looked.jobs == [] and len(looked.recalls) == 2
    assert mail.subject([looked]) == "AMG: 2 open recalls"
    text = mail.text([looked], 0, "http://amg.home.arpa")
    assert f"OUTBACK\nOpen recalls\n  • {AIR_BAG}\n  • {STEERING}\nNothing due.\n" in text
    html = mail.digest([looked], 0, "http://amg.home.arpa", "").get_body(("html",)).get_content()
    assert "Open recalls" in html and "Air bags: air bag/restraint control module" in html


def test_a_closed_recall_is_watched_no_more(conn, car, monkeypatch):
    nf.nhtsa(monkeypatch)
    _run(conn, OCT_7)
    for row in recalls.open_for(conn, car):
        recalls.close(conn, row["id"], "done", "2020-03-01")
    assert alerts.cars_watched(conn) == []
