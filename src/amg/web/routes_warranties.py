"""Warranties you add yourself: the car's own from its booklet, an extended one you bought, or a part you fitted.

A receipt's warranties are edited on the receipt, whose draft is the
record; their pages here send you there.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import RedirectResponse, Response

from ..repo import services, warranties
from . import warranties as warranty_words
from .deps import get_conn
from .routes_services import editor_types
from .routes_vehicles import vehicle_or_404
from .templating import render

router = APIRouter()


# ---------- Adding one ----------


@router.get("/vehicles/{vehicle_id}/warranties/new")
def new_warranty(request: Request, vehicle_id: int, service: int | None = None,
                 conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    """The form; ``service`` fills it in from the visit it came with."""
    car = vehicle_or_404(conn, vehicle_id)
    visit = next((v for v in warranties.visits(conn, vehicle_id) if v.id == service), None)
    # The server's local date, as the other forms'.
    raw = warranty_words.from_visit(visit) if visit else warranty_words.blank(car, date.today())
    return _form(request, conn, car, raw, {})


@router.post("/vehicles/{vehicle_id}/warranties")
async def create_warranty(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    warranty, raw, errors = warranty_words.parse(await request.form(), _types(conn), warranties.visits(conn, vehicle_id))
    if errors:
        return _form(request, conn, car, raw, errors, status_code=422)
    warranties.create(conn, vehicle_id, warranty)
    return RedirectResponse(f"/vehicles/{vehicle_id}#warranties", status_code=303)


# ---------- Changing one ----------


@router.get("/warranties/{warranty_id}/edit")
def edit_warranty(request: Request, warranty_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _warranty_or_404(conn, warranty_id)
    if row["receipt_id"]:
        return _to_receipt(row)
    car = vehicle_or_404(conn, row["vehicle_id"])
    return _form(request, conn, car, warranty_words.raw_from(row), {}, warranty=row)


@router.post("/warranties/{warranty_id}/edit")
async def update_warranty(request: Request, warranty_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _warranty_or_404(conn, warranty_id)
    if row["receipt_id"]:
        return _to_receipt(row)
    car = vehicle_or_404(conn, row["vehicle_id"])
    warranty, raw, errors = warranty_words.parse(await request.form(), _types(conn), warranties.visits(conn, car["id"]))
    if errors:
        return _form(request, conn, car, raw, errors, warranty=row, status_code=422)
    warranties.update(conn, warranty_id, warranty)
    return RedirectResponse(f"/vehicles/{car['id']}#warranties", status_code=303)


@router.post("/warranties/{warranty_id}/delete")
def delete_warranty(warranty_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _warranty_or_404(conn, warranty_id)
    if row["receipt_id"]:
        return _to_receipt(row)
    warranties.delete(conn, warranty_id)
    return RedirectResponse(f"/vehicles/{row['vehicle_id']}#warranties", status_code=303)


# ---------- Helpers ----------


def _warranty_or_404(conn: sqlite3.Connection, warranty_id: int) -> dict:
    row = warranties.get(conn, warranty_id)
    if row is None:
        raise HTTPException(status_code=404)
    return row


def _to_receipt(row: dict) -> Response:
    """One read from a receipt is changed there, where the scan is."""
    return RedirectResponse(f"/receipts/{row['receipt_id']}#warranties", status_code=303)


def _types(conn: sqlite3.Connection) -> dict:
    return {row["code"]: row for row in services.list_types(conn)}


def _form(request: Request, conn: sqlite3.Connection, car, raw: dict, errors: dict, warranty: dict | None = None,
          status_code: int = 200) -> Response:
    return render(
        request,
        "warranty_form.html",
        status_code=status_code,
        active="garage",
        car=car,
        warranty=warranty,
        raw=raw,
        errors=errors,
        visits=list(reversed(warranties.visits(conn, car["id"]))),
        editor={"codes": raw["codes"], "types": editor_types(conn, car["powertrain"], set(raw["codes"])),
                "covers": raw["covers"],
                "lifetime": bool(raw["lifetime"]), "inService": car["in_service_date"] or ""},
        today=date.today().isoformat(),
    )
