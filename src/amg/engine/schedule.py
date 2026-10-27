"""The gap engine: each schedule item walked against the services that met it.

An item falls due at the earlier of its mileage and its months, counted from
when it was last done (or from new, the first time). Then:

* **done**    — a matching service came before the *next* one fell due. Late
               if it came more than a tenth of an interval after the due point.
               The next is counted from that service.
* **gap**     — nothing matched before the next one fell due as well: missed.
               The next is counted from the missed due point, as if done then.
* **before**  — a gap that fell due before you had the car: not yours to judge.
* **overdue** — the due point has passed; the next hasn't fallen due yet.
* **due**     — due within DUE_SOON_DAYS or DUE_SOON_MILES.
* **later**   — further off.

A repeating item with a count-from date (a job you never kept records of)
starts its count on that day instead, as if done then: nothing before it is
judged, services before it don't count for it, and "first at" no longer
applies.

What meets what: a service meets an item when it covers one of the item's
service types; an inspection item is met by anything done to the part, a
replacement or procedure only by a replacement or procedure. A dealer's
multi-point inspection or a state inspection meets every inspection item.

Pure: dates and miles in, statuses out. The odometer model turns mileages
into dates; with no readings, items are judged by months alone, and an item
with only a mileage can't be judged at all.
"""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta

from .odometer import Odometer

DUE_SOON_DAYS = 30
DUE_SOON_MILES = 1_000
LATE_TOLERANCE = 0.10
INSPECTIONS = frozenset({"multipoint_inspection", "state_inspection"})
_DOING = frozenset({"replace", "perform"})
_MAX_OCCURRENCES = 400   # a 1,000-mile interval over 400,000 miles; past this something is wrong


@dataclass(frozen=True)
class Item:
    id: int
    name: str
    codes: frozenset[str]
    action: str
    interval_miles: int | None = None
    interval_months: int | None = None
    first_miles: int | None = None
    first_months: int | None = None
    applies: str = "always"
    counts_from: date | None = None


@dataclass(frozen=True)
class Service:
    id: int
    day: date
    miles: int | None
    coverage: Mapping[str, frozenset[str]]   # service type code → the actions taken on it


@dataclass(frozen=True)
class Car:
    in_service: date | None = None
    acquired_on: date | None = None
    acquired_miles: int | None = None
    severe: bool = False


@dataclass
class Occurrence:
    status: str               # done, gap, before, overdue, due, later
    due_day: date
    due_miles: int | None     # the odometer when it fell (or falls) due, where it can be told
    service: Service | None = None
    late: bool = False
    from_day: date | None = None    # where its interval was counted from: the last time it was done, a missed due
    from_miles: float | None = None  # point, or the start


@dataclass
class ItemStatus:
    item: Item
    occurrences: list[Occurrence] = field(default_factory=list)
    needs_reading: bool = False   # due by mileage only, and no odometer readings to place it

    @property
    def current(self) -> Occurrence | None:
        """The occurrence to act on next: overdue, due soon or later."""
        return next((o for o in self.occurrences if o.status in ("overdue", "due", "later")), None)

    @property
    def missed(self) -> list[Occurrence]:
        return [o for o in self.occurrences if o.status == "gap"]

    @property
    def last_done(self) -> Occurrence | None:
        return next((o for o in reversed(self.occurrences) if o.status == "done"), None)


def in_effect(item, severe_service: bool) -> bool:
    """Whether an item counts for a car following normal or severe service."""
    applies = item["applies"] if isinstance(item, Mapping) else item.applies
    return applies == "always" or (applies == "severe") == bool(severe_service)


def meets(service: Service, item: Item) -> bool:
    for code in item.codes:
        actions = service.coverage.get(code)
        if actions and (item.action == "inspect" or actions & _DOING):
            return True
    return item.action == "inspect" and any(code in service.coverage for code in INSPECTIONS)


def add_months(day: date, months: int) -> date:
    month = day.month - 1 + months
    year, month = day.year + month // 12, month % 12 + 1
    return date(year, month, min(day.day, monthrange(year, month)[1]))


def start_point(car: Car, services: Iterable[Service], odometer: Odometer) -> tuple[date, float] | None:
    """Where an item's count begins: new, else when you got it, else the first record."""
    if car.in_service:
        return car.in_service, 0.0
    if car.acquired_on:
        miles = car.acquired_miles if car.acquired_miles is not None else odometer.miles_on(car.acquired_on)
        return car.acquired_on, float(miles or 0)
    days = [s.day for s in services] + [p[0] for p in odometer.points]
    if not days:
        return None
    first = min(days)
    return first, odometer.miles_on(first) or 0.0


def _due(item: Item, car: Car, base_day: date, base_miles: float, first: bool,
         odometer: Odometer) -> tuple[date, int | None] | None:
    """When the occurrence after (base_day, base_miles) falls due, whichever comes first."""
    if first and (item.first_miles or item.first_months):
        # "First at 137,500 mi or 11 years" counts from new: from the car's in-service date and zero miles.
        months_from = car.in_service or base_day
        target_miles = item.first_miles
        target_day = add_months(months_from, item.first_months) if item.first_months else None
    else:
        target_miles = base_miles + item.interval_miles if item.interval_miles else None
        target_day = add_months(base_day, item.interval_months) if item.interval_months else None
    candidates = [d for d in (target_day, odometer.day_at(target_miles) if target_miles is not None else None) if d]
    if not candidates:
        return None
    due_day = max(min(candidates), base_day + timedelta(days=1))
    if target_miles is not None and due_day != target_day:
        due_miles: int | None = round(target_miles)
    else:
        estimate = odometer.miles_on(due_day)
        due_miles = None if estimate is None else round(estimate)
    return due_day, due_miles


def walk(item: Item, services: Iterable[Service], odometer: Odometer, car: Car, today: date,
         until: date) -> ItemStatus:
    """Every occurrence of one item, from the start to ``until`` — and always the next one to act on."""
    status = ItemStatus(item)
    services = list(services)
    matching = sorted((s for s in services if meets(s, item)), key=lambda s: (s.day, s.id))
    counting = item.counts_from if item.interval_miles or item.interval_months else None   # a one-off is from new
    if counting:
        start: tuple[date, float] | None = (counting, odometer.miles_on(counting) or 0.0)
    else:
        start = start_point(car, services, odometer)
    if start is None:
        return status
    base_day, base_miles = start
    first = counting is None
    today_miles = odometer.miles_on(today)
    for _ in range(_MAX_OCCURRENCES):
        due = _due(item, car, base_day, base_miles, first, odometer)
        if due is None:
            status.needs_reading = not status.occurrences and bool(item.interval_miles or item.first_miles)
            break
        due_day, due_miles = due
        following = _due(item, car, due_day, due_miles if due_miles is not None else base_miles, False, odometer)
        next_due_day = following[0] if following else None
        service = next((s for s in matching if s.day > base_day), None)

        if service and (next_due_day is None or service.day < next_due_day):
            stretch = ((next_due_day or due_day) - due_day).days or (due_day - base_day).days
            late = service.day > due_day + timedelta(days=stretch * LATE_TOLERANCE)
            status.occurrences.append(Occurrence("done", due_day, due_miles, service, late, base_day, base_miles))
            base_day = service.day
            base_miles = service.miles if service.miles is not None else (odometer.miles_on(service.day) or base_miles)
        elif next_due_day is not None and next_due_day <= today:
            before = car.acquired_on is not None and due_day < car.acquired_on
            status.occurrences.append(Occurrence("before" if before else "gap", due_day, due_miles,
                                                 from_day=base_day, from_miles=base_miles))
            base_day, base_miles = due_day, (due_miles if due_miles is not None else base_miles)
        else:
            if due_day <= today:
                state = "overdue"
            elif (due_day - today).days <= DUE_SOON_DAYS or (
                    due_miles is not None and today_miles is not None and due_miles - today_miles <= DUE_SOON_MILES):
                state = "due"
            else:
                state = "later"
            if due_day > until and status.current is not None:
                break   # far enough: the one to act on is already in hand
            status.occurrences.append(Occurrence(state, due_day, due_miles, from_day=base_day, from_miles=base_miles))
            if due_day > until:
                break
            base_day, base_miles = due_day, (due_miles if due_miles is not None else base_miles)
        first = False
        if next_due_day is None:
            break   # a one-off item, or one the odometer can't place again
    return status


def used(occurrence: Occurrence, today: date, today_miles: float | None) -> float | None:
    """How much of the interval up to an occurrence has gone by, 0 to 1: by days, and by miles where both ends and
    today's are known, whichever is further along (as "whichever comes first" falls due). None when it can't be
    told."""
    if occurrence.from_day is None:
        return None
    shares = []
    days = (occurrence.due_day - occurrence.from_day).days
    if days > 0:
        shares.append((today - occurrence.from_day).days / days)
    if None not in (occurrence.due_miles, occurrence.from_miles, today_miles):
        miles = occurrence.due_miles - occurrence.from_miles
        if miles > 0:
            shares.append((today_miles - occurrence.from_miles) / miles)
    if not shares:
        return None
    return max(0.0, min(1.0, max(shares)))


def assess(items: Iterable[Item], services: Iterable[Service], odometer: Odometer, car: Car, today: date,
           until: date | None = None) -> list[ItemStatus]:
    """Every item that applies to the car (normal or severe service), walked."""
    services = list(services)
    until = until or today + timedelta(days=730)
    return [walk(item, services, odometer, car, today, until) for item in items if in_effect(item, car.severe)]
