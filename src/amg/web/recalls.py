"""Recalls on the car's page, the garage and in alerts: asking NHTSA, and saying what it said.

The daily alerts run checks each car once a week (repo/recalls.due_for_check);
the car's page can check it now. A check that can't reach NHTSA is said on the
page and tried again on the next run.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from ..ingest import recalls as nhtsa
from ..repo import recalls


def check(conn: sqlite3.Connection, car, today: date | None = None) -> list[str] | None:
    """Ask NHTSA about a car and store the answer: the campaigns new to it, or None if NHTSA couldn't be asked."""
    try:
        found = nhtsa.lookup(car["year"], car["make"], car["model"])
    except nhtsa.RecallLookupError as err:
        recalls.failed(conn, car["id"], str(err))
        return None
    return recalls.record(conn, car["id"], found, today or date.today())


def component(text: str) -> str:
    """NHTSA's capitals in sentence case: 'AIR BAGS: AIR BAG MODULE' → 'Air bags: air bag module'."""
    if not text:
        return "Recall"
    parts = [part.strip().lower() for part in text.split(":")]
    return ": ".join([parts[0].capitalize(), *parts[1:]])


def day_words(iso: str | None) -> str:
    if not iso:
        return ""
    day = date.fromisoformat(iso)
    return f"{day:%b} {day.day}, {day.year}"


def advice(row) -> str:
    """What NHTSA says to do until it's fixed, if anything."""
    if row["park_it"]:
        return "NHTSA says not to drive it until this is fixed."
    if row["park_outside"]:
        return "NHTSA says to park it outside, away from buildings, until this is fixed."
    return ""


def when(row) -> str:
    """'NHTSA 19V-910 · reported Dec 19, 2019'."""
    reported = day_words(row["reported_on"])
    return f"NHTSA {nhtsa.campaign_words(row['campaign'])}" + (f" · reported {reported}" if reported else "")


@dataclass
class Section:
    """The car page's recalls."""
    searched: str                    # "2016 Subaru Outback"; '' when the car lacks a year, make or model
    checked_on: str | None
    model: str                       # NHTSA's name it matched; '' for none
    listed: list[str]                # NHTSA's models of that year and make with recalls
    error: str
    open: list[dict] = field(default_factory=list)
    closed: list[dict] = field(default_factory=list)


def load(conn: sqlite3.Connection, car) -> Section:
    rows = [_row(conn, car, row) for row in recalls.for_car(conn, car["id"])]
    can_check = car["year"] and car["make"] and car["model"]
    return Section(
        searched=f"{car['year']} {car['make']} {car['model']}" if can_check else "",
        checked_on=day_words(car["recalls_checked_on"]) or None,
        model=car["recalls_model"],
        listed=[name.title() for name in car["recalls_listed"].split(",") if name],
        error=car["recalls_error"],
        open=[row for row in rows if row["status"] == "open"],
        closed=[row for row in rows if row["status"] != "open"],
    )


def _row(conn: sqlite3.Connection, car, row) -> dict:
    found = dict(row)
    found.update(
        name=component(row["component"]), when=when(row), advice=advice(row),
        closed_words=_closed(row),
        visits=[dict(v) for v in recalls.recall_visits(conn, car["id"], row["reported_on"])]
        if row["status"] == "open" else [],
    )
    return found


def _closed(row) -> str:
    if row["status"] == "not_mine":
        return "Not my car"
    if row["status"] != "done":
        return ""
    if row["service_on"]:
        return f"Done {day_words(row['service_on'])}" + (f" at {row['service_shop']}" if row["service_shop"] else "")
    return f"Done {day_words(row['closed_on'])}" if row["closed_on"] else "Done"
