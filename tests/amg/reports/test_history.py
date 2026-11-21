"""The History report: the lines a service filter shows, what's counted, and what the visits came to."""

from __future__ import annotations

import report_fixtures as rf  # tests/ is on pytest's path

from amg.reports import history
from amg.reports.filters import Filters


def by_id(report, visit_id):
    return next(visit for visit in report.visits if visit["id"] == visit_id)


def test_the_whole_history(conn):
    ids = rf.garage(conn)
    report = history.load(conn, Filters())
    assert report.count == 5 and not report.by_service
    assert (report.first, report.last) == ("2019-03-04", "2024-05-05")
    # $270 printed, $40 and $30 with no total (their lines), $300, and nothing for "done, no receipt"
    assert report.paid_cents == 27_000 + 4_000 + 3_000 + 30_000
    first = by_id(report, ids["v1"])
    assert first["who"] == "Midas #1234" and first["car_name"] == "Outback"
    assert [line["description"] for line in first["shown"]] == ["Front brake pads", "Oil and filter change"]
    assert first["others"] == 0 and first["paid"] == 27_000
    assert by_id(report, ids["v4"])["paid"] is None and by_id(report, ids["v2"])["who"] == "Your own work"


def test_a_service_shows_its_lines_and_counts_the_rest(conn):
    ids = rf.garage(conn)
    report = history.load(conn, Filters(service="category:Brakes"))
    assert report.by_service
    first = by_id(report, ids["v1"])
    assert [line["description"] for line in first["shown"]] == ["Front brake pads"]
    assert (first["others"], first["others_cents"], first["matched_cents"]) == (1, 5_000, 20_000)
    assert report.matched_cents == 20_000 + 30_000      # the pads and the Civic's rotors; the fluid had no amount
    assert report.paid_cents == 27_000 + 30_000         # what those visits came to, whole


def test_a_line_covering_two_types_shows_once(conn):
    car = rf.car(conn, "Outback")
    rf.visit(conn, car, "2020-01-01", lines=[rf.line("Brakes and rotation", 9_000, "brake_pads", "tire_rotation")])
    report = history.load(conn, Filters(service="category:Brakes"))
    assert len(report.visits[0]["shown"]) == 1 and report.matched_cents == 9_000


def test_what_a_visit_paid():
    def visit(total=None, tax=None, *amounts):
        return {"total_cents": total, "tax_cents": tax, "lines": [{"amount_cents": a} for a in amounts]}

    assert history.paid(visit(5_000, 300, 4_000)) == 5_000       # the total wins
    assert history.paid(visit(None, 300, 4_000, None)) == 4_300  # lines and tax
    assert history.paid(visit(None, None, None)) is None         # nothing to go on
    assert history.paid(visit(0)) == 0                           # free is a price


# ---------- Years, the gap since the visit before, the main category ----------


def test_visits_by_year_newest_first(conn):
    rf.garage(conn)
    years = history.load(conn, Filters()).years()
    assert [(y["year"], y["count"], y["paid"]) for y in years] == [
        ("2024", 1, 0), ("2023", 1, 3_000), ("2021", 2, 34_000), ("2019", 1, 27_000)]


def test_a_years_paid_is_the_matching_lines_when_narrowed(conn):
    rf.garage(conn)
    years = history.load(conn, Filters(service="category:Brakes")).years()
    assert [(y["year"], y["paid"]) for y in years] == [("2024", 0), ("2021", 30_000), ("2019", 20_000)]


def test_each_visit_says_how_long_after_the_one_before_for_its_car(conn):
    ids = rf.garage(conn)
    report = history.load(conn, Filters())
    assert by_id(report, ids["v1"])["since"] == ""                     # the Outback's first
    assert by_id(report, ids["v2"])["since"] == "2 yr 2 mo"            # no odometer on v2, so no miles
    assert by_id(report, ids["v3"])["since"] == "19 mo"
    assert by_id(report, ids["v6"])["since"] == ""                     # the Civic's first: the Outback's don't count


def test_since_counts_the_miles_when_both_say():
    earlier = {"performed_on": "2025-01-10", "odometer": 40_000}
    assert history.since_words(earlier, {"performed_on": "2025-07-10", "odometer": 45_210}) == "+5,210 mi · 6 mo"
    assert history.since_words(earlier, {"performed_on": "2025-07-09", "odometer": None}) == "5 mo"
    assert history.since_words(earlier, {"performed_on": "2025-02-01", "odometer": 39_000}) == "3 wk"  # a lower reading: no miles
    assert history.since_words(earlier, {"performed_on": "2025-01-10", "odometer": None}) == "same day"
    assert history.since_words(earlier, {"performed_on": "2025-01-11", "odometer": None}) == "1 day"


def test_narrowed_the_one_before_is_the_one_before_that_matched(conn):
    ids = rf.garage(conn)
    report = history.load(conn, Filters(service="category:Brakes"))
    assert by_id(report, ids["v4"])["since"] == "5 yr 2 mo"            # back to v1's brakes, past the oil and tires


def test_the_main_category_is_where_most_of_the_money_went(conn):
    ids = rf.garage(conn)
    report = history.load(conn, Filters())
    first = by_id(report, ids["v1"])                                   # $200 of brakes, $50 of oil
    assert (first["main"], first["tone"]) == ("Brakes", "2")
    assert by_id(report, ids["v4"])["main"] == "Brakes"                # no amounts: the first line's
    assert history.main_category([{"covers": [], "amount_cents": 500}]) is None
