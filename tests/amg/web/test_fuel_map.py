"""Where you filled up: each fill-up at its town, the filters, and the page."""

from __future__ import annotations

import report_fixtures as rf  # tests/ is on pytest's path

from amg import geo
from amg.repo import fuel
from amg.repo.fuel import FillInput
from amg.web import fuel_map
from amg.web.fuel_map import MapFilters


def row(n, city, state, station="Shell", day="2026-01-01", car=1, energy="gas", cost=3_000, quantity=10.0):
    return {"id": n, "vehicle_id": car, "car_name": "Outback" if car == 1 else "Leaf", "energy": energy,
            "filled_on": day, "station": station, "station_city": city, "station_state": state,
            "cost_cents": cost, "quantity": quantity}


def by_name(places):
    return {p.name: p for p in places}


# ---------- Placing a fill-up ----------


def test_the_data_knows_towns_and_townships():
    towns = geo.towns()
    assert ("NJ", "trenton") in towns and ("QC", "montreal") in towns and ("NL", "saint johns") in towns
    assert len(towns[("NJ", "hamilton")]) == 2                  # Mercer County's township, and Atlantic County's
    assert {"NJ", "ON", "AK", "HI", "DC"} <= set(geo.regions())


def test_each_fill_up_goes_at_its_town():
    places, unplaced = fuel_map.place([row(1, "Trenton", "NJ"), row(2, "  trenton ", "NJ"),
                                       row(3, "St. Augustine", "FL")])
    found = by_name(places)
    assert set(found) == {"Trenton, NJ", "St. Augustine, FL"} and unplaced == []
    assert found["Trenton, NJ"].count == 2 and found["Trenton, NJ"].how == "town"


def test_a_town_the_list_doesnt_know_goes_at_the_middle_of_its_state():
    places, _ = fuel_map.place([row(1, "Hamiltn", "NJ"), row(2, "", "NJ")])
    (middle,) = places
    assert (middle.name, middle.how, middle.count) == ("New Jersey", "state", 2)
    assert [middle.x, middle.y] == geo.regions()["NJ"]["label"]


def test_no_state_isnt_placed():
    places, unplaced = fuel_map.place([row(1, "Trenton", ""), row(2, "", "")])
    assert places == [] and [r["id"] for r in unplaced] == [1, 2]


def test_a_name_the_state_has_twice_goes_at_the_one_nearest_your_others():
    places, _ = fuel_map.place([row(1, "Hamilton", "NJ"), row(2, "Trenton", "NJ"), row(3, "Ewing", "NJ")])
    hamilton, trenton = by_name(places)["Hamilton, NJ"], by_name(places)["Trenton, NJ"]
    assert hamilton.how == "guessed"
    assert abs(hamilton.x - trenton.x) < 20 and abs(hamilton.y - trenton.y) < 20    # Mercer's, by Trenton


def test_a_towns_price_is_over_its_fills_with_a_cost():
    places, _ = fuel_map.place([row(1, "Trenton", "NJ", cost=3_000), row(2, "Trenton", "NJ", cost=None),
                                row(3, "Trenton", "NJ", cost=3_400)])
    (trenton,) = places
    assert trenton.price == 320.0 and trenton.spent == 6_400 and trenton.count == 3


# ---------- The filters ----------

ROWS = [
    row(1, "Trenton", "NJ", "Wawa on Route 33", "2026-03-01"),
    row(2, "Ewing", "NJ", "WAWA 8812", "2025-06-01"),
    row(3, "Yardley", "PA", "Shell", "2026-02-01"),
    row(4, "Yardley", "PA", "", "2026-02-15"),
    row(5, "Trenton", "NJ", "Tesla Supercharger", "2026-01-01", car=2, energy="electric"),
]


def test_brands_go_by_name_and_stations_without_one_stay_as_typed():
    assert fuel_map.brand_of("WAWA 8812") == ("Wawa", "Wawa")
    assert fuel_map.brand_of("Corner Gas & Go") == ("Corner Gas & Go", "Corner Gas & Go")
    assert fuel_map.brand_of("  ") == (fuel_map.NO_STATION, "No station")
    offered = fuel_map.options(ROWS, "gas")
    assert [(b["label"], b["count"]) for b in offered["brands"]] == [("Wawa", 2), ("Shell", 1), ("No station", 1)]
    assert offered["states"] == ["NJ", "PA"] and [c["name"] for c in offered["cars"]] == ["Outback"]


def chosen(**filters):
    return [r["id"] for r in fuel_map.chosen(ROWS, MapFilters(**filters))]


def test_each_filter_alone_and_together():
    assert chosen() == [1, 2, 3, 4]                                         # fuel only: the charge is apart
    assert chosen(energy="electric") == [5]
    assert chosen(start="2026-01-01", end="2026-02-01") == [3]
    assert chosen(brand="wawa") == [1, 2]
    assert chosen(brand=fuel_map.NO_STATION) == [4]
    assert chosen(state="PA") == [3, 4]
    assert chosen(state="NJ", city="TRENTON") == [1]
    assert chosen(brand="Wawa", start="2026-01-01") == [1]
    assert chosen(car=2) == []


def test_filters_are_read_forgivingly_and_kept_in_the_address():
    read = MapFilters.read({"from": "2026-05-01", "to": "2026-01-01", "car": "x", "state": "nj", "sort": "bogus",
                            "energy": "diesel"}, ["gas", "electric"])
    assert (read.start, read.end, read.car, read.state, read.sort, read.energy) == (
        "2026-01-01", "2026-05-01", None, "NJ", "fills", "gas")
    kept = read.within(fuel_map.options(ROWS, "gas"))
    assert kept.state == "NJ" and kept.url() == "/fuel/map?from=2026-01-01&to=2026-05-01&state=NJ"
    assert MapFilters(state="ZZ").within(fuel_map.options(ROWS, "gas")).state == ""   # not on offer: dropped
    assert MapFilters.read({}, ["electric"]).energy == "electric"            # only charges: charging


# ---------- The map and the words ----------


def test_the_map_frames_the_dots_and_draws_whats_near():
    places, _ = fuel_map.place([row(1, "Trenton", "NJ"), row(2, "Yardley", "PA")])
    drawing = fuel_map.drawing(places)
    _, _, width, height = (float(v) for v in drawing["view"].split())
    assert width == fuel_map.CLOSEST and round(width / height, 1) == fuel_map.ASPECT   # two towns close together
    codes = {r["code"]: r for r in drawing["regions"]}
    assert {"NJ", "PA"} <= set(codes) and "CA" not in codes and codes["NJ"]["visited"]
    assert [d["name"] for d in drawing["dots"]] != ["", ""]                    # close in: towns named


def test_one_town_alone_is_framed_not_divided_by_nothing():
    places, _ = fuel_map.place([row(1, "Trenton", "NJ")])
    _, _, width, height = (float(v) for v in fuel_map.drawing(places)["view"].split())
    assert width == fuel_map.CLOSEST and height > 0


def test_with_nothing_the_map_shows_the_lower_48():
    drawing = fuel_map.drawing([])
    assert {"CA", "ME", "FL", "WA"} <= {r["code"] for r in drawing["regions"]} and drawing["dots"] == []


def test_dots_are_shaded_cheapest_to_dearest():
    places, _ = fuel_map.place([row(1, "Trenton", "NJ", cost=3_000), row(2, "Yardley", "PA", cost=3_500)])
    tones = {d["title"].split(":")[0]: d["tone"] for d in fuel_map.drawing(places)["dots"]}
    assert tones == {"Trenton, NJ": 0, "Yardley, PA": 4}


def test_the_summary_says_what_was_placed_and_what_wasnt():
    rows = [row(1, "Trenton", "NJ"), row(2, "Hamiltn", "NJ"), row(3, "", ""), row(4, "Hamilton", "NJ")]
    places, unplaced = fuel_map.place(rows)
    found = fuel_map.summary(places, unplaced, "gas")
    assert found["line"] == ("3 fill-ups in 2 towns across 1 state · 1 at the middle of the state"
                             " · 1 in a town whose name the state has more than once · 1 with no location")
    assert found["unplaced"] == [{"car": "Outback", "count": 1, "url": "/vehicles/1/fuel?look=location#log-heading"}]


def test_canada_is_said_as_provinces():
    places, unplaced = fuel_map.place([row(1, "Montréal", "QC"), row(2, "Ottawa", "ON")])
    assert "2 fill-ups in 2 towns across 2 provinces" in fuel_map.summary(places, unplaced, "gas")["line"]


# ---------- The page ----------


def test_the_map_page(signed_in, conn):
    car = rf.car(conn, "Outback")
    for day, odo, city, state, station in (("2026-01-02", 1_000, "Trenton", "NJ", "Wawa"),
                                           ("2026-01-20", 1_300, "Ewing", "NJ", "Shell"),
                                           ("2026-02-05", 1_600, "", "", "Shell")):
        fuel.create(conn, car, FillInput(day, odo, "gas", 10.0, 3_200, station=station, station_city=city,
                                         station_state=state))
    page = signed_in.get("/fuel/map").text
    assert "Where you filled up" in page and 'class="fmap__svg"' in page
    assert "2 fill-ups in 2 towns across 1 state · 1 with no location" in page
    assert 'id="town-nj-trenton"' in page and 'href="#town-nj-trenton"' in page
    assert f'href="/vehicles/{car}/fuel?state=NJ&amp;city=Trenton#log-heading"' in page
    assert "GeoNames" in page
    narrowed = signed_in.get("/fuel/map?brand=Wawa").text
    assert "1 fill-up in 1 town" in narrowed and "Clear filters" in narrowed
    assert "See where you filled up" in signed_in.get("/reports?view=fuel").text
    assert f'href="/fuel/map?car={car}"' in signed_in.get(f"/vehicles/{car}/fuel").text


def test_nothing_to_map(signed_in, conn):
    rf.car(conn, "Outback")
    assert "Nothing to map yet" in signed_in.get("/fuel/map").text
