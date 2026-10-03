"""The forecast, against figures worked out by hand.

**What visits cost** (today is 2028-03-01; prices from 2024-03-01 are four
years old and from 2020-03-01 eight, each exactly 4 × 365.25 days, so the
inflation factors are 1.04⁴ = 1.16985856 and 1.04⁸ = 1.36856905):

A, 2024-03-01: oil and filter $60, tire rotation $20, a multi-point check at
   $0, shop supplies $4 (a fee covering nothing) and tax $4. The $8 of
   overhead is shared across the $80 of work: oil and filter $60 + $6 = $66,
   rotation $20 + $2 = $22.
B, 2020-03-01: a "30,000-mile service" at $300 that replaced the oil, the oil
   filter, the cabin filter and the brake fluid, and inspected the brake lines
   and the steering. Four things done: $75 each, so oil and filter (two of
   them) is $150. The inspections rode along and cost nothing.
C, 2026-03-01: an oil filter bought on its own, $8 — not an oil change.
D, 2026-03-01: brake fluid done as goodwill, $0 — not a price.
E, 2024-03-01: brake fluid $120 less a $20 coupon (covering nothing): $100.
F, 2028-03-01: a brake inspection on its own, $40, looking at the brake lines
   and the pads: $20 for the brake lines.
G, 2028-03-01: oil $30 and a filter $8, your own work: $38.
H, 2024-03-01: an engine air filter, $30.
O, 2028-03-01, the other car: wiper blades, $30.

**Estimates:**

| Job | Source | Prices in today's money | Price |
|---|---|---|---|
| Engine air filter | yours, $45 (H is ignored) | | $45.00 |
| Oil and filter | paid: A, B, G (C isn't one) | 7,721, 20,529, 3,800 | median $77.21 |
| Tire rotation | paid: A | 2,574 | $25.74 |
| Brake fluid | paid: B, E (D isn't one) | 10,264, 11,699 | median $109.82 |
| Brake lines inspection | paid: F | 2,000 | $20.00 |
| Spark plugs | quoted $280 on 2024-03-01 | 32,756 | $327.56 |
| Wiper blades | the other car: O | 3,000 | $30.00 |
| Timing belt | Claude, $600–900 | | $750.00 |
| Steering inspection | B rode along: nothing | | none |
| Engine coolant | nothing knows | | none |

The oil and filter's mean would be $106.83. The median keeps B's package
price from pulling it up. Brake fluid counted with D's $0 would have been
$102.64.
"""

from __future__ import annotations

from datetime import date

import pytest

from amg.engine.forecast import (
    Due, Job, Line, Price, Quote, Visit, budget, estimate, fuel_cents, months, paid, quoted, today_money, upcoming)
from amg.engine.odometer import Odometer
from amg.engine.schedule import Car, Item, ItemStatus, Occurrence, Service, assess

TODAY = date(2028, 3, 1)
CAR, OTHER = 1, 2


def job(*codes, action="replace"):
    return Job(frozenset(codes), action)


def line(cents, *covers, kind="labor"):
    return Line(cents, kind, dict(covers))


R, I, P = "replace", "inspect", "perform"
A = Visit(1, CAR, date(2024, 3, 1), (
    line(6_000, ("engine_oil", R), ("oil_filter", R)),
    line(2_000, ("tire_rotation", P)),
    line(0, ("multipoint_inspection", I)),
    line(400, kind="fee"),
), tax_cents=400)
B = Visit(2, CAR, date(2020, 3, 1), (
    line(30_000, ("engine_oil", R), ("oil_filter", R), ("cabin_air_filter", R), ("brake_fluid", R),
         ("brake_system", I), ("steering_suspension", I)),
))
C = Visit(3, CAR, date(2026, 3, 1), (line(800, ("oil_filter", R), kind="part"),))
D = Visit(4, CAR, date(2026, 3, 1), (line(0, ("brake_fluid", R)),))
E = Visit(5, CAR, date(2024, 3, 1), (line(12_000, ("brake_fluid", R)), line(-2_000, kind="other")))
F = Visit(6, CAR, date(2028, 3, 1), (line(4_000, ("brake_system", I), ("brake_pads", I)),))
G = Visit(7, CAR, date(2028, 3, 1), (line(3_000, ("engine_oil", R), kind="part"), line(800, ("oil_filter", R), kind="part")))
H = Visit(8, CAR, date(2024, 3, 1), (line(3_000, ("engine_air_filter", R), kind="part"),))
O = Visit(9, OTHER, date(2028, 3, 1), (line(3_000, ("wiper_blades", R), kind="part"),))
HERE = (A, B, C, D, E, F, G, H)
QUOTES = (Quote(date(2024, 3, 1), frozenset({"spark_plugs"}), 28_000),)

OIL = job("engine_oil", "oil_filter")
ROTATION = job("tire_rotation", action=P)
BRAKE_FLUID = job("brake_fluid")
BRAKE_LINES = job("brake_system", action=I)
STEERING = job("steering_suspension", action=I)


# ---------- What one visit charged ----------


def test_a_visits_overhead_is_shared_across_its_work():
    assert paid(A, OIL) == 6_600
    assert paid(A, ROTATION) == 2_200
    assert paid(A, BRAKE_FLUID) is None   # it didn't do it


def test_a_package_line_is_split_between_the_things_it_did():
    assert paid(B, OIL) == 15_000
    assert paid(B, job("cabin_air_filter")) == 7_500
    assert paid(B, BRAKE_FLUID) == 7_500


def test_inspections_riding_along_cost_nothing_and_alone_cost_their_share():
    assert paid(B, BRAKE_LINES) is None and paid(B, STEERING) is None
    assert paid(F, BRAKE_LINES) == 2_000
    assert paid(A, BRAKE_LINES) is None   # a multi-point check meets inspections, but prices none of them


def test_a_visit_must_do_all_of_a_job_to_price_it():
    assert paid(C, OIL) is None
    assert paid(C, job("oil_filter")) == 800
    assert paid(G, OIL) == 3_800


def test_a_visit_at_no_charge_is_not_a_price():
    assert paid(D, BRAKE_FLUID) is None
    assert paid(Visit(10, CAR, TODAY, (line(None, ("brake_fluid", R)),)), BRAKE_FLUID) is None


def test_a_discount_comes_off_and_a_credit_against_the_work_counts():
    assert paid(E, BRAKE_FLUID) == 10_000
    battery = Visit(11, CAR, TODAY, (line(15_000, ("battery_12v", R), kind="part"),
                                     line(-10_000, ("battery_12v", R), kind="other")))
    assert paid(battery, job("battery_12v")) == 5_000
    refunded = Visit(12, CAR, TODAY, (line(15_000, ("battery_12v", R)), line(-15_000, ("battery_12v", R))))
    assert paid(refunded, job("battery_12v")) is None


def test_a_quote_prices_the_part_of_it_that_is_the_job():
    both = Quote(TODAY, frozenset({"spark_plugs", "drive_belts"}), 40_000)
    assert quoted(both, job("spark_plugs")) == 20_000
    assert quoted(both, job("spark_plugs", "engine_air_filter")) is None   # it didn't quote for all of it
    assert quoted(Quote(TODAY, frozenset({"brake_system"}), 5_000), BRAKE_LINES) is None


def test_older_prices_are_brought_up_to_today():
    assert today_money(5_000, date(2024, 3, 1), TODAY) == 5_849      # $50 × 1.04⁴ = $58.49
    assert today_money(5_000, date(2020, 3, 1), TODAY) == 6_843      # × 1.04⁸
    assert today_money(5_000, TODAY, TODAY) == 5_000
    assert today_money(5_000, date(2029, 1, 1), TODAY) == 5_000      # never deflated


# ---------- The estimate, source by source ----------


def _estimate(j, **kw):
    return estimate(j, TODAY, visits=HERE, quotes=QUOTES, elsewhere=(O,), **kw)


def test_your_price_beats_your_history():
    assert _estimate(job("engine_air_filter"), yours=4_500) == Price(4_500, 4_500, 4_500, "yours")
    assert _estimate(job("engine_air_filter")).source == "paid"


def test_paid_on_this_car_is_the_median_in_todays_money():
    assert _estimate(OIL) == Price(7_721, 3_800, 20_529, "paid", 3, TODAY, frozenset({CAR}))
    assert _estimate(ROTATION).cents == 2_574
    assert _estimate(BRAKE_LINES).cents == 2_000


def test_a_zero_dollar_visit_does_not_lower_the_estimate():
    price = _estimate(BRAKE_FLUID)
    assert (price.cents, price.count) == (10_982, 2)   # D's $0 would have made it 10,264


def test_then_quotes_then_the_other_cars_then_claude():
    assert _estimate(job("spark_plugs")) == Price(32_756, 32_756, 32_756, "quoted", 1, date(2024, 3, 1))
    assert _estimate(job("wiper_blades")) == Price(3_000, 3_000, 3_000, "elsewhere", 1, TODAY, frozenset({OTHER}))
    assert _estimate(job("timing_belt"), claude=(60_000, 90_000)) == Price(75_000, 60_000, 90_000, "claude")


def test_each_source_wins_over_the_ones_after_it():
    # spark plugs paid on this car beat the quote; the quote beats the other car; the other car beats Claude
    plugs = Visit(20, CAR, TODAY, (line(25_000, ("spark_plugs", R)),))
    assert estimate(job("spark_plugs"), TODAY, visits=(plugs,), quotes=QUOTES).source == "paid"
    there = Visit(21, OTHER, TODAY, (line(25_000, ("spark_plugs", R)),))
    assert estimate(job("spark_plugs"), TODAY, quotes=QUOTES, elsewhere=(there,)).source == "quoted"
    assert estimate(job("wiper_blades"), TODAY, elsewhere=(O,), claude=(1, 2)).source == "elsewhere"


def test_nothing_knows_some_jobs():
    assert _estimate(STEERING) is None
    assert _estimate(job("engine_coolant")) is None


# ---------- When, and the budget ----------
#
# A car new on 2026-01-01, driven 30 mi a day; today is 2026-10-03 (8,250 mi)
# and the horizon is 12 months, October 2026 to September 2027.
#
# Oil and filter, every 6,000 mi or 12 months: done early at 4,800 mi on
#   2026-06-10, so due at 10,800 (2026-12-27), then 16,800 (2027-07-15).
#   22,800 falls on 2028-01-31: past the horizon.
# Tire rotation, every 6,000 mi, never done: overdue since 6,000 (2026-07-20),
#   so due now; then 12,000 (2027-02-05) and 18,000 (2027-08-24).
# Cabin air filter, every 12 months: 2027-01-01.
# Timing belt, once at 12,000 mi: 2027-02-05, and never again.
# Engine coolant, first at 137,500 mi or 11 years: past the horizon.
#
# Priced at oil $80, rotation $25, cabin filter $40; the belt has no price.
# Maintenance: 25 + 80 + 40 + 25 + 80 + 25 = $275.
# Fuel at 12¢ a mile: 360¢ a day. October from the 3rd is 29 days, $104.40;
# November $108.00; February $100.80; the 363 days in all, $1,306.80.

START = date(2026, 1, 1)
NOW = date(2026, 10, 3)
END = date(2027, 9, 30)


@pytest.fixture
def statuses():
    items = [
        Item(1, "Oil and filter", frozenset({"engine_oil", "oil_filter"}), R, interval_miles=6_000, interval_months=12),
        Item(2, "Tire rotation", frozenset({"tire_rotation"}), P, interval_miles=6_000),
        Item(3, "Cabin air filter", frozenset({"cabin_air_filter"}), R, interval_months=12),
        Item(4, "Timing belt", frozenset({"timing_belt"}), R, first_miles=12_000),
        Item(5, "Engine coolant", frozenset({"engine_coolant"}), R, interval_miles=30_000, interval_months=36,
             first_miles=137_500, first_months=132),
    ]
    oil_change = Service(1, date(2026, 6, 10), 4_800, {"engine_oil": frozenset({R}), "oil_filter": frozenset({R})})
    odometer = Odometer([(date(2026, 6, 10), 4_800), (date(2026, 10, 1), 8_190)], in_service=START)
    return assess(items, [oil_change], odometer, Car(in_service=START), NOW, until=END)


def test_upcoming_lists_every_occurrence_in_the_horizon_and_overdue_ones_today(statuses):
    found = [(d.name, d.status, d.day.isoformat(), d.miles) for d in upcoming(statuses, NOW, END)]
    assert found == [
        ("Tire rotation", "overdue", "2026-10-03", 6_000),
        ("Oil and filter", "later", "2026-12-27", 10_800),
        ("Cabin air filter", "later", "2027-01-01", 10_950),
        ("Timing belt", "later", "2027-02-05", 12_000),
        ("Tire rotation", "later", "2027-02-05", 12_000),
        ("Oil and filter", "later", "2027-07-15", 16_800),
        ("Tire rotation", "later", "2027-08-24", 18_000),
    ]


def test_only_occurrences_still_to_come_count():
    item = Item(1, "Oil", frozenset({"engine_oil"}), R, interval_months=6)
    done = Occurrence("done", date(2026, 1, 1), None, Service(1, date(2026, 1, 2), None, {}))
    statuses = [ItemStatus(item, [done, Occurrence("gap", date(2026, 7, 1), None),
                                  Occurrence("before", date(2025, 7, 1), None), Occurrence("later", NOW, None)])]
    assert [d.status for d in upcoming(statuses, NOW, END)] == ["later"]


def test_months_start_with_the_rest_of_this_one():
    found = months(NOW, 12)
    assert found[0] == (NOW, date(2026, 10, 31))
    assert found[1] == (date(2026, 11, 1), date(2026, 11, 30))
    assert found[4] == (date(2027, 2, 1), date(2027, 2, 28))
    assert found[-1] == (date(2027, 9, 1), END)


def test_fuel_is_miles_a_day_times_the_cost_a_mile():
    assert fuel_cents(30.0, 12.0, NOW, date(2026, 10, 31)) == 10_440
    assert fuel_cents(30.0, 12.0, NOW, END) == 130_680


def test_the_budget_month_by_month(statuses):
    prices = {
        ("engine_oil,oil_filter", R): Price(8_000, 8_000, 8_000, "yours"),
        ("tire_rotation", P): Price(2_500, 2_500, 2_500, "yours"),
        ("cabin_air_filter", R): Price(4_000, 4_000, 4_000, "yours"),
    }
    found = budget(upcoming(statuses, NOW, END), prices, NOW, 12, rate=30.0, cents_a_mile=12.0)
    by_month = {m.start.strftime("%Y-%m"): (m.maintenance, m.fuel) for m in found}
    assert by_month["2026-10"] == (2_500, 10_440)
    assert by_month["2026-11"] == (0, 10_800)
    assert by_month["2026-12"] == (8_000, 11_160)
    assert by_month["2027-01"] == (4_000, 11_160)
    assert by_month["2027-02"] == (2_500, 10_080)
    assert by_month["2027-07"] == (8_000, 11_160)
    assert by_month["2027-08"] == (2_500, 11_160)
    assert sum(m.maintenance for m in found) == 27_500
    assert sum(m.fuel for m in found) == 130_680
    february = found[4]
    assert [d.name for d in february.unpriced] == ["Timing belt"]
    assert february.total == 2_500 + 10_080


def test_without_a_pace_or_a_cost_a_mile_there_is_no_fuel(statuses):
    found = budget(upcoming(statuses, NOW, END), {}, NOW, 12, rate=30.0)
    assert all(m.fuel is None and m.fuel_miles is None for m in found)


def test_an_unpriced_inspection_is_not_counted_as_missing():
    look = Due(1, "Brake lines", BRAKE_LINES, "later", NOW, NOW, None)
    (month,) = budget([look], {}, NOW, 1)
    assert month.unpriced == [] and month.maintenance == 0
