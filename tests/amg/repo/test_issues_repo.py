"""Issues in the database: their photos, closing and reopening, and the visits they were still there after."""

from __future__ import annotations

from io import BytesIO

import pytest
import report_fixtures as rf  # tests/ is on pytest's path
from PIL import Image

from amg.repo import documents, issues, services
from amg.repo.issues import IssueInput

RATTLE = IssueInput("Rattle at 40 mph", "From the front, warm or cold", "2026-09-02")


def photo(conn, colour):
    out = BytesIO()
    Image.new("RGB", (60, 40), colour).save(out, "PNG")
    return documents.store(conn, out.getvalue(), f"{colour}.png")[0]["id"]


@pytest.fixture
def car(conn):
    return rf.car(conn, "Civic")


def test_create_update_and_delete_with_photos_in_order(conn, car):
    red, green, blue = (photo(conn, colour) for colour in ("red", "green", "blue"))
    issue = issues.create(conn, car, RATTLE, [red, green])
    row = issues.get(conn, issue)
    assert (row["title"], row["details"], row["noticed_on"], row["status"]) == (
        "Rattle at 40 mph", "From the front, warm or cold", "2026-09-02", "open")
    assert [p["id"] for p in row["photos"]] == [red, green] and row["checks"] == []

    issues.update(conn, issue, IssueInput("Rattle at 45 mph", "", "2026-09-03"), [blue, red])
    row = issues.get(conn, issue)
    assert (row["title"], row["details"], row["noticed_on"]) == ("Rattle at 45 mph", "", "2026-09-03")
    assert [p["id"] for p in row["photos"]] == [blue, red]

    issues.delete(conn, issue)
    assert issues.get(conn, issue) is None and documents.get(conn, green) is not None   # the files stay


def test_ten_photos_at_most(conn, car):
    ids = [photo(conn, f"#{n:02x}0000") for n in range(11)]
    with pytest.raises(ValueError, match="up to 10"):
        issues.create(conn, car, RATTLE, ids)
    assert issues.for_car(conn, car) == []


def test_fix_drop_and_reopen(conn, car):
    issue = issues.create(conn, car, RATTLE)
    visit = rf.visit(conn, car, "2026-09-20", shop="Valley Honda", lines=[rf.line("Heat shield clamp", 4_000)])
    issues.fix(conn, issue, "2026-09-20", visit)
    row = issues.get(conn, issue)
    assert (row["status"], row["closed_on"], row["fixed_by_event_id"], row["fixed_shop"]) == (
        "fixed", "2026-09-20", visit, "Valley Honda")
    assert [r["id"] for r in issues.fixed_by(conn, visit)] == [issue]

    issues.reopen(conn, issue)
    row = issues.get(conn, issue)
    assert (row["status"], row["closed_on"], row["fixed_by_event_id"]) == ("open", None, None)

    issues.drop(conn, issue, "2026-10-08")
    assert (issues.get(conn, issue)["status"], issues.get(conn, issue)["closed_on"]) == ("dropped", "2026-10-08")


def test_still_there_is_kept_and_a_fix_by_the_same_visit_replaces_it(conn, car):
    issue = issues.create(conn, car, RATTLE)
    first = rf.visit(conn, car, "2026-09-20", shop="Valley Honda", lines=[rf.line("Looked for rattle", 0)])
    second = rf.visit(conn, car, "2026-10-01", lines=[rf.line("Clamp", 500, kind="part")])
    issues.still_there(conn, issue, second)
    issues.still_there(conn, issue, first)
    issues.still_there(conn, issue, first)        # answered twice: kept once
    assert [(c["event_id"], c["shop"]) for c in issues.get(conn, issue)["checks"]] == [
        (first, "Valley Honda"), (second, "")]     # oldest first
    issues.fix(conn, issue, "2026-10-01", second)
    assert [c["event_id"] for c in issues.get(conn, issue)["checks"]] == [first]


def test_deleting_the_fixing_service_keeps_the_fix_and_its_date(conn, car):
    issue = issues.create(conn, car, RATTLE)
    visit = rf.visit(conn, car, "2026-09-20", shop="Valley Honda", lines=[rf.line("Clamp", 4_000)])
    issues.fix(conn, issue, "2026-09-20", visit)
    services.delete_event(conn, visit)
    row = issues.get(conn, issue)
    assert (row["status"], row["closed_on"], row["fixed_by_event_id"], row["fixed_service_on"]) == (
        "fixed", "2026-09-20", None, None)


def test_deleting_a_service_takes_its_check(conn, car):
    issue = issues.create(conn, car, RATTLE)
    visit = rf.visit(conn, car, "2026-09-20", shop="Valley Honda", lines=[rf.line("Looked", 0)])
    issues.still_there(conn, issue, visit)
    services.delete_event(conn, visit)
    assert issues.get(conn, issue)["checks"] == []


def test_visits_are_confirmed_services_you_or_a_shop_did(conn, car):
    shop = rf.visit(conn, car, "2026-09-20", shop="Valley Honda", lines=[rf.line("Oil", 5_000)])
    mine = rf.visit(conn, car, "2026-09-20", source="diy", lines=[rf.line("Wipers", 2_000)])
    rf.visit(conn, car, "2026-09-25", source="attested", lines=[rf.line("Brake fluid", None)])
    rf.visit(conn, car, "2026-09-26", shop="Midas", confirmed=False, lines=[rf.line("Pads", 9_000)])
    assert [v.id for v in issues.visits(conn, car)] == [mine, shop]


def test_open_ones_first_and_counts_for_the_garage(conn, car):
    older = issues.create(conn, car, IssueInput("Squeak", "", "2026-08-01"))
    newer = issues.create(conn, car, RATTLE)
    dropped = issues.create(conn, car, IssueInput("Smell", "", "2026-07-01"))
    issues.drop(conn, dropped, "2026-07-10")
    assert [r["id"] for r in issues.for_car(conn, car)] == [newer, older, dropped]
    other = rf.car(conn, "Outback")
    assert issues.open_counts(conn) == {car: 2}
    assert issues.for_car(conn, other) == []


def test_a_car_gone_from_the_database_takes_its_issues(conn, car):
    issue = issues.create(conn, car, RATTLE, [photo(conn, "red")])
    conn.execute("DELETE FROM vehicles WHERE id = ?", (car,))     # AMG only archives cars; this is the database
    assert issues.get(conn, issue) is None
    assert conn.execute("SELECT count(*) FROM issue_photos").fetchone()[0] == 0
