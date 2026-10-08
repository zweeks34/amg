"""Which shop recommendations are still open: a later service doing the work closes one, and so do you."""

from __future__ import annotations

from datetime import date

from amg.engine.follow_ups import Outcome, Recommendation, follow
from amg.engine.schedule import Service

MAR_3 = date(2026, 3, 3)
DEFAULTS = {"brake_pads": "replace", "brake_fluid": "replace", "multipoint_inspection": "inspect"}


def rec(*codes, day=MAR_3, event_id=1, key="rear brake pads"):
    return Recommendation(receipt_id=10, event_id=event_id, day=day, shop="Main St Subaru",
                          description="Rear brake pads, 3 mm left", codes=codes, quoted_cents=28_000, key=key)


def visit(id, day, **coverage):
    return Service(id, day, None, {code: frozenset({action}) for code, action in coverage.items()})


def only(recommendation, *visits, outcomes=None):
    (found,) = follow([recommendation], list(visits), DEFAULTS, outcomes or {})
    return found


def test_a_later_replacement_closes_it():
    found = only(rec("brake_pads"), visit(2, date(2026, 4, 1), brake_pads="replace"))
    assert not found.open and found.done_by.id == 2


def test_a_later_inspection_isnt_the_work():
    assert only(rec("brake_pads"), visit(2, date(2026, 4, 1), brake_pads="inspect")).open


def test_an_inspection_closes_one_for_a_type_you_only_inspect():
    assert not only(rec("multipoint_inspection"), visit(2, date(2026, 4, 1), multipoint_inspection="inspect")).open


def test_the_same_visit_or_an_earlier_one_doesnt_count():
    assert only(rec("brake_pads"), visit(1, MAR_3, brake_pads="replace"),
                visit(2, date(2026, 2, 1), brake_pads="replace")).open


def test_another_visit_the_same_day_counts():
    assert not only(rec("brake_pads"), visit(2, MAR_3, brake_pads="replace")).open


def test_one_with_no_services_stays_open_until_you_close_it():
    assert only(rec(), visit(2, date(2026, 4, 1), brake_pads="replace")).open
    closed = only(rec(), outcomes={(10, "rear brake pads"): Outcome("skipped", None)})
    assert not closed.open and closed.skipped


def test_yours_wins():
    found = only(rec("brake_pads"), visit(2, date(2026, 4, 1), brake_pads="replace"),
                 outcomes={(10, "rear brake pads"): Outcome("skipped", None)})
    assert found.skipped and not found.open


def test_the_first_service_to_do_it_is_the_one():
    found = only(rec("brake_pads", "brake_fluid"), visit(3, date(2026, 6, 1), brake_pads="replace"),
                 visit(2, date(2026, 4, 1), brake_fluid="replace"))
    assert found.done_by.id == 2
