"""Next up, the chart, the garage line and marking a missed item as done — on the pages.

The hand-checked car (schedule_fixtures.steady_car), new 1000 days ago, so today is its day 1000.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from schedule_fixtures import steady_car  # tests/ is on pytest's path

from amg.repo import schedules, services, vehicles
from amg.web import status


@pytest.fixture
def steady(conn):
    car, day, visits = steady_car(conn, date.today() - timedelta(days=1000))
    return car, day, visits


def _item(conn, car, name):
    return next(i for i in schedules.items(conn, car) if i["name"] == name)


def test_the_car_page_shows_next_up_missed_and_the_chart(signed_in, steady):
    car, _, visits = steady
    page = signed_in.get(f"/vehicles/{car}").text
    assert "Next up" in page and "Cabin air filter" in page and "mi overdue" in page
    assert "1 missed in the past" in page and "Today, estimated" in page and "~30,000 mi" in page
    assert 'class="ichart"' in page and f'href="/services/{visits[190]}"' in page
    assert "Mark as done" in page


def test_the_garage_counts_whats_overdue_and_missed(signed_in, steady):
    page = signed_in.get("/").text
    assert "2 overdue" in page and "1 missed" in page and "Next:" in page


def test_a_car_with_nothing_wrong_says_so(signed_in, conn):
    car = vehicles.create(conn, vehicles.VehicleFields(name="Fresh", in_service_date=date.today().isoformat()))
    draft = schedules.create_draft(conn, car, "template", draft={"origin": "template", "items": []})
    schedules.confirm(conn, draft, car, [schedules.ItemInput("Cabin air filter", "replace", ["cabin_air_filter"],
                                                             interval_months=12)], {})
    assert "Nothing overdue or missed" in signed_in.get("/").text


def test_mark_a_missed_item_as_done(signed_in, conn, steady):
    car, day, _ = steady
    rotation = _item(conn, car, "Tire rotation")
    missed = status.missed(status.load(conn, vehicles.get(conn, car)))
    assert [row["name"] for row in missed] == ["Tire rotation"]

    form = signed_in.get(missed[0]["attest_url"]).text
    due = missed[0]["attest_url"].rsplit("due=", 1)[1]
    assert "Mark as done" in form and f"It was due around {due}" in form and f'value="{due}"' in form

    response = signed_in.post(f"/vehicles/{car}/schedule-items/{rotation['id']}/done",
                              data={"performed_on": due, "odometer": "", "notes": "Rotated at home", "due": due},
                              follow_redirects=False)
    assert response.headers["location"] == f"/vehicles/{car}?attested=1#next"
    page = signed_in.get(response.headers["location"].split("#")[0]).text
    assert "Marked as done" in page and "missed in the past" not in page and "Done, no receipt" in page

    (attested,) = [e for e in services.history(conn, car) if e["source"] == "attested"]
    event = services.get_event(conn, attested["id"])
    assert event["notes"] == "Rotated at home" and event["odometer"] is None
    assert event["lines"][0]["covers"] == [{"code": "tire_rotation", "name": "Tire rotation", "action": "perform"}]


def test_mark_an_overdue_item_as_done_today(signed_in, conn, steady):
    car, _, _ = steady
    cabin = _item(conn, car, "Cabin air filter")
    form = signed_in.get(f"/vehicles/{car}/schedule-items/{cabin['id']}/done").text
    assert f'value="{date.today().isoformat()}"' in form
    signed_in.post(f"/vehicles/{car}/schedule-items/{cabin['id']}/done",
                   data={"performed_on": date.today().isoformat(), "odometer": "30,000", "notes": ""})
    state = status.load(conn, vehicles.get(conn, car))
    cabin_status = next(s for s in state.statuses if s.item.name == "Cabin air filter")
    assert cabin_status.current.status == "later"


@pytest.mark.parametrize(("fields", "message"), [
    ({"performed_on": ""}, "Enter the date it was done"),
    ({"performed_on": (date.today() + timedelta(days=3)).isoformat()}, "in the future"),
    ({"performed_on": date.today().isoformat(), "odometer": "1,000"}, "lower than the"),
])
def test_marking_as_done_checks_the_date_and_odometer(signed_in, conn, steady, fields, message):
    car, _, _ = steady
    cabin = _item(conn, car, "Cabin air filter")
    response = signed_in.post(f"/vehicles/{car}/schedule-items/{cabin['id']}/done",
                              data={"odometer": "", "notes": "", **fields})
    assert response.status_code == 422 and message in response.text


def test_another_cars_item_is_not_found(signed_in, conn, steady):
    car, _, _ = steady
    other = vehicles.create(conn, vehicles.VehicleFields(name="Other"))
    cabin = _item(conn, car, "Cabin air filter")
    assert signed_in.get(f"/vehicles/{other}/schedule-items/{cabin['id']}/done").status_code == 404


def test_an_old_reading_is_asked_for_on_the_car_page(signed_in, conn, steady):
    car, day, _ = steady                                # the last reading is the day-900 visit, 100 days ago
    page = signed_in.get(f"/vehicles/{car}").text
    assert f"The last odometer reading was {day(900):%b} {day(900).day}" in page and "3 months ago" in page
    assert 'href="#add-reading"' in page and 'id="add-reading"' in page
    signed_in.post(f"/vehicles/{car}/odometer", data={"read_on": date.today().isoformat(), "miles": "30100"})
    assert "The last odometer reading was" not in signed_in.get(f"/vehicles/{car}").text
