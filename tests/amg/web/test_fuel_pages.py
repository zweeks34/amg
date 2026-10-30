"""Logging fill-ups and charges, the log, and what the car page says about them."""

from __future__ import annotations

import json
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


def test_each_fill_copies_as_one_line_in_the_logs_words(conn, car, ev):
    from amg.web import fuel_status

    for fill in (fuel.FillInput("2026-10-01", 45_000, "gas", 10.0, 3_400),                  # the first: no economy
                 fuel.FillInput("2026-10-10", 45_150, "gas", 4.0, full=False),               # partial, no cost
                 fuel.FillInput("2026-10-20", 45_330, "gas", 6.2, 2_108, station="Shell"),   # 330 mi on 10.2 gal
                 fuel.FillInput("2026-10-25", 45_600, "gas", 9.0, 3_000, missed_before=True, note="Costco\non Main")):
        fuel.create(conn, car, fill)
    rows = fuel_status.log_rows(fuel_status.load(conn, vehicles.get(conn, car)))
    assert [row["line"] for row in rows] == [
        "Oct 25, 2026 · 45,600 mi · 9.000 gal · $30.00 ($3.333/gal) · Full tank · After one not logged · Costco on Main",
        "Oct 20, 2026 · Shell · 45,330 mi · 6.200 gal · $21.08 ($3.400/gal) · 32.4 mpg · Full tank",
        "Oct 10, 2026 · 45,150 mi · 4.000 gal · Partial fill",
        "Oct 1, 2026 · 45,000 mi · 10.000 gal · $34.00 ($3.400/gal) · Full tank",
    ]

    fuel.create(conn, ev, fuel.FillInput("2026-10-01", 12_000, "electric", 30.0, 420, place="home"))
    fuel.create(conn, ev, fuel.FillInput("2026-10-20", 12_121, "electric", 31.5, 441, place="home"))
    fuel.create(conn, ev, fuel.FillInput("2026-10-22", 12_180, "electric", 12.5, full=False, place="public"))
    rows = fuel_status.log_rows(fuel_status.load(conn, vehicles.get(conn, ev)))
    assert [row["line"] for row in rows] == [
        "Oct 22, 2026 · 12,180 mi · 12.5 kWh · Partial charge · Public",
        "Oct 20, 2026 · 12,121 mi · 31.5 kWh · $4.41 (14.0¢/kWh) · 3.84 mi/kWh · Full charge · Home",
        "Oct 1, 2026 · 12,000 mi · 30 kWh · $4.20 (14.0¢/kWh) · Full charge · Home",
    ]


def test_a_fill_up_says_where_and_the_form_offers_your_recent_stations(signed_in, conn, car, ev):
    assert "Your recent stations" not in signed_in.get(f"/vehicles/{car}/fuel/new").text    # none yet
    for day, miles, station in (("2026-09-01", "30,000", "Costco"), ("2026-09-10", "30,300", "  Wawa   on Route 9 "),
                                ("2026-09-20", "30,600", "shell"), ("2026-09-30", "30,900", "Shell"),
                                ("2026-10-05", "31,200", "")):
        _log(signed_in, car, day, miles, "10", station=station)
    _log(signed_in, ev, "2026-10-06", "5,000", "20", station="O'Neil's Chargers", place="public")
    assert [row["station"] for row in fuel.log(conn, car)][:3] == ["", "Shell", "shell"]
    assert fuel.get(conn, fuel.log(conn, car)[3]["id"])["station"] == "Wawa on Route 9"      # spaces tidied
    # every car's, most recent first, each once whatever its capitals, as last typed; pumps or chargers
    assert fuel.stations(conn, "gas") == ["Shell", "Wawa on Route 9", "Costco"]
    assert fuel.stations(conn, "electric") == ["O'Neil's Chargers"]

    form = signed_in.get(f"/vehicles/{car}/fuel/new").text
    assert 'value="" x-model="station" list="f-stations"' in form                                # a new one starts blank
    assert '<ul class="chips stations" aria-label="Your recent stations">' in form
    assert form.count('class="chip stations__pick"') == 3 and "Chargers" not in form            # no chargers
    charge = signed_in.get(f"/vehicles/{ev}/fuel/new").text
    assert r"""@click='station = "O\u0027Neil\u0027s Chargers"'""" in charge                    # safe in its quotes
    assert '<option value="Costco"></option>' in form

    shell = fuel.log(conn, car)[1]["id"]
    assert 'value="Shell" x-model="station"' in signed_in.get(f"/fuel/{shell}/edit").text
    page = signed_in.get(f"/vehicles/{car}/fuel").text
    assert '<p class="fuellog__station">At Shell</p>' in page and page.count('class="fuellog__station"') == 4


def test_tapping_a_fill_opens_edit_copy_and_delete(signed_in, conn, car):
    _log(signed_in, car, "2026-09-28", "64,300", "11.482", cost="39.72")
    fill_id = fuel.last(conn, car)["id"]
    page = signed_in.get(f"/vehicles/{car}/fuel").text
    assert "Tap a fill-up to edit, copy or delete it." in page
    assert page.count('<details class="fuellog__item" name="fuellog">') == 1       # one open at a time
    assert f'href="/fuel/{fill_id}/edit" aria-label="Edit the fill-up of Sep 28, 2026">Edit</a>' in page
    line = "Sep 28, 2026 · 64,300 mi · 11.482 gal · $39.72 ($3.459/gal) · Full tank"
    assert f"x-data='copyLine({json.dumps(line)})'" in page
    assert 'aria-label="Copy the fill-up of Sep 28, 2026"' in page
    assert f'<form method="post" action="/fuel/{fill_id}/delete" class="confirm"' in page
    assert "Delete this fill-up? Its odometer reading goes with it." in page and "Keep it" in page

    response = signed_in.post(f"/fuel/{fill_id}/delete", follow_redirects=False)
    assert response.headers["location"] == f"/vehicles/{car}/fuel?deleted=1"
    assert "Fill-up deleted." in signed_in.get(response.headers["location"]).text
    assert fuel.get(conn, fill_id) is None


def test_an_evs_log_says_charge(signed_in, conn, ev):
    fuel.create(conn, ev, fuel.FillInput("2026-10-20", 12_121, "electric", 31.5, 441, place="home"))
    fill_id = fuel.last(conn, ev)["id"]
    page = signed_in.get(f"/vehicles/{ev}/fuel").text
    assert "Tap a charge to edit, copy or delete it." in page and "Delete this charge?" in page
    assert 'aria-label="Copy the charge of Oct 20, 2026"' in page
    response = signed_in.post(f"/fuel/{fill_id}/delete")
    assert "Charge deleted." in response.text


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


def test_tank_to_tank_counts_each_tank_alike_and_leaves_the_unusual_out(signed_in, conn, car):
    _steady(conn, car)
    from amg.web import fuel_status

    shown = fuel_status.tank_to_tank(fuel_status.load(conn, vehicles.get(conn, car)))
    assert shown["heading"] == "Tank to tank"
    assert shown["line"] == ("Each tank's own MPG, last 12 months. 1 unusual tank left out. The mean counts every "
                             "tank alike; the Last 12 months figure above weighs each by its miles.")
    assert [(f["label"], f["value"], f["unit"], f["note"]) for f in shown["figures"]] == [
        ("Lowest", "25.0", "mpg", _days_ago(10)),          # three tanks the same: the latest
        ("Highest", "25.0", "mpg", _days_ago(10)),
        ("Mean", "25.0", "mpg", "of 3 tanks"),
        ("Std deviation", "±0.0", "mpg", "all 3 tanks at 25.0"),
    ]
    page = signed_in.get(f"/vehicles/{car}/fuel").text
    assert '<h2 class="h3" id="spread-heading">Tank to tank</h2>' in page and "<dt>Std deviation</dt>" in page
    assert '<dl class="figures figures--four sheet">' in page


def test_tank_to_tank_names_the_station_and_counts_those_within(conn, car):
    # 25, 30, 35, 26 mpg; the last two at Wawa: mean 29.0, std deviation 4.546 (24.45 to 33.55 holds three)
    for days_ago, miles, station in ((50, 10_000, ""), (40, 10_250, "Sunoco"), (30, 10_550, ""),
                                     (20, 10_900, "Wawa"), (10, 11_160, "Wawa")):
        fuel.create(conn, car, fuel.FillInput(_days_ago(days_ago), miles, "gas", 10.0, 3_500, station=station))
    from amg.web import fuel_status

    shown = fuel_status.tank_to_tank(fuel_status.load(conn, vehicles.get(conn, car)))
    assert "left out" not in shown["line"]
    assert [(f["value"], f["note"]) for f in shown["figures"]] == [
        ("25.0", f"{_days_ago(40)} at Sunoco"), ("35.0", f"{_days_ago(20)} at Wawa"),
        ("29.0", "of 4 tanks"), ("±4.5", "3 of 4 tanks within 24.5–33.5")]


def test_tank_to_tank_takes_all_time_when_the_last_year_is_thin_and_needs_three(conn, car, ev):
    from amg.web import fuel_status

    for on, miles in (("2024-03-01", 1_000), ("2024-04-01", 1_250), ("2024-05-01", 1_500), ("2024-06-01", 1_760)):
        fuel.create(conn, car, fuel.FillInput(on, miles, "gas", 10.0, 3_500))
    fuel.create(conn, car, fuel.FillInput(_days_ago(5), 2_020, "gas", 10.0, 3_500))
    shown = fuel_status.tank_to_tank(fuel_status.load(conn, vehicles.get(conn, car)))
    assert shown["line"].startswith("Each tank's own MPG, all time. The mean") and "the All time figure above" in shown["line"]
    for on, miles in ((_days_ago(30), 5_000), (_days_ago(20), 5_130), (_days_ago(10), 5_260)):
        fuel.create(conn, ev, fuel.FillInput(on, miles, "electric", 40.0, 600, place="home"))
    assert fuel_status.tank_to_tank(fuel_status.load(conn, vehicles.get(conn, ev))) is None    # two charges
    fuel.create(conn, ev, fuel.FillInput(_days_ago(1), 5_400, "electric", 40.0, 600, place="home"))
    charges = fuel_status.tank_to_tank(fuel_status.load(conn, vehicles.get(conn, ev)))
    assert charges["heading"] == "Charge to charge" and charges["figures"][2]["value"] == "3.33"
    assert charges["figures"][3]["unit"] == "mi/kWh" and charges["figures"][2]["note"] == "of 3 charges"


def test_the_trend_scale(conn, car):
    _steady(conn, car)
    from amg.web import fuel_status

    chart = fuel_status.trend(fuel_status.load(conn, vehicles.get(conn, car)))
    assert [t["label"] for t in chart["ticks"]] == ["25", "30", "35", "40", "45"]
    assert [(p["x"], p["y"], p["unusual"]) for p in chart["points"]] == [
        (0.0, 100.0, False), (34.483, 100.0, False), (68.966, 100.0, False), (100.0, 0.0, True)]   # 10, 20, 29 days on
    assert chart["average"] == {"y": 75.0, "label": "30.0 mpg average, last 12 months"}


def test_the_trend_shades_the_usual_range(signed_in, conn, car):
    # 25, 30, 35, 26 mpg: mean 29.0, std deviation 4.546, so 24.454 to 33.546 on a 20-35 scale (steps of 5)
    for days_ago, miles in ((50, 10_000), (40, 10_250), (30, 10_550), (20, 10_900), (10, 11_160)):
        fuel.create(conn, car, fuel.FillInput(_days_ago(days_ago), miles, "gas", 10.0, 3_500))
    from amg.web import fuel_status

    chart = fuel_status.trend(fuel_status.load(conn, vehicles.get(conn, car)))
    band = chart["band"]
    assert (band["x"], band["width"]) == (0.0, 100.0)
    assert band["y"] == pytest.approx(100 - 13.546 / 15 * 100, abs=0.01)
    assert band["height"] == pytest.approx(9.092 / 15 * 100, abs=0.01)
    assert band["label"] == "Usual, last 12 months: 24.5–33.5 mpg, mean ± 1 std deviation"
    page = signed_in.get(f"/vehicles/{car}/fuel").text
    assert '<rect class="trend__band" x="0.0"' in page and "trend__key--band" in page


def test_the_band_covers_only_the_months_it_describes(conn, car):
    # One tank two years ago, then 25, 26, 25 in the last month: the band starts 12 months back
    for on, miles in (("2024-01-01", 1_000), ("2024-02-01", 1_250), (_days_ago(30), 1_500), (_days_ago(20), 1_760),
                      (_days_ago(10), 2_010)):
        fuel.create(conn, car, fuel.FillInput(on, miles, "gas", 10.0, 3_500))
    from amg.web import fuel_status

    state = fuel_status.load(conn, vehicles.get(conn, car))
    band = fuel_status.trend(state)["band"]
    first, last = date(2024, 2, 1), date.today() - timedelta(days=10)
    assert band["x"] == round((state.year_ago - first).days / (last - first).days * 100, 3)
    assert band["width"] == round(100 - band["x"], 3) and band["label"].startswith("Usual, last 12 months: 24.8–25.9")


def test_no_band_when_every_usual_tank_is_alike(conn, car):
    _steady(conn, car)       # 25, 25, 25, and the unusual 45 left out
    from amg.web import fuel_status

    assert fuel_status.trend(fuel_status.load(conn, vehicles.get(conn, car)))["band"] is None


def test_the_price_paid_over_time(signed_in, conn, car):
    # $3.299, $3.359 and $3.419 a gallon, a partial at $3.400 counted too, and one with no cost left out
    for days_ago, miles, gallons, cents, full in ((40, 10_000, 10.0, 3_299, True), (30, 10_300, 10.0, 3_359, True),
                                                  (25, 10_400, 4.0, 1_360, False), (20, 10_600, 10.0, None, True),
                                                  (10, 10_900, 10.0, 3_419, True)):
        fuel.create(conn, car, fuel.FillInput(_days_ago(days_ago), miles, "gas", gallons, cents, full=full))
    from amg.web import fuel_status

    chart = fuel_status.price_trend(fuel_status.load(conn, vehicles.get(conn, car)))
    assert [t["label"] for t in chart["ticks"]] == ["$3.20", "$3.30", "$3.40", "$3.50"]
    assert [(p["y"], p["label"]) for p in chart["points"]] == [
        (67.0, f"{_days_ago(40)}: $3.299/gal"), (47.0, f"{_days_ago(30)}: $3.359/gal"),
        (33.333, f"{_days_ago(25)}: $3.400/gal"), (27.0, f"{_days_ago(10)}: $3.419/gal")]
    assert chart["average"]["label"] == "$3.364/gal average, last 12 months"      # $114.37 over 34 gallons
    assert (chart["unit"], chart["per"]) == ("$/gal", "fill-up")
    page = signed_in.get(f"/vehicles/{car}/fuel").text
    assert '<p class="trend__title">Economy</p>' in page and '<p class="trend__title">Price paid</p>' in page


def test_a_charges_price_says_home_or_public_and_needs_two(conn, ev):
    from amg.web import fuel_status

    fuel.create(conn, ev, fuel.FillInput(_days_ago(20), 5_000, "electric", 40.0, 600, place="home"))
    assert fuel_status.price_trend(fuel_status.load(conn, vehicles.get(conn, ev))) is None
    fuel.create(conn, ev, fuel.FillInput(_days_ago(10), 5_130, "electric", 39.0, 1_300, place="public"))
    chart = fuel_status.price_trend(fuel_status.load(conn, vehicles.get(conn, ev)))
    assert [t["label"] for t in chart["ticks"]] == ["15¢", "20¢", "25¢", "30¢", "35¢"]
    assert [p["label"] for p in chart["points"]] == [f"{_days_ago(20)}, Home: 15.0¢/kWh",
                                                    f"{_days_ago(10)}, Public: 33.3¢/kWh"]
    assert (chart["unit"], chart["per"]) == ("¢/kWh", "charge")


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


def test_the_garage_card_draws_the_last_tanks_as_a_line(signed_in, conn, car):
    from amg.web import fuel_status

    for day, miles, gallons in (("2026-09-01", 45_000, 10.0), ("2026-09-08", 45_300, 10.0),     # 30 mpg
                                ("2026-09-15", 45_640, 10.0)):                                 # 34 mpg
        fuel.create(conn, car, fuel.FillInput(day, miles, "gas", gallons))
    assert fuel_status.sparkline(fuel_status.load(conn, vehicles.get(conn, car))) is None      # two tanks: not yet
    assert "spark__line" not in signed_in.get("/").text
    fuel.create(conn, car, fuel.FillInput("2026-09-22", 45_960, "gas", 10.0))                  # 32 mpg
    line = fuel_status.sparkline(fuel_status.load(conn, vehicles.get(conn, car)))
    # 30, 34 and 32 mpg, evenly spaced; the average 32.0 (960 mi on 30 gal); 0.6 mpg kept off each edge
    assert [(p["x"], p["y"]) for p in line["points"]] == [(0, 88.46), (50, 11.54), (100, 50.0)]
    assert line["average"] == 50.0 and (line["value"], line["unit"]) == ("32.0", "mpg")
    assert line["words"] == "MPG, last 3 tanks: from 30.0 mpg to 32.0 mpg, average 32.0 mpg"
    page = signed_in.get("/").text
    assert '<dt>Economy</dt>' in page and 'aria-label="MPG, last 3 tanks: from 30.0 mpg to 32.0 mpg' in page
    assert '<polyline points="0.0,88.46 50.0,11.54 100.0,50.0 "/>' in page and 'd="M100.0,50.0h0"' in page

    for n in range(4, 16):                                                                     # only the last 12
        fuel.create(conn, car, fuel.FillInput(f"2026-10-{n:02d}", 45_960 + n * 300, "gas", 10.0))
    assert len(fuel_status.sparkline(fuel_status.load(conn, vehicles.get(conn, car)))["points"]) == 12
