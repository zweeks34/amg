"""What a car's pages say about its fill-ups: economy, cost a mile, the log.

The arithmetic is engine/fuel.py's; this loads a car's fills, runs it, and
words the answers — "28.6 mpg", "12.4¢", "$3.459/gal". A gas or hybrid car
is filled up in gallons; an electric car is charged in kWh.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from ..engine import fuel as engine
from ..engine.fuel import Fill, Stretch
from ..repo import fuel
from .recalls import day_words
from .templating import money

YEAR = timedelta(days=365)


@dataclass(frozen=True)
class Units:
    energy: str
    quantity: str       # gal, kWh
    economy: str        # mpg, mi/kWh
    economy_name: str   # what economy is called in a sentence
    fill: str           # a fill-up, a charge
    title: str          # the car page block and the log page
    full: str           # the checkbox
    full_noun: str      # "since your last full tank"
    last: str           # the last stretch's figure


UNITS = {
    "gas": Units("gas", "gal", "mpg", "MPG", "fill-up", "Fuel", "Filled the tank", "full tank", "Last tank"),
    "electric": Units("electric", "kWh", "mi/kWh", "mi/kWh", "charge", "Charging", "Charged to your usual limit",
                      "full charge", "Last charge"),
}


def units_for(car) -> Units:
    return UNITS[fuel.energy_for(car["powertrain"])]


@dataclass
class FuelStatus:
    units: Units
    rows: list[sqlite3.Row]         # the car's fills, newest first, whatever their energy
    fills: list[Fill]               # those in the car's own energy, for the arithmetic
    stretches: list[Stretch]
    today: date

    @property
    def year_ago(self) -> date:
        return self.today - YEAR

    def ending(self, fill_id: int) -> Stretch | None:
        return next((s for s in self.stretches if s.end.id == fill_id), None)


def _fill(row) -> Fill:
    return Fill(row["id"], date.fromisoformat(row["filled_on"]), row["odometer"], row["quantity"], row["cost_cents"],
                bool(row["full"]), bool(row["missed_before"]), row["place"])


def load(conn: sqlite3.Connection, car, today: date | None = None) -> FuelStatus:
    units = units_for(car)
    rows = fuel.log(conn, car["id"])
    fills = [_fill(row) for row in rows if row["energy"] == units.energy]
    return FuelStatus(units, rows, fills, engine.stretches(fills), today or date.today())


# ---------- Words ----------


def economy_words(value: float | None, units: Units) -> str | None:
    if value is None:
        return None
    return f"{value:.1f} mpg" if units.quantity == "gal" else f"{value:.2f} mi/kWh"


def cents_a_mile(value: float | None) -> str | None:
    if value is None:
        return None
    return f"{value:.1f}¢" if value < 100 else f"${value / 100:,.2f}"


def price_words(cents: float | None, units: Units) -> str | None:
    if cents is None:
        return None
    return f"${cents / 100:,.3f}/gal" if units.quantity == "gal" else f"{cents:.1f}¢/kWh"


def quantity_words(quantity: float, units: Units) -> str:
    if units.quantity == "gal":
        return f"{quantity:.3f} gal"
    return f"{quantity:.3f}".rstrip("0").rstrip(".") + " kWh"


_PLACES = {"home": "Home", "public": "Public"}


def copy_words(row, units: Units, stretch: Stretch | None) -> str:
    """A fill on one line, for the clipboard, in the log's own words:
    'Oct 20, 2026 · 45,210 mi · 10.200 gal · $34.67 ($3.399/gal) · 32.4 mpg · Full tank · Costco on Main'.
    A part it hasn't got (a cost, economy) is left out."""
    cost = None
    if row["cost_cents"] is not None:
        cost = f"{money(row['cost_cents'])} ({price_words(row['cost_cents'] / row['quantity'], units)})"
    parts = [
        day_words(row["filled_on"]),
        f"{row['odometer']:,} mi",
        quantity_words(row["quantity"], units),
        cost,
        economy_words(stretch.economy, units) if stretch else None,
        units.full_noun.capitalize() if row["full"] else "Partial " + ("fill" if units.quantity == "gal" else "charge"),
        _PLACES.get(row["place"] or ""),
        "After one not logged" if row["missed_before"] else None,
        " ".join((row["note"] or "").split()),
    ]
    return " · ".join(part for part in parts if part)


def _span(state: FuelStatus) -> tuple[date | None, str]:
    """The last 12 months when a stretch ended in them, else all time: (since, its words)."""
    if engine.economy(state.stretches, since=state.year_ago) is not None:
        return state.year_ago, "last 12 months"
    return None, "all time"


def cost_a_mile(state: FuelStatus) -> tuple[float | None, str]:
    """Cents a mile over the last 12 months, else all time, and which: what the budget runs fuel at."""
    since, span = _span(state)
    return engine.cost_per_mile(state.stretches, since=since), span


def summary(state: FuelStatus) -> dict:
    """The car page's block: economy and cost a mile over the last year (or all time), and the last fill."""
    since, span = _span(state)
    return {
        "units": state.units,
        "count": len(state.rows),
        "economy": economy_words(engine.economy(state.stretches, since=since), state.units),
        "cost_a_mile": cents_a_mile(engine.cost_per_mile(state.stretches, since=since)),
        "span": span,
        "last": state.rows[0] if state.rows else None,
    }


def _figure(label: str, words: str | None, note: str | None = None) -> dict:
    """A figure, its unit split off to be set small: "3.29 mi/kWh" → 3.29 + mi/kWh, "$3.459/gal" → $3.459 + /gal."""
    number, unit = words or "—", None
    if " " in number:
        number, unit = number.split(" ", 1)
    elif "/" in number:
        number, rest = number.split("/", 1)
        unit = "/" + rest
    return {"label": label, "value": number, "unit": unit, "note": note}


def figures(state: FuelStatus) -> list[dict]:
    """The fuel page's figures: economy three ways, then what it costs."""
    units, found, year = state.units, state.stretches, state.year_ago
    since, span = _span(state)
    shown = []
    if found:
        shown += [
            _figure(units.last, economy_words(found[-1].economy, units), found[-1].end.day.isoformat()),
            _figure("Last 12 months", economy_words(engine.economy(found, since=year), units)),
            _figure("All time", economy_words(engine.economy(found), units)),
        ]
        if (cost := engine.cost_per_mile(found, since=since)) is not None:
            shown.append(_figure("Cost a mile", cents_a_mile(cost), span))
    if state.fills:
        shown.append(_figure("Spent", money(engine.spent(state.fills, since=year)), "last 12 months"))
        if (price := engine.unit_price(state.fills, since=year)) is not None:
            shown.append(_figure("Price paid", price_words(price, units), "average, last 12 months"))
    return shown


# Gridline steps for the trend chart: mpg in whole numbers, mi/kWh in tenths.
_STEPS = {"gal": (1, 2, 5, 10, 20), "kWh": (0.1, 0.2, 0.5, 1, 2)}


def trend(state: FuelStatus) -> dict | None:
    """Economy for each stretch over time, with the average as a line: positions as 0–100 for the SVG."""
    found = state.stretches
    if len(found) < 2:
        return None
    since, span = _span(state)
    flagged = engine.unusual(found)
    points = [(s.end.day, s.economy, s.end.day.isoformat(), s.end.id in flagged) for s in found]
    per = "tank" if state.units.quantity == "gal" else "charge"
    return chart(points, engine.economy(found, since=since), span, state.units, per)  # type: ignore[arg-type]


def chart(points: list[tuple[date, float, str, bool]], average: float, span: str, units: Units, per: str) -> dict:
    """An economy trend for the SVG, from (day, economy, label, unusual) points oldest first: positions as 0–100,
    gridlines at round numbers, and the average as a line. ``per`` is what each dot is: a tank, a charge, a month."""
    values = [value for _, value, _, _ in points] + [average]
    low, high = min(values), max(values)
    steps = _STEPS[units.quantity]
    step = next((s for s in steps if (high - low) / s <= 4), steps[-1])
    bottom = math.floor(low / step) * step
    top = max(math.ceil(high / step) * step, bottom + step)

    def y(value: float) -> float:
        return round(100 - (value - bottom) / (top - bottom) * 100, 3)

    first, last = points[0][0], points[-1][0]
    days = max(1, (last - first).days)
    count = round((top - bottom) / step)
    decimals = 0 if units.quantity == "gal" else 1
    return {
        "unit": units.economy,
        "per": per,
        "points": [{"x": round((day - first).days / days * 100, 3), "y": y(value),
                    "label": f"{label}: {economy_words(value, units)}", "unusual": unusual}
                   for day, value, label, unusual in points],
        "ticks": [{"y": y(bottom + i * step), "label": f"{bottom + i * step:.{decimals}f}"} for i in range(count + 1)],
        "average": {"y": y(average), "label": f"{economy_words(average, units)} average, {span}"},
        "first": f"{first:%b %Y}",
        "last": f"{last:%b %Y}",
    }


def saved(state: FuelStatus, fill_id: int) -> str | None:
    """The line after saving a fill: what it measured, or when it will."""
    row = next((r for r in state.rows if r["id"] == fill_id), None)
    if row is None:
        return None
    units = UNITS[row["energy"]]
    if stretch := state.ending(fill_id):
        return f"Saved. {economy_words(stretch.economy, units)} since your last {units.full_noun}."
    if not row["full"]:
        return f"Saved. {units.economy_name} shows at your next {units.full_noun}."
    return f"Saved. {units.economy_name} is measured from this {units.full_noun} to the next."


def log_rows(state: FuelStatus) -> list[dict]:
    """The log, newest first, each fill worded in its own units."""
    flagged = engine.unusual(state.stretches)
    rows = []
    for row in state.rows:
        units = UNITS[row["energy"]]
        stretch = state.ending(row["id"]) if row["energy"] == state.units.energy else None
        price = row["cost_cents"] / row["quantity"] if row["cost_cents"] is not None else None
        rows.append({
            "id": row["id"],
            "day": row["filled_on"],
            "when": day_words(row["filled_on"]),
            "fill": units.fill,
            "line": copy_words(row, units, stretch),
            "odometer": row["odometer"],
            "quantity": quantity_words(row["quantity"], units),
            "price": price_words(price, units),
            "total": money(row["cost_cents"]) if row["cost_cents"] is not None else None,
            "economy": economy_words(stretch.economy, units) if stretch else None,
            "partial": not row["full"],
            "missed_before": bool(row["missed_before"]),
            "unusual": row["id"] in flagged,
            "place": _PLACES.get(row["place"] or ""),
            "note": row["note"],
        })
    return rows
