"""A car's issues as its pages show them, and reading the issue forms back.

The car's page lists the open ones, each asking about the newest visit since
you noticed it (engine/issues.py), and folds the fixed and dropped ones away.
A service's page shows the ones it fixed, and asks about itself.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from starlette.datastructures import UploadFile

from ..engine import issues as engine
from ..engine.issues import Visit
from ..engine.odometer import Odometer
from ..repo import documents, issues
from ..repo.issues import MAX_PHOTOS, IssueInput
from . import forms
from .recalls import day_words
from .templating import page_url

MAX_TITLE = 120
MAX_DETAILS = 2000
PHOTO_TYPES = (".png", ".jpg", ".jpeg", ".gif")


@dataclass
class Photo:
    id: int
    url: str     # a thumbnail
    full: str    # full size


@dataclass
class Row:
    id: int
    title: str
    details: str
    status: str
    noticed_on: str
    noticed: str                         # "Noticed Sep 2, 2026, at about 91,800 mi"
    photos: list[Photo]
    tried: str = ""                      # "Still there after Valley Honda on Sep 20, 2026"
    ask: Visit | None = None             # the visit to ask about
    question: str = ""
    visits: list[Visit] = field(default_factory=list)   # what It's fixed offers, newest first
    closed: str = ""                     # "Fixed Sep 20, 2026 at Valley Honda"
    fixed_by: int | None = None          # the service that fixed it


@dataclass
class Section:
    open: list[Row] = field(default_factory=list)
    closed: list[Row] = field(default_factory=list)


# ---------- Words ----------


def visit_words(visit: Visit | Mapping) -> str:
    """'Valley Honda on Sep 20, 2026', or 'your work on …' for one with no shop."""
    day, shop = (visit.day.isoformat(), visit.shop) if isinstance(visit, Visit) else (visit["performed_on"],
                                                                                      visit["shop"])
    return f"{shop or 'your work'} on {day_words(day)}"


def question(visit: Visit) -> str:
    day = day_words(visit.day.isoformat())
    return f"Did {visit.shop} fix it on {day}?" if visit.shop else f"Did your work on {day} fix it?"


def _noticed(issue: Mapping, odometer: Odometer | None) -> str:
    words = f"Noticed {day_words(issue['noticed_on'])}"
    miles = odometer.miles_on(date.fromisoformat(issue["noticed_on"])) if odometer else None
    return words + (f", at about {round(miles, -2):,.0f} mi" if miles else "")


def _closed(issue: Mapping) -> str:
    if issue["status"] == "dropped":
        return f"Dropped {day_words(issue['closed_on'])}".strip()
    if issue["status"] != "fixed":
        return ""
    if issue["fixed_service_on"]:
        by = f" at {issue['fixed_shop']}" if issue["fixed_shop"] else " by you"
        return f"Fixed {day_words(issue['fixed_service_on'])}{by}"
    return f"Fixed {day_words(issue['closed_on'])}".strip()


def photos(rows: Sequence[Mapping]) -> list[Photo]:
    return [Photo(row["id"], page_url(row["id"], row["sha256"], 1, thumb=True),
                  page_url(row["id"], row["sha256"], 1, full=True)) for row in rows]


def row(issue: Mapping, visits: Sequence[Visit], odometer: Odometer | None = None) -> Row:
    found = Row(issue["id"], issue["title"], issue["details"], issue["status"], issue["noticed_on"],
                _noticed(issue, odometer), photos(issue["photos"]), closed=_closed(issue),
                fixed_by=issue["fixed_by_event_id"])
    if issue["checks"]:
        found.tried = "Still there after " + _and([visit_words(check) for check in issue["checks"]])
    if issue["status"] == "open":
        noticed = date.fromisoformat(issue["noticed_on"])
        found.visits = engine.since(noticed, visits)
        found.ask = engine.to_ask(noticed, visits, {check["event_id"] for check in issue["checks"]})
        found.question = question(found.ask) if found.ask else ""
    return found


def _and(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + ", and " + parts[-1]


# ---------- Loading them ----------


def load(conn: sqlite3.Connection, car: Mapping, odometer: Odometer | None = None) -> Section:
    visits = issues.visits(conn, car["id"])
    rows = [row(issue, visits, odometer) for issue in issues.for_car(conn, car["id"])]
    return Section([r for r in rows if r.status == "open"], [r for r in rows if r.status != "open"])


def for_service(conn: sqlite3.Connection, event: Mapping) -> tuple[list[Row], list[Row]]:
    """A service's page: the issues it fixed, and the open ones that ask about it."""
    visits = issues.visits(conn, event["vehicle_id"])
    fixed = [row(issue, visits) for issue in issues.fixed_by(conn, event["id"])]
    asked = [r for r in load(conn, {"id": event["vehicle_id"]}).open if r.ask and r.ask.id == event["id"]]
    return fixed, asked


# ---------- The forms ----------


def parse(form) -> tuple[IssueInput, dict, dict]:
    """The issue a form gives, with the raw values and any errors."""
    raw = {key: forms.text(form.get(key)) for key in ("title", "details", "noticed_on")}
    errors: dict[str, str] = {}
    if not raw["title"]:
        errors["title"] = "Say what's wrong, such as Rattle at 40 mph."
    elif len(raw["title"]) > MAX_TITLE:
        errors["title"] = f"Keep it under {MAX_TITLE} characters. The details can say more."
    if len(raw["details"]) > MAX_DETAILS:
        errors["details"] = f"Keep the details under {MAX_DETAILS:,} characters."
    noticed = None
    try:
        noticed = forms.day(raw["noticed_on"])
    except ValueError as err:
        errors["noticed_on"] = str(err)
    else:
        if noticed is None:
            errors["noticed_on"] = "Enter the day you noticed it."
    return IssueInput(raw["title"], raw["details"], noticed or ""), raw, errors


async def store_photos(conn: sqlite3.Connection, form) -> tuple[list[int], str]:
    """The photos a form keeps (hidden ``photo`` ids) and the ones it uploads, stored; and any error to show.

    Uploads are stored even when something else on the form is wrong, so they
    stay attached when it comes back.
    """
    kept: list[int] = []
    for value in form.getlist("photo"):
        text = forms.text(value)
        document = documents.get(conn, int(text)) if text.isdigit() else None
        if document is not None and document["media_type"].startswith("image/"):
            kept.append(document["id"])
    error = ""
    for upload in form.getlist("photos"):
        if not isinstance(upload, UploadFile) or not upload.filename:
            continue
        name = Path(upload.filename).name
        if Path(name).suffix.lower() not in PHOTO_TYPES:
            error = f"{name}: add photos as PNG, JPG or GIF."
            continue
        try:
            document, _ = documents.store(conn, await upload.read(), name)
        except documents.UploadError as err:
            error = str(err)
            continue
        kept.append(document["id"])
    kept = list(dict.fromkeys(kept))
    if len(kept) > MAX_PHOTOS and not error:
        error = f"An issue holds up to {MAX_PHOTOS} photos. Remove {len(kept) - MAX_PHOTOS}."
    return kept, error


def photo_rows(conn: sqlite3.Connection, ids: Sequence[int]) -> list[Photo]:
    """Photos by id, for a form coming back."""
    return photos([document for document in (documents.get(conn, i) for i in ids) if document is not None])


def parse_fix(form, issue: Mapping, visits: Sequence[Visit]) -> tuple[str, int | None, dict, str]:
    """It's fixed: (day, the service if one was chosen, raw, error)."""
    raw = {key: forms.text(form.get(key)) for key in ("service_event_id", "fixed_on")}
    offered = {str(v.id): v for v in engine.since(date.fromisoformat(issue["noticed_on"]), visits)}
    if visit := offered.get(raw["service_event_id"]):
        return visit.day.isoformat(), visit.id, raw, ""
    try:
        day = forms.day(raw["fixed_on"])
    except ValueError as err:
        return "", None, raw, str(err)
    if day is None:
        return "", None, raw, "Enter the day it was fixed."
    if day < issue["noticed_on"]:
        return "", None, raw, f"That's before you noticed it, on {day_words(issue['noticed_on'])}."
    return day, None, raw, ""
