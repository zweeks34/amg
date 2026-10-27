"""The garage: every car at a glance. The front page."""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request
from starlette.responses import Response

from ..repo import issues, recalls, schedules, vehicles
from . import budget
from . import follow_ups as follow_up_words
from . import fuel_status
from . import recalls as recall_words
from . import renewals as renewal_words
from . import running_cost
from . import status as car_status
from . import warranties as warranty_words
from .deps import get_conn
from .routes_vehicles import POWERTRAIN_LABELS
from .templating import render

router = APIRouter()


@router.get("/")
def garage(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    active, archived = vehicles.garage(conn)
    noted = issues.open_counts(conn)
    for car in active:
        car["schedule"] = car_status.summary(car_status.load(conn, car)) if schedules.count(conn, car["id"]) else None
        car["renewals"] = renewal_words.urgent(renewal_words.rows(conn, car, offers=False))
        car["recommended"] = len(follow_up_words.load(conn, car).recent)
        car["issues"] = noted.get(car["id"], 0)
        car["warranties"] = len(warranty_words.load(conn, car).ending)
        car["recalls"] = [recall_words.component(row["component"]) for row in recalls.open_for(conn, car["id"])]
        car["running"] = running_cost.figure(running_cost.load(conn, car))
        car["economy"] = fuel_status.sparkline(fuel_status.load(conn, car))
    return render(
        request,
        "garage.html",
        active="garage",
        vehicles=active,
        archived=archived,
        budget=budget.strip(budget.garage(conn, active)),
        powertrains=POWERTRAIN_LABELS,
    )
