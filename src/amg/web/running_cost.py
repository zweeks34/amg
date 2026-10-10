"""What a car costs to run, a mile: the car page's Running cost block, and the garage's figure.

The arithmetic is engine/running_cost.py's. This gathers what was paid since
you got the car — each confirmed visit at what it cost (its total, or its
lines and tax, as the Spending report counts it), each inspection and
registration with a cost, and the fill-ups — and words the answer: "31.2¢ a
mile", "$14,230 over 45,600 mi from Mar 12, 2019".

An inspection logged from a visit is already in that visit's total, so its
cost moves from the visit to Fees rather than counting twice. A fee with no
day done is counted a kind's usual length before it expires.

The next 12 months are the budget's, from the CarBudget the car page already
has, so the two pages never disagree.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from ..engine import running_cost as engine
from ..engine.odometer import Odometer
from ..engine.renewals import KINDS
from ..engine.running_cost import Period, Spend
from ..engine.schedule import add_months
from ..reports.history import paid
from ..repo import renewals
from ..repo import reports as report_repo
from . import fuel_status
from .budget import CarBudget
from .fuel_status import cents_a_mile
from .recalls import day_words
from .status import odometer_for
from .templating import dollars

NO_ODOMETER = "AMG needs two odometer readings a while apart to tell how far the car goes."


@dataclass
class RunningCost:
    units: fuel_status.Units
    today: date
    since: str = ""                  # "since you got it"
    start: date | None = None
    years: list[Period] = field(default_factory=list)   # oldest first
    whole: Period | None = None
    rate: float | None = None        # fuel's cost a mile, in cents, that unmeasured miles are counted at
    rate_span: str = ""              # last 12 months, or all time
    reason: str = ""                 # why there's no figure, when there isn't


def start_of(car, odometer: Odometer) -> tuple[date, str] | None:
    """Where the count begins: when you got it, else new, else the first reading."""
    if car["acquired_date"]:
        return date.fromisoformat(car["acquired_date"]), "since you got it"
    if car["in_service_date"]:
        return date.fromisoformat(car["in_service_date"]), "since it was new"
    if odometer.points:
        return odometer.points[0][0], "since your first record"
    return None


def end_of(car, odometer: Odometer, today: date) -> date:
    """Today; for a car you've archived, its last reading, since a car you've sold stops adding miles."""
    if not car["archived_at"]:
        return today
    days = [today, date.fromisoformat(car["archived_at"][:10])]
    if odometer.points:
        days.append(odometer.points[-1][0])
    return min(days)


def fee_day(row) -> date:
    """The day a fee was paid: the day it was done, else its kind's usual length before it expires."""
    if row["done_on"]:
        return date.fromisoformat(row["done_on"])
    return add_months(date.fromisoformat(row["expires_on"]), -KINDS[row["kind"]].months)


def spends(conn: sqlite3.Connection, car, start: date, end: date) -> list[Spend]:
    """Every visit and fee from ``start`` to ``end`` with something paid, a linked fee moved off its visit."""
    visits = report_repo.visits(conn, car["id"], start.isoformat(), end.isoformat())
    days = {v["id"]: date.fromisoformat(v["performed_on"]) for v in visits}
    left = {v["id"]: paid(v) or 0 for v in visits}     # what's still the visit's own, after the fees moved off it
    found = [Spend(days[visit_id], "service", cents) for visit_id, cents in left.items() if cents]
    for rows in renewals.for_car(conn, car["id"]).values():
        for row in rows:
            day = fee_day(row)
            if not row["cost_cents"] or not start <= day <= end:
                continue
            found.append(Spend(day, "fees", row["cost_cents"]))
            visit_id = row["service_event_id"]
            moved = min(row["cost_cents"], max(0, left.get(visit_id, 0)))
            if moved:
                left[visit_id] -= moved
                found.append(Spend(days[visit_id], "service", -moved))
    return found


def load(conn: sqlite3.Connection, car, odometer: Odometer | None = None, today: date | None = None) -> RunningCost:
    today = today or date.today()
    odometer = odometer if odometer is not None else odometer_for(conn, car)
    fuel = fuel_status.load(conn, car, today)
    found = RunningCost(fuel.units, today)
    begun = start_of(car, odometer)
    if not odometer or begun is None:
        found.reason = NO_ODOMETER
        return found
    found.start, found.since = begun
    end = end_of(car, odometer, today)
    rate, span = fuel_status.cost_a_mile(fuel)
    years = engine.years(found.start, end, odometer, spends(conn, car, found.start, end), fuel.stretches, rate)
    whole = engine.whole(years)
    if whole is None or whole.miles < engine.MIN_MILES:
        found.reason = f"Too few miles yet: {round(whole.miles) if whole else 0:,} mi {found.since}."
        return found
    found.years, found.whole, found.rate, found.rate_span = years, whole, rate, span
    return found


# ---------- Words ----------


def _cents(value: float | None) -> str:
    return dollars(None if value is None else round(value))


def headline(found: RunningCost) -> dict:
    """'Since you got it: 31.2¢ a mile', what it came to, and its parts."""
    whole, units = found.whole, found.units
    assert whole is not None and found.start is not None
    note = f"{_cents(whole.total)} over {round(whole.miles):,} mi from {day_words(found.start.isoformat())}"
    if whole.fuel is None:
        note += f", not counting {units.title.lower()}"
    parts = []
    if whole.fuel is not None:
        parts.append({"label": units.title, "value": cents_a_mile(whole.a_mile(whole.fuel)), "estimated": whole.estimated})
    parts.append({"label": "Service and repairs", "value": cents_a_mile(whole.a_mile(whole.service)), "estimated": False})
    if whole.fees:
        parts.append({"label": "Fees", "value": cents_a_mile(whole.a_mile(whole.fees)), "estimated": False})
    return {"label": found.since[0].upper() + found.since[1:], "value": cents_a_mile(whole.cents_a_mile),
            "note": note, "parts": parts}


def _row(label: str, note: str, period: Period) -> dict:
    return {
        "label": label,
        "note": note,
        "miles": f"{round(period.miles):,}",
        "fuel": "" if period.fuel is None else _cents(period.fuel),
        "estimated": period.estimated,
        "service": dollars(period.service) if period.service else "",
        "fees": dollars(period.fees) if period.fees else "",
        "a_mile": (cents_a_mile(period.cents_a_mile) if period.total else None) or "—",   # nothing recorded: no figure
    }


def year_rows(found: RunningCost) -> list[dict]:
    """A row a year, newest first: '2026 so far', and the first year 'from Mar 12'."""
    rows = []
    for period in found.years:
        year = period.start.year
        current = period.end == found.today
        label = f"{year} so far" if current else str(year)
        notes = []
        if period.start != date(year, 1, 1):
            notes.append(f"from {period.start:%b} {period.start.day}")
        if not current and period.end != date(year, 12, 31):
            notes.append(f"to {period.end:%b} {period.end.day}")
        rows.append(_row(label, ", ".join(notes), period))
    return rows[::-1]


def total_row(found: RunningCost) -> dict:
    assert found.whole is not None
    return _row("In all", "", found.whole)


def fuel_note(found: RunningCost) -> str | None:
    """How fuel was counted, when any of it is estimated or none of it is counted."""
    whole, units = found.whole, found.units
    assert whole is not None
    if whole.fuel is None:
        return f"{units.title} isn't counted: log {units.fill}s with their cost and it will be."
    if not whole.estimated:
        return None
    lately = "over the last 12 months" if found.rate_span == "last 12 months" else "so far"
    return (f"{units.title} marked est. is at {cents_a_mile(found.rate)} a mile, what your {units.fill}s have cost "
            f"{lately}, for the miles no logged {units.fill} measured. The miles they measured, from one "
            f"{units.full_noun} to the next, are at what they cost.")


def ahead_words(plan: CarBudget) -> dict | None:
    """'Next 12 months: ~27¢ a mile', what goes into it, and what it leaves out."""
    found = engine.ahead(plan.months, plan.rate)
    if found is None or found.period.cents_a_mile is None:
        return None
    period, units = found.period, plan.units
    parts = []
    if period.fuel is not None:
        parts.append(f"{units.title.lower()} ~{_cents(period.fuel)}")
    if plan.jobs:
        parts.append(f"maintenance ~{dollars(period.service)}")
    if period.fees:
        parts.append(f"fees ~{dollars(period.fees)}")
    miles = round(period.miles / 100) * 100
    extras = []
    if found.due_now:
        extras.append(f"Not counting {dollars(found.due_now)} due now.")
    if found.unpriced:
        extras.append(f"{found.unpriced} job{'s' if found.unpriced != 1 else ''} not priced yet.")
    if period.fuel is None:
        extras.append(f"Not counting {units.title.lower()}: log {units.fill}s with their cost.")
    if not plan.jobs:
        only = " and ".join(w for w, cents in ((units.title.lower(), period.fuel), ("fees", period.fees)) if cents)
        extras.append(f"{only.capitalize() + ' only' if only else 'Nothing yet'}: with a maintenance schedule, "
                      f"AMG counts its jobs too.")
    return {"label": f"Next {plan.count} months", "value": f"~{cents_a_mile(period.cents_a_mile)}",
            "note": f"~{_cents(period.total)} for ~{miles:,} mi: {', '.join(parts)}" if parts
                    else f"~{_cents(period.total)} for ~{miles:,} mi",
            "extras": extras}


def figure(found: RunningCost) -> dict | None:
    """The garage's figure: '31.2¢ a mile', saying so when fuel isn't in it; None with nothing to go on."""
    if found.reason or found.whole is None:
        return None
    unit = "a mile" if found.whole.fuel is not None else f"a mile, not counting {found.units.title.lower()}"
    return {"value": cents_a_mile(found.whole.cents_a_mile), "unit": unit}


def block(found: RunningCost, plan: CarBudget | None = None) -> dict:
    """Everything the car page's block shows; ``plan`` brings the next 12 months, for a car still on the road."""
    if found.reason:
        return {"reason": found.reason}
    return {"reason": "", "headline": headline(found), "ahead": ahead_words(plan) if plan else None,
            "rows": year_rows(found), "total": total_row(found), "fuel_note": fuel_note(found), "units": found.units}
