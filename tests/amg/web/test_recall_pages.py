"""Recalls on the car's page and the garage: checking now, done, not my car, undo, and what a check said.

NHTSA is recall_fixtures' stand-in for a 2016 Subaru Outback: an air bag
recall reported Dec 19, 2019, and a steering one that says not to drive it.
"""

from __future__ import annotations

import html
from datetime import date, timedelta

import pytest
import recall_fixtures as nf  # tests/ is on pytest's path
import report_fixtures as rf  # tests/ is on pytest's path

from amg.repo import recalls, vehicles
from amg.web import recalls as recall_words


@pytest.fixture
def car(conn):
    return vehicles.create(conn, vehicles.VehicleFields(name="Outback", year=2016, make="Subaru", model="Outback"))


def _check(signed_in, car):
    response = signed_in.post(f"/vehicles/{car}/recalls/check", follow_redirects=False)
    assert response.headers["location"] == f"/vehicles/{car}#recalls"
    return signed_in.get(f"/vehicles/{car}").text


def _air_bag(conn, car):
    return next(r for r in recalls.for_car(conn, car) if r["campaign"] == "19V910000")


def test_check_now_lists_what_nhtsa_lists(signed_in, car, monkeypatch):
    nf.nhtsa(monkeypatch)
    page = _check(signed_in, car)
    assert 'id="recalls"' in page and "Air bags: air bag/restraint control module" in page
    assert "NHTSA 19V-910 · reported Dec 19, 2019" in page and "Steering: column" in page
    assert "NHTSA says not to drive it until this is fixed." in page and "What can happen, and the fix" in page
    assert f"Checked {recall_words.day_words(date.today().isoformat())}: NHTSA lists 2 for the" in page
    assert "2016 Subaru Outback" in page and "It's been done" in page and "Not my car" in page


def test_done_on_a_visit_with_a_recall_line(signed_in, conn, car, monkeypatch):
    nf.nhtsa(monkeypatch)
    _check(signed_in, car)
    visit = rf.visit(conn, car, "2020-03-01", shop="Subaru of Town",
                     lines=[rf.line("Recall WUX-09: replace module", 0, "recall", action="perform")])
    page = signed_in.get(f"/vehicles/{car}").text
    assert f'<option value="{visit}">2020-03-01 · Subaru of Town</option>' in page
    signed_in.post(f"/recalls/{_air_bag(conn, car)['id']}/done", data={"service_event_id": str(visit)})
    assert (_air_bag(conn, car)["status"], _air_bag(conn, car)["closed_on"]) == ("done", "2020-03-01")
    page = signed_in.get(f"/vehicles/{car}").text
    assert "1 done or not my car" in page and "Done Mar 1, 2020 at Subaru of Town" in page


def test_done_on_a_date_and_never_in_the_future(signed_in, conn, car, monkeypatch):
    nf.nhtsa(monkeypatch)
    _check(signed_in, car)
    recall = _air_bag(conn, car)["id"]
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    response = signed_in.post(f"/recalls/{recall}/done", data={"closed_on": tomorrow})
    assert response.status_code == 422 and "That date is in the future." in response.text
    signed_in.post(f"/recalls/{recall}/done", data={"closed_on": "2021-05-02"})
    assert "Done May 2, 2021" in signed_in.get(f"/vehicles/{car}").text


def test_not_my_car_then_undo(signed_in, conn, car, monkeypatch):
    nf.nhtsa(monkeypatch)
    _check(signed_in, car)
    recall = _air_bag(conn, car)["id"]
    signed_in.post(f"/recalls/{recall}/not-mine")
    assert "1 done or not my car" in signed_in.get(f"/vehicles/{car}").text
    signed_in.post(f"/recalls/{recall}/undo")
    assert _air_bag(conn, car)["status"] == "open"
    assert signed_in.post("/recalls/999/undo").status_code == 404


def test_no_match_lists_nhtsas_names(signed_in, conn, monkeypatch):
    nf.nhtsa(monkeypatch)
    car = vehicles.create(conn, vehicles.VehicleFields(name="Forester", year=2016, make="Subaru", model="Forester"))
    page = _check(signed_in, car)
    assert "NHTSA lists no recalls for the 2016 Subaru Forester. Its 2016 Subaru models with recalls: Legacy, " \
           "Outback." in page


def test_nhtsa_being_down_is_said(signed_in, car, monkeypatch):
    nf.down(monkeypatch)
    page = html.unescape(_check(signed_in, car))
    assert ("The last check didn't work: Couldn't reach NHTSA's recall service. AMG tries again on the next daily "
            "run.") in page


def test_a_car_without_a_model_is_told_how(signed_in, conn):
    car = vehicles.create(conn, vehicles.VehicleFields(name="Mystery"))
    page = signed_in.get(f"/vehicles/{car}").text
    assert "Add the car's year, make and model on" in page and "Check now" not in page


def test_the_garage_shows_open_recalls(signed_in, car, monkeypatch):
    nf.nhtsa(monkeypatch)
    _check(signed_in, car)
    page = signed_in.get("/").text
    assert "Recall</span>" in page and "Air bags: air bag/restraint control module" in page
