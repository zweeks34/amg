"""Fuel economy and running cost, from a car's fill-ups (or charges).

Economy is measured from one full fill to the next: the miles between them
÷ everything put in after the first, the second included. Partial fills in
between add to what went in. A partial before the first full fill is left
out — it fuelled miles nobody measured — and a fill marked "I didn't log the
one before" breaks the count, since fuel went in that nobody wrote down: no
stretch crosses it, and a full one starts the count again.

Every average here is miles over quantity, summed — never an average of
averages — so a short tank weighs less than a long one. Gallons and kWh are
handled alike; nothing here knows which it is.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

UNUSUAL = 0.40          # a stretch further than this from the median is flagged
MIN_FOR_UNUSUAL = 3     # with fewer stretches there's no median worth the name


@dataclass(frozen=True)
class Fill:
    id: int
    day: date
    odometer: int
    quantity: float               # US gallons or kWh
    cost_cents: int | None
    full: bool = True
    missed_before: bool = False
    place: str | None = None      # home or public, for charges


@dataclass(frozen=True)
class Stretch:
    """From one full fill to the next: the miles, and what went in to cover them."""
    start: Fill
    end: Fill
    miles: int
    quantity: float
    cost_cents: int | None        # None when a fill in it has no cost

    @property
    def economy(self) -> float:
        return self.miles / self.quantity


def _order(fills: Iterable[Fill]) -> list[Fill]:
    return sorted(fills, key=lambda f: (f.day, f.odometer, f.id))


def stretches(fills: Iterable[Fill]) -> list[Stretch]:
    """Every measured stretch, oldest first."""
    found: list[Stretch] = []
    anchor: Fill | None = None
    quantity, cost = 0.0, 0
    for fill in _order(fills):
        if fill.missed_before:
            anchor = None
        if anchor is None:
            if fill.full:
                anchor, quantity, cost = fill, 0.0, 0
            continue
        quantity += fill.quantity
        cost = None if cost is None or fill.cost_cents is None else cost + fill.cost_cents
        if fill.full:
            if fill.odometer > anchor.odometer:     # a top-off at no new miles measures nothing
                found.append(Stretch(anchor, fill, fill.odometer - anchor.odometer, quantity, cost))
            anchor, quantity, cost = fill, 0.0, 0
    return found


def _since(found: Iterable[Stretch], since: date | None) -> list[Stretch]:
    return [s for s in found if since is None or s.end.day >= since]


def economy(found: Iterable[Stretch], since: date | None = None) -> float | None:
    """Miles per gallon (or kWh) over the stretches that ended on or after ``since``."""
    chosen = _since(found, since)
    quantity = sum(s.quantity for s in chosen)
    return sum(s.miles for s in chosen) / quantity if quantity else None


def cost_per_mile(found: Iterable[Stretch], since: date | None = None) -> float | None:
    """Cents a mile, over the stretches whose every fill has a cost; one with a cost missing is left out."""
    chosen = [s for s in _since(found, since) if s.cost_cents is not None]
    miles = sum(s.miles for s in chosen)
    return sum(s.cost_cents for s in chosen) / miles if miles else None  # type: ignore[misc]


def spent(fills: Iterable[Fill], since: date | None = None) -> int:
    """Cents paid for every fill on or after ``since``, partial ones included."""
    return sum(f.cost_cents or 0 for f in fills if since is None or f.day >= since)


def unit_price(fills: Iterable[Fill], since: date | None = None) -> float | None:
    """The average paid per gallon (or kWh), in cents, over the fills with a cost."""
    priced = [f for f in fills if f.cost_cents is not None and (since is None or f.day >= since)]
    quantity = sum(f.quantity for f in priced)
    return sum(f.cost_cents for f in priced) / quantity if quantity else None  # type: ignore[misc]


def unusual(found: Iterable[Stretch]) -> set[int]:
    """The ids of the fills ending a stretch far from the usual: often a fill that wasn't logged, or a typo."""
    found = list(found)
    if len(found) < MIN_FOR_UNUSUAL:
        return set()
    median = statistics.median(s.economy for s in found)
    return {s.end.id for s in found if abs(s.economy - median) > UNUSUAL * median}


def home_rate(fills: Iterable[Fill]) -> float | None:
    """Cents a kWh at home: what the last home charge with a cost came to."""
    home = [f for f in _order(fills) if f.place == "home" and f.cost_cents is not None]
    return home[-1].cost_cents / home[-1].quantity if home else None  # type: ignore[operator]
