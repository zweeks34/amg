"""The garage: every car at a glance. The front page."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request
from starlette.responses import Response

from ..repo import vehicles
from .deps import get_conn
from .routes_vehicles import POWERTRAIN_LABELS
from .templating import render

router = APIRouter()


@router.get("/")
def garage(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    active, archived = vehicles.garage(conn)
    return render(
        request,
        "garage.html",
        active="garage",
        vehicles=active,
        archived=archived,
        powertrains=POWERTRAIN_LABELS,
    )
