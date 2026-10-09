"""Warranties: when each ends, whether it's ending soon, and which later visit to ask about.

A warranty runs from a day, and the miles then, for some months or some
miles, whichever comes first, or for life. It's in force through its last
day, and until the car reaches its miles. It covers some services (a
battery, a visit's parts and labor) or the whole car.

A later visit that replaced a part it covers raises a question, not an
answer. Done under the warranty keeps it, since a part replaced under
warranty usually keeps the rest of the term. Paid for it ends it that day,
since the part it covered is gone. Inspections and procedures never ask: a
lifetime rotation is used, not used up. Neither does "Other repair", too
vague to match one repair to another, nor a whole-car warranty, whose parts
aren't listed.

Pure: no database, no I/O.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date

from .odometer import Odometer
from .schedule import add_months

ENDING_DAYS = 60                   # ending soon: this close by date, or by the miles driven in this many days
NEVER_ASKS = frozenset({"other"})


@dataclass(frozen=True)
class Warranty:
    id: int
    starts_on: date
    start_miles: int | None        # None: estimated from the readings
    months: int | None
    miles: int | None
    codes: frozenset[str] = frozenset()
    whole_car: bool = False
    event_id: int | None = None    # the visit it came with

    @property
    def lifetime(self) -> bool:
        return self.months is None and self.miles is None


@dataclass(frozen=True)
class Visit:
    id: int
    day: date
    shop: str
    odometer: int | None
    replaced: frozenset[str]       # the service codes it replaced


@dataclass(frozen=True)
class Standing:
    state: str                     # in_force, ending or ended
    ends_on: date | None           # its last day by time
    end_miles: int | None          # the miles it ends at
    end_day: date | None = None    # the day it ends (or ended): the sooner of its date and its miles, when known
    by: str = ""                   # what ends it first: date, miles, or (ended only) paid
    paid: Visit | None = None      # the visit you paid for, when that ended it


def ends_on(warranty: Warranty) -> date | None:
    return None if warranty.months is None else add_months(warranty.starts_on, warranty.months)


def start_miles(warranty: Warranty, odometer: Odometer | None) -> float | None:
    if warranty.start_miles is not None:
        return float(warranty.start_miles)
    return odometer.miles_on(warranty.starts_on) if odometer is not None else None


def end_miles(warranty: Warranty, odometer: Odometer | None) -> int | None:
    """The miles it ends at; None when it has no mileage limit, or the miles it started at aren't known."""
    if warranty.miles is None:
        return None
    start = start_miles(warranty, odometer)
    return None if start is None else round(start) + warranty.miles


def in_force_on(warranty: Warranty, day: date, miles: float | None, odometer: Odometer | None) -> bool:
    """By its dates and miles alone; what you said about later visits is ``standing``'s business."""
    if day < warranty.starts_on:
        return False
    last = ends_on(warranty)
    if last is not None and day > last:
        return False
    limit = end_miles(warranty, odometer)
    return limit is None or miles is None or miles < limit


def replacing(warranty: Warranty, visits: Iterable[Visit], odometer: Odometer | None) -> list[Visit]:
    """Later visits that replaced a part it covers while it was in force, oldest first.

    Not its own visit, nor one the same day: that's the visit that fitted
    the part, whether or not you said so.
    """
    if warranty.whole_car:
        return []
    asks = warranty.codes - NEVER_ASKS
    found = [
        v for v in visits
        if v.day > warranty.starts_on and v.id != warranty.event_id and v.replaced & asks
        and in_force_on(warranty, v.day, _miles(v, odometer), odometer)
    ]
    return sorted(found, key=lambda v: (v.day, v.id))


def paid(warranty: Warranty, visits: Iterable[Visit], answers: Mapping[int, str]) -> Visit | None:
    """The earliest visit since it started that you said you paid for: the part was replaced, and it ended."""
    said = [v for v in visits if answers.get(v.id) == "paid" and v.day >= warranty.starts_on]
    return min(said, key=lambda v: (v.day, v.id), default=None)


def to_ask(warranty: Warranty, visits: Iterable[Visit], answers: Mapping[int, str],
           odometer: Odometer | None) -> Visit | None:
    """The earliest later visit that replaced a covered part and you haven't answered; none once one was paid for."""
    visits = list(visits)
    ended = paid(warranty, visits, answers)
    for visit in replacing(warranty, visits, odometer):
        if ended is not None and (visit.day, visit.id) >= (ended.day, ended.id):
            return None
        if visit.id not in answers:
            return visit
    return None


def standing(warranty: Warranty, today: date, odometer: Odometer | None, visits: Iterable[Visit] = (),
             answers: Mapping[int, str] | None = None) -> Standing:
    """In force, ending soon, or ended (by date, by miles, or because you paid to replace the part)."""
    last = ends_on(warranty)
    limit = end_miles(warranty, odometer)
    reached = odometer.day_at(limit) if (limit is not None and odometer) else None
    bought = paid(warranty, visits, answers or {})
    ends = [(day, by) for day, by in ((last, "date"), (reached, "miles")) if day is not None]
    first = min(ends, default=(None, ""))

    over = [(day, by) for day, by in ends if (day < today if by == "date" else day <= today)]
    if bought is not None and bought.day <= today:
        over.append((bought.day, "paid"))
    if over:
        day, by = min(over)
        return Standing("ended", last, limit, day, by, bought if by == "paid" else None)
    if first[0] is not None and (first[0] - today).days <= ENDING_DAYS:
        return Standing("ending", last, limit, first[0], first[1])
    return Standing("in_force", last, limit, first[0], first[1])


def _miles(visit: Visit, odometer: Odometer | None) -> float | None:
    if visit.odometer is not None:
        return float(visit.odometer)
    return odometer.miles_on(visit.day) if odometer is not None else None
