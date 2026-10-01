"""Services typed in by hand, and the catalogue of service types they map to.

The line editor on the form is an Alpine component that posts every line as
one JSON field (``lines_json``), which keeps rows, their service-type chips
and their checkboxes together however many are added or removed.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import RedirectResponse, Response

from ..repo import odometer, services
from . import forms
from .deps import get_conn
from .routes_vehicles import POWERTRAIN_LABELS, vehicle_or_404
from .templating import render

router = APIRouter()

SOURCE_LABELS = {"shop": "A shop", "diy": "I did it", "receipt": "From a receipt", "attested": "Done, no receipt"}
KIND_LABELS = {"labor": "Labor", "part": "Part", "fee": "Fee", "other": "Other"}
ACTION_LABELS = {"replace": "Replaced", "inspect": "Inspected", "perform": "Done"}
_FIELDS = ("performed_on", "odometer", "source", "shop", "invoice_number", "tax", "total", "notes")


# ---------- Log, view, edit, delete ----------


@router.get("/vehicles/{vehicle_id}/services/new")
def new_service(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    raw = {"performed_on": date.today().isoformat(), "source": "shop"}
    return _form(request, conn, car, raw=raw, lines=[_blank_line()], errors={})


@router.post("/vehicles/{vehicle_id}/services")
async def create_service(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    raw, lines_raw = await _raw(request)
    event, errors, line_errors = _read(conn, vehicle_id, raw, lines_raw)
    if errors or any(line_errors):
        return _form(request, conn, car, raw, lines_raw, errors, line_errors, status_code=422)
    event_id = services.create_event(conn, vehicle_id, event)
    return RedirectResponse(f"/services/{event_id}", status_code=303)


@router.get("/services/{event_id}")
def service_page(request: Request, event_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    event = _event_or_404(conn, event_id)
    car = vehicle_or_404(conn, event["vehicle_id"])
    return render(
        request,
        "service.html",
        active="garage",
        car=car,
        event=event,
        sources=SOURCE_LABELS,
        kinds=KIND_LABELS,
        actions=ACTION_LABELS,
    )


@router.get("/services/{event_id}/edit")
def edit_service(request: Request, event_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    event = _event_or_404(conn, event_id)
    car = vehicle_or_404(conn, event["vehicle_id"])
    raw = {
        "performed_on": event["performed_on"],
        "odometer": "" if event["odometer"] is None else f"{event['odometer']:,}",
        "source": event["source"],
        "shop": event["shop"],
        "invoice_number": event["invoice_number"],
        "tax": _dollars(event["tax_cents"]),
        "total": _dollars(event["total_cents"]),
        "notes": event["notes"],
    }
    lines = [
        {
            "description": line["description"],
            "kind": line["kind"],
            "amount": _dollars(line["amount_cents"]),
            "covers": [c["code"] for c in line["covers"]],
            "inspect_only": bool(line["covers"]) and all(c["action"] == "inspect" for c in line["covers"]),
            "part_number": line["part_number"],
            "quantity": "" if line["quantity"] is None else f"{line['quantity']:g}",
        }
        for line in event["lines"]
    ] or [_blank_line()]
    return _form(request, conn, car, raw, lines, errors={}, event=event)


@router.post("/services/{event_id}/edit")
async def update_service(request: Request, event_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    existing = _event_or_404(conn, event_id)
    car = vehicle_or_404(conn, existing["vehicle_id"])
    raw, lines_raw = await _raw(request)
    event, errors, line_errors = _read(conn, car["id"], raw, lines_raw, event_id=event_id)
    if errors or any(line_errors):
        return _form(request, conn, car, raw, lines_raw, errors, line_errors, event=existing, status_code=422)
    services.update_event(conn, event_id, event)
    return RedirectResponse(f"/services/{event_id}", status_code=303)


@router.post("/services/{event_id}/delete")
def delete_service(event_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    event = _event_or_404(conn, event_id)
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
    types = [
        {"code": row["code"], "name": row["name"], "category": row["category"]}
        for row in services.list_types(conn)
        if car["powertrain"] in row["powertrains"].split(",") or row["code"] in in_use
    ]
    return render(
        request,
        "service_form.html",
        status_code=status_code,
        active="garage",
        car=car,
        event=event,
        raw=raw,
        errors=errors,
        editor={"lines": lines, "errors": line_errors or [None] * len(lines), "types": types},
        sources=SOURCE_LABELS,
        kinds=KIND_LABELS,
    )


async def _raw(request: Request) -> tuple[dict[str, str], list[dict]]:
    form = await request.form()
    raw = {key: forms.text(form.get(key)) for key in _FIELDS}
    try:
        lines = json.loads(form.get("lines_json") or "[]")
        if not isinstance(lines, list):
            raise ValueError
    except ValueError:
        lines = []
    cleaned = []
    for item in lines:
        if not isinstance(item, dict):
            continue
        cleaned.append({
            "description": forms.text(str(item.get("description", ""))),
            "kind": str(item.get("kind", "other")),
            "amount": forms.text(str(item.get("amount", ""))),
            "covers": [str(c) for c in item.get("covers", []) if isinstance(c, str)],
            "inspect_only": bool(item.get("inspect_only")),
            "part_number": forms.text(str(item.get("part_number", ""))),
            "quantity": forms.text(str(item.get("quantity", ""))),
        })
    return raw, cleaned or [_blank_line()]


def _read(
    conn: sqlite3.Connection,
    vehicle_id: int,
    raw: dict,
    lines_raw: list[dict],
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
    lines: list[services.LineInput] = []
    line_errors: list[str | None] = []
    for item in lines_raw:
        covers = [code for code in dict.fromkeys(item["covers"]) if code in types]
        try:
            amount = forms.money(item["amount"])
            qty = forms.quantity(item["quantity"])
        except ValueError as err:
            line_errors.append(str(err))
            continue
        if not item["description"] and not covers and amount is None:
            line_errors.append(None)  # an empty row: ignored
            continue
        line_errors.append(None)
        lines.append(services.LineInput(
            description=item["description"] or ", ".join(types[c]["name"] for c in covers) or "Unnamed item",
            kind=item["kind"] if item["kind"] in services.KINDS else "other",
            part_number=item["part_number"],
            quantity=qty,
            amount_cents=amount,
            covers=[
                services.Coverage(code, "inspect" if item["inspect_only"] else types[code]["default_action"])
                for code in covers
            ],
        ))
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


def _blank_line() -> dict:
    return {"description": "", "kind": "other", "amount": "", "covers": [], "inspect_only": False, "part_number": "", "quantity": ""}


def _dollars(cents: int | None) -> str:
    return "" if cents is None else f"{cents / 100:.2f}"
