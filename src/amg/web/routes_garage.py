"""The garage: every car at a glance. The front page."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request
from starlette.responses import Response

from ..repo import schedules, vehicles
from . import budget
from . import follow_ups as follow_up_words
from . import renewals as renewal_words
from . import status as car_status
from .deps import get_conn
from .routes_vehicles import POWERTRAIN_LABELS
from .templating import render

router = APIRouter()


@router.get("/")
def garage(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    active, archived = vehicles.garage(conn)
    for car in active:
        car["schedule"] = car_status.summary(car_status.load(conn, car)) if schedules.count(conn, car["id"]) else None
        car["renewals"] = renewal_words.urgent(renewal_words.rows(conn, car, offers=False))
        car["recommended"] = len(follow_up_words.load(conn, car).recent)
    return render(
        request,
        "garage.html",
        active="garage",
        vehicles=active,
        archived=archived,
        budget=budget.strip(budget.garage(conn, active)),
        powertrains=POWERTRAIN_LABELS,
    )
