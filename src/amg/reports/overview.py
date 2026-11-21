"""The Overview report: what the cars cost to run — fuel, service and repairs, and fees — over the dates asked for.

The arithmetic is engine/running_cost.py's, gathered as the car page's
Running cost block gathers it (web/running_cost.py), so with no dates the
two agree. Dates narrow each car's span: from when you got it, or From if
later, to today (a sold car, its last reading), or To if earlier.

Each car gets a card; the garage gets their sum, year by year and month by
month. A month spreads each tank over the days it covered (engine.months), and
a month whose logged tanks cover less than half its miles is a gap: its fuel is
mostly estimated, so it's marked and left out of the average month. So is a
month the dates only partly cover, the current one say. The next 12 months are
the budget's, for a car still on the road, when no To date is asked for.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..engine import running_cost as engine
from ..engine.running_cost import MIN_MILES, Period
from ..web import budget, fuel_status
from ..web import running_cost as words
from ..web.fuel_status import Units, cents_a_mile
from ..web.status import odometer_for
from ..web.templating import dollars
from .filters import Filters

SHOWN_MONTHS = 24           # the month bars and the table's open rows; the rest under "Show all"
DAYS_A_MONTH = 365.25 / 12
PARTS = (("fuel", "Fuel"), ("service", "Service and repairs"), ("fees", "Fees"))


@dataclass
class CarCost:
    car: dict
    units: Units
    reason: str = ""                                    # why there's no figure, when there isn't
    since: str = ""
    start: date | None = None
    end: date | None = None
    years: list[Period] = field(default_factory=list)   # oldest first
    months: list[Period] = field(default_factory=list)
    whole: Period | None = None
    ahead: dict | None = None                           # the budget's next 12 months, in words

    @property
    def a_mile(self) -> float | None:
        """Cents a mile; None with too few miles, or with nothing recorded, which isn't the same as free."""
        return self.whole.cents_a_mile if self.whole and self.whole.total > 0 else None

    @property
    def fuel_counted(self) -> bool:
        return self.whole is not None and self.whole.fuel is not None


@dataclass
class Overview:
    cars: list[CarCost]                 # cheapest a mile first, then those with no figure
    years: list[dict]                   # the garage's, newest first: {"label", "note", "period"}
    months: list[dict]                  # newest first: {"label", "period", "gap", "partial", "change"}
    whole: Period | None
    average_month: float | None         # cents, over the months with records
    unfuelled: list[str]                # cars whose fuel isn't counted
    estimated: bool                     # some fuel is at a cost a mile, not measured

    @property
    def a_month(self) -> float | None:
        """The whole span's cost a month, by days."""
        if not self.whole:
            return None
        return self.whole.total / (((self.whole.end - self.whole.start).days + 1) / DAYS_A_MONTH)

    @property
    def gaps(self) -> int:
        return sum(1 for m in self.months if m["gap"])


def load(conn: sqlite3.Connection, cars: list[dict], filters: Filters, today: date | None = None) -> Overview:
    today = today or date.today()
    found = [c for c in (car_cost(conn, car, filters, today) for car in cars) if c is not None]
    # Cheapest a mile first; a car whose fuel isn't counted only looks cheap, so it follows those whose is.
    found.sort(key=lambda c: (c.a_mile is None, not c.fuel_counted, c.a_mile or 0.0, c.car["name"].lower()))
    counted = [c for c in found if c.whole is not None]
    overview = Overview(
        cars=found,
        years=_years(counted, today),
        months=_months(counted, today),
        whole=_add([c.whole for c in counted if c.whole]),
        average_month=None,
        unfuelled=[c.car["name"] for c in counted if not c.fuel_counted],
        estimated=any(c.whole.estimated for c in counted if c.whole),
    )
    _average(overview)
    return overview


def car_cost(conn: sqlite3.Connection, car: dict, filters: Filters, today: date) -> CarCost | None:
    """One car over the dates asked for; None when it wasn't yours in them."""
    odometer = odometer_for(conn, car)
    fuel = fuel_status.load(conn, car, today)
    found = CarCost(car, fuel.units)
    begun = words.start_of(car, odometer)
    if not odometer or begun is None:
        found.reason = words.NO_ODOMETER
        return found
    first, found.since = begun
    last = words.end_of(car, odometer, today)
    if filters.start:
        first = max(first, date.fromisoformat(filters.start))
    if filters.end:
        last = min(last, date.fromisoformat(filters.end))
    if last < first:
        return None
    rate, _ = fuel_status.cost_a_mile(fuel)
    spends = words.spends(conn, car, first, last)
    found.start, found.end = first, last
    found.years = engine.years(first, last, odometer, spends, fuel.stretches, rate)
    found.months = engine.months(first, last, odometer, spends, fuel.stretches, rate)
    found.whole = engine.whole(found.years)
    if found.whole is not None and found.whole.miles < MIN_MILES:
        found.reason = f"Too few miles to say a mile: {round(found.whole.miles):,} mi in these dates."
    if not filters.end and not car["archived_at"]:
        plan = budget.load(conn, car, 12, today=today)
        coming = engine.ahead(plan.months, plan.rate)
        if coming is not None and coming.period.total > 0:   # nothing priced and no fuel: nothing to say
            found.ahead = words.ahead_words(plan)
    return found


# ---------- The garage ----------


def _add(periods: list[Period]) -> Period | None:
    """Periods side by side (cars over the same span) added up; fuel where it's counted, None where it never is."""
    if not periods:
        return None
    fuels = [p.fuel for p in periods if p.fuel is not None]
    return Period(min(p.start for p in periods), max(p.end for p in periods), sum(p.miles for p in periods),
                  sum(fuels) if fuels else None,
                  sum(p.estimated_miles for p in periods if p.fuel is not None),
                  sum(p.service for p in periods), sum(p.fees for p in periods))


def _years(cars: list[CarCost], today: date) -> list[dict]:
    """The garage a year, newest first; "2026 so far", and a first or last year the dates cut short noted."""
    by_year: dict[int, list[Period]] = {}
    for car in cars:
        for period in car.years:
            by_year.setdefault(period.start.year, []).append(period)
    rows = []
    for year in sorted(by_year, reverse=True):
        period = _add(by_year[year])
        assert period is not None
        current = period.end == today
        notes = []
        if period.start != date(year, 1, 1):
            notes.append(f"from {period.start:%b} {period.start.day}")
        if not current and period.end != date(year, 12, 31):
            notes.append(f"to {period.end:%b} {period.end.day}")
        rows.append({"label": f"{year} so far" if current else str(year), "note": ", ".join(notes),
                     "period": period})
    return rows


def _months(cars: list[CarCost], today: date) -> list[dict]:
    """The garage a month, newest first, each saying whether it's a gap (fuel mostly estimated) or partial."""
    by_month: dict[tuple[int, int], list[tuple[Period, bool]]] = {}
    for car in cars:
        for period in car.months:
            by_month.setdefault((period.start.year, period.start.month), []).append((period, car.fuel_counted))
    rows = []
    for key in sorted(by_month, reverse=True):
        entries = by_month[key]
        period = _add([p for p, _ in entries])
        assert period is not None
        fuelled = [p for p, counted in entries if counted]
        miles = sum(p.miles for p in fuelled)
        gap = miles >= 1 and sum(p.estimated_miles for p in fuelled) > miles / 2
        partial = any(p.start.day != 1 or p.end != _month_end(p.start) for p, _ in entries)
        label = f"{period.start:%b %Y}"
        if period.end == today and partial:
            label += " so far"
        rows.append({"label": label, "key": f"{key[0]}-{key[1]:02d}", "period": period, "gap": gap,
                     "partial": partial, "change": None})
    return rows


def _month_end(day: date) -> date:
    return date(day.year + day.month // 12, day.month % 12 + 1, 1) - timedelta(days=1)


def _average(overview: Overview) -> None:
    """The average month over the whole months with records, and each such month's change against it."""
    usual = [m for m in overview.months if not m["gap"] and not m["partial"]]
    if len(usual) < 2:
        return
    average = overview.average_month = sum(m["period"].total for m in usual) / len(usual)
    if average > 0:
        for m in usual:
            m["change"] = round((m["period"].total - average) / average * 100)


# ---------- For the page ----------


def split(period: Period) -> list[dict]:
    """A period's fuel, service and fees: each one's cents and share of the whole, 0–100."""
    values = {"fuel": period.fuel or 0.0, "service": float(period.service), "fees": float(period.fees)}
    whole = sum(max(0.0, v) for v in values.values())
    return [{"key": key, "label": label, "cents": values[key],
             "share": round(max(0.0, values[key]) / whole * 100, 1) if whole > 0 else 0.0}
            for key, label in PARTS if values[key] or key != "fees"]


def a_mile_words(period: Period | None, cents: float | None = None) -> str:
    """'12.4¢' a mile, or a dash where there are too few miles to say."""
    if period is None or period.total <= 0:
        return "—"
    return cents_a_mile(period.a_mile(period.total if cents is None else cents)) or "—"


def bars(rows: list[dict], per: str) -> dict | None:
    """Stacked bars, oldest first, for the budget's bar chart: fuel (hatched where it's mostly estimated),
    service and repairs, and fees, in ink and greys. ``rows`` are _years' or _months' rows, newest first."""
    rows = list(reversed(rows))
    top = max((r["period"].total for r in rows), default=0)
    if top <= 0 or len(rows) < 2:
        return None
    steps = (5_000, 10_000, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000, 2_500_000, 5_000_000)
    step = next((s for s in steps if top / s <= 4), steps[-1])
    scale = -(-top // step) * step
    dense = len(rows) > 12
    shown, totals = [], {label: 0.0 for _, label in PARTS}
    for r in rows:
        period, segs, below = r["period"], [], None
        for key, label in PARTS:
            cents = {"fuel": period.fuel or 0.0, "service": period.service, "fees": period.fees}[key]
            if cents <= 0:
                continue
            mostly = period.fuel is not None and period.estimated_miles > period.miles / 2
            tone = "est" if key == "fuel" and (r.get("gap") or (per == "year" and mostly)) else key
            segs.append({"type": label, "colour": tone, "cents": round(cents), "gap": below is not None,
                         "title": f"{r['label']} · {label}: {dollars(round(cents))}"
                                  + (", mostly estimated" if tone == "est" else "")})
            below = tone
            totals[label] += cents
        if per == "year":
            label = r["label"][:4]
        else:
            label = (str(period.start.year) if period.start.month == 1 else "") if dense else f"{period.start:%b}"
        shown.append({"h": round(max(0.0, period.total) / scale * 100, 2), "label": label, "year": per == "year",
                      "title": f"{r['label']}: {dollars(round(period.total))}", "segs": segs})
    present = [label for _, label in PARTS if totals[label] > 0]
    tones = {"Fuel": "fuel", "Service and repairs": "service", "Fees": "fees"}
    colours = [{"label": label, "colour": tones[label]} for label in present]
    if any(seg["colour"] == "est" for bar in shown for seg in bar["segs"]):
        colours.append({"label": "Fuel, mostly estimated", "colour": "est"})
    return {
        "bars": shown,
        "types": [{"label": label, "total": round(totals[label]), "colour": tones[label]} for label in present],
        "tones": {label: tones[label] for label in present},
        "colours": colours,
        "ticks": [{"y": round(i * step / scale * 100, 2), "label": dollars(i * step)}
                  for i in range(1, round(scale / step) + 1)],
        "line": None,
        "per_month": None,
        "dense": dense,
        "what": "What it cost to run",
        "per": per,
    }
