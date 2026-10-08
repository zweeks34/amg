"""The specs card: the page, typing it in, and what your receipts suggest."""

from __future__ import annotations

import html

import pytest
import report_fixtures as rf  # tests/ is on pytest's path

from amg.repo import documents, specs
from amg.repo.services import Coverage, LineInput
from amg.repo.specs import SpecInput


@pytest.fixture
def car(conn):
    return rf.car(conn, "Outback", year=2016, make="Subaru", model="Outback", trim="2.5i Limited")


def part(description, code, part_number="", quantity=None):
    return LineInput(description, "part", part_number=part_number, quantity=quantity, amount_cents=1_000,
                     covers=[Coverage(code, "replace")])


def _save(client, car, **fields):
    data = {f"spec_{key}": value for key, value in fields.items()}
    return client.post(f"/vehicles/{car}/specs/edit", data=data, follow_redirects=False)


def test_an_empty_card_says_how_to_fill_it(signed_in, car):
    assert f'href="/vehicles/{car}/specs">Specs</a>' in signed_in.get(f"/vehicles/{car}").text
    page = html.unescape(signed_in.get(f"/vehicles/{car}/specs").text)
    assert "Nothing on Outback's card yet." in page and "Edit specs" in page and "Print</button>" not in page


def test_type_them_in(signed_in, conn, car):
    form = signed_in.get(f"/vehicles/{car}/specs/edit").text
    assert 'name="spec_oil_grade"' in form and 'placeholder="0W-20 synthetic"' in form and "Add a line" in form
    response = _save(signed_in, car, oil_grade="0W-20 synthetic", tire_size="225/65R17 98H", wiper_driver="")
    assert response.headers["location"] == f"/vehicles/{car}/specs?saved=1"
    page = signed_in.get(f"/vehicles/{car}/specs?saved=1").text
    assert "Specs saved." in page and "0W-20 synthetic" in page and "225/65R17 98H" in page
    assert "Set by you" in page and "Driver's wiper blade" not in page
    assert "What to buy for Outback, a 2016 Subaru Outback 2.5i Limited, gasoline." in page
    assert "Print</button>" in page and '<p class="printhead">Outback · 2016 Subaru Outback' in page
    assert [(r["key"], r["source"]) for r in specs.values(conn, car)] == [("oil_grade", "you"), ("tire_size", "you")]


def test_a_cleared_box_removes_it_and_an_untouched_one_keeps_its_page(signed_in, conn, car):
    manual = documents.store(conn, rf.pdf_bytes("MANUAL"), "manual.pdf")[0]["id"]
    specs.save(conn, car, [SpecInput("oil_grade", "0W-20", source="read", document_id=manual, page=412),
                           SpecInput("fuel", "87 octane", source="read", document_id=manual, page=413)])
    assert "manual.pdf, p. 412" in signed_in.get(f"/vehicles/{car}/specs").text
    _save(signed_in, car, oil_grade="0W-20", fuel="")
    assert [(r["key"], r["source"], r["page"]) for r in specs.values(conn, car)] == [("oil_grade", "read", 412)]
    _save(signed_in, car, oil_grade="5W-30")
    assert [(r["value"], r["source"], r["page"]) for r in specs.values(conn, car)] == [("5W-30", "you", None)]


def test_lines_of_your_own(signed_in, conn, car):
    response = signed_in.post(f"/vehicles/{car}/specs/edit", data={
        "custom_label": ["Trunk light", "", "Hitch pin"], "custom_value": ["168", "", "5/8 in"]}, follow_redirects=False)
    assert response.status_code == 303
    assert [(r["label"], r["value"]) for r in specs.values(conn, car)] == [("Trunk light", "168"), ("Hitch pin", "5/8 in")]
    page = signed_in.get(f"/vehicles/{car}/specs").text
    assert ">Other</h2>" in page and "Trunk light" in page and "5/8 in" in page
    form = html.unescape(signed_in.get(f"/vehicles/{car}/specs/edit").text)
    assert '"label": "Trunk light", "value": "168"' in form


def test_a_line_needs_a_name_and_a_value(signed_in, conn, car):
    response = signed_in.post(f"/vehicles/{car}/specs/edit", data={
        "spec_oil_grade": "0W-20", "custom_label": ["", "Hitch pin"], "custom_value": ["168", ""]})
    assert response.status_code == 422
    page = html.unescape(response.text)
    assert "Some boxes need a look." in page and "Name this line, such as Trunk light." in page
    assert "Add its value, or remove the line." in page and 'value="0W-20"' in page
    assert specs.values(conn, car) == []


def test_too_long(signed_in, conn, car):
    response = _save(signed_in, car, oil_grade="x" * 200)
    assert response.status_code == 422 and "Keep it under 160 characters." in response.text


def test_your_receipts_suggest_and_show_what_went_in(signed_in, conn, car):
    rf.visit(conn, car, "2026-08-01", shop="Valley Honda", lines=[
        part("Oil filter", "oil_filter", "15208AA15A"), part("0W20 FULL SYN", "engine_oil", quantity=5),
        part("Wiper blade 26 in", "wiper_blades"), part("Wiper blade 17 in", "wiper_blades")])
    form = html.unescape(signed_in.get(f"/vehicles/{car}/specs/edit").text)
    assert 'data-for="f-spec_oil_filter" data-use="15208AA15A"' in form and "Use 0W-20" in form
    assert form.count('data-use="Wiper blade 26 in"') == 3    # driver's, passenger's and rear: a receipt rarely says which
    assert 'data-for="f-spec_tire_size"' not in form
    page = html.unescape(signed_in.get(f"/vehicles/{car}/specs").text)
    assert "Last fitted" in page and "Aug 1, 2026 at Valley Honda</a>: Oil filter 15208AA15A; 0W20 FULL SYN × 5" in page
    assert "Wiper blade 26 in; Wiper blade 17 in" in page and ">Engine oil</h2>" in page


def test_an_electric_cars_form(signed_in, conn):
    ev = rf.car(conn, "Leaf", powertrain="ev")
    form = signed_in.get(f"/vehicles/{ev}/specs/edit").text
    assert 'name="spec_cabin_air_filter"' in form and 'name="spec_oil_grade"' not in form
    assert 'name="spec_fuel"' not in form and 'name="spec_tire_size"' in form


def test_another_cars_specs_are_its_own(signed_in, conn, car):
    other = rf.car(conn, "Civic")
    _save(signed_in, car, oil_grade="0W-20")
    assert "0W-20" not in signed_in.get(f"/vehicles/{other}/specs").text
    assert signed_in.get("/vehicles/999/specs").status_code == 404
