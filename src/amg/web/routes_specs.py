"""A car's specs card: the card itself, and typing it in."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request
from starlette.responses import RedirectResponse, Response

from ..ingest import manuals
from ..repo import specs
from . import specs as spec_words
from .deps import get_conn
from .routes_vehicles import vehicle_or_404
from .templating import render

router = APIRouter()


@router.get("/vehicles/{vehicle_id}/specs")
def card(request: Request, vehicle_id: int, saved: int | None = None,
         conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    return render(
        request,
        "specs.html",
        active="garage",
        car=car,
        car_words=manuals.describe_car(car),
        groups=spec_words.card(conn, car),
        fitted_words=spec_words.fitted_words,
        saved=bool(saved),
    )


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
