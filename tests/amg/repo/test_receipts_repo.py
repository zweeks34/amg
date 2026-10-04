from __future__ import annotations

import json
from io import BytesIO

import pymupdf
import pytest
import receipt_fixtures as fx  # tests/ is on pytest's path
from PIL import Image

from amg.ingest import drafts
from amg.repo import documents, jobs, receipts, services, vehicles

OUTBACK_VIN = "1M8GDM9AXKP042788"   # a check-digit-valid stand-in
WRONG_VIN = "2HGFC2F59JH000001"     # made up: what a shop might print for another car


def _pdf_bytes(text="CHANGE MOTOR OIL"):
    with pymupdf.open() as doc:
        doc.new_page(width=612, height=792).insert_text((72, 72), text)
        return doc.tobytes()


def _types(conn):
    return {r["code"]: dict(r) for r in services.list_types(conn)}


@pytest.fixture
def outback(conn):
    return vehicles.create(conn, vehicles.VehicleFields(
        name="Outback", year=2016, make="Subaru", model="Outback", vin=OUTBACK_VIN, plate="ABC1234"))


@pytest.fixture
def receipt(conn):
    """A receipt that has been read, with its car left to the suggestion."""
    def make(extraction=None, vehicle_id=None):
        document, _ = documents.store(conn, _pdf_bytes(str(id(extraction))), "scan.pdf")
        job_id = jobs.create(conn, "read_receipts")
        receipt_id = receipts.create(conn, document["id"], job_id, vehicle_id)
        assert receipts.claim_next(conn, job_id) == receipt_id
        ex = extraction or fx.extraction()
        draft = drafts.from_extraction(ex, _types(conn), receipts.learned(conn))
        receipts.mark_read(conn, receipt_id, ex.model_dump(), draft, [], fx.USAGE)
        return receipt_id
    return make


# ---------- Documents ----------


def test_store_dedupes_by_content(conn):
    data = _pdf_bytes()  # each new PDF gets a unique ID, so store the very same bytes twice
    first, created = documents.store(conn, data, "a.pdf")
    again, created_again = documents.store(conn, data, "renamed.pdf")
    assert created and not created_again and again["id"] == first["id"]
    assert documents.path(first).exists()
    assert first["page_count"] == 1 and first["media_type"] == "application/pdf"


@pytest.mark.parametrize(("data", "name", "message"), [
    (b"%PDF", "x.heic", "PDF, PNG, JPG and GIF"),
    (b"", "x.pdf", "empty"),
    (b"not a pdf at all", "x.pdf", "couldn't be opened"),
])
def test_store_refuses_bad_files(conn, data, name, message):
    with pytest.raises(documents.UploadError, match=message):
        documents.store(conn, data, name)


def test_phone_photos_are_stored_upright(conn):
    image = Image.new("RGB", (400, 200), "white")
    exif = image.getexif()
    exif[0x0112] = 6  # "rotate 90° clockwise to display"
    out = BytesIO()
    image.save(out, "JPEG", exif=exif)
    document, _ = documents.store(conn, out.getvalue(), "photo.jpg")
    assert Image.open(documents.path(document)).size == (200, 400)


def test_combine_makes_one_pdf_in_order(conn):
    photo = BytesIO()
    Image.new("RGB", (300, 400), "white").save(photo, "PNG")
    data, name = documents.combine([(_pdf_bytes(), "page1.pdf"), (photo.getvalue(), "page2.png")])
    document, _ = documents.store(conn, data, name)
    assert document["page_count"] == 2 and name == "page1-combined.pdf"


def test_page_images_are_cached(conn):
    document, _ = documents.store(conn, _pdf_bytes(), "a.pdf")
    first = documents.page_image(document, 1, 800)
    assert first.exists() and documents.page_image(document, 1, 800) == first
    with pytest.raises(ValueError):
        documents.page_image(document, 2, 800)


# ---------- Drafts ----------


def test_draft_from_extraction(conn):
    draft = drafts.from_extraction(fx.extraction(vin="1m8gdm9a xkp042788", plate="va abc-1234"), _types(conn))
    assert draft.performed_on == "2016-08-15" and draft.total_cents == 7779 and draft.tax_cents == 276
    assert draft.printed_vin == OUTBACK_VIN and draft.printed_plate == "VAABC1234"
    assert draft.lines[0]["covers"] == [{"code": "engine_oil", "action": "replace"}, {"code": "oil_filter", "action": "replace"}]
    assert draft.lines[0]["covers_source"] == "claude"
    assert draft.recommendations == [{"description": "Brake fluid flush", "codes": ["brake_fluid"], "quoted_cents": 12995}]


def test_inspection_types_are_never_replaced(conn):
    ex = fx.extraction(lines=[fx.line("Multi-point inspection", 0.0, ["multipoint_inspection"], "replace")])
    assert drafts.from_extraction(ex, _types(conn)).lines[0]["covers"][0]["action"] == "inspect"


def test_learned_phrases_win_over_claude(conn):
    learned = {"synthetic oil and filter change": [{"code": "engine_oil", "action": "replace"}]}
    draft = drafts.from_extraction(fx.extraction(), _types(conn), learned)
    assert draft.lines[0]["covers"] == [{"code": "engine_oil", "action": "replace"}]
    assert draft.lines[0]["covers_source"] == "learned"


def test_phrase_ignores_numbers_and_case():
    assert drafts.phrase("Added 4 QTS Standard Motor Oil") == drafts.phrase("ADDED 5 QTS, standard motor-oil")


def test_draft_round_trips_through_json(conn):
    draft = drafts.from_extraction(fx.extraction(), _types(conn))
    assert drafts.Draft.from_dict(json.loads(json.dumps(draft.to_dict()))) == draft


def test_mismatch_notes():
    draft = drafts.Draft(printed_vin=WRONG_VIN, printed_vehicle="2016 Subaru Forester")
    notes = drafts.mismatches(draft, {"name": "Outback", "vin": OUTBACK_VIN, "plate": "", "model": "Outback"})
    assert len(notes) == 2 and "isn't Outback's VIN" in notes[0] and "Forester" in notes[1]


# ---------- Which car ----------


def test_vin_match_wins(conn, outback, receipt):
    vehicles.create(conn, vehicles.VehicleFields(name="Other", make="Toyota", model="Prius"))
    receipt_id = receipt(fx.extraction(vin=OUTBACK_VIN))
    row = receipts.get(conn, receipt_id)
    assert row["vehicle_id"] == outback and row["vehicle_reason"] == "The VIN matches."


def test_plate_match(conn, outback, receipt):
    vehicles.create(conn, vehicles.VehicleFields(name="Other"))
    receipt_id = receipt(fx.extraction(plate="ABC 1234", vehicle=None))
    assert receipts.get(conn, receipt_id)["vehicle_reason"] == "The plate matches."


def test_a_shops_wrong_vin_is_learned_from_confirmed_receipts(conn, outback, receipt):
    other = vehicles.create(conn, vehicles.VehicleFields(name="Other", make="Toyota", model="Prius"))
    wrong = fx.extraction(vin=WRONG_VIN, vehicle="2016 Subaru Forester")
    first = receipt(wrong)
    assert receipts.get(conn, first)["vehicle_id"] is None        # two cars, nothing matches
    receipts.confirm(conn, first, receipts.get(conn, first)["draft"], outback)
    second = receipt(fx.extraction(vin=WRONG_VIN, vehicle="2016 Subaru Forester", date="2018-09-13", total=197.12))
    row = receipts.get(conn, second)
    assert row["vehicle_id"] == outback and "Earlier receipts with this VIN were for Outback" in row["vehicle_reason"]
    assert other  # the other car was never suggested


def test_year_make_model_match(conn, outback, receipt):
    vehicles.create(conn, vehicles.VehicleFields(name="Other", year=2020, make="Toyota", model="Prius"))
    receipt_id = receipt(fx.extraction(vehicle="16 SUBARU OUTBACK WAGON"))
    assert receipts.get(conn, receipt_id)["vehicle_reason"] == "The year, make and model match."


def test_only_car_is_suggested_weakly(conn, outback, receipt):
    receipt_id = receipt(fx.extraction(vehicle="2016 Subaru Forester"))
    assert receipts.get(conn, receipt_id)["vehicle_reason"] == "It's your only car."


def test_a_car_chosen_at_upload_is_kept(conn, outback, receipt):
    other = vehicles.create(conn, vehicles.VehicleFields(name="Other"))
    receipt_id = receipt(fx.extraction(vin=OUTBACK_VIN), vehicle_id=other)
    assert receipts.get(conn, receipt_id)["vehicle_id"] == other


# ---------- Confirming ----------


def test_confirm_writes_the_service_and_learns(conn, outback, receipt):
    receipt_id = receipt()
    draft = receipts.get(conn, receipt_id)["draft"]
    draft.lines[0]["covers"] = [{"code": "engine_oil", "action": "replace"}]   # you corrected it
    event_id = receipts.confirm(conn, receipt_id, draft, outback)
    event = services.get_event(conn, event_id)
    assert event["source"] == "receipt" and event["total_cents"] == 7779
    assert [c["code"] for c in event["lines"][0]["covers"]] == ["engine_oil"]
    row = receipts.get(conn, receipt_id)
    assert row["status"] == "confirmed" and row["service_event_id"] == event_id
    assert row["extraction"]["lines"][0]["service_codes"] == ["engine_oil", "oil_filter"]   # the original read is kept
    assert receipts.learned(conn)["synthetic oil and filter change"] == [{"code": "engine_oil", "action": "replace"}]


def test_reconfirming_rewrites_the_same_event_and_can_move_it(conn, outback, receipt):
    other = vehicles.create(conn, vehicles.VehicleFields(name="Other"))
    receipt_id = receipt()
    event_id = receipts.confirm(conn, receipt_id, receipts.get(conn, receipt_id)["draft"], outback)
    draft = receipts.get(conn, receipt_id)["draft"]
    draft.total_cents = 8000
    assert receipts.confirm(conn, receipt_id, draft, other) == event_id
    event = services.get_event(conn, event_id)
    assert event["total_cents"] == 8000 and event["vehicle_id"] == other
    assert conn.execute("SELECT count(*) FROM service_events").fetchone()[0] == 1


def test_car_details_are_only_filled_never_overwritten(conn, receipt):
    car = vehicles.create(conn, vehicles.VehicleFields(name="Outback", vin=OUTBACK_VIN))
    receipt_id = receipt()
    receipts.confirm(conn, receipt_id, receipts.get(conn, receipt_id)["draft"], car,
                     {"plate": "ABC1234", "vin": WRONG_VIN, "in_service_date": "2016-03-01"})
    row = vehicles.get(conn, car)
    assert row["plate"] == "ABC1234" and row["in_service_date"] == "2016-03-01"
    assert row["vin"] == OUTBACK_VIN


def test_deleting_the_service_sends_the_receipt_back(conn, outback, receipt):
    receipt_id = receipt()
    event_id = receipts.confirm(conn, receipt_id, receipts.get(conn, receipt_id)["draft"], outback)
    receipts.release_event(conn, event_id)
    services.delete_event(conn, event_id)
    row = receipts.get(conn, receipt_id)
    assert row["status"] == "read" and row["service_event_id"] is None


def test_unconfirmed_receipts_count_for_nothing(conn, outback, receipt):
    receipt()
    assert services.history(conn, outback) == []
    assert receipts.count_to_check(conn) == 1


def test_possible_duplicates(conn, receipt):
    first = receipt()
    second = receipt(fx.extraction(shop_name="Same paper, scanned again"))
    draft = receipts.get(conn, second)["draft"]
    assert [d["id"] for d in receipts.possible_duplicates(conn, second, draft)] == [first]


def test_confirmed_receipts_come_newest_receipt_date_first(conn, outback, receipt):
    newer = receipt(fx.extraction(date="2024-03-11", shop_name="Midas"))
    older = receipt(fx.extraction(date="2019-08-15", shop_name="Corner Garage"))
    for receipt_id in (newer, older):   # the older one confirmed last
        receipts.confirm(conn, receipt_id, receipts.get(conn, receipt_id)["draft"], outback)
    confirmed = receipts.inbox(conn)["confirmed"]
    assert [r["id"] for r in confirmed] == [newer, older]
    assert confirmed[0]["lines"][0]["description"] == "Synthetic oil and filter change"   # what search reads
    assert (confirmed[0]["invoice_number"], confirmed[0]["vehicle_archived"]) == ("A100", 0)


def test_discard_and_restore(conn, receipt):
    receipt_id = receipt()
    receipts.discard(conn, receipt_id)
    assert receipts.inbox(conn)["discarded"][0]["id"] == receipt_id
    receipts.restore(conn, receipt_id)
    assert receipts.get(conn, receipt_id)["status"] == "read"


# ---------- Jobs ----------


def test_stalled_job_detection_and_resume(conn, receipt):
    from datetime import datetime, timedelta, timezone

    job_id = jobs.create(conn, "read_receipts")
    document, _ = documents.store(conn, _pdf_bytes("stalled"), "s.pdf")
    receipt_id = receipts.create(conn, document["id"], job_id)
    receipts.claim_next(conn, job_id)
    job = jobs.get(conn, job_id)
    later = datetime.now(timezone.utc) + timedelta(seconds=jobs.STALL_SECONDS + 5)
    assert not jobs.is_stalled(job) and jobs.is_stalled(job, now=later)
    jobs.resume(conn, job_id)
    assert receipts.get(conn, receipt_id)["status"] == "queued"
