from __future__ import annotations

from datetime import date, timedelta

import pytest

from amg.engine.odometer import Odometer

D = date.fromisoformat


def test_between_readings_is_a_straight_line():
    odo = Odometer([(D("2020-01-01"), 10_000), (D("2020-01-11"), 10_500)])
    assert odo.miles_on(D("2020-01-06")) == 10_250
    assert odo.day_at(10_250) == D("2020-01-06")
    assert odo.day_at(10_251) == D("2020-01-07")    # the first day at or past it


def test_after_the_last_reading_it_carries_on_at_the_recent_pace():
    odo = Odometer([
        (D("2018-01-01"), 0),          # a slow first stretch, years ago
        (D("2023-01-01"), 20_000),
        (D("2023-07-01"), 26_000),     # the last year: 6,000 mi in 181 days
        (D("2024-01-01"), 32_000),
    ])
    pace = (32_000 - 20_000) / 365
    assert odo.rate() == pytest.approx(pace)
    assert odo.miles_on(D("2024-01-31")) == pytest.approx(32_000 + 30 * pace)
    assert odo.day_at(32_000 + 30 * pace) == D("2024-01-31")


def test_a_short_recent_stretch_uses_the_whole_history():
    odo = Odometer([(D("2020-01-01"), 0), (D("2023-01-01"), 30_000), (D("2023-01-21"), 31_000)])
    assert odo.rate() == pytest.approx(31_000 / (D("2023-01-21") - D("2020-01-01")).days)


def test_the_in_service_date_is_a_reading_of_zero():
    odo = Odometer([(D("2017-01-01"), 12_000)], in_service=D("2016-01-01"))
    assert odo.points[0] == (D("2016-01-01"), 0)
    assert odo.miles_on(D("2016-07-02")) == pytest.approx(12_000 * 183 / 366)
    assert odo.day_at(6_000) == D("2016-07-02")


def test_before_the_first_reading_it_runs_back_never_below_zero():
    odo = Odometer([(D("2020-01-01"), 1_000), (D("2020-01-11"), 2_000)])
    assert odo.miles_on(D("2019-12-30")) == 800
    assert odo.miles_on(D("2019-01-01")) == 0
    assert odo.day_at(800) == D("2019-12-30")


def test_one_reading_answers_only_for_its_own_day():
    odo = Odometer([(D("2020-01-01"), 5_000)])
    assert not odo
    assert odo.miles_on(D("2020-01-01")) == 5_000
    assert odo.miles_on(D("2020-02-01")) is None
    assert odo.day_at(6_000) is None and odo.rate() is None


def test_no_readings_answers_nothing():
    odo = Odometer([])
    assert not odo
    assert odo.miles_on(D("2020-01-01")) is None and odo.day_at(1) is None and odo.rate() is None


def test_same_day_readings_count_as_the_highest():
    odo = Odometer([(D("2020-01-01"), 1_000), (D("2020-01-01"), 1_200), (D("2020-01-11"), 2_200)])
    assert odo.points == [(D("2020-01-01"), 1_200), (D("2020-01-11"), 2_200)]


def test_a_reading_that_runs_backwards_is_ignored():
    odo = Odometer([(D("2020-01-01"), 5_000), (D("2020-02-01"), 4_000), (D("2020-03-01"), 6_000)])
    assert [miles for _, miles in odo.points] == [5_000, 6_000]


def test_a_parked_car_never_reaches_more_miles():
    odo = Odometer([(D("2020-01-01"), 5_000), (D("2021-01-01"), 5_000)])
    assert odo.day_at(5_001) is None
    assert odo.miles_on(D("2022-01-01")) == 5_000


def test_flat_stretches_are_skipped_when_finding_a_day():
    start = D("2020-01-01")
    odo = Odometer([(start, 1_000), (start + timedelta(days=10), 1_000), (start + timedelta(days=20), 2_000)])
    assert odo.day_at(1_500) == start + timedelta(days=15)
