"""Reading specs: finding the spec pages, what Claude is asked, and what a reading fills in."""

from __future__ import annotations

import pymupdf
import pytest

from amg.ingest import claude, manuals
from amg.ingest import specs as reader
from amg.ingest.specs import SpecsExtraction, SpecValue

FILLER = ("To adjust the driver's seat, pull the lever under the front of the cushion and slide the seat "
          "to the position you want. Release the lever and make sure the seat locks in place.")
SPECS = ("SPECIFICATIONS. Capacities. Engine oil with filter 4.4 US qt (4.2 liters). Recommended oil: SAE 0W-20. "
         "Fuel tank 18.5 US gal. Brake fluid DOT 3 or DOT 4. Use unleaded gasoline, 87 octane (AKI).")
TIRES = ("Tire size P225/65R17 102H. Cold tire inflation pressure: front 230 kPa (33 psi), rear 220 kPa (32 psi). "
         "Bulbs: headlight low beam H11, high beam 9005.")
SCHEDULE = ("MAINTENANCE SCHEDULE. Replace engine oil and filter every 6,000 miles or 6 months, whichever comes "
            "first. Inspect brake pads every 12,000 miles.")
CAR = {"year": 2016, "make": "Subaru", "model": "Outback", "trim": "2.5i Limited", "engine": "2.5L 4-cyl",
       "powertrain": "gas"}


def _manual(tmp_path, pages: dict[int, str], count: int = 40):
    path = tmp_path / "manual.pdf"
    with pymupdf.open() as doc:
        for number in range(1, count + 1):
            page = doc.new_page(width=612, height=792)
            page.insert_textbox(pymupdf.Rect(54, 54, 558, 738), pages.get(number, FILLER), fontsize=10)
        doc.save(path)
    return path


def test_the_spec_pages_are_found_not_the_schedule(tmp_path):
    path = _manual(tmp_path, {12: SCHEDULE, 35: SPECS, 36: TIRES})
    chosen = reader.find_pages(path)
    assert {35, 36} <= set(chosen) <= {34, 35, 36, 37}
    assert reader.score(SPECS) > reader.score(SCHEDULE) and reader.score(FILLER) == 0


def test_typed_pages_and_short_documents(tmp_path):
    assert reader.find_pages(_manual(tmp_path, {35: SPECS}), "30-31") == [30, 31]
    assert reader.find_pages(_manual(tmp_path, {}, count=3)) == [1, 2, 3]


def test_no_spec_pages_asks_for_them(tmp_path):
    with pytest.raises(manuals.ManualError, match="couldn't find the specifications in this document"):
        reader.find_pages(_manual(tmp_path, {12: SCHEDULE}))


def test_claude_is_asked_for_the_cards_fields_from_the_page(tmp_path, monkeypatch):
    asked = {}

    def parse(model, system, content, effort, max_tokens, stream):
        asked.update(model=model, system=system, content=content, effort=effort)
        return SpecsExtraction(printed_for="2016 Outback", specs=[], uncertain=""), claude.Usage(
            "claude-opus-5-5", 1, 1, 0, 0, 0.01, "req")

    monkeypatch.setattr(claude, "parse", parse)
    read = reader.read_specs(_manual(tmp_path, {35: SPECS, 36: TIRES}), CAR)
    assert {35, 36} <= set(read.pages) and asked["model"] is SpecsExtraction and asked["effort"] == "medium"
    assert "oil_grade — Oil grade, e.g. 0W-20 synthetic" in asked["system"]
    assert "never fill one in from what you know about the car" in asked["system"]
    texts = [b["text"] for b in asked["content"] if b["type"] == "text"]
    assert "2016 Subaru Outback 2.5i Limited" in texts[0] and texts[-1] == "Read the specifications on these pages."


def test_an_unsupported_file_is_said(tmp_path):
    path = tmp_path / "manual.docx"
    path.write_bytes(b"x")
    with pytest.raises(manuals.ManualError, match=".docx files aren't supported"):
        reader.read_specs(path, CAR)


def test_what_a_reading_fills_in():
    extraction = SpecsExtraction(printed_for="", uncertain="The bulb chart is blurred.", specs=[
        SpecValue(key="oil_grade", value=" 0W-20 ", page=412, note=""),
        SpecValue(key="oil_grade", value="5W-30", page=413, note=""),
        SpecValue(key="tire_size", value="225/65R17 102H", page=420, note="225/60R18 100H on the Touring"),
        SpecValue(key="horn", value="Dual tone", page=430, note=""),
        SpecValue(key="fuel", value="  ", page=412, note=""),
    ])
    values, warnings = reader.to_draft(extraction)
    assert values == {"oil_grade": {"value": "0W-20", "page": 412}, "tire_size": {"value": "225/65R17 102H", "page": 420}}
    assert warnings == [
        "Oil grade: Claude read “0W-20” first, and also “5W-30”. The first is filled in.",
        "Tire size: 225/60R18 100H on the Touring",
        "Claude also read “Dual tone” as horn, which the card has no box for. Add it under Other if you want it.",
        "The bulb chart is blurred.",
    ]
