"""What a car costs to run, a mile: fuel, service and repairs, and fees, over the miles it went.

Looking back, a row a calendar year, the first from the day you got it and
the last to today (for a car you've archived, its last reading). A year's
miles are the odometer model's, from its first day to the next year's. Its
fuel is what logged fill-ups measured, full tank to full tank, at what they
cost, counted in the year each stretch ended as the Fuel report counts them;
every other mile is at the car's cost a mile, and said to be estimated. With
no cost a mile to go on, fuel isn't counted at all. Service and fees are what
was paid, on the day. The whole span is the years added up, so the table
adds up to the headline.

Looking ahead, the budget's months: its fuel, and the jobs and fees it
prices, over the miles the car goes at its recent pace. What's overdue now is
left out, as the budget's put-aside figure leaves it out: it's owed for miles
already driven, not the ones to come.

A figure a mile needs MIN_MILES behind it: under that, one oil change swamps
it. Pure: no database, no I/O.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from .forecast import Due, Month
from .fuel import Stretch
from .odometer import Odometer

MIN_MILES = 500


@dataclass(frozen=True)
class Spend:
    day: date
    part: str                     # service or fees
    cents: int


@dataclass(frozen=True)
class Period:
    start: date
    end: date                     # the last day counted
    miles: float
    fuel: float | None            # cents; None with no cost a mile to go on
    estimated_miles: float = 0.0  # those of its miles whose fuel is at the cost a mile, not measured
    service: int = 0
    fees: int = 0

    @property
    def total(self) -> float:
        return (self.fuel or 0.0) + self.service + self.fees

    @property
    def estimated(self) -> bool:
        return self.fuel is not None and self.estimated_miles >= 0.5

    def a_mile(self, cents: float | None) -> float | None:
        """``cents`` a mile over its miles; None under MIN_MILES, where it would mean nothing."""
        return None if cents is None or self.miles < MIN_MILES else cents / self.miles

    @property
    def cents_a_mile(self) -> float | None:
        return self.a_mile(self.total)


def years(start: date, end: date, odometer: Odometer, spends: Iterable[Spend], stretches: Iterable[Stretch],
          rate: float | None) -> list[Period]:
    """A period a calendar year from ``start`` to ``end``, both included, oldest first.

    ``rate`` is the car's cost a mile for fuel, in cents: what the miles no
    stretch with a cost measured are counted at.
    """
    if end < start:
        return []
    spends = list(spends)
    measured = [s for s in stretches if s.cost_cents is not None]
    firsts = [start] + [date(year, 1, 1) for year in range(start.year + 1, end.year + 1)]
    found = []
    for index, first in enumerate(firsts):
        following = firsts[index + 1] if index + 1 < len(firsts) else None
        last = following - timedelta(days=1) if following else end
        miles = _miles(odometer, first, following or end)
        ended = [s for s in measured if first <= s.end.day <= last]
        estimated = max(0.0, miles - sum(s.miles for s in ended)) if rate is not None else 0.0
        fuel = None if rate is None else sum(s.cost_cents for s in ended) + estimated * rate  # type: ignore[misc]
        paid = [s for s in spends if first <= s.day <= last]
        found.append(Period(first, last, miles, fuel, estimated,
                            sum(s.cents for s in paid if s.part == "service"),
                            sum(s.cents for s in paid if s.part == "fees")))
    return found


def months(start: date, end: date, odometer: Odometer, spends: Iterable[Spend], stretches: Iterable[Stretch],
           rate: float | None) -> list[Period]:
    """A period a calendar month from ``start`` to ``end``, both included, oldest first.

    Unlike ``years``, a tank isn't counted in the month it ended: its miles and
    cost are spread over the days it covered (the day after one full fill to
    the day of the next), so a fill-up on March 2 pays mostly for February.
    Over a month, one tank lands in the wrong place; over a year, hardly at
    all, which is why ``years`` keeps the simpler rule. ``estimated_miles`` is
    the miles no tank covered, whether or not there's a ``rate`` to count them at.
    """
    if end < start:
        return []
    spends = list(spends)
    measured = [s for s in stretches if s.cost_cents is not None]
    firsts = [start]
    while (nxt := _next_month(firsts[-1])) <= end:
        firsts.append(nxt)
    found = []
    for index, first in enumerate(firsts):
        following = firsts[index + 1] if index + 1 < len(firsts) else None
        last = following - timedelta(days=1) if following else end
        miles = _miles(odometer, first, following or end)
        covered = cost = 0.0
        for stretch in measured:
            share = _share(stretch.start.day, stretch.end.day, first, last)
            covered += share * stretch.miles
            cost += share * stretch.cost_cents  # type: ignore[operator]
        uncovered = max(0.0, miles - covered)
        fuel = None if rate is None else cost + uncovered * rate
        paid = [s for s in spends if first <= s.day <= last]
        found.append(Period(first, last, miles, fuel, uncovered,
                            sum(s.cents for s in paid if s.part == "service"),
                            sum(s.cents for s in paid if s.part == "fees")))
    return found


def _next_month(day: date) -> date:
    return date(day.year + day.month // 12, day.month % 12 + 1, 1)


def _share(began: date, ended: date, first: date, last: date) -> float:
    """How much of a tank that ran from ``began`` (its fill, not counted) to ``ended`` falls from ``first`` to
    ``last``, by days. A tank filled twice on one day falls on that day."""
    span = (ended - began).days
    if span <= 0:
        return 1.0 if first <= ended <= last else 0.0
    inside = (min(ended, last) - max(began, first - timedelta(days=1))).days
    return max(0, inside) / span


def whole(periods: list[Period]) -> Period | None:
    """The periods added up."""
    if not periods:
        return None
    fuels = [p.fuel for p in periods]
    return Period(periods[0].start, periods[-1].end, sum(p.miles for p in periods),
                  None if any(f is None for f in fuels) else sum(fuels),  # type: ignore[arg-type]
                  sum(p.estimated_miles for p in periods), sum(p.service for p in periods),
                  sum(p.fees for p in periods))


@dataclass(frozen=True)
class Ahead:
    period: Period
    due_now: int                  # cents overdue or expired now, left out
    unpriced: int                 # jobs with no price, so not in it


def ahead(months: list[Month], rate: float | None) -> Ahead | None:
    """The budget's months as a period; None when the car's pace isn't known."""
    if not months or not rate or rate <= 0:
        return None
    start, end = months[0].start, months[-1].end
    service = fees = due_now = 0
    for month in months:
        for due, price in month.items:
            if price is None:
                continue
            if due.status == "overdue":
                due_now += price.cents
            elif isinstance(due, Due):
                service += price.cents
            else:
                fees += price.cents
    fuels = [m.fuel for m in months]
    fuel = None if any(f is None for f in fuels) else float(sum(fuels))  # type: ignore[arg-type]
    period = Period(start, end, rate * ((end - start).days + 1), fuel, 0.0, service, fees)
    return Ahead(period, due_now, sum(len(m.unpriced) for m in months))


def _miles(odometer: Odometer, first: date, after: date) -> float:
    """The miles from one day to another, never fewer than none."""
    start, end = odometer.miles_on(first), odometer.miles_on(after)
    return 0.0 if start is None or end is None else max(0.0, end - start)
