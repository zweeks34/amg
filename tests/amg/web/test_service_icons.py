"""Each kind of service's icon: picked from what a job covers, drawn from icons.svg, shown beside its name."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import pytest
from schedule_fixtures import steady_car  # tests/ is on pytest's path

from amg.repo import services, vehicles
from amg.repo.services import Coverage, EventInput, LineInput
from amg.web import service_icons
from amg.web.service_icons import icon_for
from amg.web.templating import STATIC_DIR


def _symbols():
    tree = ET.parse(STATIC_DIR / "icons.svg")
    return {el.get("id") for el in tree.getroot() if el.tag.endswith("symbol")}


def test_every_service_type_and_category_has_an_icon_that_is_drawn(conn):
    types = conn.execute("SELECT code, category FROM service_types WHERE is_custom = 0").fetchall()
    assert {row["code"] for row in types} == set(service_icons.BY_CODE)
    assert {row["category"] for row in types} == set(service_icons.BY_CATEGORY)
    used = {*service_icons.BY_CODE.values(), *service_icons.BY_CATEGORY.values(), service_icons.OIL_CHANGE,
            service_icons.FALLBACK}
    assert used <= _symbols()


def test_the_sprite_draws_in_the_texts_colour_on_a_24px_grid():
    for symbol in ET.parse(STATIC_DIR / "icons.svg").getroot():
        if symbol.tag.endswith("symbol"):
            assert symbol.get("viewBox") == "0 0 24 24" and symbol.get("stroke") == "currentColor"
            assert symbol.get("fill") == "none"


@pytest.mark.parametrize(("codes", "category", "icon"), [
    (["oil_filter", "engine_oil"], "Engine", "oil-change"),            # an oil change: a drop and a filter
    (["engine_oil"], "Engine", "oil"),
    (["spark_plugs"], "Engine", "spark-plug"),
    (["cabin_air_filter", "engine_air_filter"], "Engine", "air-filter"),   # the catalogue's first
    (["custom_throttle_body_cleaning"], "Engine", "engine"),            # yours: its category's
    (["custom_bed_liner"], "Body", "wrench"),
    ([], None, "wrench"),
])
def test_a_jobs_icon(codes, category, icon):
    assert icon_for(codes, category) == icon


@pytest.fixture
def steady(conn):
    car, _, _ = steady_car(conn, date.today() - timedelta(days=1000))
    return car


def _icon(name):
    return rf'<svg class="sicon(?: sicon--small)?" aria-hidden="true" focusable="false"><use href="/static/icons\.svg\?v=\d+#{name}"></use></svg>'


def test_next_up_the_chart_the_schedule_and_the_garage_show_each_jobs_icon(signed_in, steady):
    page = signed_in.get(f"/vehicles/{steady}").text
    assert re.search(_icon("cabin-filter") + r'<span class="vh">Replace: </span>Cabin air filter', page)    # next up
    assert re.search(r'<span class="ichart__item">' + _icon("cabin-filter") + "Cabin air filter</span>", page)
    schedule = signed_in.get(f"/vehicles/{steady}/schedule").text
    assert re.search(r'<p class="sched__name">' + _icon("cabin-filter") + '<span class="vh">Replace: </span>', schedule)
    assert re.search(_icon("cabin-filter") + "Cabin air filter", signed_in.get("/").text)          # Next, on the card


def test_a_services_chips_and_your_own_work(signed_in, conn):
    car = vehicles.create(conn, vehicles.VehicleFields(name="Outback"))
    visit = services.create_event(conn, car, EventInput(
        performed_on="2026-09-01", source="diy", odometer=30_000,
        lines=[LineInput("Oil and filter", covers=[Coverage("engine_oil", "replace"), Coverage("oil_filter", "replace")]),
               LineInput("Plugs", covers=[Coverage("spark_plugs", "replace")])]))
    page = signed_in.get(f"/vehicles/{car}").text
    assert re.search(r'<span class="chip">' + _icon("oil") + "Engine oil", page)
    assert re.search(r'<span class="chip">' + _icon("spark-plug") + "Spark plugs", page)
    assert re.search(r'<span class="logo logo--row logo--diy" aria-hidden="true">' + _icon("wrench") + "</span>"
                     r'<span class="withlogo__text">Your own work</span>', page)
    assert re.search(_icon("spark-plug") + "Spark plugs", signed_in.get(f"/services/{visit}").text)
