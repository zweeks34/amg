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
    """A row for the arithmetic; a charge at home that names no station is at Home."""
    station = row["station"] or ("Home" if row["place"] == "home" else "")
    return Fill(row["id"], date.fromisoformat(row["filled_on"]), row["odometer"], row["quantity"], row["cost_cents"],
                bool(row["full"]), bool(row["missed_before"]), row["place"], station)


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
    'Oct 20, 2026 · Shell · 45,210 mi · 10.200 gal · $34.67 ($3.399/gal) · 32.4 mpg · Full tank · Paid inside'.
    A part it hasn't got (a cost, economy) is left out."""
    cost = None
    if row["cost_cents"] is not None:
        cost = f"{money(row['cost_cents'])} ({price_words(row['cost_cents'] / row['quantity'], units)})"
    parts = [
        day_words(row["filled_on"]),
        row["station"],
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


def _spread(state: FuelStatus) -> tuple[engine.Spread | None, date | None, str]:
    """The spread of the last 12 months' usual tanks when there are three, else of all time's: (it, since, words)."""
    flagged = engine.unusual(state.stretches)
    if (found := engine.spread(state.stretches, flagged, since=state.year_ago)) is not None:
        return found, state.year_ago, "last 12 months"
    return engine.spread(state.stretches, flagged), None, "all time"


def _number(words: str) -> str:
    return words.split(" ", 1)[0]


def tank_to_tank(state: FuelStatus) -> dict | None:
    """The fuel page's Tank to tank: the lowest, highest and mean of each tank's own figure, and how far apart they
    run; with the line that says which tanks, and how the mean differs from the figures above."""
    found, _, span = _spread(state)
    if found is None:
        return None
    units = state.units
    tank = "tank" if units.quantity == "gal" else "charge"
    rows = {row["id"]: row for row in state.rows}

    def words(value: float) -> str:
        return economy_words(value, units)  # type: ignore[return-value]

    def when(stretch: Stretch) -> str:
        station = rows[stretch.end.id]["station"] if stretch.end.id in rows else ""
        return stretch.end.day.isoformat() + (f" at {station}" if station else "")

    low, high = _number(words(found.mean - found.stdev)), _number(words(found.mean + found.stdev))
    if low == high:
        within = f"all {found.count} {tank}s at {_number(words(found.mean))}"
    else:
        within = f"{found.within} of {found.count} {tank}s within {low}–{high}"
    left_out = f" {found.left_out} unusual {tank}{'s' if found.left_out != 1 else ''} left out." if found.left_out else ""
    return {
        "heading": f"{tank.capitalize()} to {tank}",
        "line": f"Each {tank}'s own {units.economy_name}, {span}.{left_out} The mean counts every {tank} alike; "
                f"the {span.capitalize()} figure above weighs each by its miles.",
        "figures": [
            _figure("Lowest", words(found.lowest.economy), when(found.lowest)),
            _figure("Highest", words(found.highest.economy), when(found.highest)),
            _figure("Mean", words(found.mean), f"of {found.count} {tank}s"),
            _figure("Std deviation", "±" + words(found.stdev), within),
        ],
    }


# Gridline steps for the trend chart: mpg in whole numbers, mi/kWh in tenths.
_STEPS = {"gal": (1, 2, 5, 10, 20), "kWh": (0.1, 0.2, 0.5, 1, 2)}


def trend(state: FuelStatus) -> dict | None:
    """Economy for each stretch over time, with the average as a line and Tank to tank's mean ± 1 std deviation
    shaded over the months it covers: positions as 0–100 for the SVG."""
    found = state.stretches
    if len(found) < 2:
        return None
    since, span = _span(state)
    flagged = engine.unusual(found)
    points = [(s.end.day, s.economy, s.end.day.isoformat(), s.end.id in flagged) for s in found]
    per = "tank" if state.units.quantity == "gal" else "charge"
    band = None
    spread, spread_since, spread_span = _spread(state)
    if spread is not None:
        low, high = spread.mean - spread.stdev, spread.mean + spread.stdev
        low_words, high_words = economy_words(low, state.units), economy_words(high, state.units)
        if _number(low_words) != _number(high_words):        # every tank alike: no band to draw
            band = (low, high, spread_since,
                    f"Usual, {spread_span}: {_number(low_words)}–{high_words}, mean ± 1 std deviation")
    return chart(points, engine.economy(found, since=since), span, state.units, per, band)  # type: ignore[arg-type]


def where_you_fill(state: FuelStatus) -> dict | None:
    """Where you fill up (or charge): each station's fills over the last 12 months (else all time), most first, with
    what they came to and the average paid. The cheapest are marked, by the price as shown ($3.299, 42.0¢), so a tie
    marks each; when every station with a price shows the same, none is."""
    units = state.units
    since = state.year_ago if any(f.day >= state.year_ago for f in state.fills) else None
    found, unnamed = engine.stations(state.fills, since=since)
    if not found:
        return None
    priced = [s for s in found if s.unit_price is not None]
    shown = {s.name: price_words(s.unit_price, units) for s in priced}
    lowest = shown[min(priced, key=lambda s: s.unit_price).name] if priced else None  # type: ignore[arg-type,return-value]
    cheapest = {name for name, words in shown.items() if words == lowest} if len(set(shown.values())) > 1 else set()

    def count(n: int) -> str:
        return f"{n} {units.fill}{'s' if n != 1 else ''}"

    line = ("Last 12 months" if since else "All time") + ", most visits first."
    if unnamed:
        line += f" {count(unnamed)} {'doesn' if unnamed == 1 else 'don'}'t name a station."
    return {
        "heading": "Where you fill up" if units.quantity == "gal" else "Where you charge",
        "line": line,
        "rows": [{"name": s.name,
                  "visits": count(s.fills) + (f" · {money(s.spent)}" if s.spent else ""),
                  "price": price_words(s.unit_price, units),
                  "cheapest": s.name in cheapest} for s in found],
    }


# Gridline steps for the price chart, in cents: a gallon by dimes and quarters, a kWh by cents.
_PRICE_STEPS = {"gal": (10, 20, 25, 50, 100), "kWh": (1, 2, 5, 10, 20, 50)}


def price_trend(state: FuelStatus) -> dict | None:
    """What each fill with a cost came to a gallon (or kWh), partial ones included, over time; the average paid over
    the last 12 months (else all time) as a line, as Price paid has it. A charge says whether it was at home."""
    units = state.units
    gal = units.quantity == "gal"
    priced = sorted((f for f in state.fills if f.cost_cents is not None), key=lambda f: (f.day, f.odometer, f.id))
    if len(priced) < 2:
        return None
    since = state.year_ago if any(f.day >= state.year_ago for f in priced) else None
    points = [(f.day, f.cost_cents / f.quantity,  # type: ignore[operator]
               ", ".join(part for part in (f.day.isoformat(), None if gal else _PLACES.get(f.place or "")) if part),
               False) for f in priced]
    return _chart(points, engine.unit_price(priced, since=since), "last 12 months" if since else "all time",  # type: ignore[arg-type]
                  "$/gal" if gal else "¢/kWh", units.fill, lambda cents: price_words(cents, units),
                  _PRICE_STEPS[units.quantity], (lambda cents: f"${cents / 100:.2f}") if gal else (lambda cents: f"{cents:.0f}¢"))


SPARK_TANKS = 12       # the garage card's line: this many recent tanks (or charges)


def sparkline(state: FuelStatus, tanks: int = SPARK_TANKS) -> dict | None:
    """A car's recent economy for its garage card: its last few measured tanks, oldest first, evenly spaced, as
    0–100 points for the SVG, with their average (miles over quantity) as a line. None with fewer than three."""
    found = state.stretches[-tanks:]
    if len(found) < 3:
        return None
    units = state.units
    values = [stretch.economy for stretch in found]
    average = engine.economy(found)
    low, high = min(values + [average]), max(values + [average])
    pad = (high - low) * 0.15 or 1.0        # off the edges; a steady car's line flat in the middle

    def y(value: float) -> float:
        return round(100 - (value - (low - pad)) / ((high + pad) - (low - pad)) * 100, 2)

    points = [{"x": round(i / (len(found) - 1) * 100, 2), "y": y(value)} for i, value in enumerate(values)]
    last = economy_words(values[-1], units)
    per = "tanks" if units.quantity == "gal" else "charges"
    return {
        "points": points,
        "last": points[-1],
        "average": y(average),
        "value": last.split(" ", 1)[0],
        "unit": last.split(" ", 1)[1],
        "words": f"{units.economy_name}, last {len(found)} {per}: from {economy_words(values[0], units)} to {last}, "
                 f"average {economy_words(average, units)}",
    }


Band = tuple[float, float, date | None, str]    # a range shaded from a day on (None: from the start), and its words


def chart(points: list[tuple[date, float, str, bool]], average: float, span: str, units: Units, per: str,
          band: Band | None = None) -> dict:
    """An economy trend for the SVG, from (day, economy, label, unusual) points oldest first: positions as 0–100,
    gridlines at round numbers, the average as a line, and ``band`` shaded. ``per`` is what each dot is: a tank, a
    charge, a month."""
    decimals = 0 if units.quantity == "gal" else 1
    return _chart(points, average, span, units.economy, per, lambda value: economy_words(value, units),
                  _STEPS[units.quantity], lambda value: f"{value:.{decimals}f}", band)


def _chart(points: list[tuple[date, float, str, bool]], average: float, span: str, unit: str, per: str,
           words, steps: tuple, tick, band: Band | None = None) -> dict:
    """Any trend for the SVG: ``words`` puts a value in words, ``steps`` are the gridline spacings to choose from,
    and ``tick`` labels a gridline."""
    values = [value for _, value, _, _ in points] + [average] + ([band[0], band[1]] if band else [])
    low, high = min(values), max(values)
    step = next((s for s in steps if (high - low) / s <= 4), steps[-1])
    bottom = math.floor(low / step) * step
    top = max(math.ceil(high / step) * step, bottom + step)

    def y(value: float) -> float:
        return round(100 - (value - bottom) / (top - bottom) * 100, 3)

    first, last = points[0][0], points[-1][0]
    days = max(1, (last - first).days)

    def x(day: date) -> float:
        return round((day - first).days / days * 100, 3)

    count = round((top - bottom) / step)
    shown = {
        "unit": unit,
        "per": per,
        "points": [{"x": x(day), "y": y(value), "label": f"{label}: {words(value)}", "unusual": unusual}
                   for day, value, label, unusual in points],
        "ticks": [{"y": y(bottom + i * step), "label": tick(bottom + i * step)} for i in range(count + 1)],
        "average": {"y": y(average), "label": f"{words(average)} average, {span}"},
        "band": None,
        "first": f"{first:%b %Y}",
        "last": f"{last:%b %Y}",
    }
    if band is not None:
        start = 0.0 if band[2] is None or band[2] <= first else x(band[2])
        shown["band"] = {"x": start, "width": round(100 - start, 3), "y": y(band[1]),
                         "height": round(y(band[0]) - y(band[1]), 3), "label": band[3]}
    return shown


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
            "station": row["station"],
        })
    return rows
