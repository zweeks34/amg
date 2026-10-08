"""Shop recommendations: saying you're not doing one, and taking that back.

Logging one as done goes through the new-service form (routes_services).
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import RedirectResponse, Response

from ..repo import follow_ups
from . import forms
from .deps import get_conn

router = APIRouter()


@router.post("/follow-ups/skip")
async def skip(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    receipt_id, key, vehicle_id = await _which(request, conn)
    follow_ups.skip(conn, receipt_id, key)
    return RedirectResponse(f"/vehicles/{vehicle_id}#follow-ups", status_code=303)


@router.post("/follow-ups/undo")
async def undo(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    receipt_id, key, vehicle_id = await _which(request, conn)
    follow_ups.undo(conn, receipt_id, key)
    return RedirectResponse(f"/vehicles/{vehicle_id}#follow-ups", status_code=303)


async def _which(request: Request, conn: sqlite3.Connection) -> tuple[int, str, int]:
    form = await request.form()
    receipt_id, key = forms.text(form.get("receipt_id")), forms.text(form.get("key"))
    found = follow_ups.find(conn, int(receipt_id), key) if receipt_id.isdigit() else None
    if found is None:
        raise HTTPException(status_code=404)
    return int(receipt_id), key, found[1]
