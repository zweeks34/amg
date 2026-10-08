"""Services typed in by hand, and the catalogue of service types they map to.

A service that came from a receipt is edited on the receipt instead — the
draft there is the record it was written from — so its edit link goes to the
receipt, and deleting it sends the receipt back to be checked.

A shop recommendation's "Log it" opens the new-service form with the
recommendation as its first line; saving it closes the recommendation.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import RedirectResponse, Response

from ..engine.follow_ups import Recommendation
from ..ingest.drafts import Draft
from ..repo import follow_ups, odometer, receipts, services
from . import forms, line_editor
from .deps import get_conn
from .routes_vehicles import POWERTRAIN_LABELS, vehicle_or_404
from .templating import render

router = APIRouter()

SOURCE_LABELS = {"shop": "A shop", "diy": "I did it", "receipt": "From a receipt", "attested": "Done, no receipt"}
KIND_LABELS = {"labor": "Labor", "part": "Part", "fee": "Fee", "other": "Other"}
ACTION_LABELS = {"replace": "Replaced", "inspect": "Inspected", "perform": "Done"}
_FIELDS = ("performed_on", "odometer", "source", "shop", "invoice_number", "tax", "total", "notes",
           "follow_up_receipt", "follow_up")


# ---------- Log, view, edit, delete ----------


@router.get("/vehicles/{vehicle_id}/services/new")
def new_service(request: Request, vehicle_id: int, receipt: str = "", rec: str = "",
                conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    raw = {"performed_on": date.today().isoformat(), "source": "shop", "follow_up_receipt": receipt, "follow_up": rec}
    lines = [line_editor.blank_line()]
    if recommended := _recommended(conn, vehicle_id, raw):
        lines = [{**lines[0], "description": recommended.description, "covers": list(recommended.codes)}]
    return _form(request, conn, car, raw=raw, lines=lines, errors={})


@router.post("/vehicles/{vehicle_id}/services")
async def create_service(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    raw, rows = await _raw(request)
    event, errors, line_errors = _read(conn, vehicle_id, raw, rows)
    if errors or any(line_errors):
        return _form(request, conn, car, raw, rows, errors, line_errors, status_code=422)
    event_id = services.create_event(conn, vehicle_id, event)
    if recommended := _recommended(conn, vehicle_id, raw):
        follow_ups.done(conn, recommended.receipt_id, recommended.key, event_id)
    return RedirectResponse(f"/services/{event_id}", status_code=303)


@router.get("/services/{event_id}")
def service_page(request: Request, event_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    event = _event_or_404(conn, event_id)
    car = vehicle_or_404(conn, event["vehicle_id"])
    receipt = receipts.for_event(conn, event_id)
    draft = Draft.from_dict(json.loads(receipt["draft_json"])) if receipt and receipt["draft_json"] else None
    return render(
        request,
        "service.html",
        active="garage",
        car=car,
        event=event,
        receipt=receipt,
        draft=draft,
        type_names={row["code"]: row["name"] for row in services.list_types(conn)},
        sources=SOURCE_LABELS,
        kinds=KIND_LABELS,
        actions=ACTION_LABELS,
    )


@router.get("/services/{event_id}/edit")
def edit_service(request: Request, event_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    event = _event_or_404(conn, event_id)
    if receipt := receipts.for_event(conn, event_id):
        return RedirectResponse(f"/receipts/{receipt['id']}", status_code=303)
    car = vehicle_or_404(conn, event["vehicle_id"])
    raw = {
        "performed_on": event["performed_on"],
        "odometer": "" if event["odometer"] is None else f"{event['odometer']:,}",
        "source": event["source"],
        "shop": event["shop"],
        "invoice_number": event["invoice_number"],
        "tax": line_editor.dollars(event["tax_cents"]),
        "total": line_editor.dollars(event["total_cents"]),
        "notes": event["notes"],
    }
    rows = line_editor.rows_from_draft(event["lines"]) or [line_editor.blank_line()]
    return _form(request, conn, car, raw, rows, errors={}, event=event)


@router.post("/services/{event_id}/edit")
async def update_service(request: Request, event_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    existing = _event_or_404(conn, event_id)
    if receipt := receipts.for_event(conn, event_id):
        return RedirectResponse(f"/receipts/{receipt['id']}", status_code=303)
    car = vehicle_or_404(conn, existing["vehicle_id"])
    raw, rows = await _raw(request)
    event, errors, line_errors = _read(conn, car["id"], raw, rows, event_id=event_id)
    if errors or any(line_errors):
        return _form(request, conn, car, raw, rows, errors, line_errors, event=existing, status_code=422)
    services.update_event(conn, event_id, event)
    return RedirectResponse(f"/services/{event_id}", status_code=303)


@router.post("/services/{event_id}/delete")
def delete_service(event_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    event = _event_or_404(conn, event_id)
    receipts.release_event(conn, event_id)
    services.delete_event(conn, event_id)
    return RedirectResponse(f"/vehicles/{event['vehicle_id']}", status_code=303)


# ---------- Service types ----------


@router.get("/service-types")
def service_types(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    return _types_page(request, conn, raw={}, errors={})


@router.post("/service-types")
async def add_service_type(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    form = await request.form()
    raw = {key: forms.text(form.get(key)) for key in ("name", "category", "default_action")}
    categories = _categories(conn)
    errors: dict[str, str] = {}
    if raw["category"] not in categories:
        errors["category"] = "Choose a category."
    if not errors:
        try:
            services.add_custom_type(conn, raw["name"], raw["category"], raw["default_action"] or "replace")
        except ValueError as err:
            errors["name"] = str(err)
    if errors:
        return _types_page(request, conn, raw=raw, errors=errors, status_code=422)
    return RedirectResponse("/service-types#custom", status_code=303)


# ---------- Helpers ----------


def editor_types(conn: sqlite3.Connection, powertrain: str | None = None, in_use: set[str] | None = None) -> list[dict]:
    """The service types the editor offers: those for the powertrain, plus any already chosen."""
    in_use = in_use or set()
    return [
        {"code": row["code"], "name": row["name"], "category": row["category"]}
        for row in services.list_types(conn)
        if powertrain is None or powertrain in row["powertrains"].split(",") or row["code"] in in_use
    ]


def _recommended(conn: sqlite3.Connection, vehicle_id: int, raw: dict) -> Recommendation | None:
    """The shop recommendation the form is logging, if it was opened from one of this car's."""
    receipt = raw.get("follow_up_receipt", "")
    found = follow_ups.find(conn, int(receipt), raw.get("follow_up", "")) if receipt.isdigit() else None
    return found[0] if found and found[1] == vehicle_id else None


def _event_or_404(conn: sqlite3.Connection, event_id: int) -> dict:
    event = services.get_event(conn, event_id)
    if event is None:
        raise HTTPException(status_code=404)
    return event


def _categories(conn: sqlite3.Connection) -> list[str]:
    seen: list[str] = []
    for row in services.list_types(conn):
        if row["category"] not in seen:
            seen.append(row["category"])
    return seen


def _types_page(request: Request, conn: sqlite3.Connection, raw: dict, errors: dict, status_code: int = 200) -> Response:
    grouped: dict[str, list] = {}
    for row in services.list_types(conn):
        grouped.setdefault(row["category"], []).append(row)
    return render(
        request,
        "service_types.html",
        status_code=status_code,
        active="garage",
        grouped=grouped,
        powertrains=POWERTRAIN_LABELS,
        actions=ACTION_LABELS,
        raw=raw,
        errors=errors,
    )


def _form(
    request: Request,
    conn: sqlite3.Connection,
    car: sqlite3.Row,
    raw: dict,
    lines: list[dict],
    errors: dict,
    line_errors: list[str | None] | None = None,
    event: dict | None = None,
    status_code: int = 200,
) -> Response:
    in_use = {code for line in lines for code in line.get("covers", [])}
    return render(
        request,
        "service_form.html",
        status_code=status_code,
        active="garage",
        car=car,
        event=event,
        raw=raw,
        errors=errors,
        editor={
            "lines": lines,
            "errors": line_errors or [None] * len(lines),
            "types": editor_types(conn, car["powertrain"], in_use),
        },
        sources=SOURCE_LABELS,
        kinds=KIND_LABELS,
        recommended=None if event else _recommended(conn, car["id"], raw),
    )


async def _raw(request: Request) -> tuple[dict[str, str], list[dict]]:
    form = await request.form()
    raw = {key: forms.text(form.get(key)) for key in _FIELDS}
    return raw, line_editor.clean_lines(form.get("lines_json")) or [line_editor.blank_line()]


def _read(
    conn: sqlite3.Connection,
    vehicle_id: int,
    raw: dict,
    rows: list[dict],
    event_id: int | None = None,
) -> tuple[services.EventInput, dict, list[str | None]]:
    errors: dict[str, str] = {}

    def parse(parser, key, required=None):
        try:
            value = parser(raw.get(key))
        except ValueError as err:
            errors[key] = str(err)
            return None
        if value is None and required:
            errors[key] = required
        return value

    performed_on = parse(forms.day, "performed_on", required="Enter the date of the service.")
    miles = parse(forms.miles, "odometer")
    tax = parse(forms.money, "tax")
    total = parse(forms.money, "total")
    source = raw.get("source") if raw.get("source") in ("shop", "diy") else "shop"
    if source == "shop" and not raw.get("shop"):
        errors["shop"] = "Name the shop, or choose “I did it”."
    if performed_on and miles is not None:
        ignore = ("service", event_id) if event_id else None
        if clash := odometer.conflict(conn, vehicle_id, performed_on, miles, ignore=ignore):
            errors["odometer"] = clash.message()

    types = {row["code"]: row for row in services.list_types(conn)}
    lines, line_errors, _ = line_editor.parse_lines(rows, types)
    if not lines and not any(line_errors):
        errors["lines"] = "Add at least one thing that was done."

    if total is None and any(line.amount_cents is not None for line in lines):
        total = sum(line.amount_cents or 0 for line in lines) + (tax or 0)

    event = services.EventInput(
        performed_on=performed_on or "",
        source=source,
        odometer=miles,
        shop=raw.get("shop", "") if source == "shop" else "",
        invoice_number=raw.get("invoice_number", "") if source == "shop" else "",
        tax_cents=tax,
        total_cents=total,
        notes=raw.get("notes", ""),
        lines=lines,
    )
    return event, errors, line_errors
