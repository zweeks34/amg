"""Warranties on the car's page, the form you add your own with, a receipt's Warranties block, the question a
later visit asks, and the notes on recommendations and the sheet for the shop."""

from __future__ import annotations

import html
import json
import re
from datetime import date, timedelta

import pytest
import receipt_fixtures as fx  # tests/ is on pytest's path
import report_fixtures as rf
from schedule_fixtures import steady_car

from amg.engine.schedule import add_months
from amg.ingest.receipts import Recommendation
from amg.repo import odometer, receipts, vehicles, warranties
from amg.repo.warranties import WarrantyInput
from amg.web import status
from amg.web.recalls import day_words


@pytest.fixture
def car(conn):
    return rf.car(conn, "Civic", year=2019, make="Honda", model="Civic", in_service_date="2019-04-15")


def page(signed_in, url):
    return html.unescape(signed_in.get(url).text)


def _add(signed_in, car, codes=("battery_12v",), **fields):
    data = {"title": "Battery free replacement", "provider": "Costco", "covers": "parts", "starts_on": "2025-03-01",
            "start_miles": "50,000", "length": "3", "unit": "years", "miles": "", "details": "", "event_id": "",
            **fields}
    return signed_in.post(f"/vehicles/{car}/warranties", data={**data, "code": list(codes)}, follow_redirects=False)


# ---------- Adding your own ----------


def test_the_empty_section_and_the_form(signed_in, car):
    text = page(signed_in, f"/vehicles/{car}")
    assert 'id="warranties"' in text and "No warranties yet." in text
    assert f'href="/vehicles/{car}/warranties/new"' in text
    form = page(signed_in, f"/vehicles/{car}/warranties/new")
    assert "Add a warranty" in form and "The whole car" in form and "Lifetime" in form and "Save warranty" in form
    assert "From the in-service date, 2019-04-15" in form and f'value="{date.today().isoformat()}"' in form


def test_adding_a_part_warranty(signed_in, conn, car):
    start = date.today() - timedelta(days=30)
    response = _add(signed_in, car, starts_on=start.isoformat())
    assert response.status_code == 303 and response.headers["location"] == f"/vehicles/{car}#warranties"
    [row] = warranties.for_car(conn, car)
    assert (row["title"], row["provider"], row["months"], row["start_miles"], row["codes"]) == (
        "Battery free replacement", "Costco", 36, 50_000, ["battery_12v"])
    text = page(signed_in, f"/vehicles/{car}")
    assert "Battery free replacement" in text and "· Costco" in text
    assert "12-volt battery · 3 years" in text and re.search(r"about 2 years 1[01] months left", text)
    assert f"Until {day_words(add_months(start, 36).isoformat())}" in text
    assert f'href="/warranties/{row["id"]}/edit"' in text


def test_adding_the_whole_car_from_the_in_service_date(signed_in, conn, car):
    _add(signed_in, car, codes=(), title="Basic", provider="Honda", covers="whole", starts_on="2019-04-15",
         start_miles="0", length="3", miles="36,000")
    [row] = warranties.for_car(conn, car)
    assert (row["whole_car"], row["months"], row["miles"], row["codes"]) == (1, 36, 36_000, [])
    text = page(signed_in, f"/vehicles/{car}")
    assert "None in force." in text and "1 ended" in text and "Ended Apr 15, 2022" in text


def test_lifetime_and_months(signed_in, conn, car):
    _add(signed_in, car, codes=("brake_pads",), title="Pads for life", lifetime="1", length="")
    _add(signed_in, car, title="Alternator", length="18", unit="months", codes=("other",), starts_on=date.today().isoformat())
    rows = {w["title"]: w for w in warranties.for_car(conn, car)}
    assert (rows["Pads for life"]["months"], rows["Pads for life"]["miles"]) == (None, None)
    assert rows["Alternator"]["months"] == 18
    text = page(signed_in, f"/vehicles/{car}")
    assert "Brake pads · Lifetime" in text and "For as long as you own the car" in text
    assert "Other repair · 18 months" in text


@pytest.mark.parametrize("fields, codes, field, message", [
    ({"title": ""}, ("battery_12v",), "title", "Name it, such as Powertrain or Battery free replacement."),
    ({"length": "", "miles": ""}, ("battery_12v",), "length", "Say how long it lasts: years or months, miles, or lifetime."),
    ({}, (), "codes", "Choose what it covers, such as 12-volt battery, or choose The whole car."),
    ({"starts_on": ""}, ("battery_12v",), "starts_on", "Enter the day it started."),
    ({"starts_on": "2999-01-01"}, ("battery_12v",), "starts_on", "That date is in the future."),
    ({"length": "three"}, ("battery_12v",), "length", "Enter a whole number, like 3."),
    ({"length": "60", "unit": "years"}, ("battery_12v",), "length", "That's more than 50 years. Check for an extra digit."),
    ({"miles": "lots"}, ("battery_12v",), "miles", "Enter whole miles, like 32,610."),
])
def test_the_forms_refusals(signed_in, conn, car, fields, codes, field, message):
    response = _add(signed_in, car, codes=codes, **fields)
    assert response.status_code == 422 and message in html.unescape(response.text)
    assert f'id="f-{field}-error"' in response.text
    assert warranties.for_car(conn, car) == []


def test_codes_come_back_with_an_error(signed_in, car):
    response = _add(signed_in, car, codes=("battery_12v", "brake_pads"), title="")
    assert '"codes": ["battery_12v", "brake_pads"]' in html.unescape(response.text)


def test_edit_and_delete(signed_in, conn, car):
    _add(signed_in, car)
    [row] = warranties.for_car(conn, car)
    form = page(signed_in, f"/warranties/{row['id']}/edit")
    assert "Edit warranty" in form and 'value="Battery free replacement"' in form and 'value="3"' in form
    assert "Delete warranty" in form
    _add_to = signed_in.post(f"/warranties/{row['id']}/edit", data={
        "title": "Battery", "provider": "", "covers": "parts", "code": ["battery_12v"], "starts_on": "2025-03-01",
        "start_miles": "", "length": "48", "unit": "months", "miles": "", "details": "Receipt in the glovebox",
        "event_id": ""}, follow_redirects=False)
    assert _add_to.status_code == 303
    row = warranties.get(conn, row["id"])
    assert (row["title"], row["months"], row["start_miles"], row["details"]) == ("Battery", 48, None,
                                                                                  "Receipt in the glovebox")
    signed_in.post(f"/warranties/{row['id']}/delete")
    assert warranties.for_car(conn, car) == []


def test_from_a_visit_it_came_with(signed_in, conn, car):
    fitted = rf.visit(conn, car, "2025-03-01", shop="AutoZone", odometer=50_000,
                      lines=[rf.line("Battery", 18_000, "battery_12v"),
                             rf.line("Check", 0, "brake_pads", action="inspect")])
    form = page(signed_in, f"/vehicles/{car}/warranties/new?service={fitted}")
    assert 'value="2025-03-01"' in form and 'value="50,000"' in form and 'value="AutoZone"' in form
    assert '"codes": ["battery_12v"]' in form and f'<option value="{fitted}" selected>' in form
    _add(signed_in, car, event_id=str(fitted), length="30")
    [row] = warranties.for_car(conn, car)
    assert row["service_event_id"] == fitted
    assert f'href="/services/{fitted}">From AutoZone on Mar 1, 2025' in page(signed_in, f"/vehicles/{car}")


def test_ending_soon_and_ended(signed_in, conn, car):
    today = date.today()
    warranties.create(conn, car, WarrantyInput("Basic", (today - timedelta(days=700)).isoformat(), months=24,
                                               whole_car=True))
    warranties.create(conn, car, WarrantyInput("Old battery", "2015-01-01", months=36, codes=["battery_12v"]))
    text = page(signed_in, f"/vehicles/{car}")
    ends = date.fromisoformat((today - timedelta(days=700)).isoformat())
    ends = ends.replace(year=ends.year + 2)
    assert f"Ends in {(ends - today).days} days" in text and "mark--due" in text
    assert "1 ended" in text and "Ended Jan 1, 2018" in text


# ---------- A receipt's warranties ----------


def _editor(text: str) -> dict:
    start = text.index("receiptEditor(") + len("receiptEditor(")
    return json.loads(text[start:text.index(")'", start)])


def _review(conn, car, warranty_rows=(), confirm=False):
    receipt_id, _ = rf.receipt(conn, car, rf.pdf_bytes("Costco battery"), "costco.pdf", confirm=confirm,
                               shop_name="Costco", date="2025-03-01", odometer=50_000,
                               lines=[fx.line("Interstate battery", 180.0, ["battery_12v"])], tax=0, total=180.0,
                               subtotal=180.0, recommendations=[], warranties=list(warranty_rows))
    return receipt_id


def _post(signed_in, receipt_id, car, held, action="confirm"):
    editor = _editor(signed_in.get(f"/receipts/{receipt_id}").text)
    data = {"vehicle_id": str(car), "document_kind": "invoice", "performed_on": "2025-03-01", "odometer": "50,000",
            "shop": "Costco", "invoice_number": "", "printed_vin": "", "printed_plate": "", "printed_vehicle": "",
            "delivery_date": "", "next_service_date": "", "next_service_miles": "", "tax": "0", "total": "180.00",
            "notes": "", "lines_json": json.dumps(editor["lines"]), "recs_json": "[]",
            "warranties_json": json.dumps(held), "action": action}
    return signed_in.post(f"/receipts/{receipt_id}", data=data, follow_redirects=False)


def test_the_review_shows_what_was_read_and_confirming_writes_it(signed_in, conn, car):
    receipt_id = _review(conn, car, [fx.warranty(months=360, provider="Interstate")])   # in force for years yet
    text = page(signed_in, f"/receipts/{receipt_id}")
    assert 'id="warranties"' in text and "Add a warranty" in text
    [held] = _editor(text)["warranties"]
    assert held == {"description": "36-month free replacement", "provider": "Interstate", "months": "360", "miles": "",
                    "lifetime": False, "covers": ["battery_12v"], "found": ""}
    assert _post(signed_in, receipt_id, car, [held]).status_code == 303
    [row] = warranties.for_car(conn, car)
    assert (row["receipt_id"], row["title"], row["provider"], row["starts_on"], row["start_miles"]) == (
        receipt_id, "36-month free replacement", "Interstate", "2025-03-01", 50_000)

    car_page = page(signed_in, f"/vehicles/{car}")
    assert "Edit on the receipt" in car_page and f'href="/receipts/{receipt_id}#warranties"' in car_page
    assert f'href="/receipts/{receipt_id}">From Costco on Mar 1, 2025' in car_page


def test_the_reviews_refusals(signed_in, conn, car):
    receipt_id = _review(conn, car)
    blank = {"description": "Guarantee", "provider": "", "months": "", "miles": "", "lifetime": False,
             "covers": ["battery_12v"]}
    response = _post(signed_in, receipt_id, car, [blank, {**blank, "months": "12", "covers": []},
                                                  {**blank, "months": "x"}])
    assert response.status_code == 422
    errors = _editor(response.text)["warrantyErrors"]
    assert errors == ["Say how long it lasts: months, miles, or lifetime.",
                      "Choose what it covers, such as 12-volt battery.", "Enter whole months, like 6."]
    assert receipts.get(conn, receipt_id)["status"] == "read" and warranties.for_car(conn, car) == []


def test_saving_again_keeps_the_row_and_removing_it_deletes_it(signed_in, conn, car):
    receipt_id = _review(conn, car, [fx.warranty()])
    held = _editor(signed_in.get(f"/receipts/{receipt_id}").text)["warranties"]
    _post(signed_in, receipt_id, car, held)
    [first] = warranties.for_car(conn, car)
    _post(signed_in, receipt_id, car, [{**held[0], "months": "48"}])
    [again] = warranties.for_car(conn, car)
    assert (again["id"], again["months"]) == (first["id"], 48)
    _post(signed_in, receipt_id, car, [])
    assert warranties.for_car(conn, car) == []


def test_a_receipts_warranty_is_changed_on_the_receipt(signed_in, conn, car):
    receipt_id = _review(conn, car, [fx.warranty()], confirm=True)
    [row] = warranties.for_car(conn, car)
    for response in (signed_in.get(f"/warranties/{row['id']}/edit", follow_redirects=False),
                     signed_in.post(f"/warranties/{row['id']}/edit", data={}, follow_redirects=False),
                     signed_in.post(f"/warranties/{row['id']}/delete", follow_redirects=False)):
        assert response.headers["location"] == f"/receipts/{receipt_id}#warranties"
    assert warranties.get(conn, row["id"]) is not None


def test_a_found_warranty_says_so_and_saving_checks_it(signed_in, conn, car):
    receipt_id = _review(conn, car, confirm=True)
    draft = receipts.get(conn, receipt_id)["draft"]
    draft.warranties = [{"description": "3 year replacement", "provider": "", "months": 36, "miles": None,
                         "lifetime": False, "codes": ["battery_12v"], "found": "2026-10-09"}]
    receipts.save_draft(conn, receipt_id, draft, car)
    [held] = _editor(signed_in.get(f"/receipts/{receipt_id}").text)["warranties"]
    assert held["found"] == f"Found {day_words('2026-10-09')}: check it against the scan."
    assert warranties.for_car(conn, car) == []

    _post(signed_in, receipt_id, car, [held])
    assert [w["title"] for w in warranties.for_car(conn, car)] == ["3 year replacement"]
    assert receipts.get(conn, receipt_id)["draft"].warranties[0]["found"] == ""


def test_a_receipt_read_before_warranties_still_opens(signed_in, conn, car):
    receipt_id = _review(conn, car)
    extraction = json.loads(conn.execute("SELECT extraction_json FROM receipts WHERE id = ?",
                                         (receipt_id,)).fetchone()[0])
    del extraction["warranties"]
    conn.execute("UPDATE receipts SET extraction_json = ? WHERE id = ?", (json.dumps(extraction), receipt_id))
    assert signed_in.get(f"/receipts/{receipt_id}").status_code == 200


def test_the_miles_estimate_when_none_was_given(signed_in, conn, car):
    odometer.add(conn, car, "2025-01-01", 48_000)
    odometer.add(conn, car, "2025-07-01", 54_000)
    warranties.create(conn, car, WarrantyInput("Tires", "2025-04-01", months=None, miles=500_000, codes=["tires"]))
    text = page(signed_in, f"/vehicles/{car}")
    assert "Until about 550,983 mi" in text and "mi left" in text   # 50,983 on Apr 1, between the readings


# ---------- When a later visit replaces a covered part ----------


def _days(n):
    return (date.today() - timedelta(days=n)).isoformat()


@pytest.fixture
def battery(conn, car):
    """A battery fitted 400 days ago with Costco's 3-year warranty, and a later visit that replaced it."""
    fitted = rf.visit(conn, car, _days(400), source="diy", lines=[rf.line("Battery", 18_000, "battery_12v")])
    made = warranties.create(conn, car, WarrantyInput("Battery free replacement", _days(400), provider="Costco",
                                                      months=36, codes=["battery_12v"], event_id=fitted))
    later = rf.visit(conn, car, _days(30), shop="Valley Honda",
                     lines=[rf.line("Battery", 21_000, "battery_12v"), rf.line("Oil", 6_000, "engine_oil")])
    return made, later


def _answer(signed_in, warranty_id, event_id, said, **extra):
    return signed_in.post(f"/warranties/{warranty_id}/answer",
                          data={"event_id": str(event_id), "answer": said, **extra}, follow_redirects=False)


def _ends():
    return day_words(add_months(date.fromisoformat(_days(400)), 36).isoformat())


def test_the_question_on_the_car_page(signed_in, conn, car, battery):
    text = page(signed_in, f"/vehicles/{car}")
    assert (f"Valley Honda replaced the 12-volt battery on {day_words(_days(30))}. "
            f"Costco's warranty covered it until {_ends()}.") in text
    assert "Done under the warranty" in text and "Paid for it" in text


def test_done_under_the_warranty_keeps_it_and_undo(signed_in, conn, car, battery):
    made, later = battery
    response = _answer(signed_in, made, later, "claimed")
    assert response.headers["location"] == f"/vehicles/{car}#warranties"
    text = page(signed_in, f"/vehicles/{car}")
    assert f"Used {day_words(_days(30))} at Valley Honda" in text and "Done under the warranty" not in text
    assert " ended</summary>" not in text
    signed_in.post(f"/warranties/{made}/unanswer", data={"event_id": str(later)})
    assert warranties.get(conn, made)["answers"] == {}


def test_paid_for_it_ends_it_and_undo_brings_it_back(signed_in, conn, car, battery):
    made, later = battery
    _answer(signed_in, made, later, "paid")
    text = page(signed_in, f"/vehicles/{car}")
    assert "1 ended" in text and "None in force." in text
    assert f"Ended {day_words(_days(30))}: you paid to replace the 12-volt battery at Valley Honda" in text
    assert f'href="/services/{later}">Ended' in text
    signed_in.post(f"/warranties/{made}/unanswer", data={"event_id": str(later)})
    assert "None in force." not in page(signed_in, f"/vehicles/{car}")


def test_a_stale_answer_changes_nothing(signed_in, conn, car, battery):
    made, later = battery
    other = rf.visit(conn, car, _days(10), shop="Midas", lines=[rf.line("Oil", 6_000, "engine_oil")])
    for event, said in ((other, "paid"), (later, "maybe")):
        _answer(signed_in, made, event, said)
    assert warranties.get(conn, made)["answers"] == {}
    _answer(signed_in, made, later, "claimed")
    _answer(signed_in, made, later, "paid")          # answered already, from a page still showing the question
    assert warranties.get(conn, made)["answers"] == {later: "claimed"}


def test_the_service_page_asks_about_itself_and_answers_come_back(signed_in, conn, car, battery):
    made, later = battery
    text = page(signed_in, f"/services/{later}")
    assert 'id="warranties"' in text and "Was this under the warranty?" in text
    assert f"It covered the 12-volt battery until {_ends()}." in text
    response = _answer(signed_in, made, later, "claimed", back="service")
    assert response.headers["location"] == f"/services/{later}#warranties"
    text = page(signed_in, f"/services/{later}")
    assert "Done under this warranty" in text and "Was this under the warranty?" not in text
    signed_in.post(f"/warranties/{made}/unanswer", data={"event_id": str(later), "back": "service"})
    assert "Was this under the warranty?" in page(signed_in, f"/services/{later}")


def test_the_visit_it_came_with_and_adding_one_to_a_visit(signed_in, conn, car, battery):
    made, _ = battery
    fitted = warranties.get(conn, made)["service_event_id"]
    text = page(signed_in, f"/services/{fitted}")
    assert "Came with this visit" in text and "Battery free replacement" in text
    assert f'href="/vehicles/{car}/warranties/new?service={fitted}"' in text
    nothing = rf.visit(conn, car, _days(5), shop="Midas", lines=[rf.line("Oil", 6_000, "engine_oil")])
    assert "None came with this visit." in page(signed_in, f"/services/{nothing}")
    done = rf.visit(conn, car, _days(5), source="attested", lines=[rf.line("Oil", None, "engine_oil")])
    assert 'id="warranties"' not in page(signed_in, f"/services/{done}")


def test_a_receipts_service_sends_you_to_the_receipt(signed_in, conn, car):
    receipt_id, event = rf.receipt(conn, car, rf.pdf_bytes("Costco"), "c.pdf", shop_name="Costco", date=_days(20))
    text = page(signed_in, f"/services/{event}")
    assert f'href="/receipts/{receipt_id}#warranties"' in text and "warranties/new?service" not in text


def test_a_procedure_under_warranty_is_a_note_not_a_question(signed_in, conn, car):
    warranties.create(conn, car, WarrantyInput("Rotations for life", _days(400), provider="Discount Tire",
                                               codes=["tire_rotation"]))
    rotated = rf.visit(conn, car, _days(20), shop="Discount Tire",
                       lines=[rf.line("Rotate", 0, "tire_rotation", action="perform")])
    text = page(signed_in, f"/services/{rotated}")
    assert "Tire rotation: under warranty (Rotations for life, Discount Tire) for life." in text
    assert "Was this under the warranty?" not in text


def test_a_review_says_what_was_under_warranty(signed_in, conn, car, battery):
    made, later = battery
    receipt_id, _ = rf.receipt(conn, car, rf.pdf_bytes("New battery"), "n.pdf", confirm=False, shop_name="Pep Boys",
                               date=_days(2), odometer=None, lines=[fx.line("Battery", 199.0, ["battery_12v"])],
                               recommendations=[], warranties=[fx.warranty()])
    text = page(signed_in, f"/receipts/{receipt_id}")
    assert f"The 12-volt battery was under warranty (Battery free replacement, Costco) until {_ends()}." in text
    _answer(signed_in, made, later, "paid")          # it ended at Valley Honda, before this receipt
    assert "was under warranty" not in page(signed_in, f"/receipts/{receipt_id}")


# ---------- Before the work ----------


def test_a_recommendation_for_a_part_under_warranty_says_so(signed_in, conn, car):
    warranties.create(conn, car, WarrantyInput("Lifetime pads", _days(400), provider="Midas", codes=["brake_pads"]))
    rf.receipt(conn, car, rf.pdf_bytes("Recs"), "r.pdf", shop_name="Valley Honda", date=_days(20), odometer=None,
               recommendations=[Recommendation(description="Front brake pads", service_codes=["brake_pads"],
                                               quoted_amount=280.0)])
    assert "Under warranty: Midas, for life" in page(signed_in, f"/vehicles/{car}")


def test_the_sheet_lists_warranties_in_force_and_notes_the_jobs_they_cover(signed_in, conn):
    vehicle, _, _ = steady_car(conn, date.today() - timedelta(days=1000))
    state = status.load(conn, vehicles.get(conn, vehicle))
    urgent = next(row for row in status.next_up(state) if row["status"] in ("overdue", "due"))
    code = state.items[urgent["item_id"]]["codes"][0]
    warranties.create(conn, vehicle, WarrantyInput("Parts for life", _days(100), provider="Midas", codes=[code]))
    warranties.create(conn, vehicle, WarrantyInput("Basic", _days(900), provider="Test Motors", months=36,
                                                   whole_car=True))
    warranties.create(conn, vehicle, WarrantyInput("Expired one", "2015-01-01", months=12, codes=[code]))
    text = page(signed_in, f"/vehicles/{vehicle}/for-the-shop")
    assert "Expired one" not in text
    assert text.index("Basic · Test Motors") < text.index("Parts for life · Midas") < text.index("Due now")
    assert "The whole car · 3 years" in text and "Under warranty: Midas, for life" in text
    assert "$" not in text
