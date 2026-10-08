"""The sheet for the shop: what to ask for at the next visit, on one page to show or print.

Your open issues first, numbered so you can say "number 2"; then the
schedule's jobs overdue or due soon; then what shops recommended in the last
year that's still open. No prices: it's the page you hand over.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date

from ..repo import vehicles
from . import follow_ups as follow_up_words
from . import issues as issue_words
from . import status as car_status
from .recalls import day_words


@dataclass
class Sheet:
    model: str                      # "2019 Honda Civic EX"; '' for a car with none of it
    odometer: str                   # "about 92,400 mi today", "91,850 mi on Sep 30, 2026", or ''
    today: str                      # "Oct 8, 2026"
    issues: list[issue_words.Row] = field(default_factory=list)
    due: list[dict] = field(default_factory=list)            # next-up rows: overdue and due soon
    recommended: list[dict] = field(default_factory=list)    # {description, where}

    @property
    def empty(self) -> bool:
        return not (self.issues or self.due or self.recommended)


def odometer_words(state: car_status.CarStatus, latest: Mapping | None) -> str:
    """Today's miles: the reading if there's one today, else the estimate, else the last reading and its date."""
    today = state.today.isoformat()
    if latest and latest["read_on"] == today:
        return f"{latest['miles']:,} mi today"
    if state.today_miles is not None:
        return f"about {round(state.today_miles, -2):,} mi today"
    return f"{latest['miles']:,} mi on {day_words(latest['read_on'])}" if latest else ""


def load(conn: sqlite3.Connection, car: Mapping, today: date | None = None) -> Sheet:
    today = today or date.today()
    state = car_status.load(conn, car, today)
    return Sheet(
        model=" ".join(str(part) for part in (car["year"], car["make"], car["model"], car["trim"]) if part),
        odometer=odometer_words(state, vehicles.latest_odometer(conn, car["id"])),
        today=day_words(today.isoformat()),
        issues=issue_words.load(conn, car, state.odometer).open,
        due=car_status.next_up(state, limit=0),
        recommended=[
            {"description": f.rec.description,
             "where": f"{f.rec.shop or 'A shop'}, {day_words(f.rec.day.isoformat())}"}
            for f in follow_up_words.load(conn, car, today).recent
        ],
    )
