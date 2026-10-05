"""Inspection and registration records, and the receipts that show an inspection."""

from __future__ import annotations

import sqlite3

import pytest
import report_fixtures as rf  # tests/ is on pytest's path

from amg.repo import renewals, vehicles
from amg.repo.renewals import RenewalInput


@pytest.fixture
def car(conn):
    return rf.car(conn, "Outback")


def test_round_trip(conn, car):
    renewal_id = renewals.create(conn, car, RenewalInput("registration", "2027-10-31", "2026-10-02", 4_075, "Online"))
    row = renewals.get(conn, renewal_id)
    assert (row["kind"], row["done_on"], row["expires_on"], row["cost_cents"], row["note"]) == (
        "registration", "2026-10-02", "2027-10-31", 4_075, "Online")
    renewals.update(conn, renewal_id, RenewalInput("safety", "2028-10-31", None, None, ""))
    row = renewals.get(conn, renewal_id)
    assert (row["kind"], row["done_on"], row["expires_on"], row["cost_cents"]) == ("registration", None, "2028-10-31", None)
    renewals.delete(conn, renewal_id)
    assert renewals.get(conn, renewal_id) is None


def test_refused(conn, car):
    with pytest.raises(ValueError, match="Unknown kind"):
        renewals.create(conn, car, RenewalInput("insurance", "2027-01-31"))
    with pytest.raises(ValueError, match="expire before"):
        renewals.create(conn, car, RenewalInput("safety", "2026-01-31", "2026-02-01"))
    with pytest.raises(sqlite3.IntegrityError):    # the table holds the line too
        conn.execute("INSERT INTO renewals (vehicle_id, kind, done_on, expires_on, created_at, updated_at)"
                     " VALUES (?, 'safety', '2026-02-01', '2026-01-31', 'now', 'now')", (car,))


def test_newest_first_by_kind(conn, car):
    other = rf.car(conn, "Civic")
    renewals.create(conn, car, RenewalInput("safety", "2026-09-30"))
    renewals.create(conn, car, RenewalInput("safety", "2027-09-30"))
    renewals.create(conn, car, RenewalInput("safety", "2025-09-30"))
    renewals.create(conn, car, RenewalInput("registration", "2027-03-31"))
    renewals.create(conn, other, RenewalInput("emissions", "2027-03-31"))
    found = renewals.for_car(conn, car)
    assert sorted(found) == ["registration", "safety"]
    assert [row["expires_on"] for row in found["safety"]] == ["2027-09-30", "2026-09-30", "2025-09-30"]


def test_the_latest_inspection_on_a_receipt(conn, car):
    rf.visit(conn, car, "2025-09-03", shop="Corner Garage",
             lines=[rf.line("State inspection", 2_000, "state_inspection", action="perform")])
    newest = rf.visit(conn, car, "2026-09-02", shop="Midas",
                      lines=[rf.line("Oil change", 5_000, "engine_oil"),
                             rf.line("State inspection", 2_000, "state_inspection", action="perform"),
                             rf.line("Sticker fee", 50, "state_inspection", action="perform", kind="fee")])
    rf.visit(conn, car, "2026-10-01", shop="Midas", confirmed=False,   # waiting to be checked: not yet
             lines=[rf.line("State inspection", 2_000, "state_inspection", action="perform")])
    rf.visit(conn, rf.car(conn, "Civic"), "2026-10-02",
             lines=[rf.line("State inspection", 2_000, "state_inspection", action="perform")])
    found = renewals.latest_service(conn, car, "state_inspection")
    assert (found["id"], found["performed_on"], found["shop"], found["cost_cents"]) == (newest, "2026-09-02", "Midas", 2_050)
    assert renewals.latest_service(conn, car, "emissions_test") is None


def test_an_inspection_line_with_no_amount(conn, car):
    rf.visit(conn, car, "2026-09-02", source="attested",
             lines=[rf.line("Emissions test", None, "emissions_test", action="perform")])
    assert renewals.latest_service(conn, car, "emissions_test")["cost_cents"] is None


def test_everything_for_the_export(conn, car):
    service = rf.visit(conn, car, "2026-09-02", shop="Midas",
                       lines=[rf.line("State inspection", 2_000, "state_inspection", action="perform")])
    renewals.create(conn, car, RenewalInput("registration", "2027-03-31"))
    renewals.create(conn, car, RenewalInput("safety", "2027-09-30", "2026-09-02", 2_000, service_event_id=service))
    renewals.create(conn, car, RenewalInput("safety", "2026-09-30"))
    vehicles.archive(conn, car)
    rows = renewals.everything(conn)
    assert [(r["car_name"], r["kind"], r["expires_on"]) for r in rows] == [
        ("Outback", "safety", "2026-09-30"), ("Outback", "safety", "2027-09-30"), ("Outback", "registration", "2027-03-31")]
    assert (rows[1]["service_on"], rows[1]["service_shop"]) == ("2026-09-02", "Midas")
