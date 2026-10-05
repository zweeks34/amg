"""Inspections and registration: logging one from the car page, and correcting or deleting it."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import RedirectResponse, Response

from ..engine.renewals import KINDS
from ..repo import renewals, services
from ..repo.renewals import RenewalInput
from . import forms
from . import renewals as renewal_words
from .deps import get_conn
from .routes_vehicles import car_page, vehicle_or_404
from .templating import render

router = APIRouter()

_FIELDS = ("done_on", "expires_on", "cost", "note")


@router.post("/vehicles/{vehicle_id}/renewals")
async def add(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    if car["archived_at"]:
        raise HTTPException(status_code=404)
    form = await request.form()
    kind = forms.text(form.get("kind"))
    if kind not in KINDS:
        raise HTTPException(status_code=400)
    raw = {key: forms.text(form.get(key)) for key in (*_FIELDS, "service_event_id")}
    renewal, errors = _read(conn, vehicle_id, kind, raw, raw["service_event_id"])
    if errors:
        return car_page(request, conn, vehicle_id, renewal_form={"kind": kind, "raw": raw, "errors": errors},
                        status_code=422)
    renewals.create(conn, vehicle_id, renewal)
    return RedirectResponse(f"/vehicles/{vehicle_id}#renewals", status_code=303)


@router.get("/renewals/{renewal_id}/edit")
def edit(request: Request, renewal_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _or_404(conn, renewal_id)
    raw = {"done_on": row["done_on"] or "", "expires_on": row["expires_on"], "cost": renewal_words.cents(row["cost_cents"]),
           "note": row["note"]}
    return _form(request, conn, row, raw, errors={})


@router.post("/renewals/{renewal_id}/edit")
async def update(request: Request, renewal_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _or_404(conn, renewal_id)
    form = await request.form()
    raw = {key: forms.text(form.get(key)) for key in _FIELDS}
    renewal, errors = _read(conn, row["vehicle_id"], row["kind"], raw, row["service_event_id"])
    if errors:
        return _form(request, conn, row, raw, errors, status_code=422)
    renewals.update(conn, renewal_id, renewal)
    return RedirectResponse(f"/vehicles/{row['vehicle_id']}#renewals", status_code=303)


@router.post("/renewals/{renewal_id}/delete")
def delete(renewal_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _or_404(conn, renewal_id)
    renewals.delete(conn, renewal_id)
    return RedirectResponse(f"/vehicles/{row['vehicle_id']}#renewals", status_code=303)


# ---------- Helpers ----------


def _or_404(conn: sqlite3.Connection, renewal_id: int) -> sqlite3.Row:
    row = renewals.get(conn, renewal_id)
    if row is None:
        raise HTTPException(status_code=404)
    return row


def _form(request: Request, conn: sqlite3.Connection, row: sqlite3.Row, raw: dict, errors: dict,
          status_code: int = 200) -> Response:
    service = services.get_event(conn, row["service_event_id"]) if row["service_event_id"] else None
    return render(
        request,
        "renewal_form.html",
        status_code=status_code,
        active="garage",
        car=vehicle_or_404(conn, row["vehicle_id"]),
        renewal=row,
        kind=KINDS[row["kind"]],
        words=renewal_words.WORDS[row["kind"]],
        service=service,
        raw=raw,
        errors=errors,
    )


def _parse(parser, value: str, key: str, errors: dict, required: str | None = None):
    try:
        parsed = parser(value)
    except ValueError as err:
        errors[key] = str(err)
        return None
    if parsed is None and required:
        errors[key] = required
    return parsed


def _read(conn: sqlite3.Connection, vehicle_id: int, kind: str, raw: dict,
          service_id: str | int | None) -> tuple[RenewalInput, dict]:
    """The form, checked. A service stays linked only while the done date is its date: change the date and it's
    another inspection."""
    errors: dict[str, str] = {}
    done = _parse(forms.day, raw["done_on"], "done_on", errors)
    expires = _parse(lambda value: forms.day(value, allow_future=True), raw["expires_on"], "expires_on", errors,
                     required="Enter the date it expires.")
    cost = _parse(forms.money, raw["cost"], "cost", errors)
    if cost is not None and cost < 0:
        errors["cost"] = "Enter what it cost, like 20.00."
    if done and expires and expires < done:
        errors["expires_on"] = "That's before it was done."
    service = None
    if service_id and str(service_id).isdigit():
        event = services.get_event(conn, int(service_id))
        if event is not None and event["vehicle_id"] == vehicle_id and event["confirmed"] and event["performed_on"] == done:
            service = event["id"]
    return RenewalInput(kind, expires or "", done, cost, raw["note"], service), errors
