"""Alerts: how they reach you, which cars send them, the calendar file, and what went out.

The sending itself is the daily run (amg/alerts/run.py, a systemd timer on the
server). This page sets which cars it watches, sends a test down each channel,
and shows what it last did.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timezone
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from starlette.responses import RedirectResponse, Response

from .. import config
from ..alerts import ics, mail, ntfy, watch
from ..repo import alerts, vehicles
from .deps import get_conn
from .templating import render

router = APIRouter()


@router.get("/alerts")
def page(request: Request, turned: str = "", car: int | None = None, tested: str = "",
         conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    switched = vehicles.get(conn, car) if car else None
    return _page(request, conn, turned=turned if switched else "", switched=switched, tested=tested)


@router.post("/alerts/cars/{vehicle_id}")
def switch(vehicle_id: int, on: int = Form(...), conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicles.get(conn, vehicle_id)
    if car is None or car["archived_at"]:
        raise HTTPException(status_code=404)
    alerts.switch(conn, vehicle_id, bool(on))
    if on:
        watch.take_stock(conn, vehicles.get(conn, vehicle_id))
    return RedirectResponse(f"/alerts?turned={'on' if on else 'off'}&car={vehicle_id}", status_code=303)


@router.post("/alerts/test-push")
def test_push(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    settings = config.ntfy()
    if settings is None:
        return _page(request, conn, problem="Pushes aren't set up yet: add AMG_NTFY_TOPIC to .env, then restart AMG.")
    try:
        ntfy.send(ntfy.Push("AMG: test push", "If you can see this, AMG's alerts will reach this phone.",
                            tags=("white_check_mark",), click=f"{config.base_url()}/alerts"), settings)
    except ntfy.SendError as err:
        return _page(request, conn, problem=f"The test push didn't go. {err}")
    return RedirectResponse("/alerts?tested=push", status_code=303)


@router.post("/alerts/test-email")
def test_email(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    settings = config.smtp()
    if settings is None:
        return _page(request, conn, problem="Email isn't set up yet: add AMG_SMTP_USER and AMG_SMTP_PASSWORD to .env, "
                                            "then restart AMG.")
    try:
        mail.send(mail.test_message(date.today()), settings)
    except mail.SendError as err:
        return _page(request, conn, problem=f"The test email didn't go. {err}")
    return RedirectResponse("/alerts?tested=email", status_code=303)


@router.get("/alerts/calendar.ics")
def calendar(conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    """The next 12 months of jobs for every car in the garage, to import into a calendar."""
    active, _ = vehicles.garage(conn)
    watches = [watch.look(conn, car) for car in active]
    return Response(ics.calendar(watch.events(watches, config.base_url())), media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{mail.CALENDAR_FILE}"'})


# ---------- Helpers ----------


def _page(request: Request, conn: sqlite3.Connection, **notices) -> Response:
    push, email = config.ntfy(), config.smtp()
    active, _ = vehicles.garage(conn)
    last = alerts.last_run(conn)
    return render(
        request,
        "alerts.html",
        active="alerts",
        push=push,
        push_where=f"{urlsplit(push.url).netloc or push.url}/{push.topic}" if push else "",
        email=email,
        cars=active,
        last=last,
        last_at=_when(last["at"]) if last else "",
        recent=[{**row, "at": _when(row["updated_at"])} for row in alerts.recent(conn)],
        **notices,
    )


def _when(stamp: str) -> str:
    """A stored time, in the server's time zone: "Today 8:00 am", "Mon Oct 5, 8:00 am"."""
    moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    moment = moment.astimezone()
    clock = f"{moment.hour % 12 or 12}:{moment.minute:02d} {'am' if moment.hour < 12 else 'pm'}"
    if moment.date() == date.today():
        return f"Today {clock}"
    return f"{moment:%a %b} {moment.day}, {clock}"
