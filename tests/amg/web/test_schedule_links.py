"""Tying a logged service to the schedule job it did: a line tagged from the car's schedule, what a service
counted for, and Mark as done with a service you logged.

The hand-checked car (schedule_fixtures.steady_car), new 1000 days ago: its cabin air filter and its oil and
filter are overdue, everything else later.
"""

from __future__ import annotations

import html
import json
import re
from datetime import date, timedelta

import pymupdf
import pytest
import receipt_fixtures as fx  # tests/ is on pytest's path
from schedule_fixtures import steady_car

from amg.ingest import drafts
from amg.repo import documents, jobs, receipts, schedules, services, vehicles
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


# ---------- Mark as done, with a service you logged ----------


def _item_row(conn, car, name):
    return next(i for i in schedules.items(conn, car) if i["name"] == name)


def _service_editor(page: str) -> dict:
    """The JSON the service form hands its line editor."""
    return json.JSONDecoder().raw_decode(page, page.index("serviceLines(") + len("serviceLines("))[0]


def _receipt(conn, car, day, work):
    """A receipt read and confirmed for the car, its one line tagged with nothing."""
    with pymupdf.open() as doc:
        doc.new_page().insert_text((72, 72), f"{day} {work}")
        document, _ = documents.store(conn, doc.tobytes(), "receipt.pdf")
    job_id = jobs.create(conn, "read_receipts")
    receipt_id = receipts.create(conn, document["id"], job_id)
    receipts.claim_next(conn, job_id)
    extraction = fx.extraction(date=day.isoformat(), odometer=None, lines=[fx.line(work, 40.0, ())],
                               recommendations=[], subtotal=40.0, tax=0, total=40.0)
    receipts.mark_read(conn, receipt_id, extraction.model_dump(), drafts.from_extraction(extraction, _types(conn)), [],
                       fx.USAGE)
    receipts.confirm(conn, receipt_id, receipts.get(conn, receipt_id)["draft"], car)
    return receipt_id


def test_mark_as_done_offers_the_cars_own_services_nearest_when_it_falls_due(signed_in, conn, steady):
    car, day, visits = steady
    cabin = _item_row(conn, car, "Cabin air filter")
    untagged = [_log(conn, car, day(999)), _log(conn, car, day(1000))]
    _log(conn, vehicles.create(conn, vehicles.VehicleFields(name="Other")), day(745))
    rotation = _item_row(conn, car, "Tire rotation")
    signed_in.post(f"/vehicles/{car}/schedule-items/{rotation['id']}/done",
                   data={"performed_on": day(746).isoformat(), "odometer": "", "notes": ""})
    found = schedule_links.candidates(conn, vehicles.get(conn, car), cabin["id"])
    # It fell due again on day 745. The five of the car's own services nearest that, newest first: not day 380's,
    # which did the filter, nor the "Done, no receipt" on day 746, nor the other car's; day 190's is sixth nearest.
    assert [row["href"] for row in found] == [f"/services/{e}/edit?item={cabin['id']}" for e in
                                              (untagged[1], untagged[0], visits[900], visits[640], visits[400])]
    assert (found[0]["who"], found[0]["lines"]) == ("Your own work", "Oil change")
    assert (found[2]["who"], found[2]["lines"]) == ("Corner Garage", "tire_rotation, brake_pads")


def test_the_mark_as_done_page_offers_a_logged_service_then_logging_one_then_no_receipt(signed_in, conn, steady):
    car, _, visits = steady
    cabin = _item_row(conn, car, "Cabin air filter")
    page = html.unescape(signed_in.get(f"/vehicles/{car}/schedule-items/{cabin['id']}/done").text)
    assert f'href="/services/{visits[900]}/edit?item={cabin["id"]}">Tag it for this job' in page
    assert f'href="/vehicles/{car}/services/new?item={cabin["id"]}">Log a service for it' in page
    assert page.index("Was it a service you logged?") < page.index("Not logged yet?") < page.index(
        "Done with no receipt") < page.index('<button class="btn btn--primary" type="submit">Mark as done')


def test_a_missed_job_offers_the_services_nearest_when_it_was_missed(signed_in, conn, steady):
    car, _, visits = steady
    [missed] = status.missed(_state(conn, car))
    rotation = _item_row(conn, car, "Tire rotation")
    page = signed_in.get(missed["attest_url"]).text
    # Missed on day 390; of the car's services, only days 380 and 400 didn't rotate the tires.
    offered = re.findall(r'href="/services/(\d+)/edit\?item=' + str(rotation["id"]), page)
    assert offered == [str(visits[400]), str(visits[380])]
    assert signed_in.get(f"/vehicles/{car}/schedule-items/{rotation['id']}/done?due=soon").status_code == 200


def test_services_on_or_before_a_jobs_count_from_day_arent_offered(conn):
    car = vehicles.create(conn, vehicles.VehicleFields(
        name="Wipers", in_service_date=(date.today() - timedelta(days=400)).isoformat()))
    _schedule(conn, car, [ItemInput("Wiper blades", "replace", ["wiper_blades"], interval_months=12,
                                    counts_from=(date.today() - timedelta(days=10)).isoformat())])
    _log(conn, car, date.today() - timedelta(days=20))
    after = _log(conn, car, date.today() - timedelta(days=5))
    item = _item_row(conn, car, "Wiper blades")
    found = schedule_links.candidates(conn, vehicles.get(conn, car), item["id"])
    assert [row["href"] for row in found] == [f"/services/{after}/edit?item={item['id']}"]


def test_tagging_a_logged_service_fills_in_its_first_untagged_line(signed_in, conn, steady):
    car, day, _ = steady
    cabin = _item_row(conn, car, "Cabin air filter")
    event = services.create_event(conn, car, services.EventInput(performed_on=day(999).isoformat(), source="diy", lines=[
        services.LineInput(description="Oil", covers=[services.Coverage("engine_oil", "replace")]),
        services.LineInput(description="Cabin filter", amount_cents=1_800)]))
    page = signed_in.get(f"/services/{event}/edit?item={cabin['id']}").text
    editor = _service_editor(page)
    assert [(line["description"], line["covers"]) for line in editor["lines"]] == [
        ("Oil", ["engine_oil"]), ("Cabin filter", ["cabin_air_filter"])]
    assert editor["lines"][1]["actions"] == {"cabin_air_filter": "replace"}
    assert "Tagged for Cabin air filter on a line below" in page
    assert _current(conn, car, "Cabin air filter").status == "overdue"           # nothing changes until it's saved
    signed_in.post(f"/services/{event}/edit", data=_service_form(editor["lines"], performed_on=day(999).isoformat()))
    assert _current(conn, car, "Cabin air filter").status == "later"


def test_a_service_with_every_line_tagged_gets_a_new_line_and_another_cars_job_is_ignored(signed_in, conn, steady):
    car, _, visits = steady
    cabin = _item_row(conn, car, "Cabin air filter")
    lines = _service_editor(signed_in.get(f"/services/{visits[900]}/edit?item={cabin['id']}").text)["lines"]
    assert [(line["description"], line["covers"]) for line in lines] == [
        ("tire_rotation", ["tire_rotation"]), ("brake_pads", ["brake_pads"]), ("Cabin air filter", ["cabin_air_filter"])]
    other = vehicles.create(conn, vehicles.VehicleFields(name="Other", in_service_date="2024-01-01"))
    _schedule(conn, other, [ItemInput("Cabin air filter", "replace", ["cabin_air_filter"], interval_months=12)])
    page = signed_in.get(f"/services/{visits[900]}/edit?item={_item_row(conn, other, 'Cabin air filter')['id']}").text
    assert "Tagged for" not in page and len(_service_editor(page)["lines"]) == 2


def test_log_a_service_for_a_job(signed_in, conn, steady):
    car, _, _ = steady
    brakes = _item_row(conn, car, "Brake inspection")
    [line] = _service_editor(signed_in.get(f"/vehicles/{car}/services/new?item={brakes['id']}").text)["lines"]
    assert (line["description"], line["covers"], line["inspect_only"], line["actions"]) == (
        "Brake inspection", ["brake_pads", "brake_rotors"], True, {})


def test_a_service_from_a_receipt_is_tagged_on_the_receipts_review(signed_in, conn, steady):
    car, day, _ = steady
    cabin = _item_row(conn, car, "Cabin air filter")
    receipt_id = _receipt(conn, car, day(990), "Cabin filter")
    event = receipts.get(conn, receipt_id)["service_event_id"]
    hrefs = [row["href"] for row in schedule_links.candidates(conn, vehicles.get(conn, car), cabin["id"])]
    assert f"/receipts/{receipt_id}?item={cabin['id']}" in hrefs
    response = signed_in.get(f"/services/{event}/edit?item={cabin['id']}", follow_redirects=False)
    assert response.headers["location"] == f"/receipts/{receipt_id}?item={cabin['id']}"
    page = signed_in.get(response.headers["location"]).text
    start = page.index("receiptEditor(") + len("receiptEditor(")
    [line] = json.JSONDecoder().raw_decode(page, start)[0]["lines"]
    assert (line["description"], line["covers"]) == ("Cabin filter", ["cabin_air_filter"])
    assert "Tagged for Cabin air filter on a line of the work done" in page
