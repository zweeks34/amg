"""Recalls on the car's page: checking NHTSA now, and saying a recall's been done or isn't for this car."""

from __future__ import annotations

import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from starlette.responses import RedirectResponse, Response

from ..repo import recalls
from . import forms
from . import recalls as recall_words
from .deps import get_conn
from .routes_vehicles import car_page, vehicle_or_404

router = APIRouter()


@router.post("/vehicles/{vehicle_id}/recalls/check")
async def check_now(vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    if car["year"] and car["make"] and car["model"]:
        await run_in_threadpool(recall_words.check, conn, car)
    return RedirectResponse(f"/vehicles/{vehicle_id}#recalls", status_code=303)


@router.post("/recalls/{recall_id}/done")
async def done(request: Request, recall_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    recall = _recall_or_404(conn, recall_id)
    form = await request.form()
    raw = {key: forms.text(form.get(key)) for key in ("closed_on", "service_event_id")}
    visits = {str(v["id"]): v for v in recalls.recall_visits(conn, recall["vehicle_id"], recall["reported_on"])}
    if visit := visits.get(raw["service_event_id"]):
        recalls.close(conn, recall_id, "done", visit["performed_on"], visit["id"])
    else:
        try:
            closed_on = forms.day(raw["closed_on"])
        except ValueError as err:
            return car_page(request, conn, recall["vehicle_id"], recall_form={"id": recall_id, "raw": raw,
                                                                              "error": str(err)}, status_code=422)
        recalls.close(conn, recall_id, "done", closed_on)
    return RedirectResponse(f"/vehicles/{recall['vehicle_id']}#recalls", status_code=303)


@router.post("/recalls/{recall_id}/not-mine")
def not_mine(recall_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    recall = _recall_or_404(conn, recall_id)
    recalls.close(conn, recall_id, "not_mine", date.today().isoformat())
    return RedirectResponse(f"/vehicles/{recall['vehicle_id']}#recalls", status_code=303)


@router.post("/recalls/{recall_id}/undo")
def undo(recall_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    recall = _recall_or_404(conn, recall_id)
    recalls.reopen(conn, recall_id)
    return RedirectResponse(f"/vehicles/{recall['vehicle_id']}#recalls", status_code=303)


def _recall_or_404(conn: sqlite3.Connection, recall_id: int) -> sqlite3.Row:
    row = recalls.get(conn, recall_id)
    if row is None:
        raise HTTPException(status_code=404)
    return row
