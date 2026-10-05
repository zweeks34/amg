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
