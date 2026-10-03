"""The hand-worked fuel log: every stretch and figure worked out on paper, then compared.

Today is 2026-10-01, so the last 12 months start 2025-10-01.

    fill  date        odometer  gallons  cost    flags
    f1    2025-06-01  30,000     5.000   $20.00  partial          before the first full: left out
    f2    2025-06-15  30,200    12.000   $42.00                   the count starts
    f3    2025-07-10  30,450    10.000   $35.00                   A: 250 / 10       = 25.0 mpg, $35.00
    f4    2025-11-01  30,800     8.000   $28.00  partial
    f5    2025-11-20  30,950    12.000   $42.00                   B: 500 / (8 + 12) = 25.0 mpg, $70.00
    f6    2026-01-15  31,342    14.000   —                        C: 392 / 14       = 28.0 mpg, cost unknown
    f7    2026-03-01  31,800    10.000   $38.00  missed before    no stretch; the count starts again
    f8    2026-04-10  32,100     6.000   $24.00  partial, missed  the count stops
    f9    2026-05-01  32,400    12.000   $48.00                   the count starts again
    f10   2026-05-01  32,400     0.500    $2.00                   a top-off at no new miles: nothing
    f11   2026-06-15  32,760    12.000   $48.00                   D: 360 / 12       = 30.0 mpg, $48.00
    f12   2026-08-01  33,300    12.000   $48.00                   E: 540 / 12       = 45.0 mpg, $48.00
    f13   2026-09-20  33,600    12.000   $45.00                   F: 300 / 12       = 25.0 mpg, $45.00

All time: 2,342 mi / 80 gal = 29.275 mpg (the six stretches' plain mean would be 29.67).
Last 12 months, B to F: 2,092 mi / 70 gal = 29.886 mpg.
Cost a mile, C left out: 24,600¢ / 1,950 mi = 12.615¢; last 12 months 21,100¢ / 1,700 mi = 12.412¢.
Spent in the last 12 months, f4 to f13: $323.00 (f6's cost unknown); all time $420.00.
Price in the last 12 months: $323.00 / 84.5 gal = 382.249¢ a gallon.
Unusual: the median of 25, 25, 25, 28, 30, 45 is 26.5; E is 70% over it, D only 13%.
"""

from __future__ import annotations

from datetime import date
from statistics import mean

import pytest

from amg.engine.fuel import Fill, cost_per_mile, economy, home_rate, spent, stretches, unit_price, unusual

D = date.fromisoformat
YEAR_AGO = D("2025-10-01")

LOG = [
    # id, date, odometer, gallons, cents, full, missed before
    (1, "2025-06-01", 30_000, 5.0, 2_000, False, False),
    (2, "2025-06-15", 30_200, 12.0, 4_200, True, False),
    (3, "2025-07-10", 30_450, 10.0, 3_500, True, False),
    (4, "2025-11-01", 30_800, 8.0, 2_800, False, False),
    (5, "2025-11-20", 30_950, 12.0, 4_200, True, False),
    (6, "2026-01-15", 31_342, 14.0, None, True, False),
    (7, "2026-03-01", 31_800, 10.0, 3_800, True, True),
    (8, "2026-04-10", 32_100, 6.0, 2_400, False, True),
    (9, "2026-05-01", 32_400, 12.0, 4_800, True, False),
    (10, "2026-05-01", 32_400, 0.5, 200, True, False),
    (11, "2026-06-15", 32_760, 12.0, 4_800, True, False),
    (12, "2026-08-01", 33_300, 12.0, 4_800, True, False),
    (13, "2026-09-20", 33_600, 12.0, 4_500, True, False),
]


def _fills(log=LOG):
    return [Fill(i, D(on), miles, gallons, cents, full, missed) for i, on, miles, gallons, cents, full, missed in log]


@pytest.fixture
def found():
    return stretches(reversed(_fills()))    # in any order


def test_the_stretches_match_the_hand_check(found):
    assert [(s.start.id, s.end.id, s.miles, s.quantity, s.cost_cents, s.economy) for s in found] == [
        (2, 3, 250, 10.0, 3_500, 25.0),
        (3, 5, 500, 20.0, 7_000, 25.0),
        (5, 6, 392, 14.0, None, 28.0),
        (10, 11, 360, 12.0, 4_800, 30.0),
        (11, 12, 540, 12.0, 4_800, 45.0),
        (12, 13, 300, 12.0, 4_500, 25.0),
    ]


def test_economy_weighs_each_stretch_by_its_miles(found):
    assert economy(found) == pytest.approx(29.275)
    assert mean(s.economy for s in found) == pytest.approx(29.667, abs=1e-3)     # not this
    assert economy(found, since=YEAR_AGO) == pytest.approx(2_092 / 70)
    assert economy(found[-1:]) == 25.0


def test_cost_per_mile_leaves_out_a_stretch_with_a_cost_missing(found):
    assert cost_per_mile(found) == pytest.approx(24_600 / 1_950)
    assert cost_per_mile(found, since=YEAR_AGO) == pytest.approx(21_100 / 1_700)


def test_spent_and_the_price(found):
    fills = _fills()
    assert spent(fills, since=YEAR_AGO) == 32_300
    assert spent(fills) == 42_000
    assert unit_price(fills, since=YEAR_AGO) == pytest.approx(32_300 / 84.5)


def test_an_unusual_stretch_is_flagged(found):
    assert unusual(found) == {12}


def test_without_the_missed_flags_the_unlogged_fill_shows_as_unusual():
    log = [row[:6] + (False,) for row in LOG]
    found = stretches(_fills(log))
    c_to_f7 = next(s for s in found if s.end.id == 7)
    assert (c_to_f7.miles, c_to_f7.quantity) == (458, 10.0)    # 45.8 mpg: a tank that never went in
    assert unusual(found) == {7, 12}


@pytest.mark.parametrize(("last_odometer", "flagged"), [(850, set()), (855, {4})])
def test_unusual_means_more_than_forty_percent_off(last_odometer, flagged):
    # 25, 25, then 35 (exactly 40% over the median of 25) or 35.5
    log = [(1, "2026-01-01", 0, 10.0, None, True, False), (2, "2026-01-10", 250, 10.0, None, True, False),
           (3, "2026-01-20", 500, 10.0, None, True, False), (4, "2026-01-30", last_odometer, 10.0, None, True, False)]
    assert unusual(stretches(_fills(log))) == flagged


def test_fewer_than_three_stretches_flags_nothing():
    log = [(1, "2026-01-01", 0, 10.0, None, True, False), (2, "2026-01-10", 250, 10.0, None, True, False),
           (3, "2026-01-20", 900, 10.0, None, True, False)]
    assert [s.economy for s in stretches(_fills(log))] == [25.0, 65.0]
    assert unusual(stretches(_fills(log))) == set()


def test_until_a_second_full_fill_there_is_nothing_to_measure():
    one = _fills(LOG[:3])[1:2]          # f2 alone
    assert stretches(one) == [] and economy([]) is None and cost_per_mile([]) is None
    assert unit_price([]) is None and spent([]) == 0
    partial_after = _fills([LOG[1], LOG[3]])
    assert stretches(partial_after) == []


def test_charges_work_alike_and_give_the_home_rate():
    charges = [
        Fill(1, D("2026-09-01"), 12_000, 40.0, 600, place="home"),
        Fill(2, D("2026-09-05"), 12_130, 39.0, 1_300, place="public"),
        Fill(3, D("2026-09-09"), 12_262, 40.0, 640, place="home"),
        Fill(4, D("2026-09-12"), 12_360, 30.0, None, place="home"),       # free? no cost: not a rate
    ]
    found = stretches(charges)
    assert [round(s.economy, 3) for s in found] == [3.333, 3.3, 3.267]
    assert home_rate(charges) == 16.0
    assert home_rate(charges[1:2]) is None
