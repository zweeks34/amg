"""Fill-ups and charges: the quick form at the pump or charger, and each car's log.

Every fill is an odometer reading too, so it goes through the same check as
any other: one lower than an earlier reading is refused.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import RedirectResponse, Response

from ..engine import fuel as engine
from ..repo import fuel, odometer, vehicles
from . import forms
from . import fuel_status as status
from .deps import get_conn
from .routes_vehicles import vehicle_or_404
from .templating import render

router = APIRouter()

_FIELDS = ("filled_on", "odometer", "quantity", "cost", "full", "missed_before", "place", "note")


@router.get("/fuel/new")
def pick_car(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    """The masthead's Fill-up: straight to the form with one car, a choice with several."""
    cars = fuel.cars_by_last_fill(conn)
    if len(cars) == 1:
        return RedirectResponse(f"/vehicles/{cars[0]['id']}/fuel/new", status_code=303)
    return render(request, "fuel_pick.html", active="fuel",
                  cars=[{"car": car, "units": status.units_for(car)} for car in cars])


@router.get("/vehicles/{vehicle_id}/fuel/new")
def new_fill(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    last = fuel.last(conn, vehicle_id)
    raw = {"filled_on": date.today().isoformat(), "full": "1",
           "place": (last["place"] if last and last["place"] else "home")}
    return _form(request, conn, car, status.units_for(car), raw, errors={})


@router.post("/vehicles/{vehicle_id}/fuel")
async def create_fill(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    units = status.units_for(car)
    raw = await _raw(request)
    fill, errors = _read(conn, vehicle_id, units, raw)
    if errors:
        return _form(request, conn, car, units, raw, errors, status_code=422)
    fill_id = fuel.create(conn, vehicle_id, fill)
    return RedirectResponse(f"/vehicles/{vehicle_id}/fuel?saved={fill_id}", status_code=303)


@router.get("/vehicles/{vehicle_id}/fuel")
def fuel_page(request: Request, vehicle_id: int, saved: int | None = None, deleted: int | None = None,
              conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    state = status.load(conn, car)
    return render(
        request,
        "fuel.html",
        active="garage",
        car=car,
        units=state.units,
        figures=status.figures(state),
        trend=status.trend(state),
        log=status.log_rows(state),
        saved=status.saved(state, saved) if saved else None,
        deleted=bool(deleted),
    )


@router.get("/fuel/{fill_id}/edit")
def edit_fill(request: Request, fill_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _fill_or_404(conn, fill_id)
    car = vehicle_or_404(conn, row["vehicle_id"])
    raw = {
        "filled_on": row["filled_on"],
        "odometer": f"{row['odometer']:,}",
        "quantity": f"{row['quantity']:.3f}".rstrip("0").rstrip("."),
        "cost": "" if row["cost_cents"] is None else f"{row['cost_cents'] / 100:.2f}",
        "full": "1" if row["full"] else "",
        "missed_before": "1" if row["missed_before"] else "",
        "place": row["place"] or "",
        "note": row["note"],
    }
    return _form(request, conn, car, status.UNITS[row["energy"]], raw, errors={}, fill=row)


@router.post("/fuel/{fill_id}/edit")
async def update_fill(request: Request, fill_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _fill_or_404(conn, fill_id)
    car = vehicle_or_404(conn, row["vehicle_id"])
    units = status.UNITS[row["energy"]]
    raw = await _raw(request)
    fill, errors = _read(conn, car["id"], units, raw, fill_id=fill_id)
    if errors:
        return _form(request, conn, car, units, raw, errors, fill=row, status_code=422)
    fuel.update(conn, fill_id, fill)
    return RedirectResponse(f"/vehicles/{car['id']}/fuel?saved={fill_id}", status_code=303)


@router.post("/fuel/{fill_id}/delete")
def delete_fill(fill_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _fill_or_404(conn, fill_id)
    fuel.delete(conn, fill_id)
    return RedirectResponse(f"/vehicles/{row['vehicle_id']}/fuel?deleted=1", status_code=303)


# ---------- Helpers ----------


def _fill_or_404(conn: sqlite3.Connection, fill_id: int) -> sqlite3.Row:
    row = fuel.get(conn, fill_id)
    if row is None:
        raise HTTPException(status_code=404)
    return row


def _form(request: Request, conn: sqlite3.Connection, car, units: status.Units, raw: dict, errors: dict,
          fill: sqlite3.Row | None = None, status_code: int = 200) -> Response:
    fills = status.load(conn, car).fills
    rate = engine.home_rate(fills) if units.energy == "electric" else None
    return render(
        request,
        "fuel_form.html",
        status_code=status_code,
        active="fuel",
        car=car,
        units=units,
        raw=raw,
        errors=errors,
        fill=fill,
        latest=vehicles.latest_odometer(conn, car["id"]),
        options={"unit": units.quantity, "rate": rate, "quantity": raw.get("quantity", ""),
                 "cost": raw.get("cost", ""), "place": raw.get("place", "")},
    )


async def _raw(request: Request) -> dict[str, str]:
    form = await request.form()
    return {key: forms.text(form.get(key)) for key in _FIELDS}


def _read(conn: sqlite3.Connection, vehicle_id: int, units: status.Units, raw: dict,
          fill_id: int | None = None) -> tuple[fuel.FillInput, dict]:
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

    filled_on = parse(forms.day, "filled_on", required="Enter the date.")
    miles = parse(forms.miles, "odometer", required=f"Enter the odometer. {units.economy_name} is worked out from it.")
    words = "gallons" if units.quantity == "gal" else "kWh"
    quantity = parse(lambda value: forms.amount(value, units.quantity), "quantity",
                     required=f"Enter the {words} that went in.")
    cost = parse(forms.money, "cost")
    if cost is not None and cost < 0:
        errors["cost"] = "Enter what you paid, like 39.72."
    place = None
    if units.energy == "electric":
        place = raw.get("place") if raw.get("place") in fuel.PLACES else None
        if place is None:
            errors["place"] = "Choose home or public."
    if filled_on and miles is not None:
        ignore = (fuel.point_source(units.energy), fill_id) if fill_id else None
        if clash := odometer.conflict(conn, vehicle_id, filled_on, miles, ignore=ignore):
            errors["odometer"] = clash.message()

    fill = fuel.FillInput(
        filled_on=filled_on or "",
        odometer=miles or 0,
        energy=units.energy,
        quantity=quantity or 0.0,
        cost_cents=cost,
        full=raw.get("full") == "1",
        missed_before=raw.get("missed_before") == "1",
        place=place,
        note=raw.get("note", ""),
    )
    return fill, errors
