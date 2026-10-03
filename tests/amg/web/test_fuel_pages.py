"""Logging fill-ups and charges, the log, and what the car page says about them."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from amg.repo import fuel, vehicles
from amg.web import status


@pytest.fixture
def car(conn):
    return vehicles.create(conn, vehicles.VehicleFields(name="Outback", powertrain="gas"))


@pytest.fixture
def ev(conn):
    return vehicles.create(conn, vehicles.VehicleFields(name="Leaf", powertrain="ev"))


def _days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


def _log(client, car, on, odometer, quantity, cost="", full=True, **more):
    data = {"filled_on": on, "odometer": odometer, "quantity": quantity, "cost": cost, "note": "", **more}
    if full:
        data["full"] = "1"
    return client.post(f"/vehicles/{car}/fuel", data=data, follow_redirects=False)


def test_a_gas_car_logs_gallons_and_an_ev_kwh_in_one_garage(signed_in, car, ev):
    gas = signed_in.get(f"/vehicles/{car}/fuel/new").text
    assert "Log a fill-up" in gas and "Gallons" in gas and "Filled the tank" in gas and "Save fill-up" in gas
    assert "Where" not in gas
    electric = signed_in.get(f"/vehicles/{ev}/fuel/new").text
    assert "Log a charge" in electric and "kWh" in electric and "Charged to your usual limit" in electric
    assert 'value="home"' in electric and 'value="public"' in electric and "Save charge" in electric


def test_saving_says_what_the_fill_measured(signed_in, car):
    first = _log(signed_in, car, _days_ago(20), "30,200", "12")
    assert first.status_code == 303 and "/fuel?saved=" in first.headers["location"]
    assert "Saved. MPG is measured from this full tank to the next." in signed_in.get(first.headers["location"]).text

    partial = _log(signed_in, car, _days_ago(10), "30,300", "4", full=False)
    assert "Saved. MPG shows at your next full tank." in signed_in.get(partial.headers["location"]).text

    second = _log(signed_in, car, _days_ago(1), "30,450", "6", cost="21.00")
    page = signed_in.get(second.headers["location"]).text
    assert "Saved. 25.0 mpg since your last full tank." in page        # 250 mi / (4 + 6) gal
    assert "Partial" in page and "$3.500/gal" in page and "$21.00" in page


def test_an_odometer_lower_than_an_earlier_reading_is_refused(signed_in, car):
    _log(signed_in, car, "2026-09-28", "64,300", "11.482")
    response = _log(signed_in, car, date.today().isoformat(), "64,030", "10")
    assert response.status_code == 422
    assert "lower than the 64,300 mi recorded earlier, on 2026-09-28 (a fill-up)." in response.text


@pytest.mark.parametrize(("fields", "message"), [
    ({"odometer": ""}, "Enter the odometer. MPG is worked out from it."),
    ({"quantity": ""}, "Enter the gallons that went in."),
    ({"quantity": "0"}, "Enter the gallons that went in, like 11.482."),
    ({"cost": "-5"}, "Enter what you paid"),
    ({"filled_on": ""}, "Enter the date."),
])
def test_a_fill_up_needs_its_figures(signed_in, car, fields, message):
    data = {"filled_on": date.today().isoformat(), "odometer": "1,000", "quantity": "10", "cost": "", "full": "1",
            **fields}
    response = signed_in.post(f"/vehicles/{car}/fuel", data=data)
    assert response.status_code == 422 and message in response.text


def test_a_charge_needs_a_place_and_offers_the_home_rate(signed_in, conn, ev):
    response = _log(signed_in, ev, _days_ago(5), "12,000", "40")
    assert response.status_code == 422 and "Choose home or public." in response.text
    _log(signed_in, ev, _days_ago(5), "12,000", "40", cost="6.00", place="home")
    form = signed_in.get(f"/vehicles/{ev}/fuel/new").text
    assert '"rate": 15.0' in form and '"place": "home"' in form
    assert fuel.last(conn, ev)["place"] == "home" and fuel.last(conn, ev)["energy"] == "electric"


def test_the_masthead_picks_the_car(signed_in, conn, car):
    assert signed_in.get("/fuel/new", follow_redirects=False).headers["location"] == f"/vehicles/{car}/fuel/new"
    other = vehicles.create(conn, vehicles.VehicleFields(name="Civic"))
    fuel.create(conn, other, fuel.FillInput(_days_ago(3), 50_000, "gas", 10.0))
    page = signed_in.get("/fuel/new").text
    assert "Which car?" in page and page.index("Civic") < page.index("Outback")
    assert "Fill-up" in page


def test_with_no_cars_the_picker_says_add_one(signed_in):
    assert "Add a car first" in signed_in.get("/fuel/new").text


def test_the_masthead_says_charge_when_every_car_is_electric(signed_in, ev):
    assert ">Charge</a>" in signed_in.get("/").text


def test_edit_and_delete_a_fill(signed_in, conn, car):
    _log(signed_in, car, "2026-09-28", "64,300", "11.482", cost="39.72")
    fill_id = fuel.last(conn, car)["id"]
    form = signed_in.get(f"/fuel/{fill_id}/edit").text
    assert 'value="64,300"' in form and 'value="11.482"' in form and 'value="39.72"' in form
    assert "Delete this fill-up" in form

    # its own old reading doesn't count against it
    response = signed_in.post(f"/fuel/{fill_id}/edit", data={"filled_on": "2026-09-28", "odometer": "64,030",
                                                             "quantity": "11.5", "cost": "", "note": "typo"},
                              follow_redirects=False)
    assert response.status_code == 303
    row = fuel.get(conn, fill_id)
    assert (row["odometer"], row["quantity"], row["cost_cents"], row["full"], row["note"]) == (64_030, 11.5, None, 0, "typo")

    signed_in.post(f"/fuel/{fill_id}/delete")
    assert fuel.get(conn, fill_id) is None
    assert signed_in.get(f"/fuel/{fill_id}/edit").status_code == 404


def test_the_car_page_shows_fuel_and_fill_ups_as_readings(signed_in, conn, car):
    assert "No fill-ups logged yet" in signed_in.get(f"/vehicles/{car}").text
    _log(signed_in, car, _days_ago(30), "30,000", "10", cost="35.00")
    _log(signed_in, car, _days_ago(2), "30,300", "10", cost="36.00")
    page = signed_in.get(f"/vehicles/{car}").text
    assert "30.0 mpg" in page and "last 12 months" in page and "12.0¢" in page
    fill_id = fuel.last(conn, car)["id"]
    assert f'<a href="/fuel/{fill_id}/edit">From a fill-up</a>' in page


def test_a_fill_up_moves_todays_estimated_odometer(conn, car):
    vehicles.update(conn, car, vehicles.VehicleFields(name="Outback", in_service_date=_days_ago(100)))
    assert status.load(conn, vehicles.get(conn, car)).today_miles is None
    fuel.create(conn, car, fuel.FillInput(_days_ago(10), 3_000, "gas", 10.0))
    assert status.load(conn, vehicles.get(conn, car)).today_miles == round(3_000 + 10 * 3_000 / 90)


def test_the_backup_page_counts_fill_ups(signed_in, conn, car):
    fuel.create(conn, car, fuel.FillInput("2026-09-28", 64_300, "gas", 11.482))
    assert "Fill-ups" in signed_in.get("/backup").text


def _steady(conn, car, last_odometer=31_200):
    """Five fills 10 days apart, $35.00 each: 25, 25, 25 mpg, then 45 (unusual) with the default last odometer."""
    for days_ago, miles in ((40, 30_000), (30, 30_250), (20, 30_500), (10, 30_750), (1, last_odometer)):
        fuel.create(conn, car, fuel.FillInput(_days_ago(days_ago), miles, "gas", 10.0, 3_500))


def test_the_fuel_page_shows_the_figures_the_trend_and_the_odd_one_out(signed_in, conn, car):
    _steady(conn, car)
    from amg.web import fuel_status

    shown = fuel_status.figures(fuel_status.load(conn, vehicles.get(conn, car)))
    assert [(f["label"], f["value"], f["unit"], f["note"]) for f in shown] == [
        ("Last tank", "45.0", "mpg", _days_ago(1)),
        ("Last 12 months", "30.0", "mpg", None),
        ("All time", "30.0", "mpg", None),
        ("Cost a mile", "11.7¢", None, "last 12 months"),        # $140.00 over 1,200 mi
        ("Spent", "$175.00", None, "last 12 months"),
        ("Price paid", "$3.500", "/gal", "average, last 12 months"),
    ]
    page = signed_in.get(f"/vehicles/{car}/fuel").text
    assert "<dt>Last tank</dt>" in page and '45.0<span class="figure__unit"> mpg</span>' in page
    assert '$3.500<span class="figure__unit">/gal</span>' in page
    assert 'class="trend"' in page and "Unusual, check it" in page and "trend__dot--unusual" in page


def test_the_trend_scale(conn, car):
    _steady(conn, car)
    from amg.web import fuel_status

    chart = fuel_status.trend(fuel_status.load(conn, vehicles.get(conn, car)))
    assert [t["label"] for t in chart["ticks"]] == ["25", "30", "35", "40", "45"]
    assert [(p["x"], p["y"], p["unusual"]) for p in chart["points"]] == [
        (0.0, 100.0, False), (34.483, 100.0, False), (68.966, 100.0, False), (100.0, 0.0, True)]   # 10, 20, 29 days on
    assert chart["average"] == {"y": 75.0, "label": "30.0 mpg average, last 12 months"}


def test_one_stretch_has_no_trend_yet(signed_in, conn, car):
    fuel.create(conn, car, fuel.FillInput(_days_ago(10), 30_000, "gas", 10.0))
    fuel.create(conn, car, fuel.FillInput(_days_ago(1), 30_300, "gas", 10.0))
    page = signed_in.get(f"/vehicles/{car}/fuel").text
    assert "30.0 mpg" in page and 'class="trend"' not in page and "Cost a mile" not in page


def test_an_ev_is_worded_in_kwh(signed_in, conn, ev):
    for days_ago, miles, kwh, cents in ((20, 12_000, 40.0, 600), (10, 12_130, 39.0, 624), (1, 12_262, 40.0, 640)):
        fuel.create(conn, ev, fuel.FillInput(_days_ago(days_ago), miles, "electric", kwh, cents, place="home"))
    page = signed_in.get(f"/vehicles/{ev}/fuel").text
    assert "<h1 class=\"display\">Charging</h1>" in page and "Last charge" in page and "3.30 mi/kWh" in page
    assert "16.0¢/kWh" in page and "40 kWh" in page and "Home" in page


def test_the_readings_list_folds_after_six(signed_in, conn, car):
    _steady(conn, car)
    fuel.create(conn, car, fuel.FillInput(_days_ago(0), 31_500, "gas", 10.0))
    fuel.create(conn, car, fuel.FillInput(_days_ago(0), 31_510, "gas", 0.5))
    page = signed_in.get(f"/vehicles/{car}").text
    assert "<summary>1 older</summary>" in page
    assert page.index("31,510 mi") < page.index("<summary>1 older</summary>") < page.index("30,000 mi")
