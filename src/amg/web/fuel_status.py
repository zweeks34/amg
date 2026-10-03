"""What a car's pages say about its fill-ups: economy, cost a mile, the log.

The arithmetic is engine/fuel.py's; this loads a car's fills, runs it, and
words the answers — "28.6 mpg", "12.4¢", "$3.459/gal". A gas or hybrid car
is filled up in gallons; an electric car is charged in kWh.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from ..engine import fuel as engine
from ..engine.fuel import Fill, Stretch
from ..repo import fuel
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


def summary(state: FuelStatus) -> dict:
    """The car page's block: economy and cost a mile over the last year (or all time), and the last fill."""
    recent = engine.economy(state.stretches, since=state.year_ago)
    span = "last 12 months" if recent is not None else "all time"
    since = state.year_ago if recent is not None else None
    last = state.rows[0] if state.rows else None
    return {
        "units": state.units,
        "count": len(state.rows),
        "economy": economy_words(engine.economy(state.stretches, since=since), state.units),
        "cost_a_mile": cents_a_mile(engine.cost_per_mile(state.stretches, since=since)),
        "span": span,
        "last": last,
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
            "odometer": row["odometer"],
            "quantity": quantity_words(row["quantity"], units),
            "price": price_words(price, units),
            "total": money(row["cost_cents"]) if row["cost_cents"] is not None else None,
            "economy": economy_words(stretch.economy, units) if stretch else None,
            "partial": not row["full"],
            "missed_before": bool(row["missed_before"]),
            "unusual": row["id"] in flagged,
            "place": {"home": "Home", "public": "Public"}.get(row["place"] or ""),
            "note": row["note"],
        })
    return rows
