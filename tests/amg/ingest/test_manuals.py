from __future__ import annotations

import pymupdf
import pytest

from amg.ingest import manuals, ocr

FILLER = ("To adjust the driver's seat, pull the lever under the front of the cushion and slide the seat "
          "to the position you want. Release the lever and make sure the seat locks in place.")
SCHEDULE_INTRO = ("MAINTENANCE SCHEDULE. Perform the maintenance at the intervals shown, whichever comes first. "
                  "Replace engine oil and filter every 7,500 miles or 6 months. Inspect brake pads every 15,000 miles "
                  "or 12 months. Rotate tires every 7,500 miles.")
SCHEDULE_TABLE = ("x 1,000 mi 15,000 mi 30,000 mi 45,000 mi 60,000 mi 75,000 mi 90,000 mi 105,000 mi 120,000 mi "
                  "Engine oil R R R R R R R R  Brake pads I I I I  Coolant R  Spark plugs R")


def _manual(tmp_path, pages: dict[int, str], count: int = 40, filler: str = FILLER):
    path = tmp_path / "manual.pdf"
    with pymupdf.open() as doc:
        for number in range(1, count + 1):
            page = doc.new_page(width=612, height=792)
            text = pages.get(number, filler)
            if text:
                page.insert_textbox(pymupdf.Rect(54, 54, 558, 738), text, fontsize=10)
        doc.save(path)
    return path


CAR = {"year": 2016, "make": "Subaru", "model": "Outback", "trim": "2.5i Limited", "engine": "2.5L 4-cyl",
       "powertrain": "gas"}


def test_the_schedule_pages_are_found_with_their_neighbours(tmp_path):
    path = _manual(tmp_path, {23: SCHEDULE_INTRO, 24: SCHEDULE_TABLE})
    chosen = manuals.find_pages(path)
    assert {23, 24} <= set(chosen)
    assert set(chosen) <= {22, 23, 24, 25}


def test_a_short_document_is_sent_whole(tmp_path):
    path = _manual(tmp_path, {}, count=3)
    assert manuals.find_pages(path) == [1, 2, 3]


def test_typed_pages_win(tmp_path):
    path = _manual(tmp_path, {23: SCHEDULE_INTRO})
    assert manuals.find_pages(path, "30-31, 5") == [5, 30, 31]


def test_no_schedule_asks_for_the_pages(tmp_path):
    path = _manual(tmp_path, {})
    with pytest.raises(manuals.ManualError, match="Type the page numbers"):
        manuals.find_pages(path)


def test_a_long_scan_without_text_asks_for_the_pages(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: False)
    path = _manual(tmp_path, {}, filler="")
    with pytest.raises(manuals.ManualError, match="no text AMG can search"):
        manuals.find_pages(path)


def test_choosing_stops_at_the_limit():
    scores = {n: 20 for n in range(1, 41)}
    assert len(manuals.choose(scores)) == manuals.MAX_PAGES


def test_weak_pages_are_not_chosen():
    assert manuals.choose({1: 2, 2: 3, 3: 1}) == []


@pytest.mark.parametrize(("typed", "expected"), [("30-31, 45", [30, 31, 45]), ("31-30", [30, 31]), ("7 7", [7])])
def test_parse_pages(typed, expected):
    assert manuals.parse_pages(typed, 50) == expected


@pytest.mark.parametrize(("typed", "message"), [("thirty", "like 30-31"), ("49-51", "50 pages"),
                                                 ("1-13", "up to 12")])
def test_bad_pages_are_explained(typed, message):
    with pytest.raises(ValueError, match=message):
        manuals.parse_pages(typed, 50)


def test_pages_are_labelled_with_their_page_numbers(tmp_path):
    path = _manual(tmp_path, {23: SCHEDULE_INTRO})
    blocks = manuals.content_blocks(path, [23, 24], CAR, 40)
    labels = [b["text"] for b in blocks if b["type"] == "text"]
    assert "Page 23 of 40" in labels and "Page 24 of 40" in labels
    assert "2016 Subaru Outback 2.5i Limited, 2.5L 4-cyl, gasoline" in labels[0]
    assert sum(b["type"] == "image" for b in blocks) == 2
