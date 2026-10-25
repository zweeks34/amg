"""Tying a logged service to the schedule job it did: a line tagged from the car's schedule.

The hand-checked car (schedule_fixtures.steady_car), new 1000 days ago: its cabin air filter and its oil and
filter are overdue, everything else later.
"""

from __future__ import annotations

import html
import json
import re
from datetime import date, timedelta

import pytest
from schedule_fixtures import steady_car  # tests/ is on pytest's path

from amg.repo import schedules, services, vehicles
from amg.repo.schedules import ItemInput
from amg.web import line_editor, schedule_links, status


@pytest.fixture
def steady(conn):
    return steady_car(conn, date.today() - timedelta(days=1000))


def _types(conn):
    return {row["code"]: row for row in services.list_types(conn)}


def _row(**fields):
    return {**line_editor.blank_line(), **fields}


def _schedule(conn, car, items):
    draft_id = schedules.create_draft(conn, car, "template", draft={"origin": "template", "items": []})
    schedules.confirm(conn, draft_id, car, items, {"origin": "template", "items": []})


def _state(conn, car):
    return status.load(conn, vehicles.get(conn, car))


def _current(conn, car, name):
    return next(s for s in _state(conn, car).statuses if s.item.name == name).current


def _service_form(lines, **fields):
    form = {"performed_on": date.today().isoformat(), "odometer": "", "source": "diy", "shop": "",
            "invoice_number": "", "tax": "", "total": "", "notes": ""}
    form.update(fields)
    form["lines_json"] = json.dumps(lines)
    return form


def _picked(job, **fields):
    """A line as the menu leaves it: the job's service types, each with the job's action."""
    actions = {} if job["action"] == "inspect" else {code: job["action"] for code in job["codes"]}
    return _row(description=job["name"], covers=list(job["codes"]), actions=actions, **fields)


# ---------- A line's own actions ----------


def test_a_line_keeps_its_own_action_and_inspected_only_still_wins(conn):
    lines, errors, _ = line_editor.parse_lines([
        _row(description="New hoses", covers=["cooling_system"], actions={"cooling_system": "replace"}),
        _row(description="Hoses looked at", covers=["cooling_system"], actions={"cooling_system": "replace"},
             inspect_only=True),
        _row(description="Hoses", covers=["cooling_system"]),
    ], _types(conn))
    assert errors == [None, None, None]
    # The hoses' usual action is to inspect them.
    assert [line.covers[0].action for line in lines] == ["replace", "inspect", "inspect"]


def test_only_real_actions_come_in_from_a_post():
    [row] = line_editor.clean_lines(json.dumps([{"description": "x", "covers": ["engine_oil"],
                                                 "actions": {"engine_oil": "replace", "oil_filter": "polish"}}]))
    assert row["actions"] == {"engine_oil": "replace"}
    [row] = line_editor.clean_lines(json.dumps([{"description": "x", "actions": "replace"}]))
    assert row["actions"] == {}


def test_an_edited_line_keeps_the_action_it_was_saved_with(conn):
    rows = line_editor.rows_from_draft([{"description": "New hoses", "kind": "part",
                                         "covers": [{"code": "cooling_system", "action": "replace"}]}])
    assert rows[0]["actions"] == {"cooling_system": "replace"} and not rows[0]["inspect_only"]
    lines, _, _ = line_editor.parse_lines(rows, _types(conn))
    assert [(c.code, c.action) for c in lines[0].covers] == [("cooling_system", "replace")]


# ---------- The jobs a line can be tagged for ----------


def test_picks_put_whats_due_first_then_the_schedule_in_order(conn, steady):
    car, _, _ = steady
    picks = status.picks(_state(conn, car))
    assert [p["name"] for p in picks] == ["Cabin air filter", "Engine oil and filter", "Engine coolant",
                                          "Brake inspection", "Tire rotation"]
    assert "mi overdue" in picks[0]["when"] and "mi overdue" in picks[1]["when"] and picks[2]["when"] == ""
    assert (picks[1]["codes"], picks[1]["action"]) == (["engine_oil", "oil_filter"], "replace")
    assert (picks[3]["codes"], picks[3]["action"]) == (["brake_pads", "brake_rotors"], "inspect")


def test_a_severe_only_job_isnt_offered_on_a_car_in_normal_service(conn):
    car = vehicles.create(conn, vehicles.VehicleFields(name="Mild", in_service_date="2024-01-01"))
    _schedule(conn, car, [ItemInput("Engine oil", "replace", ["engine_oil"], interval_months=12),
                          ItemInput("Engine oil, severe", "replace", ["engine_oil"], interval_months=6,
                                    applies="severe")])
    assert [p["name"] for p in status.picks(_state(conn, car))] == ["Engine oil"]


def test_the_service_form_offers_the_cars_jobs(signed_in, steady):
    car, _, _ = steady
    page = html.unescape(signed_in.get(f"/vehicles/{car}/services/new").text)
    assert "From the Steady's schedule…" in page
    assert re.search(r'<option value="\d+">Cabin air filter · [\d,]+ mi overdue', page)
    assert '<option value="' in page and ">Tire rotation</option>" in page


def test_no_menu_without_a_schedule(signed_in, conn):
    car = vehicles.create(conn, vehicles.VehicleFields(name="Bare"))
    assert "line__schedule" not in signed_in.get(f"/vehicles/{car}/services/new").text


def test_a_line_tagged_from_a_job_meets_it(signed_in, conn, steady):
    car, _, _ = steady
    cabin = next(p for p in status.picks(_state(conn, car)) if p["name"] == "Cabin air filter")
    response = signed_in.post(f"/vehicles/{car}/services", data=_service_form([_picked(cabin, amount="18.00")]),
                              follow_redirects=False)
    assert response.status_code == 303
    assert _current(conn, car, "Cabin air filter").status == "later"


def test_a_job_done_in_a_way_its_types_dont_usually_say_is_met_from_the_menu(signed_in, conn):
    car = vehicles.create(conn, vehicles.VehicleFields(
        name="Hoses", in_service_date=(date.today() - timedelta(days=800)).isoformat()))
    _schedule(conn, car, [ItemInput("Coolant hoses", "replace", ["cooling_system"], interval_months=24)])
    [job] = status.picks(_state(conn, car))
    # Tagged by typing alone, the hoses read as inspected, which doesn't meet a replacement.
    signed_in.post(f"/vehicles/{car}/services", data=_service_form([_row(covers=["cooling_system"])]))
    assert _current(conn, car, "Coolant hoses").status == "overdue"
    signed_in.post(f"/vehicles/{car}/services", data=_service_form([_picked(job)]))
    assert _current(conn, car, "Coolant hoses").status == "later"


# ---------- What a service counted for ----------


def _log(conn, car, day, *covers, source="diy"):
    """A service on ``day`` covering (code, action) pairs; an empty one is a line with no tags."""
    lines = [services.LineInput(description=code, covers=[services.Coverage(code, action)]) for code, action in covers]
    return services.create_event(conn, car, services.EventInput(
        performed_on=day.isoformat(), source=source, lines=lines or [services.LineInput(description="Oil change")]))


def _counted(conn, car, event_id):
    return schedule_links.counted_for(conn, vehicles.get(conn, car), services.get_event(conn, event_id))


def test_a_service_says_what_it_counted_for(signed_in, conn, steady):
    car, day, visits = steady
    found = _counted(conn, car, visits[190])
    # Day 190's visit: the oil, the tire rotation, and a multi-point inspection meeting the brake inspection.
    assert [row["name"] for row in found.met] == ["Engine oil and filter", "Brake inspection", "Tire rotation"]
    assert found.met[0]["due"].startswith("was due at 6,000 mi · ") and found.met[0]["due"].endswith(", done early")
    assert found.unmet == []
    page = html.unescape(signed_in.get(f"/services/{visits[190]}").text)
    assert "On the schedule" in page and "Counts for it · was due at 6,000 mi" in page


def test_an_untagged_service_counts_for_nothing_and_says_how_to_fix_it(signed_in, conn, steady):
    car, _, _ = steady
    event = _log(conn, car, date.today())
    found = _counted(conn, car, event)
    assert found.met == [] and found.unmet == []
    page = html.unescape(signed_in.get(f"/services/{event}").text)
    assert "This doesn't count for anything on the Steady's schedule" in page
    assert f'href="/services/{event}/edit">edit the service</a>' in page


def test_a_service_before_a_jobs_count_from_day_says_so(conn):
    car = vehicles.create(conn, vehicles.VehicleFields(
        name="Wipers", in_service_date=(date.today() - timedelta(days=400)).isoformat()))
    counts_from = date.today() - timedelta(days=10)
    _schedule(conn, car, [ItemInput("Wiper blades", "replace", ["wiper_blades"], interval_months=12,
                                    counts_from=counts_from.isoformat())])
    event = _log(conn, car, date.today() - timedelta(days=20), ("wiper_blades", "replace"))
    found = _counted(conn, car, event)
    assert found.met == []
    assert found.unmet == [{"name": "Wiper blades",
                            "why": f"it's on or before {counts_from:%b} {counts_from.day}, {counts_from.year}, "
                                   "the day this job counts from"}]


def test_a_second_service_the_same_day_doesnt_count_and_says_so(conn, steady):
    car, _, _ = steady
    first = _log(conn, car, date.today(), ("cabin_air_filter", "replace"))
    second = _log(conn, car, date.today(), ("cabin_air_filter", "replace"))
    assert [row["name"] for row in _counted(conn, car, first).met] == ["Cabin air filter"]
    assert _counted(conn, car, second).unmet == [
        {"name": "Cabin air filter", "why": "another service the same day already counted for it"}]


def test_a_cars_first_record_is_where_its_count_starts(conn):
    car = vehicles.create(conn, vehicles.VehicleFields(name="Undated"))
    _schedule(conn, car, [ItemInput("Cabin air filter", "replace", ["cabin_air_filter"], interval_months=12)])
    event = _log(conn, car, date.today() - timedelta(days=30), ("cabin_air_filter", "replace"))
    [unmet] = _counted(conn, car, event).unmet
    assert unmet["why"].startswith("it's the car's first record, which the schedule counts from")


def test_the_same_job_marked_done_with_no_receipt_nearby_is_pointed_to(signed_in, conn, steady):
    car, _, _ = steady
    cabin = next(i for i in schedules.items(conn, car) if i["name"] == "Cabin air filter")
    signed_in.post(f"/vehicles/{car}/schedule-items/{cabin['id']}/done",
                   data={"performed_on": date.today().isoformat(), "odometer": "", "notes": ""})
    attested = next(e["id"] for e in services.history(conn, car) if e["source"] == "attested")
    logged = _log(conn, car, date.today() - timedelta(days=3), ("cabin_air_filter", "replace"))
    [met] = _counted(conn, car, logged).met
    assert met["name"] == "Cabin air filter" and [t["href"] for t in met["twins"]] == [f"/services/{attested}"]
    page = signed_in.get(f"/services/{logged}").text
    assert "You also marked it done with no receipt on" in page and f'href="/services/{attested}"' in page
    assert [m["twins"] for m in _counted(conn, car, attested).met] == [[]]   # not the other way round


def test_no_section_without_a_schedule_or_before_a_service_is_confirmed(signed_in, conn):
    car = vehicles.create(conn, vehicles.VehicleFields(name="Bare"))
    event = _log(conn, car, date.today(), ("engine_oil", "replace"))
    assert _counted(conn, car, event) is None and "On the schedule" not in signed_in.get(f"/services/{event}").text
    unconfirmed = services.create_event(conn, car, services.EventInput(
        performed_on=date.today().isoformat(), source="receipt", lines=[services.LineInput(description="Oil")]),
        confirmed=False)
    assert _counted(conn, car, unconfirmed) is None
