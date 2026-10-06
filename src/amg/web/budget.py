"""What the budget pages say: what's coming, what it will cost, how much to put aside.

engine/forecast.py does the arithmetic; this loads a car's schedule, receipts,
quotes, price book and fuel log for it, and turns its answer into words —
"Median of 3 visits, $38–205", "~$118 a month" — and into the month bars.

Inspection and registration fees count with maintenance: each one the car has
a date for, in the month it expires (due now once it has), at what you paid
last time — the cost on its newest record that has one, else for an
inspection the receipt line for it. The state sets these, so no inflation and
no Claude. Once a kind has a date, a schedule item for the same inspection
drops out of the budget, so it isn't counted twice.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass, field
from datetime import date

from ..engine import forecast
from ..engine import renewals as renewal_engine
from ..engine.forecast import Due, Fee, Job, Month, Price
from ..engine.renewals import KINDS, Kind
from ..engine.schedule import in_effect
from ..repo import jobs as job_repo
from ..repo import prices
from ..repo import renewals as renewal_repo
from . import fuel_status
from . import renewals as renewal_words
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
    fees: dict[str, dict] = field(default_factory=dict)   # each kind it has a date for: kind, price, record_id
    categories: dict[int, tuple[int, str]] = field(default_factory=dict)   # item id → (catalogue order, category)

    @property
    def maintenance(self) -> int:
        """Jobs and fees together."""
        return sum(m.maintenance for m in self.months)

    @property
    def fee_total(self) -> int:
        return sum(m.fees for m in self.months)

    @property
    def what(self) -> str:
        """What the maintenance figure is, in a sentence."""
        return "maintenance and fees" if self.fee_total else "maintenance"

    @property
    def fuel(self) -> int | None:
        return None if self.months[0].fuel is None else sum(m.fuel or 0 for m in self.months)

    @property
    def due_now(self) -> int:
        """What overdue jobs and expired fees cost: due now, so not something to save up for."""
        return sum(price.cents for due, price in self.months[0].items if due.status == "overdue" and price is not None)

    @property
    def overdue(self) -> int:
        """Overdue jobs."""
        return sum(1 for due, _ in self.months[0].items if isinstance(due, Due) and due.status == "overdue")

    @property
    def expired(self) -> list[str]:
        """The inspections and registration past their date."""
        return [due.name for due, _ in self.months[0].items if isinstance(due, Fee) and due.status == "overdue"]

    @property
    def due_now_note(self) -> str:
        return due_now_note(self.overdue, self.expired)

    @property
    def fees_unpriced(self) -> list[dict]:
        """The kinds falling due in the horizon with no cost to go on."""
        found = {due.kind for m in self.months for due, price in m.items if isinstance(due, Fee) and price is None}
        return [fee for code, fee in self.fees.items() if code in found]

    def fee_cost(self, kind: str) -> int | None:
        fee = self.fees.get(kind)
        return fee["price"].cents if fee and fee["price"] is not None else None

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
    fees, paying = _fees(conn, car, today, end)
    dated = {KINDS[code].service_type for code in fees} - {None}   # inspections the fees budget for

    found: dict[tuple[str, str], dict] = {}
    item_jobs: dict[int, tuple[str, str]] = {}
    for item_id, row in state.items.items():
        if not row["codes"] or not in_effect(row, car["severe_service"]) or set(row["codes"]) <= dated:
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
    dues = [due for due in forecast.upcoming(state.statuses, today, end)
            if not (due.job.codes and due.job.codes <= dated)]
    months = forecast.budget(dues, {k: j["price"] for k, j in found.items()}, today, count, rate, cents_a_mile, paying)
    busy = [r for r in claude.values() if r["status"] in ("queued", "asking")]
    stalled = any((job := job_repo.get(conn, job_id)) is None or job_repo.is_stalled(job)
                  for job_id in {r["job_id"] for r in busy})
    categories = {item_id: (row["category_sort"], row["category"]) for item_id, row in state.items.items()}
    return CarBudget(dict(car), count, today, months, found, item_jobs, fuel.units, rate, cents_a_mile, span, busy,
                     stalled, fees, categories)


def _fees(conn: sqlite3.Connection, car, today: date, end: date) -> tuple[dict[str, dict], list[tuple[Fee, Price | None]]]:
    """Each kind the car has a date for, priced; and every time one falls due by ``end``."""
    kinds: dict[str, dict] = {}
    paying: list[tuple[Fee, Price | None]] = []
    for code, logged in renewal_repo.for_car(conn, car["id"]).items():
        kind = KINDS[code]
        price = fee_price(conn, car["id"], kind, logged)
        kinds[code] = {"kind": kind, "price": price, "record_id": logged[0]["id"]}
        records = [renewal_words.record(row) for row in logged]
        for day, expiry in renewal_engine.coming(kind, records, today, end):
            status = renewal_words.MARKS[renewal_engine.standing(expiry, today).state]
            paying.append((Fee(code, kind.name, status, day, expiry), price))
    return {code: kinds[code] for code in KINDS if code in kinds}, paying


def fee_price(conn: sqlite3.Connection, vehicle_id: int, kind: Kind, logged: list) -> Price | None:
    """What you paid last time: the newest record with a cost, else (an inspection) its newest receipt line."""
    for row in logged:
        if row["cost_cents"] is not None:
            day = date.fromisoformat(row["done_on"]) if row["done_on"] else None
            return Price(row["cost_cents"], row["cost_cents"], row["cost_cents"], "paid", day=day)
    service = renewal_repo.latest_service(conn, vehicle_id, kind.service_type) if kind.service_type else None
    if service and service["cost_cents"] is not None and service["cost_cents"] >= 0:
        cents = service["cost_cents"]
        return Price(cents, cents, cents, "paid", day=date.fromisoformat(service["performed_on"]))
    return None


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


def fee_when(fee: Fee, today: date) -> str:
    """'Expires Mar 31, 2027', or 'Expired Sep 30'."""
    return f"{'Expired' if fee.status == 'overdue' else 'Expires'} {_day(fee.due_day, today)}"


def fee_source(price: Price | None) -> str:
    if price is None:
        return "No cost yet"
    return f"Paid {price.day:%b %Y}" if price.day else "Paid last time"


def _and(words: list[str]) -> str:
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def due_now_note(overdue: int, expired: list[str]) -> str:
    """What's due now: '3 overdue jobs, registration expired'."""
    parts = [f"{overdue} overdue job{'s' if overdue != 1 else ''}"] if overdue else []
    if expired:
        parts.append(f"{_and([name.lower() for name in expired])} expired")
    return ", ".join(parts)


def fee_names(fees: list[dict]) -> str:
    """'The registration', 'The safety inspection and the registration'."""
    words = _and([f"the {fee['kind'].name.lower()}" for fee in fees])
    return words[:1].upper() + words[1:]


def only_budgeted(plan: CarBudget) -> str:
    """With no schedule: 'fuel is', 'fuel and the registration are'."""
    words = [plan.units.title.lower()] + [f"the {fee['kind'].name.lower()}" for fee in plan.fees.values()]
    return f"{_and(words)} {'is' if len(words) == 1 else 'are'}"


def _job_row(due: Due | Fee, price: Price | None, plan: CarBudget, names: dict[int, str]) -> dict:
    if isinstance(due, Fee):
        return {"name": due.name, "status": due.status,
                "label": renewal_words.LABELS["expired"] if due.status == "overdue" else None,
                "when": fee_when(due, plan.today), "cost": None if price is None else price.cents,
                "source": fee_source(price), "claude": False, "unpriced": price is None,
                "fix": f"/renewals/{plan.fees[due.kind]['record_id']}/edit" if price is None else None}
    return {
        "name": due.name,
        "status": due.status,
        "when": when_words(due, plan.today),
        "cost": None if price is None else price.cents,
        "source": source_words(price, due.job, names),
        "claude": price is not None and price.source == "claude",
        "unpriced": price is None and not due.job.inspection,
    }


def month_rows(plan: CarBudget, names: dict[int, str]) -> list[dict]:
    """The month list: each month's jobs and fees at their prices, then fuel."""
    rows = []
    for index, month in enumerate(plan.months):
        rows.append({
            "label": f"{month.start:%B %Y}",
            "note": "from today" if index == 0 and month.start.day != 1 else "",
            "maintenance": month.maintenance,
            "fuel": month.fuel,
            "fuel_miles": None if month.fuel_miles is None else round(month.fuel_miles),
            "total": month.total,
            "jobs": [_job_row(due, price, plan, names) for due, price in month.items],
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


def chart(months: list[Month], per_month: int, count: int,
          categories: dict[int, tuple[int, str]] | None = None) -> dict | None:
    """The month bars: maintenance a month against what's put aside each month. Heights are 0–100.

    Each bar is stacked by type of work (``categories`` says each schedule
    item's): Engine, Brakes, and Tires and wheels in a colour each from the
    bottom up, then every other type in grey, in catalogue order. ``types``
    are the picker's rows, the most expensive first, and ``colours`` the
    legend's.
    """
    categories = categories or {}
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

    totals: dict[tuple[int, str], int] = {}

    def parts(month: Month) -> list[dict]:
        found: dict[tuple[int, str], int] = {}
        for due, price in month.items:
            if price is not None and price.cents > 0:
                key = type_of(due, categories)
                found[key] = found.get(key, 0) + price.cents
        segs, below = [], None
        for key in sorted(found, key=_stacking):
            tone = colour(key[1])
            segs.append({"type": key[1], "colour": tone, "cents": found[key], "gap": below not in (None, tone),
                         "title": f"{month.start:%B %Y} · {key[1]}: {dollars(found[key])}"})
            below = tone
            totals[key] = totals.get(key, 0) + found[key]
        return segs

    bars = [{"h": round(m.maintenance / scale * 100, 2), "label": label(m),
             "title": f"{m.start:%B %Y}: {dollars(m.maintenance)}", "segs": parts(m)} for m in months]
    present = [key[1] for key in totals]
    return {
        "bars": bars,
        "types": [{"label": key[1], "total": cents, "colour": colour(key[1])}
                  for key, cents in sorted(totals.items(), key=lambda item: (-item[1], item[0]))],
        "tones": {label: colour(label) for label in present},
        "colours": [{"label": label, "colour": colour(label)} for label in COLOURED if label in present]
                   + ([{"label": "Other types", "colour": "other"}] if set(present) - set(COLOURED) else []),
        "ticks": [{"y": round(i * step / scale * 100, 2), "label": dollars(i * step)}
                  for i in range(1, round(scale / step) + 1)],
        "line": round(per_month / scale * 100, 2),
        "per_month": per_month,
        "dense": count > 12,
        "what": "Maintenance and fees" if any(m.fees for m in months) else "Maintenance",
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
    fees = sum(p.fee_total for p in plans)
    expired = {name for p in plans for name in p.expired}
    return {
        "maintenance": maintenance,
        "fees": fees,
        "what": "maintenance and fees" if fees else "maintenance",
        "fuel": sum(fuel) if fuel else None,
        "fuel_word": fuel_word([p.units for p in plans if p.fuel is not None]).lower(),
        "per_month": sum(p.per_month for p in plans),
        "due_now": sum(p.due_now for p in plans),
        "due_now_note": due_now_note(sum(p.overdue for p in plans), [k.name for k in KINDS.values() if k.name in expired]),
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


# ---------- By type ----------

FEES = "Inspections and registration"
_FEES_ORDER = 10    # after the catalogue's nine categories
_OTHER = (9, "Inspections and other")   # an item with no service types, as the schedule shows it
# A colour each on the month bars, the same everywhere; every other type shares grey. A fourth hue can't be told
# from these three by everyone in both themes (the palette was checked against AMG's sheets, light and dark).
COLOURED = ("Engine", "Brakes", "Tires and wheels")


def type_of(due: Due | Fee, categories: dict[int, tuple[int, str]]) -> tuple[int, str]:
    """A job's or fee's type, with its place in the catalogue: its schedule item's category, or the fees' own."""
    return (_FEES_ORDER, FEES) if isinstance(due, Fee) else categories.get(due.item_id, _OTHER)


def colour(label: str) -> str:
    """The type's colour on the month bars: 1–3, or other."""
    return str(COLOURED.index(label) + 1) if label in COLOURED else "other"


def _stacking(key: tuple[int, str]) -> tuple:
    """The coloured types from the bottom up, then the rest in catalogue order."""
    order, label = key
    return (0, COLOURED.index(label), "") if label in COLOURED else (1, order, label)


def times_words(times: int) -> str:
    return {1: "once", 2: "twice"}.get(times, f"{times} times")


def breakdown(plans: list[CarBudget]) -> list[dict]:
    """The maintenance figure by type of work: the catalogue's categories, as the Spending report has them, with
    inspections and registration as one of their own.

    Each type's total, its share of the whole and its bar (scaled to the biggest), and its jobs, each counted
    across the horizon. The most expensive first; types with nothing priced last, in catalogue order. Inspections
    with no price of their own are left out: they're usually part of a visit.
    """
    groups: dict[str, dict] = {}
    for plan in plans:
        for month in plan.months:
            for due, price in month.items:
                fee = isinstance(due, Fee)
                if not fee and price is None and due.job.inspection:
                    continue
                order, label = type_of(due, plan.categories)
                group = groups.setdefault(label, {"label": label, "order": order, "total": 0, "priced": False,
                                                  "jobs": {}})
                job = group["jobs"].setdefault((plan.car["id"], due.name), {
                    "name": due.name, "car": plan.car["name"], "times": 0, "now": 0, "total": 0, "priced": False})
                job["times"] += 1
                job["now"] += due.status == "overdue"
                if price is not None:
                    job["total"] += price.cents
                    group["total"] += price.cents
                    job["priced"] = group["priced"] = True
    whole = sum(group["total"] for group in groups.values())
    top = max((group["total"] for group in groups.values()), default=0)
    rows = []
    for group in sorted(groups.values(), key=lambda g: (not g["total"], -g["total"], g["order"], g["label"])):
        jobs = sorted(group["jobs"].values(), key=lambda j: (not j["priced"], -j["total"], j["name"], j["car"]))
        for job in jobs:
            words = [] if job["now"] == job["times"] else [times_words(job["times"])]
            if job["now"]:
                words.append("due now" if job["now"] == job["times"] else f"{job['now']} due now")
            if not job["priced"]:
                words.append("not priced")
            job["words"] = " · ".join(words)
        rows.append({
            "label": group["label"],
            "total": group["total"],
            "priced": group["priced"],
            "share": round(group["total"] / whole * 100) if whole and group["total"] else None,
            "bar": round(group["total"] / top * 100, 2) if top and group["total"] else 0,
            "jobs": jobs,
        })
    return rows if any(row["priced"] for row in rows) else []   # nothing to break down
