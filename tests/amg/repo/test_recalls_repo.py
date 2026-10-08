"""Storing what NHTSA lists for a car: new recalls added, yours kept, untouched ones NHTSA drops dropped."""

from __future__ import annotations

from datetime import date

import recall_fixtures as nf  # tests/ is on pytest's path

from amg.ingest import recalls as nhtsa
from amg.repo import recalls, vehicles

OCT_7 = date(2026, 10, 7)


def _car(conn, **fields):
    return vehicles.create(conn, vehicles.VehicleFields(**{"name": "Outback", "year": 2016, "make": "Subaru",
                                                           "model": "Outback", **fields}))


def _lookup(*rows, model="OUTBACK"):
    return nhtsa.Lookup(model, ("LEGACY", "OUTBACK"), tuple(nhtsa.parse({"results": list(rows)})))


def test_new_recalls_are_added_and_the_check_is_kept(conn):
    car = _car(conn)
    assert recalls.record(conn, car, _lookup(nf.AIR_BAG, nf.STEERING), OCT_7) == ["19V910000", "16V292000"]
    assert [row["campaign"] for row in recalls.open_for(conn, car)] == ["19V910000", "16V292000"]   # newest first
    row = vehicles.get(conn, car)
    assert (row["recalls_checked_on"], row["recalls_model"], row["recalls_listed"], row["recalls_error"]) == (
        "2026-10-07", "OUTBACK", "LEGACY,OUTBACK", "")


def test_yours_is_kept_when_checked_again(conn):
    car = _car(conn)
    recalls.record(conn, car, _lookup(nf.AIR_BAG, nf.STEERING), OCT_7)
    steering = next(r for r in recalls.for_car(conn, car) if r["campaign"] == "16V292000")
    recalls.close(conn, steering["id"], "not_mine", "2026-10-07")
    assert recalls.record(conn, car, _lookup(nf.AIR_BAG, {**nf.STEERING, "Summary": "Reworded."}), OCT_7) == []
    again = recalls.get(conn, steering["id"])
    assert (again["status"], again["summary"]) == ("not_mine", "Reworded.")


def test_an_untouched_one_nhtsa_no_longer_lists_is_dropped(conn):
    car = _car(conn)
    recalls.record(conn, car, _lookup(nf.AIR_BAG, nf.STEERING), OCT_7)
    steering = next(r for r in recalls.for_car(conn, car) if r["campaign"] == "16V292000")
    recalls.close(conn, steering["id"], "done", "2016-06-01")
    recalls.record(conn, car, _lookup(model=""), OCT_7)             # say the model was corrected to one with none
    assert [(r["campaign"], r["status"]) for r in recalls.for_car(conn, car)] == [("16V292000", "done")]


def test_a_failed_check_is_kept_until_one_works(conn):
    car = _car(conn)
    recalls.failed(conn, car, "Couldn't reach NHTSA's recall service.")
    assert vehicles.get(conn, car)["recalls_error"] == "Couldn't reach NHTSA's recall service."
    recalls.record(conn, car, _lookup(), OCT_7)
    assert vehicles.get(conn, car)["recalls_error"] == ""


def test_each_car_is_checked_weekly(conn):
    car = _car(conn)
    _car(conn, name="Mystery", year=None)                              # nothing to ask NHTSA with
    assert [c["id"] for c in recalls.due_for_check(conn, OCT_7)] == [car]
    recalls.record(conn, car, _lookup(), OCT_7)
    assert recalls.due_for_check(conn, date(2026, 10, 13)) == []
    assert [c["id"] for c in recalls.due_for_check(conn, date(2026, 10, 14))] == [car]


def test_changing_the_model_checks_again(conn):
    car = _car(conn)
    recalls.record(conn, car, _lookup(), OCT_7)
    vehicles.update(conn, car, vehicles.VehicleFields(name="My Outback", year=2016, make="Subaru", model="Outback"))
    assert vehicles.get(conn, car)["recalls_checked_on"] == "2026-10-07"      # a new name isn't a new car
    vehicles.update(conn, car, vehicles.VehicleFields(name="My Outback", year=2016, make="Subaru", model="Legacy"))
    assert vehicles.get(conn, car)["recalls_checked_on"] is None
