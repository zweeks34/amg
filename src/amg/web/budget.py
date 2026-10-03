"""What the budget pages say: what's coming, what it will cost, how much to put aside.

engine/forecast.py does the arithmetic; this loads a car's schedule, receipts,
quotes, price book and fuel log for it, and turns its answer into words —
"Median of 3 visits, $38–205", "~$118 a month" — and into the month bars.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from datetime import date

from ..engine import forecast
from ..engine.forecast import Job, Month, Price
from ..engine.schedule import in_effect
from ..repo import jobs as job_repo
from ..repo import prices
from . import fuel_status
from . import status as car_status
from .templating import dollars

HORIZONS = {12: "12 months", 24: "2 years", 36: "3 years"}
_STEPS = (2_500, 5_000, 10_000, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000)   # cents, for the bars' scale


def horizon(value) -> int:
    """The months a page looks ahead: 12, 24 or 36, else 12."""
    try:
        months = int(value)
    except (TypeError, ValueError):
        return 12
    return months if months in HORIZONS else 12


@dataclass
class CarBudget:
    car: dict
    count: int                       # months ahead
    today: date
    months: list[Month]
    jobs: dict[tuple[str, str], dict]   # each job in the car's schedule, in schedule order
    item_jobs: dict[int, tuple[str, str]]   # schedule item id → its job
    units: fuel_status.Units
    rate: float | None               # miles a day
    cents_a_mile: float | None
    fuel_span: str
    busy: list = field(default_factory=list)   # Claude's rows still being priced
    stalled: bool = False

    @property
    def maintenance(self) -> int:
        return sum(m.maintenance for m in self.months)

    @property
    def fuel(self) -> int | None:
        return None if self.months[0].fuel is None else sum(m.fuel or 0 for m in self.months)

    @property
    def due_now(self) -> int:
        """What overdue jobs cost: due now, so not something to save up for."""
        return sum(price.cents for due, price in self.months[0].items if due.status == "overdue" and price is not None)

    @property
    def overdue(self) -> int:
        return sum(1 for due, _ in self.months[0].items if due.status == "overdue")

    @property
    def per_month(self) -> int:
        """What's still to come, spread evenly: what to put aside each month."""
        return round((self.maintenance - self.due_now) / self.count)

    @property
    def unpriced(self) -> int:
        return sum(len(m.unpriced) for m in self.months)

    @property
    def to_ask(self) -> list[dict]:
        """Jobs Claude could price: no price from anywhere, not an inspection, and not being priced already."""
        busy = set() if self.stalled else {(r["codes"], r["action"]) for r in self.busy}
        return [j for j in self.jobs.values()
                if j["price"] is None and not j["job"].inspection and j["key"] not in busy]

    def item_costs(self) -> dict[int, int]:
        """Each schedule item's price, for next up."""
        return {item_id: price.cents for item_id, key in self.item_jobs.items()
                if (price := self.jobs[key]["price"]) is not None}


def _visits(conn: sqlite3.Connection) -> list[forecast.Visit]:
    return [forecast.visit_from(row) for row in prices.visits(conn)]


def load(conn: sqlite3.Connection, car, count: int = 12, today: date | None = None,
         visits: list[forecast.Visit] | None = None, state: car_status.CarStatus | None = None) -> CarBudget:
    """A car's budget ``count`` months ahead. ``visits`` (every car's) and ``state`` may be passed in to reuse."""
    today = today or date.today()
    spans = forecast.months(today, count)
    end = spans[-1][1]
    state = state or car_status.load(conn, car, today, until=end)
    visits = visits if visits is not None else _visits(conn)
    here = [v for v in visits if v.vehicle_id == car["id"]]
    elsewhere = [v for v in visits if v.vehicle_id != car["id"]]
    quotes = [forecast.quote_from(q) for q in prices.quotes(conn, car["id"])]
    book = prices.for_car(conn, car["id"])
    yours = {(r["codes"], r["action"]): r["low_cents"] for r in book if r["source"] == "you"}
    claude = {(r["codes"], r["action"]): r for r in book if r["source"] == "claude"}

    found: dict[tuple[str, str], dict] = {}
    item_jobs: dict[int, tuple[str, str]] = {}
    for item_id, row in state.items.items():
        if not row["codes"] or not in_effect(row, car["severe_service"]):
            continue
        job = Job(frozenset(row["codes"]), row["action"])
        item_jobs[item_id] = job.key
        if job.key in found:
            continue
        asked = claude.get(job.key)
        claude_range = (asked["low_cents"], asked["high_cents"]) if asked and asked["status"] == "done" else None
        price = forecast.estimate(job, today, yours=yours.get(job.key), visits=here, quotes=quotes,
                                  elsewhere=elsewhere, claude=claude_range)
        found[job.key] = {"key": job.key, "codes": job.key[0], "action": job.action, "job": job, "name": row["name"],
                          "price": price, "yours": yours.get(job.key), "claude": asked}

    fuel = fuel_status.load(conn, car, today)
    cents_a_mile, span = fuel_status.cost_a_mile(fuel)
    rate = state.odometer.rate()
    months = forecast.budget(forecast.upcoming(state.statuses, today, end), {k: j["price"] for k, j in found.items()},
                             today, count, rate, cents_a_mile)
    busy = [r for r in claude.values() if r["status"] in ("queued", "asking")]
    stalled = any((job := job_repo.get(conn, job_id)) is None or job_repo.is_stalled(job)
                  for job_id in {r["job_id"] for r in busy})
    return CarBudget(dict(car), count, today, months, found, item_jobs, fuel.units, rate, cents_a_mile, span, busy,
                     stalled)


def garage(conn: sqlite3.Connection, cars: list, count: int = 12, today: date | None = None) -> list[CarBudget]:
    """Every car's budget, reading the receipts once."""
    visits = _visits(conn)
    return [load(conn, car, count, today, visits) for car in cars]


# ---------- Words ----------


def span_words(low: int, high: int) -> str:
    """$38–205: a range of whole dollars, the sign once."""
    return f"{dollars(low)}–{dollars(high)[1:]}"


def source_words(price: Price | None, job: Job, names: dict[int, str]) -> str:
    """Where a price came from, as the row under it says."""
    if price is None:
        return "Usually part of a visit" if job.inspection else "No price yet"
    if price.source == "yours":
        return "Your price"
    if price.source == "paid":
        if price.count == 1:
            return f"Paid {price.day:%b %Y}"
        return f"Median of {price.count} visits, {span_words(price.low, price.high)}"
    if price.source == "quoted":
        return f"Quoted {price.day:%b %Y}" if price.count == 1 else f"Median of {price.count} quotes"
    if price.source == "elsewhere":
        cars = sorted(names[v] for v in price.vehicles if v in names)
        return f"Paid on your {cars[0]}" if len(cars) == 1 else "Paid on your other cars"
    return f"Claude's estimate, {span_words(price.low, price.high)}"


def _day(day: date, today: date) -> str:
    return f"{day:%b} {day.day}" + (f", {day.year}" if day.year != today.year else "")


def when_words(due: forecast.Due, today: date) -> str:
    """'Dec 27 · 10,800 mi', or 'Overdue since Jul 20 · 6,000 mi'."""
    miles = f" · {due.miles:,} mi" if due.miles is not None else ""
    if due.status == "overdue":
        return f"Overdue since {_day(due.due_day, today)}{miles}"
    return f"{_day(due.due_day, today)}{miles}"


def fuel_note(plan: CarBudget) -> str | None:
    """Why fuel isn't in the budget, when it isn't."""
    if plan.fuel is not None:
        return None
    if plan.cents_a_mile is None:
        return f"Log {plan.units.fill}s with their cost to budget for {plan.units.title.lower()}."
    return "AMG needs two odometer readings a while apart to tell how far the car goes."


def fuel_words(plan: CarBudget) -> str:
    """How fuel is reckoned: '32 mi a day at 14.7¢ a mile', or why it can't be."""
    if plan.fuel is None:
        return fuel_note(plan) or ""
    return f"~{plan.rate:,.0f} mi a day at {fuel_status.cents_a_mile(plan.cents_a_mile)} a mile, {plan.fuel_span}"


def month_rows(plan: CarBudget, names: dict[int, str]) -> list[dict]:
    """The month list: each month's jobs at their prices, then fuel."""
    rows = []
    for index, month in enumerate(plan.months):
        rows.append({
            "label": f"{month.start:%B %Y}",
            "note": "from today" if index == 0 and month.start.day != 1 else "",
            "maintenance": month.maintenance,
            "fuel": month.fuel,
            "fuel_miles": None if month.fuel_miles is None else round(month.fuel_miles),
            "total": month.total,
            "jobs": [
                {
                    "name": due.name,
                    "status": due.status,
                    "when": when_words(due, plan.today),
                    "cost": None if price is None else price.cents,
                    "source": source_words(price, due.job, names),
                    "claude": price is not None and price.source == "claude",
                    "unpriced": price is None and not due.job.inspection,
                }
                for due, price in month.items
            ],
        })
    return rows


def price_rows(plan: CarBudget, names: dict[int, str]) -> list[dict]:
    """The price list: every job in the schedule, its price, where that came from, and what Claude said."""
    rows = []
    for job in plan.jobs.values():
        price, asked = job["price"], job["claude"]
        rows.append({
            "key": "|".join(job["key"]),
            "codes": job["codes"],
            "action": job["action"],
            "name": job["name"],
            "cost": None if price is None else price.cents,
            "source": source_words(price, job["job"], names),
            "claude": price is not None and price.source == "claude",
            "unpriced": price is None and not job["job"].inspection,
            "note": asked["note"] if asked and price is not None and price.source == "claude" else "",
            "yours": job["yours"],
            "asking": bool(asked and asked["status"] in ("queued", "asking") and not plan.stalled),
            "failed": asked["error"] if asked and asked["status"] == "failed" and price is None else "",
        })
    return rows


def chart(months: list[Month], per_month: int, count: int) -> dict | None:
    """The month bars: maintenance a month against what's put aside each month. Heights are 0–100."""
    values = [m.maintenance for m in months]
    top = max(values + [per_month])
    if top <= 0:
        return None
    step = next((s for s in _STEPS if top / s <= 4), _STEPS[-1])
    scale = math.ceil(top / step) * step

    def label(month: Month) -> str:
        """Each month over a year (just its initial on a phone); over longer, each year at its January."""
        if count == 12:
            return f"{month.start:%b}"
        return str(month.start.year) if month.start.month == 1 else ""

    return {
        "bars": [{"h": round(m.maintenance / scale * 100, 2), "label": label(m),
                  "title": f"{m.start:%B %Y}: {dollars(m.maintenance)}"} for m in months],
        "ticks": [{"y": round(i * step / scale * 100, 2), "label": dollars(i * step)}
                  for i in range(1, round(scale / step) + 1)],
        "line": round(per_month / scale * 100, 2),
        "per_month": per_month,
        "dense": count > 12,
    }


def fuel_word(units: list[fuel_status.Units]) -> str:
    """Fuel, Charging, or both, for a garage's cars."""
    titles = {u.title for u in units}
    return "Fuel and charging" if len(titles) > 1 else (titles.pop() if titles else "Fuel")


def strip(plans: list[CarBudget]) -> dict | None:
    """The garage's line: the next 12 months for every car together, or None when nothing's known."""
    if not plans:
        return None
    maintenance = sum(p.maintenance for p in plans)
    fuel = [p.fuel for p in plans if p.fuel is not None]
    if not maintenance and not fuel:
        return None
    return {
        "maintenance": maintenance,
        "fuel": sum(fuel) if fuel else None,
        "fuel_word": fuel_word([p.units for p in plans if p.fuel is not None]).lower(),
        "per_month": sum(p.per_month for p in plans),
        "due_now": sum(p.due_now for p in plans),
        "unpriced": sum(p.unpriced for p in plans),
    }


def combined(plans: list[CarBudget]) -> list[dict]:
    """Every car's months added together, month by month."""
    rows = []
    for index, month in enumerate(plans[0].months if plans else []):
        mine = [p.months[index] for p in plans]
        fuel = [m.fuel for m in mine if m.fuel is not None]
        rows.append({"label": f"{month.start:%B %Y}", "note": "from today" if index == 0 and month.start.day != 1 else "",
                     "maintenance": sum(m.maintenance for m in mine), "fuel": sum(fuel) if fuel else None,
                     "total": sum(m.total for m in mine)})
    return rows


def combined_months(plans: list[CarBudget]) -> list[Month]:
    """Every car's months as one, for the bars."""
    found = []
    for index, month in enumerate(plans[0].months if plans else []):
        whole = Month(month.start, month.end)
        for plan in plans:
            whole.items.extend(plan.months[index].items)
        found.append(whole)
    return found
