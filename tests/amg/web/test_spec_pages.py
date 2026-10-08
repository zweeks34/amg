"""The specs card: the page, typing it in, what your receipts suggest, and checking a reading of the manual."""

from __future__ import annotations

import html

import pytest
import receipt_fixtures as fx  # tests/ is on pytest's path
import report_fixtures as rf

from amg.ingest import background, manuals
from amg.ingest import specs as spec_reader
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


# ---------- Reading them from the manual ----------

READING = spec_reader.SpecsExtraction(printed_for="2016 Outback", uncertain="The bulb chart is blurred.", specs=[
    spec_reader.SpecValue(key="oil_grade", value="0W-20", page=1, note=""),
    spec_reader.SpecValue(key="tire_size", value="225/65R17 102H", page=2, note="225/60R18 on the Touring"),
])


@pytest.fixture
def reads(monkeypatch):
    """Readings run inline; Claude 'reads' the next queued outcome, or READING."""
    queue: list = []
    calls: list = []

    def read_specs(path, car, pages=""):
        calls.append(pages)
        outcome = queue.pop(0) if queue else READING
        if isinstance(outcome, Exception):
            raise outcome
        return spec_reader.SpecsRead([1, 2], outcome, fx.USAGE)

    monkeypatch.setattr(spec_reader, "read_specs", read_specs)
    monkeypatch.setattr(background, "spawn", background.run)
    return queue, calls


def _upload(client, car, pages="", **data):
    files = [("files", ("outback-manual.pdf", rf.pdf_bytes("SPECIFICATIONS", "TIRES"), "application/pdf"))]
    return client.post(f"/vehicles/{car}/specs/read", files=files, data={"pages": pages, **data},
                       follow_redirects=False)


def _read_url(response) -> str:
    assert response.status_code == 303, response.text
    return response.headers["location"]


def test_read_the_manual_check_it_and_use_it(signed_in, conn, car, reads):
    url = _read_url(_upload(signed_in, car))
    page = html.unescape(signed_in.get(url).text)
    assert "Check these specs" in page and "Pages read · 1, 2" in page and "which says it's for 2016 Outback" in page
    assert 'name="spec_oil_grade" value="0W-20" placeholder="0W-20 synthetic" autocomplete="off" data-read="0W-20" class=""' \
        in page
    assert "Dashed boxes are still as Claude read" in page and "The bulb chart is blurred." in page
    assert "Tire size: 225/60R18 on the Touring" in page and "p. 2</span>" in page
    assert specs.values(conn, car) == []                     # nothing counts before it's used

    response = signed_in.post(url, data={"spec_oil_grade": "0W-20", "spec_tire_size": "225/65R17 98H"},
                              follow_redirects=False)
    assert response.headers["location"] == f"/vehicles/{car}/specs?saved=1"
    document = conn.execute("SELECT id, sha256 FROM documents").fetchone()
    assert [(r["key"], r["source"], r["document_id"], r["page"]) for r in specs.values(conn, car)] == [
        ("oil_grade", "read", document["id"], 1), ("tire_size", "you", None, None)]
    card = html.unescape(signed_in.get(f"/vehicles/{car}/specs").text)
    assert "outback-manual.pdf, p. 1" in card and "Set by you" in card
    assert f'href="/documents/{document["id"]}/pages/1?v={document["sha256"][:12]}&size=full"' in card
    assert "These specs are on the card" in signed_in.get(url).text


def test_a_reading_says_what_you_had(signed_in, conn, car, reads):
    specs.save(conn, car, [SpecInput("oil_grade", "5W-30"), SpecInput("fuel", "87 octane"),
                           SpecInput("custom", "168", label="Trunk light")])
    page = html.unescape(signed_in.get(_read_url(_upload(signed_in, car))).text)
    assert 'value="0W-20"' in page and "Was: 5W-30" in page
    assert 'name="spec_fuel" value="87 octane"' in page and '"label": "Trunk light"' in page


def test_a_reading_on_the_card_page(signed_in, conn, car, reads, monkeypatch):
    monkeypatch.setattr(background, "spawn", lambda job_id: None)    # still waiting to be read
    url = _read_url(_upload(signed_in, car))
    card = signed_in.get(f"/vehicles/{car}/specs").text
    assert f'<a href="{url}">outback-manual.pdf</a>' in card and "being read" in card
    page = signed_in.get(url).text
    assert "Reading the specs" in page and 'hx-trigger="every 3s"' in page


def test_read_a_file_amg_already_has(signed_in, conn, car, reads):
    _, calls = reads
    url = _read_url(_upload(signed_in, car))
    signed_in.post(f"{url}/discard")
    document = conn.execute("SELECT id FROM documents").fetchone()["id"]
    card = signed_in.get(f"/vehicles/{car}/specs").text
    assert f'<option value="{document}">outback-manual.pdf · 2 pages</option>' in card
    second = _read_url(signed_in.post(f"/vehicles/{car}/specs/read", data={"document_id": str(document), "pages": "2"},
                                      follow_redirects=False))
    assert second != url and calls == ["", "2"]
    other = rf.car(conn, "Civic")
    response = signed_in.post(f"/vehicles/{other}/specs/read", data={"document_id": str(document)})
    assert response.status_code == 422 and "Choose one of the files listed" in response.text


def test_what_the_uploader_checks(signed_in, car, reads):
    response = signed_in.post(f"/vehicles/{car}/specs/read", data={"pages": ""})
    assert response.status_code == 422 and "Choose the manual, or photos of its spec pages." in response.text
    response = _upload(signed_in, car, pages="9-10")
    assert response.status_code == 422 and "This file has 2 pages." in response.text


def test_a_failed_reading_says_why_and_reads_again(signed_in, conn, car, reads):
    queue, calls = reads
    queue.append(manuals.ManualError("AMG couldn't find the specifications in this document."))
    url = _read_url(_upload(signed_in, car))
    page = html.unescape(signed_in.get(url).text)
    assert "AMG couldn't read the specs" in page and "couldn't find the specifications" in page
    assert "couldn't be read" in html.unescape(signed_in.get(f"/vehicles/{car}/specs").text)
    signed_in.post(f"{url}/read-again", data={"pages": "1-2"})
    assert calls == ["", "1-2"] and "Check these specs" in signed_in.get(url).text


def test_nothing_found_and_discard(signed_in, conn, car, reads):
    queue, _ = reads
    queue.append(spec_reader.SpecsExtraction(printed_for="", uncertain="", specs=[]))
    url = _read_url(_upload(signed_in, car))
    assert "Claude found none of the card's specs on pages\n      1, 2." in html.unescape(signed_in.get(url).text)
    response = signed_in.post(f"{url}/discard", follow_redirects=False)
    assert response.headers["location"] == f"/vehicles/{car}/specs"
    assert "You discarded this reading." in signed_in.get(url).text
    assert "Readings</p>" not in signed_in.get(f"/vehicles/{car}/specs").text
    assert signed_in.get("/spec-reads/999").status_code == 404


def test_a_bad_box_on_the_review_keeps_the_reading(signed_in, conn, car, reads):
    url = _read_url(_upload(signed_in, car))
    response = signed_in.post(url, data={"spec_oil_grade": "x" * 200, "spec_tire_size": "225/65R17 102H"})
    assert response.status_code == 422 and "Keep it under 160 characters." in response.text
    assert "Pages read · 1, 2" in response.text and specs.values(conn, car) == []
