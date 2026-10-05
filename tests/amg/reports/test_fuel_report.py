"""The Fuel report: month by month, economy is miles over what they took — never an average of tanks."""

from __future__ import annotations

from datetime import date

import pytest

from amg.engine.fuel import Fill
from amg.reports import fuel
from amg.reports.filters import Filters
from amg.web.fuel_status import UNITS

CAR = {"id": 1, "name": "Outback"}


def fill(n, day, odometer, quantity, cents, full=True):
    return Fill(n, date.fromisoformat(day), odometer, quantity, cents, full)


# January: a 300-mile tank on 10 gallons (30 mpg), then 100 miles on 5 (20 mpg) — 400 on 15, 26.7 mpg, not 25.
# February: a partial fill, then a full one: 280 miles on 10 gallons, 28 mpg.
FILLS = [
    fill(1, "2026-01-02", 1_000, 12.0, 3_600),
    fill(2, "2026-01-12", 1_300, 10.0, 3_000),
    fill(3, "2026-01-28", 1_400, 5.0, 1_500),
    fill(4, "2026-02-09", 1_550, 4.0, 1_200, full=False),
    fill(5, "2026-02-20", 1_680, 6.0, 1_800),
]


def test_a_months_economy_is_miles_over_quantity():
    section = fuel.build(CAR, UNITS["gas"], FILLS, Filters(view="fuel"))
    february, january = section.months
    assert (january.month, january.fills, january.miles, january.quantity) == ("2026-01", 3, 400, 15.0)
    assert january.economy == pytest.approx(400 / 15)
    assert january.spent == 3_600 + 3_000 + 1_500                  # every fill, the first one included
    assert january.cost_per_mile == pytest.approx(4_500 / 400)     # what the measured miles took
    assert (february.miles, february.quantity, february.economy) == (280, 10.0, 28.0)
    assert february.spent == 3_000 and february.unit_price == pytest.approx(300)   # the partial fill counts
    assert section.whole.economy == pytest.approx(680 / 25) and section.whole.fills == 5
    assert january.label == "Jan 2026" and section.whole.label == "All"


def test_a_stretch_that_began_before_the_dates_counts_in_the_month_it_ended():
    section = fuel.build(CAR, UNITS["gas"], FILLS, Filters(view="fuel", start="2026-02-01"))
    assert [m.month for m in section.months] == ["2026-02"]
    assert section.months[0].miles == 280 and section.whole.fills == 2


def test_the_trend_has_a_dot_a_month():
    trend = fuel.build(CAR, UNITS["gas"], FILLS, Filters(view="fuel")).trend
    assert trend["per"] == "month" and len(trend["points"]) == 2
    assert trend["points"][0]["label"] == "Jan 2026: 26.7 mpg"
    assert trend["average"]["label"] == "27.2 mpg average, all time"
    assert fuel.build(CAR, UNITS["gas"], FILLS[:3], Filters(view="fuel")).trend is None     # one month: no line to draw


def test_an_electric_car_in_kwh():
    charges = [fill(1, "2026-03-01", 500, 40.0, 600), fill(2, "2026-03-15", 640, 40.0, 600)]
    month = fuel.build(CAR, UNITS["electric"], charges, Filters(view="fuel")).months[0]
    assert month.economy == pytest.approx(3.5) and month.unit_price == pytest.approx(15)


def test_no_fills_in_the_dates_is_no_section():
    assert fuel.build(CAR, UNITS["gas"], FILLS, Filters(view="fuel", start="2026-03-01")) is None
    assert fuel.build(CAR, UNITS["gas"], [], Filters(view="fuel")) is None
