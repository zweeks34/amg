"""A car's shop recommendations, as its page, the garage and the weekly email show them.

Open ones from the last 12 months come first; older open ones fold away, so
years of old receipts don't bury what the shop said last month. The ones
you're not doing fold away too, with a way back.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from ..engine import follow_ups as engine
from ..engine.schedule import Service, add_months
from ..repo import follow_ups, services

RECENT_MONTHS = 12


@dataclass
class FollowUps:
    recent: list[engine.FollowUp] = field(default_factory=list)    # open, newest first
    older: list[engine.FollowUp] = field(default_factory=list)     # open, over RECENT_MONTHS old
    skipped: list[engine.FollowUp] = field(default_factory=list)   # yours: not doing it

    @property
    def open(self) -> list[engine.FollowUp]:
        return self.recent + self.older

    @property
    def quoted(self) -> int:
        """What the shops quoted for the open ones, where they did."""
        return sum(f.rec.quoted_cents or 0 for f in self.open if (f.rec.quoted_cents or 0) > 0)

    def __bool__(self) -> bool:
        return bool(self.open or self.skipped)


def everything(conn: sqlite3.Connection, car) -> list[engine.FollowUp]:
    """Every recommendation on the car's confirmed receipts, open or closed, oldest first."""
    visits = [
        Service(row["id"], date.fromisoformat(row["performed_on"]), row["odometer"],
                {code: frozenset(actions) for code, actions in row["coverage"].items()})
        for row in services.coverage(conn, car["id"])
    ]
    defaults = {row["code"]: row["default_action"] for row in services.list_types(conn)}
    return engine.follow(follow_ups.recommendations(conn, car["id"]), visits, defaults,
                         follow_ups.outcomes(conn, car["id"]))


def load(conn: sqlite3.Connection, car, today: date | None = None) -> FollowUps:
    today = today or date.today()
    every = sorted(everything(conn, car), key=lambda f: (f.rec.day, f.rec.event_id), reverse=True)
    since = add_months(today, -RECENT_MONTHS)
    return FollowUps(
        recent=[f for f in every if f.open and f.rec.day >= since],
        older=[f for f in every if f.open and f.rec.day < since],
        skipped=[f for f in every if f.skipped],
    )
