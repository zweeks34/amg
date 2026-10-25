"""A service and the schedule's jobs: what a service counted for, and the services a job might have been done in.

Nothing stores which job a service did: the gap engine counts a service for a
job when one of its lines covers one of the job's service types, with an
action that meets it (engine/schedule.meets). So what a service counted for is
read off the engine's answer, the done marks it made. A service can match a job
and still not count for it, and the page says why, so a line tagged wrongly, or
not at all, can be put right.

Mark as done offers the car's own services near when a job fell due, so a job
done in one you logged is tagged there (on its edit form, or its receipt's
review, with the job applied as the menu would apply it) rather than recorded
again as done with no receipt.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from ..engine.schedule import ItemStatus, Service, meets, start_point
from ..repo import receipts, services
from . import line_editor
from . import status as car_status
from .recalls import day_words
from .templating import who

TWIN_DAYS = 30   # a "Done, no receipt" this close to a service, for the same job, is likely the same work
CANDIDATES = 5   # services Mark as done offers


@dataclass
class Counted:
    met: list[dict] = field(default_factory=list)     # {name, due, twins}: the jobs it counted for
    unmet: list[dict] = field(default_factory=list)   # {name, why}: jobs it matches but didn't count for


def counted_for(conn: sqlite3.Connection, car, event: dict) -> Counted | None:
    """What a confirmed service counted for on its car's schedule; None when there's no schedule to count for."""
    if not event["confirmed"]:
        return None
    state = car_status.load(conn, car)
    service = next((s for s in state.services if s.id == event["id"]), None)
    if not state.statuses or service is None:
        return None
    attested = [s for s in state.services if s.id in _attested(conn, car["id"]) and s.id != service.id]
    found = Counted()
    for item_status in state.statuses:
        done = [o for o in item_status.occurrences if o.status == "done" and o.service and o.service.id == service.id]
        if done:
            twins = [] if event["source"] == "attested" else [
                {"day": day_words(s.day.isoformat()), "href": f"/services/{s.id}"}
                for s in attested if meets(s, item_status.item) and abs((s.day - service.day).days) <= TWIN_DAYS
            ]
            found.met.append({"name": item_status.item.name, "due": _due(done[0], service), "twins": twins})
        elif meets(service, item_status.item):
            found.unmet.append({"name": item_status.item.name, "why": _why(item_status, service, state, car)})
    return found


def _due(occurrence, service: Service) -> str:
    """When the job it counted for was due, and whether it came early or late."""
    day = day_words(occurrence.due_day.isoformat())
    words = f"was due at {occurrence.due_miles:,} mi · {day}" if occurrence.due_miles is not None else f"was due {day}"
    if occurrence.late:
        return words + ", done late"
    return words + (", done early" if service.day < occurrence.due_day else "")


def _why(item_status: ItemStatus, service: Service, state: car_status.CarStatus, car) -> str:
    """Why a service that matches a job didn't count for it."""
    item = item_status.item
    repeats = bool(item.interval_miles or item.interval_months)
    if repeats and item.counts_from and service.day <= item.counts_from:
        return f"it's on or before {day_words(item.counts_from.isoformat())}, the day this job counts from"
    vehicle = car_status.engine_car(car)
    start = start_point(vehicle, state.services, state.odometer)
    if not (repeats and item.counts_from) and start and service.day <= start[0]:
        if vehicle.in_service:
            return "it's from on or before the day the car was new, which the schedule counts from"
        if vehicle.acquired_on:
            return "it's from on or before the day you got the car, which the schedule counts from"
        return ("it's the car's first record, which the schedule counts from. Add the day you got the car, or "
                "the day it was new, to the car's details")
    if item_status.needs_reading or not item_status.occurrences:
        return "this job falls due by mileage, and the car has no odometer readings to place it"
    if not repeats:
        return "it's done once, and an earlier service already did it"
    return "another service the same day already counted for it"



def candidates(conn: sqlite3.Connection, car, item_id: int, near: date | None = None) -> list[dict]:
    """The car's own services a job might have been done in, newest first: none marked done with no receipt,
    none that already meet it, none on or before the day it counts from; the few dated nearest ``near`` (by
    default when the job fell or falls due next)."""
    state = car_status.load(conn, car)
    item_status = next((s for s in state.statuses if s.item.id == item_id), None)
    if item_status is None:
        return []
    item = item_status.item
    if near is None:
        near = item_status.current.due_day if item_status.current else state.today
    attested = _attested(conn, car["id"])
    counts_from = item.counts_from if item.interval_miles or item.interval_months else None
    found = [s for s in state.services
             if s.id not in attested and not meets(s, item) and not (counts_from and s.day <= counts_from)]
    nearest = sorted(found, key=lambda s: (abs((s.day - near).days), -s.id))[:CANDIDATES]
    rows = []
    for service in sorted(nearest, key=lambda s: (s.day, s.id), reverse=True):
        event = services.get_event(conn, service.id)
        receipt = receipts.for_event(conn, service.id)
        names = [line["description"] for line in event["lines"]]
        rows.append({
            "day": day_words(event["performed_on"]),
            "who": who(event),
            "lines": ", ".join(names[:3]) + (f" and {len(names) - 3} more" if len(names) > 3 else ""),
            "href": (f"/receipts/{receipt['id']}?item={item_id}" if receipt
                     else f"/services/{service.id}/edit?item={item_id}"),
        })
    return rows


def job(conn: sqlite3.Connection, car, item_id: int | None) -> dict | None:
    """One of the car's jobs, as the menu offers it; None for another car's, or one that doesn't apply to this car."""
    if item_id is None:
        return None
    return next((p for p in car_status.picks(car_status.load(conn, car)) if p["id"] == item_id), None)


def apply_item(rows: list[dict], picked: dict) -> list[dict]:
    """Editor rows with a job applied, as picking it from the menu applies it: on the first untagged row, else
    on a new one. Its service types go on with the job's own action, and the row takes its name if it has none."""
    rows = [dict(row) for row in rows]
    target = next((row for row in rows if not row.get("covers")), None)
    if target is None:
        target = line_editor.blank_line()
        rows.append(target)
    covers, actions = list(target.get("covers") or []), dict(target.get("actions") or {})
    for code in picked["codes"]:
        if code not in covers:
            covers.append(code)
        if picked["action"] != "inspect":
            actions[code] = picked["action"]
    target.update(covers=covers, actions=actions, inspect_only=picked["action"] == "inspect", covers_source="you")
    if not str(target.get("description") or "").strip():
        target["description"] = picked["name"]
    return rows


def _attested(conn: sqlite3.Connection, vehicle_id: int) -> set[int]:
    return {row["id"] for row in services.history(conn, vehicle_id) if row["source"] == "attested"}
