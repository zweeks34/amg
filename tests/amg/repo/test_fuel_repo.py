from __future__ import annotations

import sqlite3

import pytest

from amg.repo import fuel, odometer, vehicles
from amg.repo.fuel import FillInput


@pytest.fixture
def car(conn):
    return vehicles.create(conn, vehicles.VehicleFields(name="Wagon", year=2016, make="Subaru", model="Outback"))


@pytest.fixture
def ev(conn):
    return vehicles.create(conn, vehicles.VehicleFields(name="Volt", powertrain="ev"))


def _fill(on="2026-09-28", miles=64_300, gallons=11.482, cents=3_972, **kw):
    return FillInput(filled_on=on, odometer=miles, energy="gas", quantity=gallons, cost_cents=cents, **kw)


def test_fill_round_trip(conn, car):
    fill_id = fuel.create(conn, car, _fill(note="Costco"))
    row = fuel.get(conn, fill_id)
    assert (row["filled_on"], row["odometer"], row["quantity"], row["cost_cents"], row["full"], row["note"]) == (
        "2026-09-28", 64_300, 11.482, 3_972, 1, "Costco")

    fuel.update(conn, fill_id, _fill(miles=64_310, full=False, missed_before=True))
    row = fuel.get(conn, fill_id)
    assert (row["odometer"], row["full"], row["missed_before"]) == (64_310, 0, 1)

    fuel.delete(conn, fill_id)
    assert fuel.get(conn, fill_id) is None


def test_the_log_is_newest_first(conn, car):
    fuel.create(conn, car, _fill(on="2026-09-01", miles=64_000))
    fuel.create(conn, car, _fill(on="2026-09-28", miles=64_300))
    fuel.create(conn, car, _fill(on="2026-09-28", miles=64_290, full=False))
    assert [row["odometer"] for row in fuel.log(conn, car)] == [64_300, 64_290, 64_000]
    assert fuel.last(conn, car)["odometer"] == 64_300


def test_a_charge_has_a_place_and_a_fill_does_not(conn, car, ev):
    fuel.create(conn, ev, FillInput("2026-09-28", 12_000, "electric", 42.5, 638, place="home"))
    with pytest.raises(ValueError):
        fuel.create(conn, car, _fill(place="home"))
    with pytest.raises(ValueError):
        fuel.create(conn, car, _fill(gallons=0))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE fuel_logs SET place = 'driveway'")


def test_fills_and_charges_are_odometer_readings(conn, car, ev):
    odometer.add(conn, car, "2026-08-01", 63_000)
    fill_id = fuel.create(conn, car, _fill())
    charge_id = fuel.create(conn, ev, FillInput("2026-09-28", 12_000, "electric", 42.5, place="public"))
    assert [(p["source"], p["source_id"], p["miles"]) for p in odometer.points(conn, car)] == [
        ("manual", 1, 63_000), ("fill", fill_id, 64_300)]
    assert [(p["source"], p["source_id"]) for p in odometer.points(conn, ev)] == [("charge", charge_id)]
    assert vehicles.latest_odometer(conn, car) == {"read_on": "2026-09-28", "miles": 64_300, "source": "fill"}


def test_an_odometer_lower_than_an_earlier_fill_is_refused(conn, car):
    fill_id = fuel.create(conn, car, _fill(on="2026-09-28", miles=64_300))
    clash = odometer.conflict(conn, car, "2026-10-02", 64_030)
    assert clash.message() == "That's lower than the 64,300 mi recorded earlier, on 2026-09-28 (a fill-up)."
    # editing the fill itself: its old 64,300 doesn't count against it
    assert odometer.conflict(conn, car, "2026-09-28", 64_030, ignore=(fuel.point_source("gas"), fill_id)) is None


def test_cars_by_last_fill(conn, car, ev):
    later = vehicles.create(conn, vehicles.VehicleFields(name="Another"))
    gone = vehicles.create(conn, vehicles.VehicleFields(name="Sold"))
    vehicles.archive(conn, gone)
    fuel.create(conn, car, _fill(on="2026-09-01"))
    fuel.create(conn, ev, FillInput("2026-09-28", 12_000, "electric", 42.5, place="home"))
    assert [row["name"] for row in fuel.cars_by_last_fill(conn)] == ["Volt", "Wagon", "Another"]
    assert later in [row["id"] for row in fuel.cars_by_last_fill(conn)]
    assert all("photo_sha256" in row.keys() for row in fuel.cars_by_last_fill(conn))   # for the picker's avatars


def test_energy_follows_the_powertrain():
    assert [fuel.energy_for(p) for p in vehicles.POWERTRAINS] == ["gas", "gas", "electric"]
