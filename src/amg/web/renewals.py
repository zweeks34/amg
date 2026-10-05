"""What the car page and the garage say about inspections and registration.

engine/renewals.py decides; this puts its answer into words — "expires Oct 31
· in 26 days" — and works out what each row's form starts with: an inspection
your service history shows and the expiry it points to, else today and AMG's
guess at the next expiry, else (nothing logged yet) blanks to fill from the
sticker.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from ..engine import renewals as engine
from ..engine.renewals import KINDS, Kind, Record, Standing
from ..repo import renewals as repo

MARKS = {"later": "later", "due": "due", "week": "due", "expired": "overdue"}   # the schedule's marks
LABELS = {"later": "Later", "due": "Due soon", "week": "Due soon", "expired": "Expired"}
RECENT = 60   # days: an expiry further back than this is said by its date alone


@dataclass(frozen=True)
class Words:
    done: str       # the done date's label
    log: str        # the button that opens the form, once one is logged
    save: str       # the form's button
    receipt: str    # what a service shows, in a sentence; "" if it never does
    expires: str    # the expiry's hint


WORDS = {
    "safety": Words("Inspected on", "Log an inspection", "Save inspection", "a state inspection",
                    "The last day it's good for: a sticker punched 9/27 is good through Sep 30, 2027."),
    "emissions": Words("Inspected on", "Log an inspection", "Save inspection", "an emissions test",
                       "The last day it's good for."),
    "registration": Words("Renewed on", "Log a renewal", "Save registration", "",
                          "The last day it's good for, from the registration card."),
}


@dataclass
class Row:
    kind: Kind
    records: list[dict]                        # newest first: the first is the one in force
    standing: Standing | None
    when: str                                  # "expires Oct 31 · in 26 days"; "not tracked"
    offer: dict | None = None                  # an inspection in your service history worth logging
    form: dict = field(default_factory=dict)   # what the form starts with

    @property
    def words(self) -> Words:
        return WORDS[self.kind.code]

    @property
    def mark(self) -> str | None:
        return MARKS[self.standing.state] if self.standing else None

    @property
    def mark_label(self) -> str | None:
        return LABELS[self.standing.state] if self.standing else None

    @property
    def urgent(self) -> bool:
        return self.standing is not None and self.standing.state != "later"

    @property
    def said(self) -> str:
        """``when``, as a sentence starts."""
        return self.when[:1].upper() + self.when[1:]

    @property
    def action(self) -> str:
        return self.words.log if self.records else "Add the expiry date"

    @property
    def hint(self) -> str:
        if not self.form.get("guessed"):
            return self.words.expires
        against = "card" if self.kind.code == "registration" else "sticker"
        return f"{self.words.expires} AMG guessed this one: check it against the {against}."


def _date(day: date, today: date) -> str:
    return f"{day:%b} {day.day}" + (f", {day.year}" if day.year != today.year else "")


def when(standing: Standing, expires_on: date, today: date) -> str:
    day = _date(expires_on, today)
    if standing.state == "later":
        return f"expires {day}"
    if standing.days > 0:
        return f"expires {day} · in {standing.days} day{'s' if standing.days != 1 else ''}"
    if standing.days == 0:
        return "expires today"
    ago = -standing.days
    return f"expired {day}" + (f" · {ago} day{'s' if ago != 1 else ''} ago" if ago <= RECENT else "")


def record(row) -> Record:
    return Record(date.fromisoformat(row["expires_on"]), date.fromisoformat(row["done_on"]) if row["done_on"] else None,
                  row["service_event_id"])


def cents(value: int | None) -> str:
    return "" if value is None else f"{value / 100:.2f}"


def rows(conn: sqlite3.Connection, car, today: date | None = None, offers: bool = True) -> list[Row]:
    """A row for each kind the car can need — emissions not for an electric one, unless it has some logged.

    ``offers`` looks for inspections in the service history worth logging; the
    garage and the alerts don't need them.
    """
    today = today or date.today()
    found = repo.for_car(conn, car["id"])
    result = []
    for kind in KINDS.values():
        logged = [dict(row) for row in found.get(kind.code, [])]
        if not logged and car["powertrain"] not in kind.powertrains:
            continue
        records = [record(row) for row in logged]
        standing = engine.standing(records[0].expires_on, today) if records else None
        row = Row(kind, logged, standing, when(standing, records[0].expires_on, today) if standing else "not tracked")
        if offers and kind.service_type and (service := repo.latest_service(conn, car["id"], kind.service_type)):
            day = date.fromisoformat(service["performed_on"])
            if expiry := engine.offer(kind, day, service["id"], records, today):
                row.offer = {**service, "expires_on": expiry,
                             "said": f"{row.words.receipt}" + (f" at {service['shop']}" if service["shop"] else "")
                                     + f" on {_date(day, today)}"}
        row.form = _form(kind, records, row.offer, today)
        result.append(row)
    return result


def urgent(found: list[Row]) -> list[Row]:
    """The ones due soon or expired, the soonest (or longest gone) first."""
    return sorted((row for row in found if row.urgent), key=lambda row: row.standing.days)


def _form(kind: Kind, records: list[Record], offer: dict | None, today: date) -> dict:
    if offer:
        return {"done_on": offer["performed_on"], "expires_on": offer["expires_on"].isoformat(),
                "cost": cents(offer["cost_cents"]), "note": "", "service_event_id": str(offer["id"]), "guessed": True}
    if records:
        return {"done_on": today.isoformat(), "expires_on": engine.suggest(kind, today, records).isoformat(),
                "cost": "", "note": "", "guessed": True}
    return {"done_on": "", "expires_on": "", "cost": "", "note": ""}
