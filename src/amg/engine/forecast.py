"""The forecast: what's coming, when, and what it will cost.

**When** is the gap engine's: every occurrence still to come, dated by the
odometer projection, whichever of its miles and months comes first. One
already overdue is due now.

**What it costs** is the first of these that knows:

1. your price for the job;
2. what visits that did it on this car cost — the median, in today's money;
3. what shops quoted for it on this car's receipts;
4. what it cost on your other cars;
5. Claude's estimate, a range, counted at its midpoint.

A *job* is what a schedule item asks for: its service types and its action.
What one visit charged for a job is its share of the lines that did the work
— a line that did several things split evenly between them — plus the same
share of the visit's tax, shop fees and discounts. A visit counts only if it
did all of the job: buying a filter isn't the price of an oil change. A visit
whose share comes to nothing (warranty work, a $0 line) isn't a price at all,
so it can't drag an estimate towards zero.

Older prices are brought up to today's at INFLATION a year. Fuel is miles a
day times the cost a mile, month by month. Inspection and registration fees
come in priced (web/budget.py), each in the month it falls due.

Pure: no database, no I/O.
"""

from __future__ import annotations

import statistics
from calendar import monthrange
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta

from .schedule import ItemStatus

# About what US car maintenance and repair prices rose a year, 2016–2025 (BLS CPI).
INFLATION = 0.04
_YEAR = 365.25
_DOING = frozenset({"replace", "perform"})
_COMING = ("overdue", "due", "later")


@dataclass(frozen=True)
class Line:
    amount_cents: int | None
    kind: str = "other"
    covers: Mapping[str, str] = field(default_factory=dict)   # service type code → action


@dataclass(frozen=True)
class Visit:
    id: int
    vehicle_id: int
    day: date
    lines: tuple[Line, ...]
    tax_cents: int | None = None


@dataclass(frozen=True)
class Quote:
    day: date
    codes: frozenset[str]
    cents: int


@dataclass(frozen=True)
class Job:
    codes: frozenset[str]
    action: str

    @property
    def key(self) -> tuple[str, str]:
        return ",".join(sorted(self.codes)), self.action

    @property
    def inspection(self) -> bool:
        return self.action == "inspect"


@dataclass(frozen=True)
class Price:
    cents: int                  # what the budget counts
    low: int
    high: int
    source: str                 # yours, paid, quoted, elsewhere, claude
    count: int = 1              # how many prices it's the median of
    day: date | None = None     # the most recent of them
    vehicles: frozenset[int] = frozenset()   # elsewhere: the cars it was paid on


def visit_from(row: Mapping) -> Visit:
    """A visit as repo/prices.visits reads it: {id, vehicle_id, performed_on, tax_cents, lines}."""
    lines = tuple(Line(line["amount_cents"], line["kind"], dict(line["covers"])) for line in row["lines"])
    return Visit(row["id"], row["vehicle_id"], date.fromisoformat(row["performed_on"]), lines, row["tax_cents"])


def quote_from(row: Mapping) -> Quote:
    """A quote as repo/prices.quotes reads it: {day, codes, cents}."""
    return Quote(date.fromisoformat(row["day"]), frozenset(row["codes"]), row["cents"])


# ---------- What one visit charged ----------


def _overhead(line: Line) -> bool:
    """Tax-like: a shop fee or a discount that did no work of its own, shared across the visit."""
    return not line.covers and (line.kind == "fee" or (line.amount_cents or 0) < 0)


def paid(visit: Visit, job: Job) -> int | None:
    """What one visit charged for a job, or None when it didn't do it, or did it for nothing."""
    share, did = 0.0, set()
    for line in visit.lines:
        amount = line.amount_cents or 0
        doing = {code for code, action in line.covers.items() if action in _DOING}
        if job.inspection:
            if doing:
                continue   # a look taken while replacing something costs nothing extra
            mine = job.codes & set(line.covers)
            if mine:
                share += amount * len(mine) / len(line.covers)
                did |= mine
        else:
            mine = job.codes & doing
            if mine:
                share += amount * len(mine) / len(doing)
                did |= mine
    if not did or (not job.inspection and did != job.codes) or share <= 0:
        return None
    base = sum(line.amount_cents or 0 for line in visit.lines if not _overhead(line) and (line.amount_cents or 0) > 0)
    overhead = (visit.tax_cents or 0) + sum(line.amount_cents or 0 for line in visit.lines if _overhead(line))
    total = share + (overhead * share / base if base > 0 else 0)
    return round(total) if total > 0 else None


def quoted(quote: Quote, job: Job) -> int | None:
    """A shop's quote for work that included the whole job, split across what it quoted for."""
    if job.inspection or not job.codes <= quote.codes or quote.cents <= 0:
        return None
    return round(quote.cents * len(job.codes) / len(quote.codes))


def today_money(cents: int, day: date, today: date, rate: float = INFLATION) -> int:
    years = max(0, (today - day).days) / _YEAR
    return round(cents * (1 + rate) ** years)


# ---------- The estimate ----------


def _median(found: Sequence[tuple[date, int, int | None]], source: str, today: date) -> Price | None:
    """(day, cents, vehicle id or None) prices → their median in today's money."""
    if not found:
        return None
    values = [today_money(cents, day, today) for day, cents, _ in found]
    return Price(round(statistics.median(values)), min(values), max(values), source, len(values),
                 max(day for day, _, _ in found), frozenset(v for _, _, v in found if v is not None))


def estimate(job: Job, today: date, *, yours: int | None = None, visits: Iterable[Visit] = (),
             quotes: Iterable[Quote] = (), elsewhere: Iterable[Visit] = (),
             claude: tuple[int, int] | None = None) -> Price | None:
    """The job's price from the first source that knows it; None when none does."""
    if yours is not None:
        return Price(yours, yours, yours, "yours")
    here = [(v.day, cents, v.vehicle_id) for v in visits if (cents := paid(v, job)) is not None]
    if found := _median(here, "paid", today):
        return found
    asked = [(q.day, cents, None) for q in quotes if (cents := quoted(q, job)) is not None]
    if found := _median(asked, "quoted", today):
        return found
    there = [(v.day, cents, v.vehicle_id) for v in elsewhere if (cents := paid(v, job)) is not None]
    if found := _median(there, "elsewhere", today):
        return found
    if claude is not None:
        low, high = claude
        return Price(round((low + high) / 2), low, high, "claude")
    return None


# ---------- When ----------


@dataclass(frozen=True)
class Due:
    item_id: int
    name: str
    job: Job
    status: str             # overdue, due, later
    day: date               # when it lands in the budget: its due day, or today if that's passed
    due_day: date
    miles: int | None


@dataclass(frozen=True)
class Fee:
    """An inspection or registration to pay for: engine/renewals.py says when."""
    kind: str               # safety, emissions, registration
    name: str
    status: str             # overdue (expired), due, later
    day: date               # when it lands in the budget: its expiry, or today if that's passed
    due_day: date           # the expiry


def upcoming(statuses: Iterable[ItemStatus], today: date, end: date) -> list[Due]:
    """Every occurrence still to come by ``end``, soonest first; an overdue one is due today."""
    found = [
        Due(s.item.id, s.item.name, Job(frozenset(s.item.codes), s.item.action), o.status, max(o.due_day, today),
            o.due_day, o.due_miles)
        for s in statuses for o in s.occurrences
        if o.status in _COMING and max(o.due_day, today) <= end
    ]
    return sorted(found, key=lambda d: (d.day, d.name, d.item_id))


def months(today: date, count: int) -> list[tuple[date, date]]:
    """The horizon as calendar months, (first day, last day): the rest of this month, then whole ones."""
    found, start = [], today
    for _ in range(count):
        last = start.replace(day=monthrange(start.year, start.month)[1])
        found.append((start, last))
        start = last + timedelta(days=1)
    return found


def fuel_miles(rate: float, start: date, end: date) -> float:
    return rate * ((end - start).days + 1)


def fuel_cents(rate: float, cents_a_mile: float, start: date, end: date) -> int:
    """Fuel for the days from ``start`` to ``end``, both included."""
    return round(fuel_miles(rate, start, end) * cents_a_mile)


# ---------- The budget ----------


@dataclass
class Month:
    start: date
    end: date
    items: list[tuple[Due | Fee, Price | None]] = field(default_factory=list)   # jobs and fees, by day
    fuel_miles: float | None = None
    fuel: int | None = None

    @property
    def maintenance(self) -> int:
        """Jobs and fees together."""
        return sum(price.cents for _, price in self.items if price is not None)

    @property
    def fees(self) -> int:
        return sum(price.cents for due, price in self.items if isinstance(due, Fee) and price is not None)

    @property
    def total(self) -> int:
        return self.maintenance + (self.fuel or 0)

    @property
    def unpriced(self) -> list[Due]:
        """Jobs with no price that aren't inspections (those are usually part of a visit). Fees aren't jobs."""
        return [due for due, price in self.items
                if price is None and isinstance(due, Due) and not due.job.inspection]


def budget(dues: Iterable[Due], prices: Mapping[tuple[str, str], Price | None], today: date, count: int,
           rate: float | None = None, cents_a_mile: float | None = None,
           fees: Iterable[tuple[Fee, Price | None]] = ()) -> list[Month]:
    """Month by month: what falls due, at its price, the fees, and fuel where the pace and cost a mile are known."""
    found = [Month(start, end) for start, end in months(today, count)]
    for item in [(due, prices.get(due.job.key)) for due in dues] + list(fees):
        month = next((m for m in found if m.start <= item[0].day <= m.end), None)
        if month is not None:
            month.items.append(item)
    for month in found:
        month.items.sort(key=lambda item: item[0].day)   # stable: jobs keep their order within a day
    if rate is not None and cents_a_mile is not None:
        for month in found:
            month.fuel_miles = fuel_miles(rate, month.start, month.end)
            month.fuel = fuel_cents(rate, cents_a_mile, month.start, month.end)
    return found
