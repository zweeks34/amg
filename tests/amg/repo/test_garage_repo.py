from __future__ import annotations

import sqlite3

import pytest

from amg.repo import documents, odometer, services, vehicles
from amg.repo.services import Coverage, EventInput, LineInput


@pytest.fixture
def car(conn):
    return vehicles.create(conn, vehicles.VehicleFields(name="Wagon", year=2016, make="Subaru", model="Outback"))


def test_a_cars_photo_comes_with_its_hash_and_can_be_taken_off(conn, car):
    assert vehicles.get(conn, car)["photo_document_id"] is None and vehicles.get(conn, car)["photo_sha256"] is None
    photo, _ = documents.store(conn, b"GIF89a" + b"\0" * 32, "wagon.gif")
    vehicles.set_photo(conn, car, photo["id"])
    row = vehicles.get(conn, car)
    assert (row["photo_document_id"], row["photo_sha256"]) == (photo["id"], photo["sha256"])
    (card,), _ = vehicles.garage(conn)
    assert card["photo_sha256"] == photo["sha256"]
    assert (row["photo_zoom"], row["photo_x"], row["photo_y"]) == (1, 0, 0)       # the whole photo, centred
    vehicles.set_photo(conn, car, photo["id"], vehicles.PhotoFrame(2.25, -30, 12.5))
    row = vehicles.get(conn, car)
    assert (row["photo_zoom"], row["photo_x"], row["photo_y"]) == (2.25, -30, 12.5)
    with pytest.raises(sqlite3.IntegrityError):
        vehicles.set_photo(conn, car, photo["id"], vehicles.PhotoFrame(5))       # past 4×
    vehicles.set_photo(conn, car, None, vehicles.PhotoFrame(2, 10, 10))
    row = vehicles.get(conn, car)
    assert (row["photo_document_id"], row["photo_zoom"], row["photo_x"], row["photo_y"]) == (None, 1, 0, 0)
    assert documents.get(conn, photo["id"]) is not None              # the file stays


def _oil_change(on="2020-01-10", miles=30_000, **kw):
    return EventInput(
        performed_on=on,
        source="shop",
        odometer=miles,
        shop="Corner Garage",
        total_cents=8_999,
        lines=[
            LineInput("Synthetic oil and filter", kind="labor", amount_cents=7_999,
                      covers=[Coverage("engine_oil", "replace"), Coverage("oil_filter", "replace")]),
            LineInput("Multi-point inspection", covers=[Coverage("multipoint_inspection", "inspect"),
                                                         Coverage("brake_pads", "inspect")]),
            LineInput("Shop supplies", kind="fee", amount_cents=1_000),
        ],
        **kw,
    )


def test_service_type_catalogue_is_seeded(conn):
    codes = [row["code"] for row in services.list_types(conn)]
    assert len(codes) == len(set(codes)) >= 40
    assert {"engine_oil", "tire_rotation", "cabin_air_filter", "inverter_coolant", "ev_battery_coolant"} <= set(codes)


def test_types_are_filtered_by_powertrain(conn):
    ev = {row["code"] for row in services.list_types(conn, "ev")}
    gas = {row["code"] for row in services.list_types(conn, "gas")}
    assert "engine_oil" not in ev and "ev_battery_coolant" in ev
    assert "engine_oil" in gas and "inverter_coolant" not in gas


def test_custom_type_gets_a_unique_code(conn):
    code = services.add_custom_type(conn, "Throttle body cleaning", "Engine", "perform")
    assert code == "custom_throttle_body_cleaning"
    with pytest.raises(ValueError, match="already"):
        services.add_custom_type(conn, "throttle body cleaning", "Engine")


def test_event_round_trip_with_coverage(conn, car):
    event_id = services.create_event(conn, car, _oil_change())
    event = services.get_event(conn, event_id)
    assert [line["description"] for line in event["lines"]] == [
        "Synthetic oil and filter", "Multi-point inspection", "Shop supplies"]
    assert [c["code"] for c in event["lines"][0]["covers"]] == ["engine_oil", "oil_filter"]
    assert event["lines"][2]["covers"] == []
    assert services.event_input(event).lines[0].covers[0] == Coverage("engine_oil", "replace")


def test_history_marks_inspection_only_coverage(conn, car):
    services.create_event(conn, car, _oil_change())
    [event] = services.history(conn, car)
    covered = {item["code"]: item["inspected_only"] for item in event["covered"]}
    assert covered["engine_oil"] is False
    assert covered["brake_pads"] is True


def test_update_replaces_lines(conn, car):
    event_id = services.create_event(conn, car, _oil_change())
    changed = _oil_change()
    changed.lines = [LineInput("Tire rotation", covers=[Coverage("tire_rotation", "perform")])]
    services.update_event(conn, event_id, changed)
    event = services.get_event(conn, event_id)
    assert [line["description"] for line in event["lines"]] == ["Tire rotation"]
    assert conn.execute("SELECT count(*) FROM line_item_services").fetchone()[0] == 1


def test_delete_removes_lines_and_coverage(conn, car):
    event_id = services.create_event(conn, car, _oil_change())
    services.delete_event(conn, event_id)
    assert conn.execute("SELECT count(*) FROM line_items").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM line_item_services").fetchone()[0] == 0


def test_unknown_service_code_rolls_back_the_whole_event(conn, car):
    bad = _oil_change()
    bad.lines[0].covers.append(Coverage("flux_capacitor", "replace"))
    with pytest.raises(ValueError, match="flux_capacitor"):
        services.create_event(conn, car, bad)
    assert conn.execute("SELECT count(*) FROM service_events").fetchone()[0] == 0


def test_a_car_with_history_cannot_be_hard_deleted(conn, car):
    services.create_event(conn, car, _oil_change())
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM vehicles WHERE id = ?", (car,))


def test_archive_moves_a_car_out_of_the_garage(conn, car):
    vehicles.archive(conn, car)
    active, archived = vehicles.garage(conn)
    assert active == [] and [c["id"] for c in archived] == [car]
    vehicles.restore(conn, car)
    assert [c["id"] for c in vehicles.garage(conn)[0]] == [car]


def test_garage_summary_has_latest_odometer_and_last_service(conn, car):
    services.create_event(conn, car, _oil_change(on="2020-01-10", miles=30_000))
    odometer.add(conn, car, "2021-06-01", 41_000)
    [summary] = vehicles.garage(conn)[0]
    assert summary["odometer"] == {"read_on": "2021-06-01", "miles": 41_000, "source": "manual"}
    assert summary["last_service"]["performed_on"] == "2020-01-10"
    assert summary["service_count"] == 1


def test_odometer_points_gather_every_source(conn):
    car = vehicles.create(conn, vehicles.VehicleFields(name="Used", acquired_date="2019-05-01", acquired_miles=12_000))
    services.create_event(conn, car, _oil_change(on="2020-01-10", miles=20_000))
    odometer.add(conn, car, "2021-01-01", 30_000)
    assert [(p["source"], p["miles"]) for p in odometer.points(conn, car)] == [
        ("acquired", 12_000), ("service", 20_000), ("manual", 30_000)]


def test_unconfirmed_services_are_not_odometer_points(conn, car):
    services.create_event(conn, car, _oil_change(), confirmed=False)
    assert odometer.points(conn, car) == []


@pytest.mark.parametrize(
    ("on", "miles", "expected"),
    [
        ("2021-01-01", 25_000, "lower"),   # lower than an earlier reading
        ("2019-01-01", 35_000, "higher"),  # higher than a later one
        ("2020-01-10", 10, None),          # same day is never compared
        ("2020-06-01", 31_000, None),
    ],
)
def test_odometer_conflicts(conn, car, on, miles, expected):
    services.create_event(conn, car, _oil_change(on="2020-01-10", miles=30_000))
    clash = odometer.conflict(conn, car, on, miles)
    if expected is None:
        assert clash is None
    else:
        assert expected in clash.message()


def test_a_reading_is_not_judged_against_itself(conn, car):
    event_id = services.create_event(conn, car, _oil_change(on="2020-01-10", miles=30_000))
    odometer.add(conn, car, "2020-06-01", 32_000)
    assert odometer.conflict(conn, car, "2020-01-10", 33_000) is not None
    # editing the service itself: its old 30,000 must not count against it
    assert odometer.conflict(conn, car, "2020-01-10", 31_000, ignore=("service", event_id)) is None
