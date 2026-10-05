"""A small history for the report tests. tests/ is on pytest's path, so: import report_fixtures as rf.

The Outback:
    v1  2019-03-04  Midas #1234     brake pads $200 and an oil change $50, tax $12.50, total $270
                                    (so $7.50 of shop supplies the invoice didn't itemise)
    v2  2021-06-01  your own work   an oil change, $40, nothing else written down
    v3  2023-01-10  Corner Garage   a tire rotation, $30, no total
    v4  2024-05-05  done, no receipt  brake fluid, no amounts
    --  2022-02-02  Midas           brake pads $999 — never confirmed, so in nobody's history
The Civic:
    v6  2021-07-01  MIDAS Auto      brake rotors $300, total $300
"""

from __future__ import annotations

from io import BytesIO

import pymupdf
import receipt_fixtures as fx
from PIL import Image

from amg.ingest import drafts
from amg.repo import documents, jobs, receipts, services, vehicles
from amg.repo.services import Coverage, EventInput, LineInput


def line(description, cents, *codes, action="replace", kind="labor"):
    return LineInput(description, kind, amount_cents=cents, covers=[Coverage(code, action) for code in codes])


def visit(conn, car, day, source="shop", shop="", lines=(), total=None, tax=None, notes="", confirmed=True,
          odometer=None, invoice=""):
    return services.create_event(conn, car, EventInput(
        performed_on=day, source=source, odometer=odometer, shop=shop, invoice_number=invoice, tax_cents=tax,
        total_cents=total, notes=notes, lines=list(lines)), confirmed=confirmed)


def car(conn, name, **fields):
    return vehicles.create(conn, vehicles.VehicleFields(name=name, **fields))


def garage(conn) -> dict:
    """Builds the history above; returns the ids by name."""
    outback, civic = car(conn, "Outback"), car(conn, "Civic")
    ids = {"outback": outback, "civic": civic}
    ids["v1"] = visit(conn, outback, "2019-03-04", shop="Midas #1234", odometer=41_200, invoice="M-77",
                      lines=[line("Front brake pads", 20_000, "brake_pads"),
                             line("Oil and filter change", 5_000, "engine_oil", "oil_filter")],
                      tax=1_250, total=27_000)
    ids["v2"] = visit(conn, outback, "2021-06-01", source="diy",
                      lines=[line("Oil change", 4_000, "engine_oil", kind="part")])
    ids["v3"] = visit(conn, outback, "2023-01-10", shop="Corner Garage",
                      lines=[line("Tire rotation", 3_000, "tire_rotation", action="perform")])
    ids["v4"] = visit(conn, outback, "2024-05-05", source="attested",
                      lines=[line("Brake fluid", None, "brake_fluid")])
    ids["v5"] = visit(conn, outback, "2022-02-02", shop="Midas", confirmed=False,
                      lines=[line("Brake pads", 99_900, "brake_pads")])
    ids["v6"] = visit(conn, civic, "2021-07-01", shop="MIDAS Auto",
                      lines=[line("Brake rotors", 30_000, "brake_rotors")], total=30_000)
    return ids


# ---------- Receipts, for the sale packet and the data export ----------


def pdf_bytes(*pages):
    """A PDF with a page for each text given: the text is how a test finds the page again."""
    with pymupdf.open() as doc:
        for text in pages:
            doc.new_page(width=612, height=792).insert_text((72, 72), text)
        return doc.tobytes()


def image_bytes(fmt="PNG"):
    out = BytesIO()
    Image.new("RGB", (400, 600), "white").save(out, fmt)
    return out.getvalue()


def receipt(conn, car, data, filename, confirm=True, **fields):
    """A receipt read from a stored file; confirmed onto the car unless asked not to. Returns (receipt, service)."""
    document, _ = documents.store(conn, data, filename)
    job = jobs.create(conn, "read_receipts")
    receipt_id = receipts.create(conn, document["id"], job, car)
    receipts.claim_next(conn, job)
    extraction = fx.extraction(**fields)
    types = {row["code"]: dict(row) for row in services.list_types(conn)}
    draft = drafts.from_extraction(extraction, types, receipts.learned(conn))
    receipts.mark_read(conn, receipt_id, extraction.model_dump(), draft, [], fx.USAGE)
    event = receipts.confirm(conn, receipt_id, draft, car) if confirm else None
    return receipt_id, event
