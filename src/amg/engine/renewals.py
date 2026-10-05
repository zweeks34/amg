"""Inspections and registration: when each runs out, and when to say so.

The state sets these, not the owner's manual: a safety or emissions sticker, a
registration card, each good through the day it expires. You type that date;
AMG only suggests one, always the last day of a month, since stickers and
registrations run to the end of the month they show:

- an inspection counts from the day it was done: inspect early and the months
  left on the old sticker are gone;
- a registration renewal extends the old expiry, or counts from the day you
  renewed if it had lapsed.

How long one lasts is what your last two records show, in whole years; until
they show it, 12 months for a safety inspection or a registration and 24 for
emissions.

Each is due soon from 30 days out, in its last week from 7, and expired the day
after it expires. Pure: no database, no I/O.
"""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from .schedule import add_months

DUE_DAYS = 30
WEEK_DAYS = 7


@dataclass(frozen=True)
class Kind:
    code: str
    name: str
    months: int                  # how long one lasts until the records say otherwise
    from_expiry: bool            # a renewal extends the old date (registration); else it counts from the day done
    service_type: str | None     # the catalogue's service type for it on a receipt
    powertrains: frozenset[str]  # the cars it's offered for (emissions: not electric ones)


KINDS: dict[str, Kind] = {kind.code: kind for kind in (
    Kind("safety", "Safety inspection", 12, False, "state_inspection", frozenset({"gas", "hybrid", "ev"})),
    Kind("emissions", "Emissions inspection", 24, False, "emissions_test", frozenset({"gas", "hybrid"})),
    Kind("registration", "Registration", 12, True, None, frozenset({"gas", "hybrid", "ev"})),
)}


@dataclass(frozen=True)
class Record:
    expires_on: date
    done_on: date | None = None
    service_id: int | None = None    # the service it was logged from


@dataclass(frozen=True)
class Standing:
    state: str    # later, due (30 days or fewer), week (7 or fewer), expired (the day after)
    days: int     # to the expiry: 0 on the day, negative once past


def standing(expires_on: date, today: date) -> Standing:
    days = (expires_on - today).days
    if days < 0:
        state = "expired"
    elif days <= WEEK_DAYS:
        state = "week"
    elif days <= DUE_DAYS:
        state = "due"
    else:
        state = "later"
    return Standing(state, days)


def end_of_month(day: date) -> date:
    return date(day.year, day.month, monthrange(day.year, day.month)[1])


def interval(kind: Kind, records: Sequence[Record]) -> int:
    """Months one lasts, from ``records`` (newest first): the gap between the last two expiries, else from the
    latest's done date to its expiry, in whole years; else the kind's usual."""
    spans = []
    if len(records) >= 2:
        spans.append(_months(records[1].expires_on, records[0].expires_on))
    if records and records[0].done_on is not None:
        spans.append(_months(records[0].done_on, records[0].expires_on))
    for months in spans:
        if months >= 6:   # two entries for the same sticker say nothing about how long one lasts
            return max(12, int(months / 12 + 0.5) * 12)
    return kind.months


def suggest(kind: Kind, done_on: date, records: Sequence[Record]) -> date:
    """The expiry to offer for one done (or renewed) on ``done_on``, given the records before it, newest first."""
    base = done_on
    if kind.from_expiry and records:
        base = max(records[0].expires_on, done_on)
    return end_of_month(add_months(base, interval(kind, records)))


def offer(kind: Kind, service_day: date, service_id: int, records: Sequence[Record], today: date) -> date | None:
    """The expiry an inspection on a receipt points to, if it's worth offering to log; else None.

    Worth it when logging it would move the expiry later. With nothing logged
    yet, only when the sticker it points to could still be on the car: an old
    receipt's would have expired long ago.
    """
    if any(record.service_id == service_id for record in records):
        return None
    expiry = suggest(kind, service_day, records)
    if records:
        return expiry if expiry > records[0].expires_on else None
    return expiry if expiry >= today else None


def _months(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + end.month - start.month
