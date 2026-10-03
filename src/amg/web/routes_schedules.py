"""A car's maintenance schedule: starting one, checking the draft, and editing it.

Every way of starting a schedule — reading the owner's manual, Claude's draft,
a generic template, another car's schedule — ends on the same review screen.
Nothing in a draft counts until you use it; using it replaces the car's
schedule, which is then edited in place.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.datastructures import UploadFile
from starlette.responses import RedirectResponse, Response

from ..ingest import background, manuals
from ..ingest import schedule_drafts as sd
from ..ingest import schedule_templates as templates
from ..repo import documents, schedules, services, vehicles
from . import forms
from .deps import get_conn
from .routes_services import editor_types
from .routes_vehicles import vehicle_or_404
from .schedule_editor import blank_row, clean_items, editor_row, parse_items
from .templating import render

router = APIRouter()

ACTION_LETTERS = {"replace": "R", "inspect": "I", "perform": "P"}
ACTION_LABELS = {"replace": "Replace", "inspect": "Inspect", "perform": "Perform"}
APPLIES_LABELS = {"always": "Both", "normal": "Normal only", "severe": "Severe only"}


# ---------- The schedule page ----------


@router.get("/vehicles/{vehicle_id}/schedule")
def schedule_page(request: Request, vehicle_id: int, used: int | None = None, saved: int | None = None,
                  conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    return _page(request, conn, vehicle_or_404(conn, vehicle_id), used=bool(used), saved=bool(saved))


@router.post("/vehicles/{vehicle_id}/schedule/manual")
async def read_manual(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    form = await request.form()
    parts = [(await f.read(), f.filename or "manual") for f in form.getlist("files")
             if isinstance(f, UploadFile) and f.filename]
    pages = forms.text(form.get("pages"))
    errors: dict[str, str] = {}
    document = None
    if not parts:
        errors["files"] = "Choose the manual, or photos of its schedule pages."
    else:
        try:
            data, name = documents.combine(parts) if len(parts) > 1 else parts[0]
            document, _ = documents.store(conn, data, name)
        except documents.UploadError as err:
            errors["files"] = str(err)
    if document is not None and pages:
        try:
            manuals.parse_pages(pages, document["page_count"])
        except ValueError as err:
            errors["pages"] = str(err)
    if errors:
        return _page(request, conn, car, status_code=422, errors=errors, raw={"pages": pages})
    draft_id = background.read_schedule(conn, vehicle_id, "manual", document["id"], pages)  # type: ignore[index]
    return RedirectResponse(f"/schedule-drafts/{draft_id}", status_code=303)


@router.post("/vehicles/{vehicle_id}/schedule/claude")
def draft_with_claude(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    if not (car["year"] and car["make"] and car["model"]):
        return _page(request, conn, car, status_code=422, errors={
            "claude": "Add the car's year, make and model first, so Claude knows whose schedule to draft."})
    draft_id = background.read_schedule(conn, vehicle_id, "claude")
    return RedirectResponse(f"/schedule-drafts/{draft_id}", status_code=303)


@router.post("/vehicles/{vehicle_id}/schedule/template")
async def from_template(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    form = await request.form()
    powertrain = forms.text(form.get("powertrain")) or car["powertrain"]
    if powertrain not in templates.LABELS:
        return _page(request, conn, car, status_code=422, errors={"template": "Choose gasoline, hybrid or electric."})
    draft_id = schedules.create_draft(conn, vehicle_id, "template", draft=templates.draft(powertrain).to_dict())
    return RedirectResponse(f"/schedule-drafts/{draft_id}", status_code=303)


@router.post("/vehicles/{vehicle_id}/schedule/copy")
async def copy_schedule(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    form = await request.form()
    chosen = forms.text(form.get("from_vehicle_id"))
    other = vehicles.get(conn, int(chosen)) if chosen.isdigit() and int(chosen) != vehicle_id else None
    items = schedules.items(conn, other["id"]) if other else []
    if not items:
        return _page(request, conn, car, status_code=422, errors={"copy": "Choose a car that has a schedule."})
    draft = sd.from_items(items, origin="copy")
    draft.printed_for = f"{other['name']}'s schedule"  # type: ignore[index]
    if source := schedules.current_draft(conn, other["id"]):  # type: ignore[index]
        draft.severe_conditions = source["draft"].get("severe_conditions", "")
    draft_id = schedules.create_draft(conn, vehicle_id, "copy", draft=draft.to_dict())
    return RedirectResponse(f"/schedule-drafts/{draft_id}", status_code=303)


@router.post("/vehicles/{vehicle_id}/schedule/severe")
async def set_severe(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    vehicle_or_404(conn, vehicle_id)
    form = await request.form()
    schedules.set_severe(conn, vehicle_id, form.get("severe") == "1")
    return RedirectResponse(f"/vehicles/{vehicle_id}/schedule", status_code=303)


# ---------- Editing the schedule ----------


@router.get("/vehicles/{vehicle_id}/schedule/edit")
def edit_schedule(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    draft = sd.from_items(schedules.items(conn, vehicle_id), origin="copy", keep_ids=True)
    rows = [editor_row(item) for item in draft.items] or [blank_row()]
    return _editor(request, conn, car, rows)


@router.post("/vehicles/{vehicle_id}/schedule/edit")
async def save_schedule(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    form = await request.form()
    rows = clean_items(form.get("items_json"))
    for row in rows:
        row["included"] = True   # leaving out is for drafts; here an item you don't want is removed
    current = schedules.items(conn, vehicle_id)
    cited = {item["document_id"] for item in current if item["document_id"]}
    items, errors = parse_items(rows, _types(conn), cited)
    if any(errors):
        return _editor(request, conn, car, rows, errors, status_code=422)
    schedules.save_items(conn, vehicle_id, sd.to_items(sd.ScheduleDraft(origin="copy", items=items)))
    return RedirectResponse(f"/vehicles/{vehicle_id}/schedule?saved=1", status_code=303)


# ---------- Checking a draft ----------


@router.get("/schedule-drafts/{draft_id}")
def review(request: Request, draft_id: int, saved: int | None = None,
           conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    return _review(request, conn, _draft_or_404(conn, draft_id), saved=bool(saved))


@router.post("/schedule-drafts/{draft_id}")
async def save_draft(request: Request, draft_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _draft_or_404(conn, draft_id)
    if row["status"] != "read":
        return RedirectResponse(f"/schedule-drafts/{draft_id}", status_code=303)
    form = await request.form()
    action = form.get("action", "save")
    rows = clean_items(form.get("items_json"))
    items, errors = parse_items(rows, _types(conn), {row["document_id"]} if row["document_id"] else set())
    previous = sd.ScheduleDraft.from_dict(row["draft"])
    draft = sd.ScheduleDraft(
        origin=previous.origin,
        printed_for=previous.printed_for,
        severe_conditions=forms.text(form.get("severe_conditions")),
        read_note=previous.read_note,
        items=items,
    )
    problems: dict[str, str] = {}
    if action == "use" and not any(errors) and not draft.included():
        problems["items"] = "Include at least one item, or discard the draft."
    if any(errors) or problems:
        return _review(request, conn, row, rows=rows, errors=errors, problems=problems,
                       severe_conditions=draft.severe_conditions, status_code=422)
    if action == "use":
        schedules.confirm(conn, draft_id, row["vehicle_id"], sd.to_items(draft), draft.to_dict())
        return RedirectResponse(f"/vehicles/{row['vehicle_id']}/schedule?used=1", status_code=303)
    schedules.save_draft(conn, draft_id, draft.to_dict())
    return RedirectResponse(f"/schedule-drafts/{draft_id}?saved=1", status_code=303)


@router.post("/schedule-drafts/{draft_id}/read-again")
async def read_again(request: Request, draft_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _draft_or_404(conn, draft_id)
    if row["status"] not in ("read", "failed") or row["origin"] not in ("manual", "claude"):
        return RedirectResponse(f"/schedule-drafts/{draft_id}", status_code=303)
    form = await request.form()
    pages = forms.text(form.get("pages")) if "pages" in form else None
    if pages and row["document"]:
        try:
            manuals.parse_pages(pages, row["document"]["page_count"])
        except ValueError as err:
            return _review(request, conn, row, problems={"pages": str(err)}, pages_raw=pages, status_code=422)
    background.read_schedule_again(conn, draft_id, pages)
    return RedirectResponse(f"/schedule-drafts/{draft_id}", status_code=303)


@router.post("/schedule-drafts/{draft_id}/carry-on")
def carry_on(draft_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _draft_or_404(conn, draft_id)
    if row["stalled"] and row["job_id"]:
        background.carry_on(conn, row["job_id"])
    return RedirectResponse(f"/schedule-drafts/{draft_id}", status_code=303)


@router.post("/schedule-drafts/{draft_id}/discard")
def discard(draft_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    row = _draft_or_404(conn, draft_id)
    schedules.discard(conn, draft_id)
    return RedirectResponse(f"/vehicles/{row['vehicle_id']}/schedule", status_code=303)


@router.post("/schedule-drafts/{draft_id}/restore")
def restore(draft_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    _draft_or_404(conn, draft_id)
    schedules.restore(conn, draft_id)
    return RedirectResponse(f"/schedule-drafts/{draft_id}", status_code=303)


# ---------- Helpers ----------


def _draft_or_404(conn: sqlite3.Connection, draft_id: int) -> dict:
    row = schedules.get_draft(conn, draft_id)
    if row is None:
        raise HTTPException(status_code=404)
    return row


def _types(conn: sqlite3.Connection) -> dict[str, dict]:
    return {row["code"]: dict(row) for row in services.list_types(conn)}


def source_label(item: dict) -> str:
    return {
        "manual": f"Owner's manual{', p. ' + str(item['page']) if item.get('page') else ''}",
        "claude": "Claude's draft",
        "template": "Generic template",
        "you": "Set by you",
    }.get(item["source"], "")


def _page(request: Request, conn: sqlite3.Connection, car, status_code: int = 200, errors: dict | None = None,
          **extra) -> Response:
    severe = bool(car["severe_service"])
    groups: list[dict] = []
    in_effect = 0
    for item in sorted(schedules.items(conn, car["id"]),
                       key=lambda i: (i["category_sort"], i["category"], i["position"])):
        item.update(letter=ACTION_LETTERS[item["action"]], words=sd.interval_words(item),
                    in_effect=sd.in_effect(item, severe), source_label=source_label(item))
        in_effect += item["in_effect"]
        if not groups or groups[-1]["label"] != item["category"]:
            groups.append({"label": item["category"], "rows": []})
        groups[-1]["rows"].append(item)
    return render(
        request,
        "schedule.html",
        status_code=status_code,
        active="garage",
        car=car,
        groups=groups,
        count=sum(len(g["rows"]) for g in groups),
        in_effect=in_effect,
        severe=severe,
        current=schedules.current_draft(conn, car["id"]),
        drafts=schedules.open_drafts(conn, car["id"]),
        copyable=schedules.cars_with_schedules(conn, exclude=car["id"]),
        template_labels=templates.LABELS,
        can_draft=bool(car["year"] and car["make"] and car["model"]),
        car_words=manuals.describe_car(car),
        actions=ACTION_LABELS,
        errors=errors or {},
        raw=extra.pop("raw", {}),
        **extra,
    )


def _editor_context(conn: sqlite3.Connection, car, rows: list[dict], errors: list | None, mode: str,
                    reading: bool = False) -> dict:
    in_use = {code for row in rows for code in row["covers"]}
    # Page links name the file's content, so the browser may keep the image (routes_receipts._cache).
    fingerprints: dict[int, str] = {}
    for document_id in {row["document_id"] for row in rows if row["document_id"]}:
        if document := documents.get(conn, document_id):
            fingerprints[document_id] = documents.fingerprint(document["sha256"])
    return {
        "items": rows,
        "fingerprints": fingerprints,
        "errors": errors or [None] * len(rows),
        "types": editor_types(conn, car["powertrain"], in_use),
        "reading": reading,
        "mode": mode,
    }


def _editor(request: Request, conn: sqlite3.Connection, car, rows: list[dict], errors: list | None = None,
            status_code: int = 200) -> Response:
    return render(
        request,
        "schedule_edit.html",
        status_code=status_code,
        active="garage",
        car=car,
        editor=_editor_context(conn, car, rows, errors, "edit"),
        actions=ACTION_LABELS,
        applies=APPLIES_LABELS,
    )


def _review(request: Request, conn: sqlite3.Connection, row: dict, rows: list[dict] | None = None,
            errors: list | None = None, problems: dict | None = None, severe_conditions: str | None = None,
            pages_raw: str | None = None, saved: bool = False, status_code: int = 200) -> Response:
    car = row["vehicle"]
    draft = sd.ScheduleDraft.from_dict(row["draft"]) if row["draft"] else None
    if draft is not None and rows is None:
        rows = [editor_row(item) for item in draft.items] or [blank_row()]
    reading = row["origin"] in ("manual", "claude") and row["status"] == "read"
    return render(
        request,
        "schedule_draft.html",
        status_code=status_code,
        active="garage",
        row=row,
        car=car,
        document=row["document"],
        draft=draft,
        editor=_editor_context(conn, car, rows or [], errors, "draft", reading) if draft else None,
        left_out=sum(1 for r in rows or [] if not r["included"]),
        severe_conditions=draft.severe_conditions if severe_conditions is None and draft else (severe_conditions or ""),
        replaces=schedules.count(conn, car["id"]),
        car_words=manuals.describe_car(car),
        actions=ACTION_LABELS,
        applies=APPLIES_LABELS,
        problems=problems or {},
        pages_raw=row["requested_pages"] if pages_raw is None else pages_raw,
        saved=saved,
    )
