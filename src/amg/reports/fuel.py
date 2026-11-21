"""The Fuel report: each car's economy and running cost, month by month.

The arithmetic is engine/fuel.py's. A month's miles, gallons (or kWh) and
economy are its measured stretches — full fill to full fill, counted in the
month the stretch ended — so its economy is miles over quantity, never an
average of tanks. What was spent and the price paid are every fill that
month, partial ones included. Stretches are found across all of a car's
fills, so one that began before the dates asked for still counts in the month
it ended.

With three months measured, the best and worst are picked out; with two
months priced, the price paid is charted beside the economy, a dot a month.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from ..engine import fuel as engine
from ..engine.fuel import Fill, Stretch
from ..web import fuel_status
from ..web.fuel_status import Units
from .filters import Filters, span_words


@dataclass(frozen=True)
class Month:
    month: str                      # "2026-09"; "" for the whole span
    fills: int
    miles: int                      # measured
    quantity: float                 # what the measured miles took
    economy: float | None
    cost_per_mile: float | None     # cents
    spent: int                      # cents
    unit_price: float | None        # cents a gallon or kWh

    @property
    def label(self) -> str:
        return f"{date.fromisoformat(self.month + '-01'):%b %Y}" if self.month else "All"


@dataclass
class Section:
    car: dict
    units: Units
    months: list[Month]             # newest first
    whole: Month                    # the whole span
    trend: dict | None              # the chart, one dot a month
    price: dict | None = None       # the price paid, one dot a month
    best: str = ""                  # the month ("2026-09") with the best economy, given three measured
    worst: str = ""


def load(conn: sqlite3.Connection, cars: list[dict], filters: Filters) -> list[Section]:
    """A section for each car with fills in the dates asked for."""
    sections = []
    for car in cars:
        state = fuel_status.load(conn, car)
        section = build(car, state.units, state.fills, filters)
        if section:
            sections.append(section)
    return sections


def build(car: dict, units: Units, fills: list[Fill], filters: Filters) -> Section | None:
    found = engine.stretches(fills)
    chosen = [fill for fill in fills if _inside(fill.day, filters)]
    if not chosen:
        return None
    ended = [stretch for stretch in found if _inside(stretch.end.day, filters)]
    keys = sorted({_key(fill.day) for fill in chosen}, reverse=True)
    months = [_month(key, [f for f in chosen if _key(f.day) == key], [s for s in ended if _key(s.end.day) == key])
              for key in keys]
    whole = _month("", chosen, ended)
    measured = [m for m in reversed(months) if m.economy is not None]
    trend = None
    if len(measured) >= 2:
        points = [(date.fromisoformat(m.month + "-01"), m.economy, m.label, False) for m in measured]
        span = span_words(filters.start, filters.end) or "all time"
        trend = fuel_status.chart(points, whole.economy, span, units, "month")  # type: ignore[arg-type]
    best = worst = ""
    if len(measured) >= 3:
        best = max(measured, key=lambda m: m.economy).month          # type: ignore[arg-type,return-value]
        worst = min(measured, key=lambda m: m.economy).month         # type: ignore[arg-type,return-value]
    priced = [m for m in reversed(months) if m.unit_price is not None]
    price = None
    if len(priced) >= 2:
        points = [(date.fromisoformat(m.month + "-01"), m.unit_price, m.label, False) for m in priced]
        price = fuel_status.month_price_chart(points, whole.unit_price, span_words(filters.start, filters.end)
                                              or "all time", units)  # type: ignore[arg-type]
    return Section(car, units, months, whole, trend, price, best, worst)


def _month(key: str, fills: list[Fill], stretches: list[Stretch]) -> Month:
    return Month(
        month=key,
        fills=len(fills),
        miles=sum(s.miles for s in stretches),
        quantity=sum(s.quantity for s in stretches),
        economy=engine.economy(stretches),
        cost_per_mile=engine.cost_per_mile(stretches),
        spent=engine.spent(fills),
        unit_price=engine.unit_price(fills),
    )


def _key(day: date) -> str:
    return f"{day:%Y-%m}"


def _inside(day: date, filters: Filters) -> bool:
    text = day.isoformat()
    return (filters.start is None or text >= filters.start) and (filters.end is None or text <= filters.end)
