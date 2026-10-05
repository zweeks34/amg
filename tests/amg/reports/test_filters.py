"""Filters: read forgivingly from the address bar, and every one set has to match."""

from __future__ import annotations

import pytest
import report_fixtures as rf  # tests/ is on pytest's path

from amg.reports import history
from amg.reports.filters import Filters, service_label, service_options, span_words
from amg.repo import reports


def found(conn, ids, **query):
    """The visit names a report finds, newest first."""
    names = {number: name for name, number in ids.items() if name.startswith("v")}
    return [names[visit["id"]] for visit in history.load(conn, Filters.read(**query)).visits]


def test_reading_the_address_bar_is_forgiving():
    filters = Filters.read(view="nonsense", car="x2", start="2024-13-01", end=" 2020-05-01 ", service=" brake_pads ",
                           shop="  midas   auto ")
    assert filters == Filters("history", None, None, "2020-05-01", "brake_pads", "midas auto")
    assert Filters.read(car="2", start="2024-01-01", end="2020-01-01") == Filters(car=2, start="2020-01-01",
                                                                                 end="2024-01-01")  # swapped


def test_a_car_or_service_not_on_offer_is_dropped():
    filters = Filters(car=9, service="category:Brakes")
    assert filters.within([1, 2], ["category:Brakes"]) == Filters(service="category:Brakes")
    assert filters.within([9], []) == Filters(car=9)


def test_a_report_is_a_link_and_fuel_keeps_only_what_it_uses():
    filters = Filters(car=2, start="2020-01-01", service="category:Tires and wheels", shop="midas")
    assert filters.url() == "/reports?car=2&from=2020-01-01&service=category%3ATires+and+wheels&shop=midas"
    assert filters.url("fuel") == "/reports?view=fuel&car=2&from=2020-01-01"
    assert Filters.read(view="spending", car="2").csv_url() == "/reports/spending.csv?car=2"
    assert filters.cleared() == "/reports" and filters.active
    assert not Filters(view="fuel", shop="midas").active


def test_unconfirmed_services_never_count(conn):
    ids = rf.garage(conn)
    assert found(conn, ids) == ["v4", "v3", "v6", "v2", "v1"]
    assert found(conn, ids, service="brake_pads") == ["v1"]


@pytest.mark.parametrize("query, expected", [
    ({"car": "outback"}, ["v4", "v3", "v2", "v1"]),
    ({"start": "2021-06-01", "end": "2023-01-10"}, ["v3", "v6", "v2"]),          # both ends included
    ({"start": "2023-01-10"}, ["v4", "v3"]),
    ({"end": "2019-03-04"}, ["v1"]),
    ({"service": "category:Brakes"}, ["v4", "v6", "v1"]),
    ({"service": "engine_oil"}, ["v2", "v1"]),
    ({"shop": "midas"}, ["v6", "v1"]),                                           # any capitals, part of the name
    ({"shop": "own work"}, ["v2"]),                                              # who did it, as the pages say
    ({"shop": "no receipt"}, ["v4"]),
    ({"car": "outback", "service": "category:Brakes"}, ["v4", "v1"]),
    ({"service": "category:Brakes", "shop": "midas"}, ["v6", "v1"]),
    ({"car": "outback", "service": "category:Brakes", "shop": "midas"}, ["v1"]),
    ({"car": "outback", "service": "category:Brakes", "shop": "midas", "start": "2020-01-01"}, []),
    ({"car": "civic", "start": "2021-07-01", "end": "2021-07-01", "service": "brake_rotors", "shop": "auto"}, ["v6"]),
])
def test_filters_combine(conn, query, expected):
    ids = rf.garage(conn)
    if "car" in query:
        query = {**query, "car": str(ids[query["car"]])}
    assert found(conn, ids, **query) == expected


def test_fuel_ignores_the_service_and_shop(conn):
    ids = rf.garage(conn)
    assert found(conn, ids, view="fuel", service="brake_rotors", shop="nowhere") == ["v4", "v3", "v6", "v2", "v1"]


def test_the_service_picker_lists_what_your_history_covers(conn):
    rf.garage(conn)
    options = service_options(reports.used_types(conn), reports.categories(conn))
    assert [group["category"] for group in options] == ["Engine", "Brakes", "Tires and wheels"]
    assert [option["label"] for option in options[1]["options"]] == [
        "Any brakes work", "Brake fluid", "Brake pads", "Brake rotors"]
    assert options[1]["options"][0]["value"] == "category:Brakes"
    assert service_label("category:Hybrid and EV", {}) == "hybrid and EV"
    assert service_label("battery_12v", {"battery_12v": "12-volt battery"}) == "12-volt battery"


def test_shops_are_listed_once_each(conn):
    car = rf.car(conn, "Outback")
    for shop in ("Midas", "MIDAS", "Midas", "Corner Garage", ""):
        rf.visit(conn, car, "2020-01-01", shop=shop)
    rf.visit(conn, car, "2020-01-01", shop="Hidden Shop", confirmed=False)
    assert reports.shops(conn) == ["Corner Garage", "Midas"]


def test_dates_in_words():
    assert span_words("2019-01-05", "2026-10-04") == "Jan 2019 – Oct 2026"
    assert span_words("2019-01-05", None) == "from Jan 2019"
    assert span_words(None, "2026-10-04") == "to Oct 2026"
    assert span_words("2026-10-01", "2026-10-04") == "Oct 2026"
    assert span_words(None, None) == ""
