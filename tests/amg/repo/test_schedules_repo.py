from __future__ import annotations

import sqlite3

import pytest
import receipt_fixtures as fx  # tests/ is on pytest's path

from amg.ingest import schedule_drafts as sd
from amg.repo import jobs, schedules, vehicles
from amg.repo.schedules import ItemInput


@pytest.fixture
def cars(conn):
    return (vehicles.create(conn, vehicles.VehicleFields(name="Outback", year=2016, make="Subaru", model="Outback")),
            vehicles.create(conn, vehicles.VehicleFields(name="Forester", year=2016, make="Subaru", model="Forester")))


def _oil(**changes):
    item = ItemInput(name="Engine oil", action="replace", codes=["engine_oil", "oil_filter"], interval_miles=6000,
                     interval_months=6, source="manual", page=1)
    for key, value in changes.items():
        setattr(item, key, value)
    return item


def _use(conn, car, items, origin="template"):
    draft = sd.ScheduleDraft(origin=origin)
    draft_id = schedules.create_draft(conn, car, origin, draft=draft.to_dict())
    schedules.confirm(conn, draft_id, car, items, draft.to_dict())
    return draft_id


def test_using_a_draft_writes_the_schedule(conn, cars):
    outback, _ = cars
    draft_id = _use(conn, outback, [_oil(), ItemInput(name="Coolant", action="replace", codes=["engine_coolant"],
                                                      first_miles=137_500, first_months=132, interval_miles=75_000,
                                                      interval_months=72)])
    oil, coolant = schedules.items(conn, outback)
    assert oil["codes"] == ["engine_oil", "oil_filter"] and oil["category"] == "Engine"
    assert (oil["interval_miles"], oil["interval_months"]) == (6000, 6)    # whichever comes first, both kept
    assert (coolant["first_miles"], coolant["first_months"], coolant["interval_miles"]) == (137_500, 132, 75_000)
    assert oil["draft_id"] == draft_id
    assert schedules.get_draft(conn, draft_id)["status"] == "confirmed"


def test_using_another_draft_replaces_the_schedule(conn, cars):
    outback, _ = cars
    _use(conn, outback, [_oil(), _oil(name="Second")])
    _use(conn, outback, [_oil(name="Only")])
    assert [item["name"] for item in schedules.items(conn, outback)] == ["Only"]


def test_saving_an_edited_schedule_keeps_ids(conn, cars):
    outback, _ = cars
    _use(conn, outback, [_oil(), _oil(name="Tires", codes=["tire_rotation"], action="perform")])
    oil, tires = schedules.items(conn, outback)
    edited = sd.to_items(sd.from_items([oil], origin="manual", keep_ids=True))
    edited[0].interval_miles = 5000
    edited.append(ItemInput(name="Wipers", action="replace", codes=["wiper_blades"], interval_months=12))
    schedules.save_items(conn, outback, edited)

    after = schedules.items(conn, outback)
    assert [(item["id"], item["name"], item["interval_miles"]) for item in after[:1]] == [(oil["id"], "Engine oil", 5000)]
    assert [item["name"] for item in after] == ["Engine oil", "Wipers"]
    assert tires["id"] not in {item["id"] for item in after}


def test_editing_a_copied_schedule_leaves_the_original_alone(conn, cars):
    outback, forester = cars
    _use(conn, outback, [_oil()])
    copy = sd.from_items(schedules.items(conn, outback))
    _use(conn, forester, sd.to_items(copy), origin="copy")

    (theirs,) = schedules.items(conn, forester)
    changed = sd.to_items(sd.from_items([theirs], keep_ids=True))
    changed[0].interval_miles = 3000
    changed[0].codes = ["engine_oil"]
    schedules.save_items(conn, forester, changed)

    (ours,) = schedules.items(conn, outback)
    assert (ours["interval_miles"], ours["codes"]) == (6000, ["engine_oil", "oil_filter"])
    assert ours["id"] != theirs["id"]


def test_an_item_needs_an_interval(conn, cars):
    with pytest.raises(sqlite3.IntegrityError):
        _use(conn, cars[0], [ItemInput(name="Never", action="inspect", codes=["clutch"])])


def test_an_unknown_service_type_is_refused(conn, cars):
    with pytest.raises(ValueError, match="Unknown service type"):
        _use(conn, cars[0], [_oil(codes=["blinker_fluid"])])
    assert schedules.items(conn, cars[0]) == []   # the transaction rolled back


def test_severe_service_switch(conn, cars):
    schedules.set_severe(conn, cars[0], True)
    assert vehicles.get(conn, cars[0])["severe_service"] == 1
    schedules.set_severe(conn, cars[0], False)
    assert vehicles.get(conn, cars[0])["severe_service"] == 0


def test_cars_with_schedules_to_copy(conn, cars):
    outback, forester = cars
    _use(conn, outback, [_oil()])
    assert schedules.cars_with_schedules(conn, exclude=forester) == [{"id": outback, "name": "Outback", "items": 1}]
    assert schedules.cars_with_schedules(conn, exclude=outback) == []


# ---------- A draft's life ----------


def test_reading_a_draft_then_reading_it_again(conn, cars):
    job = jobs.create(conn, "read_schedule")
    draft_id = schedules.create_draft(conn, cars[0], "manual", requested_pages="", job_id=job)
    assert schedules.claim_next(conn, job) == draft_id
    assert schedules.claim_next(conn, job) is None
    schedules.mark_read(conn, draft_id, {"items": []}, {"origin": "manual", "items": []}, ["Look"], [1, 2], fx.USAGE)
    read = schedules.get_draft(conn, draft_id)
    assert (read["status"], read["pages"], read["warnings"], read["cost_usd"] is not None) == ("read", [1, 2], ["Look"], True)

    again = jobs.create(conn, "read_schedule")
    schedules.requeue(conn, draft_id, again, requested_pages="30-31")
    queued = schedules.get_draft(conn, draft_id)
    assert (queued["status"], queued["job_id"], queued["requested_pages"]) == ("queued", again, "30-31")


def test_failed_drafts_can_be_discarded_and_restored(conn, cars):
    draft_id = schedules.create_draft(conn, cars[0], "claude", job_id=jobs.create(conn, "read_schedule"))
    schedules.mark_failed(conn, draft_id, "Claude took too long")
    schedules.discard(conn, draft_id)
    assert schedules.get_draft(conn, draft_id)["status"] == "discarded"
    assert schedules.open_drafts(conn, cars[0]) == []
    schedules.restore(conn, draft_id)
    assert schedules.get_draft(conn, draft_id)["status"] == "failed"


def test_a_template_draft_is_ready_to_check(conn, cars):
    draft_id = schedules.create_draft(conn, cars[0], "template", draft={"origin": "template", "items": []})
    assert schedules.get_draft(conn, draft_id)["status"] == "read"
    assert [d["id"] for d in schedules.open_drafts(conn, cars[0])] == [draft_id]
