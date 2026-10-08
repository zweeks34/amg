"""A car's specs card: the card itself, typing it in, and checking Claude's reading of the manual.

A reading ends on a review screen, as a schedule draft does: the pages beside
the same boxes as Edit specs, filled with what Claude read. Nothing counts
until Use these specs, which replaces the card with what was checked.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.datastructures import UploadFile
from starlette.responses import RedirectResponse, Response

from ..ingest import background, manuals
from ..repo import documents, specs
from . import forms
from . import specs as spec_words
from .deps import get_conn
from .routes_vehicles import vehicle_or_404
from .templating import render

router = APIRouter()


# ---------- The card ----------


@router.get("/vehicles/{vehicle_id}/specs")
def card(request: Request, vehicle_id: int, saved: int | None = None,
         conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    return _card(request, conn, vehicle_or_404(conn, vehicle_id), saved=bool(saved))


@router.post("/vehicles/{vehicle_id}/specs/read")
async def read(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    form = await request.form()
    parts = [(await f.read(), f.filename or "manual") for f in form.getlist("files")
             if isinstance(f, UploadFile) and f.filename]
    chosen = forms.text(form.get("document_id"))
    raw = {"pages": forms.text(form.get("pages")), "document_id": chosen}
    errors: dict[str, str] = {}
    document = None
    if parts:
        try:
            data, name = documents.combine(parts) if len(parts) > 1 else parts[0]
            document, _ = documents.store(conn, data, name)
        except documents.UploadError as err:
            errors["files"] = str(err)
    elif chosen:
        known = {str(f["id"]) for f in specs.car_files(conn, vehicle_id)}
        document = documents.get(conn, int(chosen)) if chosen in known else None
        if document is None:
            errors["files"] = "Choose one of the files listed, or upload one."
    else:
        errors["files"] = "Choose the manual, or photos of its spec pages."
    if document is not None and raw["pages"]:
        try:
            manuals.parse_pages(raw["pages"], document["page_count"])
        except ValueError as err:
            errors["pages"] = str(err)
    if errors:
        return _card(request, conn, car, errors=errors, raw=raw, status_code=422)
    read_id = background.read_specs(conn, vehicle_id, document["id"], raw["pages"])  # type: ignore[index]
    return RedirectResponse(f"/spec-reads/{read_id}", status_code=303)


# ---------- Typing them in ----------


@router.get("/vehicles/{vehicle_id}/specs/edit")
def edit(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    return _form(request, conn, car, spec_words.raw_from(specs.values(conn, vehicle_id)), {})


@router.post("/vehicles/{vehicle_id}/specs/edit")
async def save(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    form = await request.form()
    inputs, raw, errors = spec_words.parse(form, specs.values(conn, vehicle_id))
    if errors:
        return _form(request, conn, car, raw, errors, status_code=422)
    specs.save(conn, vehicle_id, inputs)
    return RedirectResponse(f"/vehicles/{vehicle_id}/specs?saved=1", status_code=303)


# ---------- Checking a reading ----------


@router.get("/spec-reads/{read_id}")
def review(request: Request, read_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    return _review(request, conn, _read_or_404(conn, read_id))


@router.post("/spec-reads/{read_id}")
async def use(request: Request, read_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _read_or_404(conn, read_id)
    if row["status"] != "read":
        return RedirectResponse(f"/spec-reads/{read_id}", status_code=303)
    form = await request.form()
    stored = specs.values(conn, row["vehicle_id"])
    inputs, raw, errors = spec_words.parse(form, stored, read=row["values"], document_id=row["document_id"])
    if errors:
        return _review(request, conn, row, raw=raw, errors=errors, status_code=422)
    specs.use_read(conn, read_id, row["vehicle_id"], inputs)
    return RedirectResponse(f"/vehicles/{row['vehicle_id']}/specs?saved=1", status_code=303)


@router.post("/spec-reads/{read_id}/read-again")
async def read_again(request: Request, read_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _read_or_404(conn, read_id)
    if row["status"] not in ("read", "failed"):
        return RedirectResponse(f"/spec-reads/{read_id}", status_code=303)
    form = await request.form()
    pages = forms.text(form.get("pages")) if "pages" in form else None
    if pages and row["document"]:
        try:
            manuals.parse_pages(pages, row["document"]["page_count"])
        except ValueError as err:
            return _review(request, conn, row, problems={"pages": str(err)}, pages_raw=pages, status_code=422)
    background.read_specs_again(conn, read_id, pages)
    return RedirectResponse(f"/spec-reads/{read_id}", status_code=303)


@router.post("/spec-reads/{read_id}/carry-on")
def carry_on(read_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _read_or_404(conn, read_id)
    if row["stalled"] and row["job_id"]:
        background.carry_on(conn, row["job_id"])
    return RedirectResponse(f"/spec-reads/{read_id}", status_code=303)


@router.post("/spec-reads/{read_id}/discard")
def discard(read_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _read_or_404(conn, read_id)
    specs.discard(conn, read_id)
    return RedirectResponse(f"/vehicles/{row['vehicle_id']}/specs", status_code=303)


# ---------- Helpers ----------


def _read_or_404(conn: sqlite3.Connection, read_id: int) -> dict:
    row = specs.get_read(conn, read_id)
    if row is None:
        raise HTTPException(status_code=404)
    return row


def _card(request: Request, conn: sqlite3.Connection, car, errors: dict | None = None, raw: dict | None = None,
          saved: bool = False, status_code: int = 200) -> Response:
    return render(
        request,
        "specs.html",
        status_code=status_code,
        active="garage",
        car=car,
        car_words=spec_words.car_words(car),
        groups=spec_words.card(conn, car),
        fitted_words=spec_words.fitted_words,
        reads=specs.open_reads(conn, car["id"]),
        files=specs.car_files(conn, car["id"]),
        errors=errors or {},
        raw=raw or {},
        saved=saved,
    )


def _form(request: Request, conn: sqlite3.Connection, car, raw: dict, errors: dict,
          status_code: int = 200) -> Response:
    return render(
        request,
        "specs_edit.html",
        status_code=status_code,
        active="garage",
        car=car,
        groups=spec_words.boxes(conn, car, raw),
        custom=spec_words.custom_lines(raw, errors),
        errors=errors,
    )


def _review(request: Request, conn: sqlite3.Connection, row: dict, raw: dict | None = None,
            errors: dict | None = None, problems: dict | None = None, pages_raw: str | None = None,
            status_code: int = 200) -> Response:
    car = row["vehicle"]
    stored = specs.values(conn, car["id"])
    if raw is None:   # each box starts from what Claude read, else from what the card has
        raw = spec_words.raw_from(stored)
        raw.update({spec_words.FIELD_PREFIX + key: value["value"] for key, value in row["values"].items()})
    reading = row["status"] == "read"
    return render(
        request,
        "spec_read.html",
        status_code=status_code,
        active="garage",
        row=row,
        car=car,
        document=row["document"],
        printed_for=(row["extraction"] or {}).get("printed_for", ""),
        groups=spec_words.boxes(conn, car, raw, read=row["values"], stored=stored) if reading else [],
        custom=spec_words.custom_lines(raw, errors) if reading else [],
        errors=errors or {},
        problems=problems or {},
        pages_raw=row["requested_pages"] if pages_raw is None else pages_raw,
    )
