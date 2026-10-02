from __future__ import annotations

import json

import pytest

from amg.ingest import vin
from amg.repo import services, vehicles

GOOD_VIN = "1M8GDM9AXKP042788"


@pytest.fixture
def car(conn):
    return vehicles.create(conn, vehicles.VehicleFields(name="Wagon", year=2016, make="Subaru", model="Outback"))


def _line(description="", covers=(), amount="", kind="other", inspect_only=False):
    return {"description": description, "covers": list(covers), "amount": amount, "kind": kind,
            "inspect_only": inspect_only, "part_number": "", "quantity": ""}


def _service_form(lines, **fields):
    form = {"performed_on": "2020-01-10", "odometer": "30,000", "source": "shop", "shop": "Corner Garage",
            "invoice_number": "", "tax": "", "total": "", "notes": ""}
    form.update(fields)
    form["lines_json"] = json.dumps(lines)
    return form


# ---------- Cars ----------


def test_add_a_car(signed_in, conn):
    response = signed_in.post("/vehicles", data={
        "name": "", "vin": GOOD_VIN.lower(), "year": "2019", "make": "Subaru", "model": "Outback",
        "powertrain": "gas", "acquired_date": "2019-05-01", "acquired_miles": "12,000",
    }, follow_redirects=False)
    assert response.status_code == 303
    car = vehicles.get(conn, int(response.headers["location"].rsplit("/", 1)[1]))
    assert car["name"] == "2019 Subaru Outback"
    assert car["vin"] == GOOD_VIN
    assert car["acquired_miles"] == 12_000


def test_bad_vin_is_explained(signed_in):
    response = signed_in.post("/vehicles", data={"name": "X", "vin": GOOD_VIN[:-1] + "9", "powertrain": "gas"})
    assert response.status_code == 422
    assert "check digit" in response.text


def test_duplicate_vin_is_refused(signed_in, conn):
    vehicles.create(conn, vehicles.VehicleFields(name="First", vin=GOOD_VIN))
    response = signed_in.post("/vehicles", data={"name": "Second", "vin": GOOD_VIN, "powertrain": "gas"})
    assert response.status_code == 422
    assert "already has this VIN" in response.text


def test_acquired_mileage_needs_a_date(signed_in):
    response = signed_in.post("/vehicles", data={"name": "X", "powertrain": "gas", "acquired_miles": "5000"})
    assert response.status_code == 422
    assert "Add the date you got it" in response.text


def test_vin_lookup_fills_the_form(signed_in, monkeypatch):
    monkeypatch.setattr(vin, "decode", lambda v: vin.Decoded(2020, "Toyota", "Prius", "LE", "1.8L 4-cyl", "hybrid"))
    response = signed_in.post("/vehicles/vin-lookup", data={"vin": GOOD_VIN, "name": ""}, headers={"HX-Request": "true"})
    assert response.status_code == 200
    assert 'id="vehicle-fields"' in response.text
    assert 'value="Prius"' in response.text and 'value="hybrid" checked' in response.text
    assert "Filled in from NHTSA" in response.text


def test_vin_lookup_reports_service_failure(signed_in, monkeypatch):
    def down(v):
        raise vin.VinLookupError("Couldn't reach NHTSA's VIN service.")

    monkeypatch.setattr(vin, "decode", down)
    response = signed_in.post("/vehicles/vin-lookup", data={"vin": GOOD_VIN})
    assert "reach NHTSA&#39;s VIN service" in response.text


def test_plate_is_kept_through_an_edit(signed_in, conn, car):
    signed_in.post(f"/vehicles/{car}/edit", data={"name": "Wagon", "powertrain": "gas", "plate": "abc 1234"})
    assert vehicles.get(conn, car)["plate"] == "ABC 1234"
    assert 'value="ABC 1234"' in signed_in.get(f"/vehicles/{car}/edit").text


def test_edit_and_archive_a_car(signed_in, conn, car):
    signed_in.post(f"/vehicles/{car}/edit", data={"name": "Old wagon", "powertrain": "gas"})
    assert vehicles.get(conn, car)["name"] == "Old wagon"
    signed_in.post(f"/vehicles/{car}/archive")
    assert "Archived cars (1)" in signed_in.get("/").text


def test_garage_lists_cars(signed_in, car):
    page = signed_in.get("/").text
    assert "Wagon" in page and "No cars yet" not in page


def test_unknown_car_is_a_404_page(signed_in):
    response = signed_in.get("/vehicles/999")
    assert response.status_code == 404
    assert "Nothing here" in response.text


# ---------- Odometer ----------


def test_add_and_delete_a_reading(signed_in, conn, car):
    response = signed_in.post(f"/vehicles/{car}/odometer", data={"read_on": "2021-01-01", "miles": "41,000"})
    assert response.status_code == 200  # followed the redirect back to the car
    assert "41,000 mi" in response.text
    reading_id = conn.execute("SELECT id FROM odometer_readings").fetchone()[0]
    signed_in.post(f"/odometer/{reading_id}/delete")
    assert conn.execute("SELECT count(*) FROM odometer_readings").fetchone()[0] == 0


def test_reading_that_goes_backwards_is_refused(signed_in, car):
    signed_in.post(f"/vehicles/{car}/odometer", data={"read_on": "2021-01-01", "miles": "41,000"})
    response = signed_in.post(f"/vehicles/{car}/odometer", data={"read_on": "2022-01-01", "miles": "40,000"})
    assert response.status_code == 422
    assert "lower than the 41,000 mi" in response.text


# ---------- Services ----------


def test_log_a_service(signed_in, conn, car):
    lines = [
        _line("Oil and filter", ["engine_oil", "oil_filter"], "79.99", "labor"),
        _line("", ["tire_rotation"], "20"),
        _line("Brakes looked at", ["brake_pads"], inspect_only=True),
        _line(),  # an empty row is ignored
    ]
    response = signed_in.post(f"/vehicles/{car}/services", data=_service_form(lines, tax="5.00"), follow_redirects=False)
    assert response.status_code == 303
    event = services.get_event(conn, int(response.headers["location"].rsplit("/", 1)[1]))
    assert len(event["lines"]) == 3
    assert event["lines"][1]["description"] == "Tire rotation"       # named after what it covers
    assert event["lines"][2]["covers"][0]["action"] == "inspect"
    assert event["total_cents"] == 7999 + 2000 + 500                  # lines plus tax
    page = signed_in.get(response.headers["location"]).text
    assert "Engine oil" in page and "inspected" in page


def test_shop_is_required_for_shop_work(signed_in, car):
    response = signed_in.post(f"/vehicles/{car}/services", data=_service_form([_line("x")], shop=""))
    assert response.status_code == 422
    assert "Name the shop" in response.text


def test_diy_service_needs_no_shop(signed_in, car):
    response = signed_in.post(f"/vehicles/{car}/services", data=_service_form([_line("Wipers", ["wiper_blades"])],
                                                                               source="diy", shop=""), follow_redirects=False)
    assert response.status_code == 303


def test_a_service_needs_something_done(signed_in, car):
    response = signed_in.post(f"/vehicles/{car}/services", data=_service_form([_line()]))
    assert response.status_code == 422
    assert "Add at least one thing" in response.text


def test_bad_line_amount_keeps_the_lines(signed_in, car):
    response = signed_in.post(f"/vehicles/{car}/services", data=_service_form([_line("Oil", ["engine_oil"], "lots")]))
    assert response.status_code == 422
    assert "Enter an amount like 89.99." in response.text   # carried in the editor's data
    assert "engine_oil" in response.text


def test_service_odometer_is_checked(signed_in, car):
    signed_in.post(f"/vehicles/{car}/odometer", data={"read_on": "2021-01-01", "miles": "41,000"})
    response = signed_in.post(f"/vehicles/{car}/services", data=_service_form([_line("Oil", ["engine_oil"])],
                                                                               performed_on="2022-01-01"))
    assert response.status_code == 422
    assert "lower than the 41,000 mi" in response.text


def test_edit_then_delete_a_service(signed_in, conn, car):
    created = signed_in.post(f"/vehicles/{car}/services", data=_service_form([_line("Oil", ["engine_oil"], "50")]),
                             follow_redirects=False)
    url = created.headers["location"]
    form_page = signed_in.get(url + "/edit").text
    assert "engine_oil" in form_page and "50.00" in form_page

    signed_in.post(url + "/edit", data=_service_form([_line("Coolant", ["engine_coolant"], "120")]))
    event_id = int(url.rsplit("/", 1)[1])
    assert services.get_event(conn, event_id)["lines"][0]["description"] == "Coolant"

    response = signed_in.post(url + "/delete", follow_redirects=False)
    assert response.headers["location"] == f"/vehicles/{car}"
    assert services.get_event(conn, event_id) is None


def test_part_number_and_quantity_are_kept_and_editable(signed_in, conn, car):
    line = {**_line("Oil filter", ["oil_filter"], "18.98", "part"), "part_number": "15208-AA15A", "quantity": "2"}
    created = signed_in.post(f"/vehicles/{car}/services", data=_service_form([line]), follow_redirects=False)
    event = services.get_event(conn, int(created.headers["location"].rsplit("/", 1)[1]))
    assert (event["lines"][0]["part_number"], event["lines"][0]["quantity"]) == ("15208-AA15A", 2.0)

    form_page = signed_in.get(created.headers["location"] + "/edit").text
    assert "15208-AA15A" in form_page and ">Part number</label>" in form_page and ">Quantity</label>" in form_page


def test_vehicle_page_shows_history(signed_in, car):
    signed_in.post(f"/vehicles/{car}/services", data=_service_form([_line("Oil", ["engine_oil"], "50")]))
    page = signed_in.get(f"/vehicles/{car}").text
    assert "Corner Garage" in page and "30,000 mi" in page and "$50.00" in page


# ---------- Service types ----------


def test_service_types_page_and_custom_type(signed_in, conn):
    assert "Inverter coolant" in signed_in.get("/service-types").text
    response = signed_in.post("/service-types", data={"name": "Throttle body cleaning", "category": "Engine",
                                                      "default_action": "perform"}, follow_redirects=False)
    assert response.status_code == 303
    assert "Throttle body cleaning" in signed_in.get("/service-types").text


def test_custom_type_needs_a_known_category(signed_in):
    response = signed_in.post("/service-types", data={"name": "X", "category": "Nope"})
    assert response.status_code == 422
