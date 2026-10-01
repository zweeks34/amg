from __future__ import annotations

from io import BytesIO

import pymupdf
import pytest
from PIL import Image

from amg.ingest import pdf


@pytest.fixture
def letter_pdf(tmp_path):
    path = tmp_path / "receipt.pdf"
    with pymupdf.open() as doc:
        page = doc.new_page(width=612, height=792)  # US letter, in points
        page.insert_text((72, 72), "OIL FILTER 1.00 6.95 6.95 — invoice total 46.95", fontsize=11)
        doc.new_page(width=612, height=792)          # a blank second page
        doc.save(path)
    return path


def test_pages_report_each_text_layer(letter_pdf):
    pages = pdf.pages(letter_pdf)
    assert [p.number for p in pages] == [1, 2]
    assert "OIL FILTER" in pages[0].text
    assert pages[1].text == ""


def test_render_hits_the_target_long_edge(letter_pdf):
    image = Image.open(BytesIO(pdf.render(letter_pdf, 1, pdf.VISION_LONG_EDGE)))
    assert image.format == "JPEG"
    assert max(image.size) == pdf.VISION_LONG_EDGE
    assert image.size[0] * image.size[1] <= 3_750_000  # within what the API reads without shrinking


def test_images_open_as_one_page(tmp_path):
    path = tmp_path / "photo.png"
    Image.new("RGB", (800, 1200), "white").save(path)
    assert [p.text for p in pdf.pages(path)] == [""]
    assert Image.open(BytesIO(pdf.render(path, 1, 600, fmt="png"))).size == (400, 600)


@pytest.mark.parametrize(("name", "ok"), [("a.PDF", True), ("b.jpeg", True), ("c.gif", True), ("d.heic", False)])
def test_supported(name, ok):
    assert pdf.is_supported(name) is ok
