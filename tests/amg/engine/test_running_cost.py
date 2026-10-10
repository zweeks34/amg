"""Running cost: fuel, service and fees a mile, a calendar year at a time, against a hand-worked car.

The car, got on Jul 1, 2023 at 40,000 mi, read on each Jan 1 since, so every
year's miles are exact:

    2023 from Jul 1   6,000 mi   service $450                    fuel all estimated
    2024             12,000 mi   service $1,200, fees $20 + $85  fuel all estimated
    2025 to Jul 1     6,000 mi   service $300                    fuel: two stretches measured

The fuel log starts in 2025: a full tank at 60,000 (its cost paid for miles
nobody measured), then full at 61,000 for $120, at 62,000 with no cost, and at
63,000 for $140. That's 26,000¢ over 2,000 measured miles: 13¢ a mile, the
rate every other mile is counted at.

    2023   fuel  6,000 × 13 = $780            total $1,230     20.5¢
    2024   fuel 12,000 × 13 = $1,560          total $2,865     23.875¢
    2025   fuel $260 + 4,000 × 13 = $780      total $1,080     18¢
    all    24,000 mi                          total $5,175     21.5625¢
"""

from __future__ import annotations

from datetime import date

import pytest

from amg.engine import forecast, fuel
from amg.engine.forecast import Due, Fee, Job, Price
from amg.engine.fuel import Fill
from amg.engine.odometer import Odometer
from amg.engine.running_cost import MIN_MILES, Period, Spend, ahead, whole, years

START, TODAY = date(2023, 7, 1), date(2025, 7, 1)
ODO = Odometer([(START, 40_000), (date(2024, 1, 1), 46_000), (date(2025, 1, 1), 58_000), (TODAY, 64_000)])
FILLS = [Fill(1, date(2025, 3, 1), 60_000, 10.0, 4_000), Fill(2, date(2025, 4, 1), 61_000, 33.0, 12_000),
         Fill(3, date(2025, 5, 1), 62_000, 33.0, None), Fill(4, date(2025, 6, 1), 63_000, 34.0, 14_000)]
STRETCHES = fuel.stretches(FILLS)
SPENDS = [
    Spend(date(2023, 6, 30), "service", 99_999),   # the day before you got it
    Spend(START, "service", 0),
    Spend(date(2023, 9, 10), "service", 45_000),
    Spend(date(2024, 3, 2), "service", 120_000),
    Spend(date(2024, 3, 2), "fees", 2_000),
    Spend(date(2024, 11, 30), "fees", 8_500),
    Spend(TODAY, "service", 30_000),                # today counts
    Spend(date(2025, 7, 2), "service", 99_999),    # after the end
]


@pytest.fixture
def rows():
    return years(START, TODAY, ODO, SPENDS, STRETCHES, fuel.cost_per_mile(STRETCHES))


def test_the_rate_is_the_measured_stretches():
    assert fuel.cost_per_mile(STRETCHES) == 13.0


def test_a_row_a_calendar_year_from_the_day_you_got_it_to_today(rows):
    assert [(p.start, p.end) for p in rows] == [(START, date(2023, 12, 31)), (date(2024, 1, 1), date(2024, 12, 31)),
                                                (date(2025, 1, 1), TODAY)]
    assert [p.miles for p in rows] == [6_000, 12_000, 6_000]


def test_what_each_year_cost(rows):
    assert [(p.fuel, p.service, p.fees) for p in rows] == [(78_000, 45_000, 0), (156_000, 120_000, 10_500),
                                                          (78_000, 30_000, 0)]
    assert [p.estimated_miles for p in rows] == [6_000, 12_000, 4_000]
    assert [p.cents_a_mile for p in rows] == [20.5, 23.875, 18.0]


def test_the_whole_span_adds_up_the_years(rows):
    found = whole(rows)
    assert (found.start, found.end, found.miles) == (START, TODAY, 24_000)
    assert (found.fuel, found.service, found.fees, found.total) == (312_000, 195_000, 10_500, 517_500)
    assert found.cents_a_mile == 21.5625 and found.a_mile(found.fuel) == 13.0
    assert found.estimated and found.estimated_miles == 22_000


def test_a_stretch_with_its_cost_missing_is_estimated_like_any_unmeasured_mile(rows):
    # 2025's 6,000 mi: 2,000 measured, and the 1,000 the costless stretch measured go in with the rest.
    assert rows[-1].estimated_miles == 4_000 and rows[-1].fuel == 26_000 + 4_000 * 13


def test_with_no_cost_a_mile_fuel_isnt_counted(rows):
    found = years(START, TODAY, ODO, SPENDS, STRETCHES, None)
    assert [p.fuel for p in found] == [None, None, None] and not any(p.estimated for p in found)
    assert whole(found).fuel is None and whole(found).total == 205_500


def test_a_stretch_longer_than_its_year_so_far_never_makes_estimated_miles_negative():
    odo = Odometer([(date(2024, 12, 1), 10_000), (date(2025, 1, 10), 11_300)])
    stretch = fuel.stretches([Fill(1, date(2024, 12, 20), 10_600, 10.0, 3_000),
                              Fill(2, date(2025, 1, 5), 11_100, 15.0, 6_000)])
    [first, current] = years(date(2024, 12, 1), date(2025, 1, 10), odo, [], stretch, 12.0)
    assert current.miles < 500 and (current.fuel, current.estimated_miles) == (6_000, 0)
    assert not current.estimated


def test_too_few_miles_for_a_figure_a_mile():
    short = Period(START, START, MIN_MILES - 1, 1_000.0, 0, 5_000, 0)
    assert short.cents_a_mile is None and short.a_mile(1_000) is None
    assert Period(START, START, MIN_MILES, None, 0, 5_000, 0).cents_a_mile == 10.0


def test_nothing_before_it_starts():
    assert years(TODAY, START, ODO, SPENDS, STRETCHES, 13.0) == [] and whole([]) is None


def test_one_year_on_its_own():
    [only] = years(date(2025, 1, 1), TODAY, ODO, SPENDS, [], 13.0)
    assert (only.miles, only.fuel, only.service) == (6_000, 78_000, 30_000)


# ---------- The next 12 months ----------


def _price(cents):
    return Price(cents, cents, cents, "yours")


def _months(cents_a_mile=13.0):
    oil, pads, belt = (Job(frozenset({code}), "replace") for code in ("engine_oil", "brake_pads", "timing_belt"))
    dues = [Due(1, "Oil", oil, "overdue", TODAY, date(2025, 5, 1), None),
            Due(2, "Pads", pads, "later", date(2025, 9, 1), date(2025, 9, 1), None),
            Due(3, "Belt", belt, "later", date(2026, 1, 1), date(2026, 1, 1), None)]
    fees = [(Fee("registration", "Registration", "overdue", TODAY, date(2025, 6, 30)), _price(8_500)),
            (Fee("safety", "Safety inspection", "later", date(2026, 3, 31), date(2026, 3, 31)), _price(2_000))]
    return forecast.budget(dues, {oil.key: _price(6_000), pads.key: _price(30_000), belt.key: None}, TODAY, 12,
                           40.0, cents_a_mile, fees)


def test_ahead_is_the_budgets_months_over_the_miles_to_come():
    found = ahead(_months(), 40.0)
    period = found.period
    assert (period.start, period.end, period.miles) == (TODAY, date(2026, 6, 30), 40.0 * 365)
    assert (period.service, period.fees) == (30_000, 2_000)
    assert abs(period.fuel - 40 * 365 * 13) < 12           # each month's fuel is rounded to the cent
    assert period.cents_a_mile == pytest.approx((period.fuel + 32_000) / 14_600)


def test_ahead_leaves_out_whats_due_now_and_counts_whats_unpriced():
    found = ahead(_months(), 40.0)
    assert (found.due_now, found.unpriced) == (6_000 + 8_500, 1)


def test_ahead_without_a_cost_a_mile_or_a_pace():
    assert ahead(_months(cents_a_mile=None), 40.0).period.fuel is None
    assert ahead(_months(), None) is None and ahead([], 40.0) is None
