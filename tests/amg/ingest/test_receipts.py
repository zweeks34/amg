from __future__ import annotations

import pymupdf
import pytest

from amg.ingest import claude, receipts
from amg.ingest.receipts import ReceiptExtraction, ReceiptLine, Recommendation

TYPES = [
    {"code": "engine_oil", "name": "Engine oil", "category": "Engine"},
    {"code": "oil_filter", "name": "Oil filter", "category": "Engine"},
    {"code": "brake_fluid", "name": "Brake fluid", "category": "Brakes"},
]
KNOWN = {t["code"] for t in TYPES}


def _line(description="Oil change", amount=40.0, codes=("engine_oil",)):
    return ReceiptLine(description=description, kind="labor", part_number=None, quantity=None,
                       amount=amount, service_codes=list(codes), action="replace")


def _extraction(**overrides):
    fields = dict(
        is_service_record=True, shop_name="Corner Garage", invoice_number="1", date="2020-06-25",
        odometer=33_698, vin=None, vehicle=None, lines=[_line(), _line("Filter", 6.95, ["oil_filter"])],
        recommendations=[], subtotal=46.95, tax=0.0, total=46.95, uncertain="",
    )
    fields.update(overrides)
    return ReceiptExtraction(**fields)


@pytest.fixture
def receipt_pdf(tmp_path):
    path = tmp_path / "r.pdf"
    with pymupdf.open() as doc:
        doc.new_page(width=612, height=792).insert_text((72, 72), "CHANGE MOTOR OIL LUBE CHASSIS 15.00 " * 3)
        doc.save(path)
    return path


def test_system_prompt_lists_the_catalogue():
    prompt = receipts.system_prompt(TYPES)
    assert "engine_oil — Engine oil, Engine" in prompt
    assert "personal details" in prompt


def test_clean_extraction_has_no_warnings():
    assert receipts.checks(_extraction(), KNOWN) == []


def test_unknown_codes_are_dropped_and_reported():
    extraction = _extraction(
        lines=[_line(codes=["engine_oil", "blinker_fluid"])],
        recommendations=[Recommendation(description="Flush", service_codes=["flux"], quoted_amount=None)],
        subtotal=40.0, total=40.0,
    )
    warnings = receipts.checks(extraction, KNOWN)
    assert extraction.lines[0].service_codes == ["engine_oil"]
    assert extraction.recommendations[0].service_codes == []
    assert len([w for w in warnings if "Dropped unknown" in w]) == 2


def test_totals_that_dont_add_up_are_flagged():
    warnings = receipts.checks(_extraction(subtotal=None, total=99.0), KNOWN)
    assert any("add up to $46.95" in w for w in warnings)


def test_missing_basics_and_bad_vin_are_flagged():
    warnings = receipts.checks(_extraction(date=None, odometer=None, vin="1M8GDM9A9KP042788"), KNOWN)
    assert "No date found." in warnings
    assert "No odometer reading found." in warnings
    assert any("check digit" in w for w in warnings)


def test_text_mode_sends_page_text_and_no_images(receipt_pdf):
    texts = receipts.local_text(receipt_pdf, use_ocr=False)
    assert texts[0].source == "text layer"
    blocks = receipts.content_blocks(receipt_pdf, "text", texts)
    assert not any(b["type"] == "image" for b in blocks)
    assert "CHANGE MOTOR OIL" in blocks[0]["text"]


def test_vision_mode_sends_images_only(receipt_pdf):
    texts = receipts.local_text(receipt_pdf, use_ocr=False)
    blocks = receipts.content_blocks(receipt_pdf, "vision", texts)
    assert [b["type"] for b in blocks] == ["text", "image", "text"]
    assert blocks[1]["source"]["media_type"] == "image/jpeg"


def test_both_mode_sends_image_then_text_hint(receipt_pdf):
    texts = receipts.local_text(receipt_pdf, use_ocr=False)
    blocks = receipts.content_blocks(receipt_pdf, "both", texts)
    assert [b["type"] for b in blocks] == ["text", "image", "text", "text"]
    assert "trust the image" in blocks[2]["text"]


def test_read_receipt_calls_claude_with_the_schema(receipt_pdf, monkeypatch):
    seen = {}

    def fake_parse(schema, system, content, effort):
        seen.update(schema=schema, system=system, effort=effort)
        return _extraction(lines=[_line(codes=["engine_oil", "nope"])], subtotal=40.0, total=40.0), claude.Usage(
            "claude-opus-5-5", 1000, 200, 0, 0, 1.0, "req_1")

    monkeypatch.setattr(claude, "parse", fake_parse)
    read = receipts.read_receipt(receipt_pdf, TYPES, mode="text", effort="low")
    assert seen["schema"] is ReceiptExtraction and seen["effort"] == "low"
    assert read.extraction.lines[0].service_codes == ["engine_oil"]
    assert read.warnings == ["Dropped unknown service codes ['nope'] from “Oil change”."]


def test_unsupported_files_are_refused(tmp_path):
    with pytest.raises(ValueError, match="aren't supported"):
        receipts.read_receipt(tmp_path / "scan.heic", TYPES)
