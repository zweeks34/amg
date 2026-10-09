"""Warranties: when each ends, ending soon, and which later visit to ask about."""

from __future__ import annotations

from datetime import date, timedelta

from amg.engine.odometer import Odometer
from amg.engine.warranties import (ENDING_DAYS, Visit, Warranty, end_miles, ends_on, in_force_on, replacing, standing,
                                   to_ask)

START = date(2025, 3, 1)
# 1,000 mi a month, near enough: 33 a day from 50,000 on the day it started.
ODO = Odometer([(START, 50_000), (date(2025, 9, 1), 56_072)])


def battery(**fields) -> Warranty:
    values = dict(id=1, starts_on=START, start_miles=50_000, months=36, miles=None, codes=frozenset({"battery_12v"}),
                  event_id=10)
    values.update(fields)
    return Warranty(**values)


def visit(id, day, *replaced, shop="Valley Honda", odometer=None) -> Visit:
    return Visit(id, day, shop, odometer, frozenset(replaced))


# ---------- When it ends ----------


def test_the_end_date_from_its_months_across_month_ends():
    assert ends_on(battery()) == date(2028, 3, 1)
    assert ends_on(battery(starts_on=date(2024, 1, 31), months=1)) == date(2024, 2, 29)
    assert ends_on(battery(months=None, miles=30_000)) is None


def test_the_end_miles_from_a_known_start_and_an_estimated_one():
    assert end_miles(battery(months=None, miles=36_000), ODO) == 86_000
    estimated = battery(starts_on=date(2025, 6, 1), start_miles=None, months=None, miles=10_000)
    assert end_miles(estimated, ODO) == round(ODO.miles_on(date(2025, 6, 1))) + 10_000
    assert end_miles(estimated, None) is None
    assert end_miles(battery(), ODO) is None


def test_in_force_by_date_by_miles_and_for_life():
    term = battery(miles=36_000)
    assert in_force_on(term, date(2028, 3, 1), 60_000, ODO)            # its last day
    assert not in_force_on(term, date(2028, 3, 2), 60_000, ODO)
    assert not in_force_on(term, date(2026, 1, 1), 86_000, ODO)        # its miles reached
    assert in_force_on(term, date(2026, 1, 1), 85_999, ODO)
    assert not in_force_on(term, date(2025, 2, 28), 49_000, ODO)       # before it started
    life = battery(months=None)
    assert life.lifetime and in_force_on(life, date(2060, 1, 1), 400_000, ODO)


# ---------- Standing ----------


def test_ending_at_sixty_days_and_not_at_sixty_one():
    last = date(2028, 3, 1)
    assert standing(battery(), last - timedelta(days=ENDING_DAYS + 1), ODO).state == "in_force"
    soon = standing(battery(), last - timedelta(days=ENDING_DAYS), ODO)
    assert (soon.state, soon.end_day, soon.by) == ("ending", last, "date")
    assert standing(battery(), last, ODO).state == "ending"
    gone = standing(battery(), last + timedelta(days=1), ODO)
    assert (gone.state, gone.end_day, gone.by) == ("ended", last, "date")


def test_ending_by_miles_at_the_rate_driven():
    term = battery(months=None, miles=20_000)          # ends at 70,000 mi
    reached = ODO.day_at(70_000)
    assert standing(term, reached - timedelta(days=61), ODO).state == "in_force"
    soon = standing(term, reached - timedelta(days=60), ODO)
    assert (soon.state, soon.by, soon.end_miles) == ("ending", "miles", 70_000)
    gone = standing(term, reached, ODO)
    assert (gone.state, gone.end_day, gone.by) == ("ended", reached, "miles")


def test_the_sooner_of_date_and_miles_ends_it():
    term = battery(miles=10_000)                        # 60,000 mi comes in about 10 months, long before 2028
    found = standing(term, date(2025, 6, 1), ODO)
    assert (found.by, found.end_day) == ("miles", ODO.day_at(60_000))
    assert found.ends_on == date(2028, 3, 1)


def test_lifetime_never_ends_by_itself():
    found = standing(battery(months=None), date(2070, 1, 1), ODO)
    assert (found.state, found.end_day, found.by) == ("in_force", None, "")


# ---------- Asking about later visits ----------


def test_asks_about_a_later_visit_that_replaced_a_covered_part():
    later = visit(20, date(2026, 9, 20), "battery_12v", "engine_oil")
    assert to_ask(battery(), [later], {}, ODO) == later


def test_never_its_own_visit_the_same_day_an_inspection_other_work_or_after_it_ended():
    own = visit(10, date(2025, 5, 1), "battery_12v")
    same_day = visit(11, START, "battery_12v")
    oil = visit(12, date(2025, 9, 1), "engine_oil")
    after = visit(13, date(2028, 4, 1), "battery_12v")
    assert replacing(battery(), [own, same_day, oil, after], ODO) == []
    other = battery(codes=frozenset({"other"}))
    assert to_ask(other, [visit(14, date(2026, 1, 1), "other")], {}, ODO) is None


def test_procedures_never_ask_since_only_replacements_count():
    rotations = battery(codes=frozenset({"tire_rotation"}), months=None)
    # A visit's ``replaced`` holds only what it replaced; a rotation is performed, so it's never there.
    assert to_ask(rotations, [visit(20, date(2026, 1, 1))], {}, ODO) is None


def test_whole_car_warranties_never_ask():
    car = battery(codes=frozenset(), whole_car=True, event_id=None)
    assert to_ask(car, [visit(20, date(2026, 1, 1), "battery_12v")], {}, ODO) is None


def test_the_earliest_unanswered_first_and_claimed_keeps_it():
    first, second = visit(20, date(2026, 1, 5), "battery_12v"), visit(21, date(2027, 2, 1), "battery_12v")
    assert to_ask(battery(), [second, first], {}, ODO) == first
    assert to_ask(battery(), [second, first], {20: "claimed"}, ODO) == second
    assert to_ask(battery(), [second, first], {20: "claimed", 21: "claimed"}, ODO) is None
    assert standing(battery(), date(2027, 6, 1), ODO, [first, second], {20: "claimed", 21: "claimed"}).state == "in_force"


def test_paid_ends_it_that_day_and_nothing_after_is_asked():
    first, second = visit(20, date(2026, 1, 5), "battery_12v"), visit(21, date(2027, 2, 1), "battery_12v")
    found = standing(battery(), date(2026, 6, 1), ODO, [first, second], {20: "paid"})
    assert (found.state, found.end_day, found.by, found.paid) == ("ended", date(2026, 1, 5), "paid", first)
    assert to_ask(battery(), [first, second], {20: "paid"}, ODO) is None
