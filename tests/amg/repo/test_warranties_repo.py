"""Warranties in the database: yours, the ones a receipt's draft writes, and the visits they're judged against."""

from __future__ import annotations

from datetime import date

import pytest
import report_fixtures as rf  # tests/ is on pytest's path

from amg.repo import receipts, services, warranties
from amg.repo.warranties import WarrantyInput


@pytest.fixture
def car(conn):
    return rf.car(conn, "Civic")


def _answer(conn, warranty_id, event_id, answer="claimed"):
    conn.execute("INSERT INTO warranty_answers (warranty_id, event_id, answer, created_at) VALUES (?, ?, ?, 'now')",
                 (warranty_id, event_id, answer))


def test_create_update_and_delete_with_covers(conn, car):
    made = warranties.create(conn, car, WarrantyInput(
        "Battery free replacement", "2025-03-01", provider="Costco", start_miles=50_000, months=36,
        codes=["battery_12v", "nonsense"], details="Keep the receipt"))
    row = warranties.get(conn, made)
    assert (row["title"], row["provider"], row["starts_on"], row["start_miles"], row["months"], row["miles"]) == (
        "Battery free replacement", "Costco", "2025-03-01", 50_000, 36, None)
    assert row["codes"] == ["battery_12v"] and row["answers"] == {} and not row["whole_car"]
    assert row["receipt_id"] is None and row["details"] == "Keep the receipt"

    warranties.update(conn, made, WarrantyInput("Basic", "2024-01-15", provider="Honda", start_miles=0, months=36,
                                                 miles=36_000, whole_car=True, codes=["battery_12v"]))
    row = warranties.get(conn, made)
    assert (row["title"], row["months"], row["miles"], row["whole_car"], row["codes"]) == ("Basic", 36, 36_000, 1, [])
    assert [w["id"] for w in warranties.for_car(conn, car)] == [made]

    warranties.delete(conn, made)
    assert warranties.get(conn, made) is None


def _receipt(conn, car, rows, **fields):
    """A receipt confirmed onto the car with these warranty rows in its draft; returns (receipt id, event id)."""
    receipt_id, event = rf.receipt(conn, car, rf.pdf_bytes(f"receipt {fields}"), "costco.pdf", confirm=False,
                                   shop_name="Costco", date="2025-03-01", odometer=50_000, **fields)
    draft = receipts.get(conn, receipt_id)["draft"]
    draft.warranties = rows
    return receipt_id, receipts.confirm(conn, receipt_id, draft, car)


def _row(description="36-month free replacement", months=36, miles=None, codes=("battery_12v",), **fields):
    return {"description": description, "provider": "", "months": months, "miles": miles, "lifetime": False,
            "codes": list(codes), "found": "", **fields}


def test_confirming_a_receipt_writes_its_warranties_and_saving_again_keeps_their_rows(conn, car):
    receipt_id, event = _receipt(conn, car, [_row(), _row("Road hazard", months=None, miles=50_000,
                                                          codes=("tires", "tire_repair"))])
    found = {w["title"]: w for w in warranties.for_car(conn, car)}
    battery = found["36-month free replacement"]
    assert (battery["receipt_id"], battery["service_event_id"], battery["starts_on"], battery["start_miles"]) == (
        receipt_id, event, "2025-03-01", 50_000)
    assert found["Road hazard"]["codes"] == ["tires", "tire_repair"]
    _answer(conn, battery["id"], event)

    draft = receipts.get(conn, receipt_id)["draft"]
    draft.warranties = [_row(months=48, provider="Interstate")]     # the same wording, new terms; road hazard gone
    receipts.confirm(conn, receipt_id, draft, car)
    [kept] = warranties.for_car(conn, car)
    assert (kept["id"], kept["months"], kept["provider"], kept["answers"]) == (battery["id"], 48, "Interstate",
                                                                               {event: "claimed"})


def test_repeated_wording_and_found_rows(conn, car):
    receipt_id, _ = _receipt(conn, car, [_row("Limited warranty"), _row("Limited warranty", months=12,
                                                                        codes=("brake_pads",)),
                                         _row("Lifetime pads", months=None, lifetime=True, found="2026-10-09")])
    rows = conn.execute("SELECT phrase, months FROM warranties WHERE receipt_id = ? ORDER BY id", (receipt_id,))
    assert [tuple(r) for r in rows] == [("limited warranty", 36), ("limited warranty 2", 12)]


def test_a_lifetime_row_stores_no_months_or_miles(conn, car):
    _receipt(conn, car, [_row("Lifetime brake pads", months=12, lifetime=True, codes=("brake_pads",))])
    [row] = warranties.for_car(conn, car)
    assert (row["months"], row["miles"]) == (None, None)


def test_moving_the_receipt_to_another_car_moves_them(conn, car):
    other = rf.car(conn, "Outback")
    receipt_id, _ = _receipt(conn, car, [_row()])
    receipts.confirm(conn, receipt_id, receipts.get(conn, receipt_id)["draft"], other)
    assert warranties.for_car(conn, car) == [] and len(warranties.for_car(conn, other)) == 1


def test_deleting_a_receipts_service_takes_its_warranties(conn, car):
    receipt_id, event = _receipt(conn, car, [_row()])
    receipts.release_event(conn, event)
    services.delete_event(conn, event)
    assert warranties.for_car(conn, car) == [] and receipts.get(conn, receipt_id)["status"] == "read"


def test_deleting_the_visit_it_came_with_keeps_it_and_an_answered_visit_drops_the_answer(conn, car):
    fitted = rf.visit(conn, car, "2025-03-01", source="diy", lines=[rf.line("Battery", 18_000, "battery_12v")])
    later = rf.visit(conn, car, "2026-01-05", shop="Valley Honda", lines=[rf.line("Battery", 0, "battery_12v")])
    made = warranties.create(conn, car, WarrantyInput("Battery", "2025-03-01", months=36, codes=["battery_12v"],
                                                      event_id=fitted))
    _answer(conn, made, later)
    services.delete_event(conn, later)
    assert warranties.get(conn, made)["answers"] == {}
    services.delete_event(conn, fitted)
    row = warranties.get(conn, made)
    assert (row["service_event_id"], row["starts_on"]) == (None, "2025-03-01")


def test_visits_leave_out_attested_and_unconfirmed_services_and_list_only_replacements(conn, car):
    shop = rf.visit(conn, car, "2026-01-05", shop="Valley Honda", odometer=60_000,
                    lines=[rf.line("Battery", 20_000, "battery_12v"),
                           rf.line("Rotate", 3_000, "tire_rotation", action="perform"),
                           rf.line("Check brakes", 0, "brake_pads", action="inspect")])
    rf.visit(conn, car, "2026-02-01", source="attested", lines=[rf.line("Battery", None, "battery_12v")])
    rf.visit(conn, car, "2026-03-01", shop="Draft", confirmed=False, lines=[rf.line("Battery", 1, "battery_12v")])
    [visit] = warranties.visits(conn, car)
    assert (visit.id, visit.day, visit.shop, visit.odometer, visit.replaced) == (
        shop, date(2026, 1, 5), "Valley Honda", 60_000, frozenset({"battery_12v"}))


def test_deleting_the_car_takes_its_warranties(conn, car):
    warranties.create(conn, car, WarrantyInput("Basic", "2024-01-15", months=36, whole_car=True))
    conn.execute("DELETE FROM vehicles WHERE id = ?", (car,))   # cars are archived, not deleted; the cascade still holds
    assert conn.execute("SELECT count(*) FROM warranties").fetchone()[0] == 0


def test_everything_names_the_car(conn, car):
    warranties.create(conn, car, WarrantyInput("Basic", "2024-01-15", months=36, whole_car=True))
    [row] = warranties.everything(conn)
    assert row["car_name"] == "Civic" and row["codes"] == []
