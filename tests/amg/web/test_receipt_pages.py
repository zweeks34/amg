from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path

import pymupdf
import pytest
import receipt_fixtures as fx  # tests/ is on pytest's path
from PIL import Image

from amg.ingest import background, drafts
from amg.ingest import receipts as reader
from amg.repo import documents, jobs, receipts, services, vehicles

OUTBACK_VIN = "1M8GDM9AXKP042788"
OTHER_VIN = "2HGFC2F59JH000001"


def _pdf(text="RECEIPT"):
    with pymupdf.open() as doc:
        doc.new_page(width=612, height=792).insert_text((72, 72), text)
        return doc.tobytes()


@pytest.fixture
def reads(monkeypatch):
    """Run reading inline, answering each read with the next queued extraction."""
    queue: list = []

    def read(path, types, mode="vision", effort="medium"):
        extraction = queue.pop(0) if queue else fx.extraction()
        warnings = reader.checks(extraction, {t["code"] for t in types})
        return reader.ReceiptRead(Path(path), mode, [], extraction, fx.USAGE, warnings)

    monkeypatch.setattr(reader, "read_receipt", read)
    monkeypatch.setattr(background, "spawn", background.run)
    return queue


@pytest.fixture
def outback(conn):
    return vehicles.create(conn, vehicles.VehicleFields(name="Outback", year=2016, make="Subaru", model="Outback",
                                                        vin=OUTBACK_VIN))


def _upload(client, *files, **fields):
    payload = [("files", (name, data, "application/octet-stream")) for name, data in files]
    return client.post("/receipts/upload", files=payload, data=fields)


def _editor(page: str) -> dict:
    """The JSON the review page hands its line editor."""
    start = page.index("receiptEditor(") + len("receiptEditor(")
    end = page.index(")'", start)
    return json.loads(page[start:end])


def _form(page: str, receipt_id: int, **changes) -> dict:
    """The review form as the browser would post it, with changes applied."""
    editor = _editor(page)
    strip = lambda rows: [{k: v for k, v in row.items()} for row in rows]  # noqa: E731
    form = {
        "vehicle_id": "", "document_kind": "invoice", "performed_on": "2016-08-15", "odometer": "3,610",
        "shop": "Corner Garage", "invoice_number": "A100", "printed_vin": "", "printed_plate": "",
        "printed_vehicle": "2016 Subaru Outback", "delivery_date": "", "next_service_date": "",
        "next_service_miles": "", "tax": "2.76", "total": "77.79", "notes": "",
        "lines_json": json.dumps(strip(editor["lines"])), "recs_json": json.dumps(strip(editor["recs"])),
        "action": "confirm",
    }
    form.update(changes)
    return form


def _only_receipt(conn) -> int:
    return conn.execute("SELECT id FROM receipts").fetchone()[0]


# ---------- Inbox and upload ----------


def test_empty_inbox(signed_in):
    page = signed_in.get("/receipts").text
    assert "No receipts yet" in page and 'name="files"' in page


def test_upload_reads_and_lists_to_check(signed_in, conn, reads, outback):
    response = _upload(signed_in, ("a.pdf", _pdf("a")), ("b.pdf", _pdf("b")))
    assert response.status_code == 200
    assert "2 files uploaded" in response.text
    assert "To check (2)" in response.text
    assert 'aria-label="2 to check"' in signed_in.get("/").text       # the nav badge


def test_reupload_is_recognised(signed_in, conn, reads):
    data = _pdf()
    _upload(signed_in, ("a.pdf", data))
    response = _upload(signed_in, ("again.pdf", data))
    assert "again.pdf was uploaded before" in response.text
    assert conn.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1


def test_unsupported_file_is_refused(signed_in, reads):
    response = _upload(signed_in, ("scan.heic", b"xxxx"))
    assert response.status_code == 422
    assert "AMG reads PDF, PNG, JPG and GIF files" in response.text


def test_photos_of_one_invoice_combine(signed_in, conn, reads):
    pages = []
    for _ in range(2):
        out = BytesIO()
        Image.new("RGB", (300, 400), "white").save(out, "JPEG")
        pages.append(out.getvalue())
    _upload(signed_in, ("p1.jpg", pages[0]), ("p2.jpg", pages[1]), combine="1")
    assert [row[0] for row in conn.execute("SELECT page_count FROM documents")] == [2]


def test_list_polls_only_while_reading(signed_in, conn, monkeypatch):
    monkeypatch.setattr(background, "spawn", lambda job_id: None)   # stays queued
    _upload(signed_in, ("a.pdf", _pdf()))
    assert 'hx-trigger="every 2s"' in signed_in.get("/receipts/list").text


# ---------- Review ----------


def test_review_shows_scan_suggestion_and_unconfirmed_fields(signed_in, conn, reads, outback):
    reads.append(fx.extraction(vin=OTHER_VIN, vehicle="2016 Subaru Forester"))
    _upload(signed_in, ("a.pdf", _pdf()))
    receipt_id = _only_receipt(conn)
    page = signed_in.get(f"/receipts/{receipt_id}").text
    document = receipts.get(conn, receipt_id)["document"]
    assert f'src="/documents/{document["id"]}/pages/1?v={document["sha256"][:12]}"' in page
    assert "It&#39;s your only car." in page                          # suggested, with the reason
    assert "which isn&#39;t Outback&#39;s VIN" in page                # printed details disagree: a note
    assert 'data-read="3,610"' in page                                # still as read
    editor = _editor(page)
    assert editor["reading"] is True and editor["lines"][0]["from_read"] is True
    assert editor["recs"][0]["description"] == "Brake fluid flush"


def test_confirm_with_corrections(signed_in, conn, reads, outback):
    _upload(signed_in, ("a.pdf", _pdf()))
    receipt_id = _only_receipt(conn)
    page = signed_in.get(f"/receipts/{receipt_id}").text
    form = _form(page, receipt_id, vehicle_id=str(outback), odometer="3,612")
    lines = json.loads(form["lines_json"])
    lines[0]["covers"] = ["engine_oil"]                    # you un-tag the filter
    recs = json.loads(form["recs_json"])
    lines.append({**recs.pop(0), "kind": "labor", "inspect_only": False, "part_number": "", "quantity": ""})
    form.update(lines_json=json.dumps(lines), recs_json=json.dumps(recs))   # "it was done after all"

    response = signed_in.post(f"/receipts/{receipt_id}", data=form, follow_redirects=False)
    assert response.status_code == 303 and response.headers["location"] == f"/receipts?confirmed={receipt_id}"

    receipt = receipts.get(conn, receipt_id)
    event = services.get_event(conn, receipt["service_event_id"])
    assert event["vehicle_id"] == outback and event["odometer"] == 3612
    assert [line["description"] for line in event["lines"]] == [
        "Synthetic oil and filter change", "Shop supplies", "Brake fluid flush"]
    assert [c["code"] for c in event["lines"][0]["covers"]] == ["engine_oil"]
    assert receipt["extraction"]["odometer"] == 3610                       # the original read is kept
    assert receipt["draft"].recommendations == []


def test_confirm_a_credit_read_with_a_negative_quantity(signed_in, conn, reads, outback):
    credit = fx.line("COOPER ENDEAVOR+ manufacturer warranty credit", -35.11, (), "perform", "other")
    reads.append(fx.extraction(lines=[fx.line(), credit.model_copy(update={"quantity": -1.0})], total=34.80))
    _upload(signed_in, ("a.pdf", _pdf()))
    receipt_id = _only_receipt(conn)
    page = signed_in.get(f"/receipts/{receipt_id}").text
    response = signed_in.post(f"/receipts/{receipt_id}", data=_form(page, receipt_id, vehicle_id=str(outback),
                                                                     total="34.80"), follow_redirects=False)
    assert response.status_code == 303

    event = services.get_event(conn, receipts.get(conn, receipt_id)["service_event_id"])
    assert [(line["quantity"], line["amount_cents"]) for line in event["lines"]] == [(None, 6715), (-1.0, -3511)]


def test_confirm_needs_a_car(signed_in, conn, reads):
    vehicles.create(conn, vehicles.VehicleFields(name="One"))
    vehicles.create(conn, vehicles.VehicleFields(name="Two"))
    _upload(signed_in, ("a.pdf", _pdf()))
    receipt_id = _only_receipt(conn)
    page = signed_in.get(f"/receipts/{receipt_id}").text
    response = signed_in.post(f"/receipts/{receipt_id}", data=_form(page, receipt_id))
    assert response.status_code == 422
    assert "Choose the car this receipt is for." in response.text


def test_save_draft_keeps_it_unconfirmed(signed_in, conn, reads, outback):
    _upload(signed_in, ("a.pdf", _pdf()))
    receipt_id = _only_receipt(conn)
    page = signed_in.get(f"/receipts/{receipt_id}").text
    signed_in.post(f"/receipts/{receipt_id}", data=_form(page, receipt_id, action="save", shop="Fixed name"))
    receipt = receipts.get(conn, receipt_id)
    assert receipt["status"] == "read" and receipt["draft"].shop == "Fixed name"
    assert services.history(conn, outback) == []
    assert 'class=" is-edited"' in signed_in.get(f"/receipts/{receipt_id}").text   # the shop field shows it changed


def test_a_confirmed_receipt_stays_correctable(signed_in, conn, reads, outback):
    _upload(signed_in, ("a.pdf", _pdf()))
    receipt_id = _only_receipt(conn)
    page = signed_in.get(f"/receipts/{receipt_id}").text
    signed_in.post(f"/receipts/{receipt_id}", data=_form(page, receipt_id, vehicle_id=str(outback)))
    event_id = receipts.get(conn, receipt_id)["service_event_id"]

    page = signed_in.get(f"/receipts/{receipt_id}").text
    assert "Save changes" in page and "data-read" not in page
    signed_in.post(f"/receipts/{receipt_id}", data=_form(page, receipt_id, vehicle_id=str(outback), total="80.00"))
    assert services.get_event(conn, event_id)["total_cents"] == 8000
    assert conn.execute("SELECT count(*) FROM service_events").fetchone()[0] == 1


def test_offers_fill_empty_car_fields_only(signed_in, conn, reads):
    car = vehicles.create(conn, vehicles.VehicleFields(name="Outback", make="Subaru", model="Outback"))
    reads.append(fx.extraction(plate="ABC1234", delivery_date="2016-03-01"))
    _upload(signed_in, ("a.pdf", _pdf()))
    receipt_id = _only_receipt(conn)
    page = signed_in.get(f"/receipts/{receipt_id}").text
    assert "Save plate ABC1234 to Outback" in page
    form = _form(page, receipt_id, vehicle_id=str(car), printed_plate="ABC1234", delivery_date="2016-03-01",
                 set_plate="1", set_in_service="1")
    signed_in.post(f"/receipts/{receipt_id}", data=form)
    row = vehicles.get(conn, car)
    assert row["plate"] == "ABC1234" and row["in_service_date"] == "2016-03-01"


def test_estimates_say_so(signed_in, conn, reads, outback):
    reads.append(fx.extraction(document_kind="estimate"))
    _upload(signed_in, ("a.pdf", _pdf()))
    page = signed_in.get(f"/receipts/{_only_receipt(conn)}").text
    assert "This looks like an estimate or quote, not an invoice." in page
    assert "Confirm it only if the work was actually done." in page


def test_discard_restore_and_read_again(signed_in, conn, reads, outback):
    _upload(signed_in, ("a.pdf", _pdf()))
    receipt_id = _only_receipt(conn)
    signed_in.post(f"/receipts/{receipt_id}/discard")
    assert receipts.get(conn, receipt_id)["status"] == "discarded"
    signed_in.post(f"/receipts/{receipt_id}/restore")
    assert receipts.get(conn, receipt_id)["status"] == "read"
    reads.append(fx.extraction(shop_name="Read twice"))
    signed_in.post(f"/receipts/{receipt_id}/read-again")
    assert receipts.get(conn, receipt_id)["draft"].shop == "Read twice"


# ---------- The service it becomes ----------


def test_receipt_backed_service_links_back_and_releases_on_delete(signed_in, conn, reads, outback):
    _upload(signed_in, ("a.pdf", _pdf()))
    receipt_id = _only_receipt(conn)
    page = signed_in.get(f"/receipts/{receipt_id}").text
    signed_in.post(f"/receipts/{receipt_id}", data=_form(page, receipt_id, vehicle_id=str(outback)))
    event_id = receipts.get(conn, receipt_id)["service_event_id"]

    service_page = signed_in.get(f"/services/{event_id}").text
    assert f'href="/receipts/{receipt_id}"' in service_page and "Brake fluid flush" in service_page
    edit = signed_in.get(f"/services/{event_id}/edit", follow_redirects=False)
    assert edit.headers["location"] == f"/receipts/{receipt_id}"

    signed_in.post(f"/services/{event_id}/delete")
    assert receipts.get(conn, receipt_id)["status"] == "read"


# ---------- Finding a confirmed receipt ----------


def _confirmed(conn, car, day, shop, total, work):
    """A receipt read and confirmed for the car, straight through the repo."""
    document, _ = documents.store(conn, _pdf(f"{day} {shop}"), f"{shop}.pdf")
    job_id = jobs.create(conn, "read_receipts")
    receipt_id = receipts.create(conn, document["id"], job_id)
    receipts.claim_next(conn, job_id)
    extraction = fx.extraction(date=day, shop_name=shop, odometer=None, lines=[fx.line(work, total, ())],
                               recommendations=[], subtotal=total, tax=0, total=total)
    types = {row["code"]: dict(row) for row in services.list_types(conn)}
    receipts.mark_read(conn, receipt_id, extraction.model_dump(), drafts.from_extraction(extraction, types), [], fx.USAGE)
    receipts.confirm(conn, receipt_id, receipts.get(conn, receipt_id)["draft"], car)
    return receipt_id


@pytest.fixture
def history(conn, outback):
    """Three receipts, confirmed out of date order, across two cars and three years."""
    forester = vehicles.create(conn, vehicles.VehicleFields(name="Forester"))
    return {
        "2019": _confirmed(conn, outback, "2019-08-15", "Corner Garage", 77.79, "Oil change"),
        "2024": _confirmed(conn, outback, "2024-03-11", "Midas", 412.37, "Front brake pads"),
        "2022": _confirmed(conn, forester, "2022-05-02", "Midas", 1234.00, "Timing belt kit"),
    }, forester


def _listed(page: str, ids: dict) -> list[str]:
    """Which of the receipts the page lists, in its order."""
    return sorted((key for key in ids if f'href="/receipts/{ids[key]}"' in page),
                  key=lambda key: page.index(f'href="/receipts/{ids[key]}"'))


def test_confirmed_receipts_are_listed_newest_receipt_date_first(signed_in, history):
    ids, _ = history
    assert _listed(signed_in.get("/receipts").text, ids) == ["2024", "2022", "2019"]
    assert _listed(signed_in.get("/receipts?sort=oldest").text, ids) == ["2019", "2022", "2024"]
    assert _listed(signed_in.get("/receipts?sort=total").text, ids) == ["2022", "2024", "2019"]


def test_a_search_shows_only_what_matches_and_why(signed_in, history):
    ids, _ = history
    page = signed_in.get("/receipts?q=brake").text
    assert _listed(page, ids) == ["2024"]
    assert "Showing 1 of 3." in page and "Front <mark>brake</mark> pads" in page
    assert 'value="brake"' in page and "Confirmed (3)" in page


def test_car_year_and_search_narrow_together(signed_in, history):
    ids, forester = history
    assert _listed(signed_in.get(f"/receipts?q=midas&car={forester}").text, ids) == ["2022"]
    assert _listed(signed_in.get("/receipts?q=midas&year=2024").text, ids) == ["2024"]
    page = signed_in.get(f"/receipts?q=oil&car={forester}&sort=oldest").text
    assert _listed(page, ids) == []
    assert 'No confirmed receipts match. <a href="/receipts?sort=oldest">Show all 3</a>' in page


def test_car_and_year_are_only_offered_when_there_is_a_choice(signed_in, conn, outback):
    _confirmed(conn, outback, "2024-03-11", "Midas", 412.37, "Front brake pads")
    _confirmed(conn, outback, "2024-06-01", "Midas", 50.00, "Wiper blades")
    page = signed_in.get(f"/receipts?car={outback}&year=2024").text
    assert 'name="q"' in page and 'name="sort"' in page
    assert 'name="car"' not in page and 'name="year"' not in page
    assert "Showing" not in page                                   # and nothing filters out of sight


def test_the_search_box_keeps_the_address_bar_in_step(signed_in, history):
    response = signed_in.get("/receipts?q=brake&car=&year=&sort=newest", headers={"HX-Request": "true"})
    assert response.headers["HX-Replace-Url"] == "/receipts?q=brake"
    assert "HX-Replace-Url" not in signed_in.get("/receipts?q=brake").headers


def test_polling_while_reading_leaves_the_confirmed_list_alone(signed_in, conn, history, monkeypatch):
    monkeypatch.setattr(background, "spawn", lambda job_id: None)   # stays queued
    _upload(signed_in, ("new.pdf", _pdf("new")))
    polled = signed_in.get("/receipts/list").text
    assert 'hx-trigger="every 2s"' in polled
    assert "Confirmed (" not in polled and 'name="q"' not in polled


# ---------- Files ----------


def test_page_images_and_original_file(signed_in, conn, reads):
    _upload(signed_in, ("a.pdf", _pdf()))
    document_id, sha = conn.execute("SELECT id, sha256 FROM documents").fetchone()
    image = signed_in.get(f"/documents/{document_id}/pages/1?v={sha[:12]}")
    assert image.headers["content-type"] == "image/jpeg" and "immutable" in image.headers["cache-control"]
    assert signed_in.get(f"/documents/{document_id}/pages/2").status_code == 404
    original = signed_in.get(f"/documents/{document_id}/file?v={sha[:12]}")
    assert original.headers["content-type"] == "application/pdf" and "immutable" in original.headers["cache-control"]
    assert original.content.startswith(b"%PDF")


@pytest.mark.parametrize("v", ["", "?v=000000000000"])
def test_a_link_that_doesnt_name_the_file_is_checked_each_time(signed_in, conn, reads, v):
    """After a restore or a fresh database, the same id can be a different file."""
    _upload(signed_in, ("a.pdf", _pdf()))
    document_id = conn.execute("SELECT id FROM documents").fetchone()[0]
    for url in (f"/documents/{document_id}/pages/1{v}", f"/documents/{document_id}/file{v}"):
        assert signed_in.get(url).headers["cache-control"] == "private, no-cache"


def test_files_need_a_session(client, conn, reads):
    assert client.get("/documents/1/pages/1", follow_redirects=False).status_code == 303


def test_review_offers_the_cars_schedule_to_tag_lines_from(signed_in, conn, reads, outback):
    from amg.repo import schedules
    from amg.repo.schedules import ItemInput

    draft_id = schedules.create_draft(conn, outback, "template", draft={"origin": "template", "items": []})
    schedules.confirm(conn, draft_id, outback, [ItemInput("Engine oil and filter", "replace", ["engine_oil", "oil_filter"],
                                                          interval_months=12)], {"origin": "template", "items": []})
    reads.append(fx.extraction(vin=OUTBACK_VIN))
    _upload(signed_in, ("a.pdf", _pdf()))
    page = signed_in.get(f"/receipts/{_only_receipt(conn)}").text
    assert [job["name"] for job in _editor(page)["schedule"]] == ["Engine oil and filter"]
    assert "From the Outback's schedule…" in page


def test_review_without_a_car_has_no_schedule(signed_in, conn, reads):
    _upload(signed_in, ("a.pdf", _pdf()))
    page = signed_in.get(f"/receipts/{_only_receipt(conn)}").text
    assert _editor(page)["schedule"] == [] and "line__schedule" not in page
