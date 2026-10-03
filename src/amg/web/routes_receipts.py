"""Receipts: upload, watch them being read, and check each one.

The review screen edits the receipt's draft — every field, every line, the
car — beside the scan. Confirming writes the service; a confirmed receipt
opens on the same screen and can be corrected and saved again at any time.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.datastructures import UploadFile
from starlette.responses import FileResponse, RedirectResponse, Response

from ..ingest import background, drafts, vin as vins
from ..ingest.drafts import Draft
from ..ingest.receipts import DOCUMENT_KINDS, ReceiptExtraction
from ..repo import documents, odometer, receipts, services, vehicles
from . import forms, line_editor
from .deps import get_conn
from .routes_services import KIND_LABELS, editor_types
from .templating import render

router = APIRouter()

DOCUMENT_KIND_LABELS = {
    "invoice": "Invoice or receipt",
    "estimate": "Estimate or quote",
    "deposit": "Deposit receipt",
    "inspection_report": "Inspection report",
    "other": "Something else",
}
_FIELDS = (
    "document_kind", "performed_on", "odometer", "shop", "invoice_number", "printed_vin", "printed_plate",
    "printed_vehicle", "delivery_date", "next_service_date", "next_service_miles", "tax", "total", "notes",
)


# ---------- The inbox ----------


@router.get("/receipts")
def inbox(request: Request, confirmed: int | None = None, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    return _inbox(request, conn, confirmed=confirmed)


@router.get("/receipts/list")
def inbox_list(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    """The receipt lists alone — what the inbox polls while anything is being read."""
    return render(request, "_receipt_list.html", groups=receipts.inbox(conn))


@router.post("/receipts/upload")
async def upload(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    form = await request.form()
    files = [f for f in form.getlist("files") if isinstance(f, UploadFile) and f.filename]
    chosen = form.get("vehicle_id") or ""
    vehicle_id = int(chosen) if chosen.isdigit() and vehicles.get(conn, int(chosen)) else None
    parts = [(await f.read(), f.filename or "upload") for f in files]

    problems: list[str] = []
    already: list[dict] = []
    new_documents: list[int] = []
    if not parts:
        problems.append("Choose at least one file to upload.")
    if form.get("combine") and len(parts) > 1:
        try:
            parts = [documents.combine(parts)]
        except documents.UploadError as err:
            problems.append(str(err))
            parts = []
    for data, name in parts:
        try:
            document, created = documents.store(conn, data, name)
        except documents.UploadError as err:
            problems.append(str(err))
            continue
        existing = None if created else receipts.for_document(conn, document["id"])
        if existing:
            already.append({"filename": name, "receipt_id": existing["id"]})
        else:
            new_documents.append(document["id"])
    if new_documents:
        background.start(conn, new_documents, vehicle_id)
    return _inbox(
        request, conn,
        added=len(new_documents), already=already, problems=problems,
        status_code=422 if problems and not new_documents and not already else 200,
    )


@router.post("/jobs/{job_id}/carry-on")
def carry_on(job_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    background.carry_on(conn, job_id)
    return RedirectResponse("/receipts", status_code=303)


# ---------- One receipt ----------


@router.get("/receipts/{receipt_id}")
def review(
    request: Request,
    receipt_id: int,
    confirmed: int | None = None,
    saved: int | None = None,
    conn: sqlite3.Connection = Depends(get_conn),
) -> Response:
    receipt = _receipt_or_404(conn, receipt_id)
    return _review(request, conn, receipt, confirmed=confirmed, saved=bool(saved))


@router.post("/receipts/{receipt_id}")
async def save(request: Request, receipt_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    receipt = _receipt_or_404(conn, receipt_id)
    if receipt["status"] not in ("read", "confirmed"):
        return RedirectResponse(f"/receipts/{receipt_id}", status_code=303)
    form = await request.form()
    action = form.get("action", "save")
    raw = {key: forms.text(form.get(key)) for key in _FIELDS}
    raw["vehicle_id"] = forms.text(form.get("vehicle_id"))
    rows = line_editor.clean_lines(form.get("lines_json")) or [line_editor.blank_line()]
    recs = line_editor.clean_recs(form.get("recs_json"))
    types = {row["code"]: row for row in services.list_types(conn)}

    errors: dict[str, str] = {}
    draft, line_errors, rec_errors = _read(raw, rows, recs, types, receipt["draft"], errors)
    vehicle_id = int(raw["vehicle_id"]) if raw["vehicle_id"].isdigit() and vehicles.get(conn, int(raw["vehicle_id"])) else None

    updates: dict[str, str] = {}
    if action == "confirm":
        if vehicle_id is None:
            errors["vehicle_id"] = "Choose the car this receipt is for."
        if not draft.performed_on and "performed_on" not in errors:
            errors["performed_on"] = "Enter the date of the service."
        if not draft.shop:
            errors["shop"] = "Name the shop."
        if not draft.lines and not any(line_errors):
            errors["lines"] = "Add at least one thing that was done, or discard the receipt."
        if vehicle_id and draft.performed_on and draft.odometer is not None:
            ignore = ("service", receipt["service_event_id"]) if receipt["service_event_id"] else None
            if clash := odometer.conflict(conn, vehicle_id, draft.performed_on, draft.odometer, ignore=ignore):
                errors["odometer"] = clash.message()
        updates = _car_updates(conn, form, draft, vehicle_id, errors)
        if draft.total_cents is None and any(line.get("amount_cents") is not None for line in draft.lines):
            draft.total_cents = sum(line.get("amount_cents") or 0 for line in draft.lines) + (draft.tax_cents or 0)

    if errors or any(line_errors) or any(rec_errors):
        return _review(request, conn, receipt, raw=raw, rows=rows, recs=recs, errors=errors,
                       line_errors=line_errors, rec_errors=rec_errors, status_code=422)

    if action == "confirm":
        receipts.confirm(conn, receipt_id, draft, vehicle_id, updates)  # type: ignore[arg-type]
        upcoming = receipts.next_to_check(conn, after_id=receipt_id)
        target = f"/receipts/{upcoming}?confirmed={receipt_id}" if upcoming else f"/receipts?confirmed={receipt_id}"
        return RedirectResponse(target, status_code=303)
    receipts.save_draft(conn, receipt_id, draft, vehicle_id)
    return RedirectResponse(f"/receipts/{receipt_id}?saved=1", status_code=303)


@router.post("/receipts/{receipt_id}/discard")
def discard(receipt_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    _receipt_or_404(conn, receipt_id)
    receipts.discard(conn, receipt_id)
    upcoming = receipts.next_to_check(conn, after_id=receipt_id)
    return RedirectResponse(f"/receipts/{upcoming}" if upcoming else "/receipts", status_code=303)


@router.post("/receipts/{receipt_id}/restore")
def restore(receipt_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    _receipt_or_404(conn, receipt_id)
    receipts.restore(conn, receipt_id)
    return RedirectResponse(f"/receipts/{receipt_id}", status_code=303)


@router.post("/receipts/{receipt_id}/read-again")
def read_again(receipt_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    receipt = _receipt_or_404(conn, receipt_id)
    if receipt["status"] in ("read", "failed"):
        background.read_again(conn, receipt_id)
    return RedirectResponse("/receipts", status_code=303)


# ---------- The files ----------


@router.get("/documents/{document_id}/pages/{page}")
def page_image(document_id: int, page: int, size: str = "preview", v: str = "",
               conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    document = documents.get(conn, document_id)
    if document is None or not 1 <= page <= document["page_count"]:
        raise HTTPException(status_code=404)
    long_edge = documents.FULL_LONG_EDGE if size == "full" else documents.PREVIEW_LONG_EDGE
    return FileResponse(documents.page_image(document, page, long_edge), media_type="image/jpeg",
                        headers=_cache(document, v))


@router.get("/documents/{document_id}/file")
def original_file(document_id: int, v: str = "", conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    document = documents.get(conn, document_id)
    if document is None:
        raise HTTPException(status_code=404)
    return FileResponse(documents.path(document), media_type=document["media_type"],
                        filename=document["filename"], content_disposition_type="inline", headers=_cache(document, v))


def _cache(document, v: str) -> dict[str, str]:
    """Keep for good only when the URL names the file's content (``v``, its fingerprint).

    A document id alone isn't enough: restore a different backup, or start a
    fresh database, and the same id is another file — a browser that kept the
    old one would show the wrong scan. Without a matching ``v`` the browser
    asks again each time.
    """
    if v and v == documents.fingerprint(document["sha256"]):
        return {"Cache-Control": "private, max-age=31536000, immutable"}
    return {"Cache-Control": "private, no-cache"}


# ---------- Helpers ----------


def _receipt_or_404(conn: sqlite3.Connection, receipt_id: int) -> dict:
    receipt = receipts.get(conn, receipt_id)
    if receipt is None:
        raise HTTPException(status_code=404)
    return receipt


def _inbox(request: Request, conn: sqlite3.Connection, status_code: int = 200, **notices) -> Response:
    confirmed = notices.pop("confirmed", None)
    return render(
        request,
        "receipts.html",
        status_code=status_code,
        active="receipts",
        groups=receipts.inbox(conn),
        cars=[dict(r) for r in conn.execute("SELECT id, name FROM vehicles WHERE archived_at IS NULL ORDER BY name")],
        just_confirmed=receipts.get(conn, confirmed) if confirmed else None,
        **notices,
    )


def _raw_from(draft: Draft) -> dict[str, str]:
    return {
        "document_kind": draft.document_kind,
        "performed_on": draft.performed_on or "",
        "odometer": "" if draft.odometer is None else f"{draft.odometer:,}",
        "shop": draft.shop,
        "invoice_number": draft.invoice_number,
        "printed_vin": draft.printed_vin,
        "printed_plate": draft.printed_plate,
        "printed_vehicle": draft.printed_vehicle,
        "delivery_date": draft.delivery_date or "",
        "next_service_date": draft.next_service_date or "",
        "next_service_miles": "" if draft.next_service_miles is None else f"{draft.next_service_miles:,}",
        "tax": line_editor.dollars(draft.tax_cents),
        "total": line_editor.dollars(draft.total_cents),
        "notes": draft.notes,
    }


def _read(raw: dict, rows: list[dict], recs: list[dict], types: dict, previous: Draft | None,
          errors: dict[str, str]) -> tuple[Draft, list, list]:
    """The posted review form as a draft, with an error per bad field or row."""
    def parse(parser, key, **options):
        try:
            return parser(raw.get(key), **options)
        except ValueError as err:
            errors[key] = str(err)
            return None

    _, line_errors, draft_lines = line_editor.parse_lines(rows, types)
    draft_recs, rec_errors = line_editor.parse_recs(recs, types)
    draft = Draft(
        document_kind=raw["document_kind"] if raw.get("document_kind") in DOCUMENT_KINDS else "invoice",
        shop=raw.get("shop", ""),
        invoice_number=raw.get("invoice_number", ""),
        performed_on=parse(forms.day, "performed_on"),
        odometer=parse(forms.miles, "odometer"),
        printed_vin=vins.normalize(raw.get("printed_vin", "")),
        printed_plate=drafts.normalize_plate(raw.get("printed_plate", "")),
        printed_vehicle=raw.get("printed_vehicle", ""),
        delivery_date=parse(forms.day, "delivery_date"),
        next_service_date=parse(forms.day, "next_service_date", allow_future=True),
        next_service_miles=parse(forms.miles, "next_service_miles"),
        lines=draft_lines,
        recommendations=draft_recs,
        subtotal_cents=previous.subtotal_cents if previous else None,
        tax_cents=parse(forms.money, "tax"),
        total_cents=parse(forms.money, "total"),
        notes=raw.get("notes", ""),
        read_note=previous.read_note if previous else "",
    )
    return draft, line_errors, rec_errors


def _offers(draft: Draft, car: dict | None) -> list[dict]:
    """Details from the receipt that could fill an empty field on the car."""
    if not car:
        return []
    offers = []
    if draft.printed_plate and not car["plate"]:
        offers.append({"name": "set_plate", "label": f"Save plate {draft.printed_plate} to {car['name']}"})
    if draft.printed_vin and not car["vin"] and not vins.problem(draft.printed_vin):
        offers.append({"name": "set_vin", "label": f"Save VIN {draft.printed_vin} to {car['name']}",
                       "hint": "Only if it's really this car's VIN — shops sometimes print another car's."})
    if draft.delivery_date and not car["in_service_date"]:
        offers.append({"name": "set_in_service", "label": f"Use {draft.delivery_date} as {car['name']}'s in-service date",
                       "hint": "The invoice gives it as the delivery date."})
    return offers


def _car_updates(conn: sqlite3.Connection, form, draft: Draft, vehicle_id: int | None, errors: dict) -> dict[str, str]:
    updates: dict[str, str] = {}
    if vehicle_id is None:
        return updates
    if form.get("set_plate") and draft.printed_plate:
        updates["plate"] = draft.printed_plate
    if form.get("set_in_service") and draft.delivery_date:
        updates["in_service_date"] = draft.delivery_date
    if form.get("set_vin") and draft.printed_vin:
        if problem := vins.problem(draft.printed_vin):
            errors["set_vin"] = problem
        elif (owner := vehicles.vin_owner(conn, draft.printed_vin)) and owner != vehicle_id:
            errors["set_vin"] = "Another car in your garage already has this VIN."
        else:
            updates["vin"] = draft.printed_vin
    return updates


def _review(
    request: Request,
    conn: sqlite3.Connection,
    receipt: dict,
    raw: dict | None = None,
    rows: list[dict] | None = None,
    recs: list[dict] | None = None,
    errors: dict | None = None,
    line_errors: list | None = None,
    rec_errors: list | None = None,
    confirmed: int | None = None,
    saved: bool = False,
    status_code: int = 200,
) -> Response:
    draft: Draft | None = receipt["draft"]
    types_by_code = {row["code"]: dict(row) for row in services.list_types(conn)}
    reading = receipt["status"] == "read"
    original = None
    if receipt["extraction"]:
        original = drafts.from_extraction(ReceiptExtraction.model_validate(receipt["extraction"]), types_by_code)

    if draft is not None:
        raw = raw or {**_raw_from(draft), "vehicle_id": str(receipt["vehicle_id"] or "")}
        rows = rows or line_editor.rows_from_draft(draft.lines, original.lines if original else None) or [line_editor.blank_line()]
        recs = recs if recs is not None else line_editor.recs_from_draft(draft.recommendations)
    selected = vehicles.get(conn, int(raw["vehicle_id"])) if raw and str(raw.get("vehicle_id", "")).isdigit() else None
    car = dict(selected) if selected else None

    return render(
        request,
        "receipt.html",
        status_code=status_code,
        active="receipts",
        receipt=receipt,
        document=receipt["document"],
        draft=draft,
        raw=raw or {},
        read_raw=_raw_from(original) if (original and reading) else None,
        errors=errors or {},
        cars=[dict(r) for r in conn.execute("SELECT id, name, archived_at FROM vehicles ORDER BY archived_at IS NOT NULL, name")],
        car=car,
        mismatches=drafts.mismatches(draft, car) if (draft and car) else [],
        duplicates=receipts.possible_duplicates(conn, receipt["id"], draft) if draft else [],
        offers=_offers(draft, car) if draft else [],
        editor={
            "lines": rows or [],
            "errors": line_errors or [None] * len(rows or []),
            "recs": recs or [],
            "recErrors": rec_errors or [None] * len(recs or []),
            "types": editor_types(conn),
            "reading": reading,
        },
        kinds=KIND_LABELS,
        document_kinds=DOCUMENT_KIND_LABELS,
        just_confirmed=receipts.get(conn, confirmed) if confirmed else None,
        saved=saved,
    )
