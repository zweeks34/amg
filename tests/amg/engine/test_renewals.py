"""Inspections and registration: when each is due, the expiry AMG suggests, and when each is paid for."""

from __future__ import annotations

from datetime import date

import pytest

from amg.engine.renewals import KINDS, Record, Standing, coming, end_of_month, interval, offer, standing, suggest

SAFETY, EMISSIONS, REGISTRATION = KINDS["safety"], KINDS["emissions"], KINDS["registration"]
TODAY = date(2026, 10, 5)


@pytest.mark.parametrize(("expires", "state", "days"), [
    (date(2026, 11, 5), "later", 31),
    (date(2026, 11, 4), "due", 30),
    (date(2026, 10, 13), "due", 8),
    (date(2026, 10, 12), "week", 7),
    (date(2026, 10, 5), "week", 0),       # good through today
    (date(2026, 10, 4), "expired", -1),   # the day after
])
def test_standing_at_its_edges(expires, state, days):
    assert standing(expires, TODAY) == Standing(state, days)


def test_end_of_month():
    assert end_of_month(date(2027, 9, 3)) == date(2027, 9, 30)
    assert end_of_month(date(2028, 2, 10)) == date(2028, 2, 29)    # a leap year
    assert end_of_month(date(2027, 2, 10)) == date(2027, 2, 28)


def test_an_inspection_counts_from_the_day_it_was_done():
    assert suggest(SAFETY, date(2026, 9, 3), []) == date(2027, 9, 30)
    # Inspected a month early: the sticker it replaces had to Oct 31, but the new one runs from September.
    assert suggest(SAFETY, date(2026, 9, 3), [Record(date(2026, 10, 31), date(2025, 10, 2))]) == date(2027, 9, 30)
    assert suggest(EMISSIONS, date(2026, 3, 15), []) == date(2028, 3, 31)


def test_a_month_end_inspection_lands_on_a_month_end():
    assert suggest(SAFETY, date(2027, 1, 31), []) == date(2028, 1, 31)
    assert suggest(SAFETY, date(2027, 2, 28), []) == date(2028, 2, 29)


def test_a_registration_extends_the_old_expiry():
    before = [Record(date(2026, 10, 31), date(2025, 10, 20))]
    assert suggest(REGISTRATION, date(2026, 10, 2), before) == date(2027, 10, 31)


def test_a_lapsed_registration_counts_from_the_renewal():
    before = [Record(date(2026, 7, 31), date(2025, 7, 10))]
    assert suggest(REGISTRATION, date(2026, 10, 2), before) == date(2027, 10, 31)


def test_the_interval_is_learned_from_the_records():
    two_years = [Record(date(2028, 10, 31), date(2026, 10, 2)), Record(date(2026, 10, 31))]
    assert interval(REGISTRATION, two_years) == 24
    assert suggest(REGISTRATION, date(2028, 10, 1), two_years) == date(2030, 10, 31)
    # One record with its renewal date says it too.
    assert interval(REGISTRATION, [Record(date(2029, 10, 31), date(2026, 10, 2))]) == 36
    # Inspected a month early each year still reads as a year.
    assert interval(SAFETY, [Record(date(2026, 8, 31)), Record(date(2025, 9, 30))]) == 12


def test_the_usual_interval_until_the_records_say():
    assert [interval(kind, []) for kind in (SAFETY, EMISSIONS, REGISTRATION)] == [12, 24, 12]
    assert interval(EMISSIONS, [Record(date(2027, 3, 31))]) == 24     # no done date: nothing to learn from
    # The same sticker typed twice says nothing about how long one lasts.
    assert interval(EMISSIONS, [Record(date(2027, 3, 31)), Record(date(2027, 3, 31))]) == 24


def test_a_receipt_is_offered_when_it_moves_the_expiry():
    current = [Record(date(2026, 9, 30), date(2025, 9, 3))]
    assert offer(SAFETY, date(2026, 9, 2), 7, current, TODAY) == date(2027, 9, 30)
    # The inspection behind the sticker already logged: nothing to move.
    assert offer(SAFETY, date(2025, 9, 3), 6, current, TODAY) is None
    # Logged from this very receipt.
    assert offer(SAFETY, date(2026, 9, 2), 7, [Record(date(2027, 9, 30), date(2026, 9, 2), 7)], TODAY) is None
    # Its expiry typed in from the sticker, without the date it was done.
    assert offer(SAFETY, date(2026, 9, 2), 7, [Record(date(2027, 9, 30))], TODAY) is None


def test_with_nothing_logged_only_a_sticker_that_could_still_be_on():
    assert offer(SAFETY, date(2026, 2, 10), 3, [], TODAY) == date(2027, 2, 28)
    assert offer(SAFETY, date(2019, 3, 4), 1, [], TODAY) is None


# ---------- When each is paid for ----------

YEAR_OUT = date(2027, 10, 31)     # the end of a 12-month budget from TODAY


def test_paid_in_the_month_it_expires_then_every_interval_after():
    assert coming(REGISTRATION, [Record(date(2027, 3, 31), date(2026, 3, 10))], TODAY, YEAR_OUT) == [
        (date(2027, 3, 31), date(2027, 3, 31))]
    three_years = coming(REGISTRATION, [Record(date(2027, 3, 31), date(2026, 3, 10))], TODAY, date(2029, 10, 31))
    assert [day for day, _ in three_years] == [date(2027, 3, 31), date(2028, 3, 31), date(2029, 3, 31)]


def test_an_expired_one_is_paid_now_and_the_next_counted_from_today():
    assert coming(SAFETY, [Record(date(2026, 8, 31))], TODAY, YEAR_OUT) == [
        (TODAY, date(2026, 8, 31)), (date(2027, 10, 31), date(2027, 10, 31))]


def test_a_two_year_one_and_one_beyond_the_horizon():
    assert coming(EMISSIONS, [Record(date(2027, 4, 30))], TODAY, YEAR_OUT) == [(date(2027, 4, 30), date(2027, 4, 30))]
    assert coming(EMISSIONS, [Record(date(2027, 4, 30))], TODAY, date(2029, 10, 31))[1][0] == date(2029, 4, 30)
    assert coming(EMISSIONS, [Record(date(2027, 11, 30))], TODAY, YEAR_OUT) == []
    assert coming(SAFETY, [], TODAY, YEAR_OUT) == []                                  # nothing logged: nothing known
