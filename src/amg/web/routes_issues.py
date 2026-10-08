"""Issues: noting what's wrong with a car, and saying what became of it.

The car's page lists them and asks about the newest visit since each was
noticed; a service's page asks about itself, and its answers come back there
(``back=service``).
"""

from __future__ import annotations

import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.responses import RedirectResponse, Response

from ..repo import issues
from . import forms
from . import issues as issue_words
from .deps import get_conn
from .routes_vehicles import car_page, vehicle_or_404
from .templating import render

router = APIRouter()


# ---------- Noting one ----------


@router.get("/vehicles/{vehicle_id}/issues/new")
def new_issue(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    # The server's local date, as the odometer form's.
    return _form(request, conn, car, {"noticed_on": date.today().isoformat()}, [], {})


@router.post("/vehicles/{vehicle_id}/issues")
async def create_issue(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    form = await request.form()
    issue, raw, errors = issue_words.parse(form)
    photo_ids, photo_error = await issue_words.store_photos(conn, form)
    if photo_error:
        errors["photos"] = photo_error
    if errors:
        return _form(request, conn, car, raw, photo_ids, errors, status_code=422)
    issues.create(conn, vehicle_id, issue, photo_ids)
    return RedirectResponse(f"/vehicles/{vehicle_id}#issues", status_code=303)


@router.get("/issues/{issue_id}/edit")
def edit_issue(request: Request, issue_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _issue_or_404(conn, issue_id)
    car = vehicle_or_404(conn, row["vehicle_id"])
    raw = {key: row[key] for key in ("title", "details", "noticed_on")}
    return _form(request, conn, car, raw, [photo["id"] for photo in row["photos"]], {}, issue=row)


@router.post("/issues/{issue_id}/edit")
async def update_issue(request: Request, issue_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _issue_or_404(conn, issue_id)
    car = vehicle_or_404(conn, row["vehicle_id"])
    form = await request.form()
    issue, raw, errors = issue_words.parse(form)
    photo_ids, photo_error = await issue_words.store_photos(conn, form)
    if photo_error:
        errors["photos"] = photo_error
    if errors:
        return _form(request, conn, car, raw, photo_ids, errors, issue=row, status_code=422)
    issues.update(conn, issue_id, issue, photo_ids)
    return RedirectResponse(f"/vehicles/{car['id']}#issues", status_code=303)


@router.post("/issues/{issue_id}/delete")
def delete_issue(issue_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _issue_or_404(conn, issue_id)
    issues.delete(conn, issue_id)
    return RedirectResponse(f"/vehicles/{row['vehicle_id']}#issues", status_code=303)


# ---------- What became of it ----------


@router.post("/issues/{issue_id}/fixed")
async def fixed(request: Request, issue_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _issue_or_404(conn, issue_id)
    form = await request.form()
    if row["status"] != "open":   # answered already, in another tab
        return _back(form, row)
    day, event_id, raw, error = issue_words.parse_fix(form, row, issues.visits(conn, row["vehicle_id"]))
    if error:
        return car_page(request, conn, row["vehicle_id"], issue_form={"id": issue_id, "raw": raw, "error": error},
                        status_code=422)
    issues.fix(conn, issue_id, day, event_id)
    return _back(form, row)


@router.post("/issues/{issue_id}/still-there")
async def still_there(request: Request, issue_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _issue_or_404(conn, issue_id)
    form = await request.form()
    chosen = forms.text(form.get("service_event_id"))
    if row["status"] == "open" and any(str(v.id) == chosen for v in issues.visits(conn, row["vehicle_id"])):
        issues.still_there(conn, issue_id, int(chosen))
    return _back(form, row)


@router.post("/issues/{issue_id}/drop")
def drop(issue_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _issue_or_404(conn, issue_id)
    issues.drop(conn, issue_id, date.today().isoformat())
    return RedirectResponse(f"/vehicles/{row['vehicle_id']}#issues", status_code=303)


@router.post("/issues/{issue_id}/reopen")
def reopen(issue_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _issue_or_404(conn, issue_id)
    issues.reopen(conn, issue_id)
    return RedirectResponse(f"/vehicles/{row['vehicle_id']}#issues", status_code=303)


# ---------- Helpers ----------


def _issue_or_404(conn: sqlite3.Connection, issue_id: int) -> dict:
    row = issues.get(conn, issue_id)
    if row is None:
        raise HTTPException(status_code=404)
    return row


def _back(form, row: dict) -> Response:
    """Back to the service's page the answer came from, or to the car's issues."""
    event = forms.text(form.get("service_event_id"))
    if forms.text(form.get("back")) == "service" and event.isdigit():
        return RedirectResponse(f"/services/{event}#issues", status_code=303)
    return RedirectResponse(f"/vehicles/{row['vehicle_id']}#issues", status_code=303)


def _form(request: Request, conn: sqlite3.Connection, car, raw: dict, photo_ids: list[int], errors: dict,
          issue: dict | None = None, status_code: int = 200) -> Response:
    return render(
        request,
        "issue_form.html",
        status_code=status_code,
        active="garage",
        car=car,
        issue=issue,
        raw=raw,
        photos=issue_words.photo_rows(conn, photo_ids),
        errors=errors,
        today=date.today().isoformat(),
    )
