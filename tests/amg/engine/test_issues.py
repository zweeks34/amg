"""Which visit an issue asks about."""

from __future__ import annotations

from datetime import date

from amg.engine.issues import Visit, since, to_ask

NOTICED = date(2026, 9, 2)
BEFORE = Visit(1, date(2026, 8, 20), "Midas")
SAME_DAY = Visit(2, date(2026, 9, 2), "Valley Honda")
LATER = Visit(3, date(2026, 9, 20), "")


def test_asks_about_the_newest_visit_since_it_was_noticed():
    assert to_ask(NOTICED, [BEFORE, SAME_DAY, LATER], set()) == LATER
    assert since(NOTICED, [LATER, BEFORE, SAME_DAY]) == [LATER, SAME_DAY]


def test_a_visit_the_same_day_counts():
    assert to_ask(NOTICED, [BEFORE, SAME_DAY], set()) == SAME_DAY


def test_never_a_visit_before_it_was_noticed():
    assert to_ask(NOTICED, [BEFORE], set()) is None
    assert to_ask(NOTICED, [], set()) is None


def test_quiet_once_you_said_it_was_still_there_after_the_newest():
    assert to_ask(NOTICED, [SAME_DAY, LATER], {LATER.id}) is None


def test_asks_again_after_a_newer_visit():
    newer = Visit(4, date(2026, 10, 1), "Corner Garage")
    assert to_ask(NOTICED, [SAME_DAY, LATER, newer], {LATER.id}) == newer


def test_two_visits_the_same_day_newest_logged_first():
    other = Visit(5, LATER.day, "Tire shop")
    assert to_ask(NOTICED, [LATER, other], set()) == other
