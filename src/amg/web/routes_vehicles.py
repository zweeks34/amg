"""A car: adding and editing it, its page, and its odometer readings."""

from __future__ import annotations

import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse, Response

from ..ingest import vin as vins
from ..repo import odometer, schedules, services, vehicles
from . import budget, forms
from . import follow_ups as follow_up_words
from . import renewals as renewal_words
from . import fuel_status
from . import status as car_status
from .deps import get_conn
from .templating import render

router = APIRouter()

POWERTRAIN_LABELS = {"gas": "Gasoline", "hybrid": "Hybrid", "ev": "Electric"}
_FIELDS = (
    "name", "vin", "plate", "year", "make", "model", "trim", "engine", "powertrain",
    "in_service_date", "acquired_date", "acquired_miles", "notes",
)


def vehicle_or_404(conn: sqlite3.Connection, vehicle_id: int) -> sqlite3.Row:
    row = vehicles.get(conn, vehicle_id)
    if row is None:
        raise HTTPException(status_code=404)
    return row


# ---------- Add and edit ----------


@router.get("/vehicles/new")
def new_vehicle(request: Request) -> Response:
    return _form(request, raw={"powertrain": "gas"}, errors={})


@router.post("/vehicles")
async def create_vehicle(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    raw = await _raw(request)
    fields, errors = _read(conn, raw)
    if errors:
        return _form(request, raw=raw, errors=errors, status_code=422)
    vehicle_id = vehicles.create(conn, fields)
    return RedirectResponse(f"/vehicles/{vehicle_id}", status_code=303)


@router.post("/vehicles/vin-lookup")
async def vin_lookup(request: Request) -> Response:
    """Fill the form from the VIN (htmx: returns just the fields)."""
    raw = await _raw(request)
    errors: dict[str, str] = {}
    notice = None
    vin = vins.normalize(raw.get("vin", ""))
    raw["vin"] = vin
    if not vin:
        errors["vin"] = "Type the VIN first."
    elif problem := vins.problem(vin):
        errors["vin"] = problem
    else:
        try:
            decoded = await run_in_threadpool(vins.decode, vin)
        except vins.VinLookupError as err:
            errors["vin"] = str(err)
        else:
            raw.update(
                year=str(decoded.year or ""),
                make=decoded.make,
                model=decoded.model,
                trim=decoded.trim,
                engine=decoded.engine,
                powertrain=decoded.powertrain,
            )
            if not raw.get("name"):
                raw["name"] = decoded.model
            notice = "Filled in from NHTSA's records. Check them before saving."
    return render(
        request,
        "_vehicle_fields.html",
        raw=raw,
        errors=errors,
        notice=notice,
        powertrains=POWERTRAIN_LABELS,
    )


@router.get("/vehicles/{vehicle_id}/edit")
def edit_vehicle(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = vehicle_or_404(conn, vehicle_id)
    raw = {key: "" if row[key] is None else str(row[key]) for key in _FIELDS}
    return _form(request, raw=raw, errors={}, vehicle=row)


@router.post("/vehicles/{vehicle_id}/edit")
async def update_vehicle(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = vehicle_or_404(conn, vehicle_id)
    raw = await _raw(request)
    fields, errors = _read(conn, raw, vehicle_id=vehicle_id)
    if errors:
        return _form(request, raw=raw, errors=errors, vehicle=row, status_code=422)
    vehicles.update(conn, vehicle_id, fields)
    return RedirectResponse(f"/vehicles/{vehicle_id}", status_code=303)


@router.post("/vehicles/{vehicle_id}/archive")
def archive_vehicle(vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    vehicle_or_404(conn, vehicle_id)
    vehicles.archive(conn, vehicle_id)
    return RedirectResponse("/", status_code=303)


@router.post("/vehicles/{vehicle_id}/restore")
def restore_vehicle(vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    vehicle_or_404(conn, vehicle_id)
    vehicles.restore(conn, vehicle_id)
    return RedirectResponse(f"/vehicles/{vehicle_id}", status_code=303)


# ---------- The car's page ----------


@router.get("/vehicles/{vehicle_id}")
def vehicle_page(request: Request, vehicle_id: int, attested: int | None = None,
                 conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    return car_page(request, conn, vehicle_id, attested=bool(attested))


@router.post("/vehicles/{vehicle_id}/odometer")
async def add_reading(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    vehicle_or_404(conn, vehicle_id)
    form = await request.form()
    raw = {key: forms.text(form.get(key)) for key in ("read_on", "miles", "note")}
    errors: dict[str, str] = {}
    read_on = _parse(forms.day, raw["read_on"], "read_on", errors, required="Enter the date of the reading.")
    miles = _parse(forms.miles, raw["miles"], "miles", errors, required="Enter the odometer reading.")
    if not errors and (clash := odometer.conflict(conn, vehicle_id, read_on, miles)):
        errors["miles"] = clash.message()
    if errors:
        return car_page(request, conn, vehicle_id, reading=raw, reading_errors=errors, status_code=422)
    odometer.add(conn, vehicle_id, read_on, miles, raw["note"])
    return RedirectResponse(f"/vehicles/{vehicle_id}#odometer", status_code=303)


@router.post("/odometer/{reading_id}/delete")
def delete_reading(reading_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = odometer.get(conn, reading_id)
    if row is None:
        raise HTTPException(status_code=404)
    odometer.delete(conn, reading_id)
    return RedirectResponse(f"/vehicles/{row['vehicle_id']}#odometer", status_code=303)


# ---------- Helpers ----------


def car_page(request: Request, conn: sqlite3.Connection, vehicle_id: int, status_code: int = 200, **extra) -> Response:
    """The car's page; ``extra`` carries a form that came back with errors, or a notice."""
    car = vehicle_or_404(conn, vehicle_id)
    state = car_status.load(conn, car)
    plan = budget.load(conn, car, 12, state=state)
    return render(
        request,
        "vehicle.html",
        status_code=status_code,
        active="garage",
        car=car,
        powertrains=POWERTRAIN_LABELS,
        latest=vehicles.latest_odometer(conn, vehicle_id),
        history=services.history(conn, vehicle_id),
        schedule_count=schedules.count(conn, vehicle_id),
        state=state,
        upcoming=car_status.next_up(state, costs=plan.item_costs()),
        plan=plan,
        missed=car_status.missed(state),
        stale=None if car["archived_at"] else car_status.stale_reading(state),
        chart=car_status.chart(state, car["name"]),
        fuel=fuel_status.summary(fuel_status.load(conn, car)),
        attested=extra.get("attested", False),
        schedule_from=schedules.current_draft(conn, vehicle_id),
        schedule_drafts=schedules.open_drafts(conn, vehicle_id),
        points=odometer.points(conn, vehicle_id),
        # The server's local date — the deploy guide sets the container's time zone to yours.
        reading=extra.get("reading", {"read_on": date.today().isoformat()}),
        reading_errors=extra.get("reading_errors", {}),
        renewals=None if car["archived_at"] else renewal_words.rows(conn, car),
        renewal_form=extra.get("renewal_form"),
        follow_ups=follow_up_words.load(conn, car),
        type_names={row["code"]: row["name"] for row in services.list_types(conn)},
    )


def _form(request: Request, raw: dict, errors: dict, vehicle: sqlite3.Row | None = None, status_code: int = 200) -> Response:
    return render(
        request,
        "vehicle_form.html",
        status_code=status_code,
        active="garage",
        raw=raw,
        errors=errors,
        vehicle=vehicle,
        notice=None,
        powertrains=POWERTRAIN_LABELS,
    )


async def _raw(request: Request) -> dict[str, str]:
    form = await request.form()
    return {key: forms.text(form.get(key)) for key in _FIELDS}


def _parse(parser, value, key, errors, required: str | None = None):
    try:
        parsed = parser(value)
    except ValueError as err:
        errors[key] = str(err)
        return None
    if parsed is None and required:
        errors[key] = required
    return parsed


def _read(conn: sqlite3.Connection, raw: dict, vehicle_id: int | None = None) -> tuple[vehicles.VehicleFields, dict]:
    errors: dict[str, str] = {}
    vin = vins.normalize(raw.get("vin", "")) or None
    raw["vin"] = vin or ""
    if vin:
        if problem := vins.problem(vin):
            errors["vin"] = problem
        elif (owner := vehicles.vin_owner(conn, vin)) and owner != vehicle_id:
            errors["vin"] = "Another car in your garage already has this VIN."

    year = _parse(forms.year, raw.get("year"), "year", errors)
    make, model = raw.get("make", ""), raw.get("model", "")
    name = raw.get("name") or " ".join(str(p) for p in (year, make, model) if p)
    if not name:
        errors["name"] = "Give the car a name, or fill in its make and model."

    powertrain = raw.get("powertrain") or "gas"
    if powertrain not in vehicles.POWERTRAINS:
        errors["powertrain"] = "Choose gasoline, hybrid or electric."

    in_service = _parse(forms.day, raw.get("in_service_date"), "in_service_date", errors)
    acquired = _parse(forms.day, raw.get("acquired_date"), "acquired_date", errors)
    acquired_miles = _parse(forms.miles, raw.get("acquired_miles"), "acquired_miles", errors)
    if acquired_miles is not None and acquired is None and "acquired_date" not in errors:
        errors["acquired_date"] = "Add the date you got it, so that mileage has a date."
    if in_service and acquired and acquired < in_service:
        errors["acquired_date"] = "That's before the car went into service."
    if acquired and acquired_miles is not None and vehicle_id and not errors:
        if clash := odometer.conflict(conn, vehicle_id, acquired, acquired_miles, ignore=("acquired", vehicle_id)):
            errors["acquired_miles"] = clash.message()

    fields = vehicles.VehicleFields(
        name=name,
        vin=vin,
        year=year,
        make=make,
        model=model,
        trim=raw.get("trim", ""),
        engine=raw.get("engine", ""),
        powertrain=powertrain,
        plate=raw.get("plate", "").upper(),
        in_service_date=in_service,
        acquired_date=acquired,
        acquired_miles=acquired_miles,
        notes=raw.get("notes", ""),
    )
    return fields, errors
