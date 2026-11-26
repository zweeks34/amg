"""The Spending report: what went on each category of work, year by year.

Each year's column adds up to what you actually paid. A line's amount goes
under its category (history.category says which); a visit's tax goes under
Tax; and whatever its printed total leaves over — shop supplies, a line nobody
tagged, a discount the invoice didn't itemise — goes under Other with the
untagged lines. A visit with no total counts its lines and tax.

Narrowed to a service, only the lines that did it count, so Tax and the
leftovers drop out.

Around the table: the years as stacked bars in the budget's colours, the
latest year against the one before, where the money went by kind of line
(labor, parts, fees), by shop and by car, and what it came to a mile over the
miles the cars went in the report's dates.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import date

from ..engine.running_cost import MIN_MILES
from ..web.budget import COLOURED, colour
from ..web.templating import dollars
from .filters import Filters
from .history import OTHER, History, category

TAX = "Tax"
KINDS = {"labor": "Labor", "part": "Parts", "fee": "Fees", "other": "Other"}


@dataclass
class Spending:
    years: list[int]        # oldest first, every year from the first visit to the last
    rows: list[dict]        # {"label", "cells": {year: cents}, "total"}, in catalogue order, then Other and Tax
    totals: dict[int, int]  # by year
    total: int

    @property
    def top_cell(self) -> int:
        """The biggest category-year, for shading the others against."""
        return max((cents for row in self.rows for cents in row["cells"].values()), default=0)

    def heat(self, cents: int | None) -> float:
        """A cell's shade, 0–1."""
        return round(max(0, cents or 0) / self.top_cell, 3) if self.top_cell > 0 else 0.0

    def share(self, cents: int) -> float:
        """A row's share of the whole, 0–100."""
        return round(max(0, cents) / self.total * 100, 1) if self.total > 0 else 0.0


def table(history: History, filters: Filters, order: list[str]) -> Spending | None:
    """The table for the visits a History report found; None when it found none."""
    if not history.visits:
        return None
    cells: dict[str, dict[int, int]] = {}

    def add(label: str, year: int, cents: int) -> None:
        if cents:
            row = cells.setdefault(label, {})
            row[year] = row.get(year, 0) + cents

    for visit in history.visits:
        year = int(visit["performed_on"][:4])
        for line in visit["shown"]:
            add(category(line, filters), year, line["amount_cents"] or 0)
        if history.by_service:
            continue
        tax = visit["tax_cents"] or 0
        add(TAX, year, tax)
        if visit["total_cents"] is not None:
            itemised = sum(line["amount_cents"] or 0 for line in visit["lines"])
            add(OTHER, year, visit["total_cents"] - itemised - tax)

    years = [int(visit["performed_on"][:4]) for visit in history.visits]
    span = list(range(min(years), max(years) + 1))
    place = {name: n for n, name in enumerate(order)}
    labels = sorted((label for label in cells if label not in (OTHER, TAX)),
                    key=lambda label: (place.get(label, len(place)), label))
    labels += [label for label in (OTHER, TAX) if label in cells]
    rows = [{"label": label, "cells": cells[label], "total": sum(cells[label].values()), "tone": colour(label)}
            for label in labels]
    totals = {year: sum(row["cells"].get(year, 0) for row in rows) for year in span}
    return Spending(span, rows, totals, sum(totals.values()))


# ---------- Around the table ----------


def latest(spent: Spending, today: date | None = None) -> dict | None:
    """The latest year against the one before: {"year", "cents", "words", "change", "up"}. None with one year.
    The current year is "so far"; with nothing the year before, there's no change to give."""
    if len(spent.years) < 2:
        return None
    year, before = spent.years[-1], spent.years[-2]
    now, then = spent.totals[year], spent.totals[before]
    so_far = year == (today or date.today()).year
    found = {"year": year, "cents": now, "words": f"{year} so far" if so_far else str(year), "change": "",
             "up": False}
    if then > 0:
        change = round((now - then) / then * 100)
        found["change"] = f"{'▲' if change > 0 else '▼' if change < 0 else '='} {abs(change)}% on {before}"
        found["up"] = change > 0
    return found


_STEPS = (5_000, 10_000, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000, 2_500_000, 5_000_000)


def bars(spent: Spending) -> dict | None:
    """The years as stacked bars, for the budget's bar chart: a segment a category, the four coloured ones
    (budget.COLOURED) in the budget's colours from the bottom up, the rest in grey. No put-aside tape. None
    for one year."""
    top = max((max(0, cents) for cents in spent.totals.values()), default=0)
    if top <= 0 or len(spent.years) < 2:
        return None
    step = next((s for s in _STEPS if top / s <= 4), _STEPS[-1])
    scale = math.ceil(top / step) * step
    order = sorted(spent.rows, key=lambda row: (0, COLOURED.index(row["label"])) if row["label"] in COLOURED
                   else (1, spent.rows.index(row)))
    shown = []
    for year in spent.years:
        segs, below = [], None
        for row in order:
            cents = row["cells"].get(year, 0)
            if cents <= 0:
                continue
            tone = colour(row["label"])
            segs.append({"type": row["label"], "colour": tone, "cents": cents, "gap": below not in (None, tone),
                         "title": f"{year} · {row['label']}: {dollars(cents)}"})
            below = tone
        shown.append({"h": round(max(0, spent.totals[year]) / scale * 100, 2), "label": str(year), "year": True,
                      "title": f"{year}: {dollars(spent.totals[year])}", "segs": segs})
    present = [row["label"] for row in spent.rows if row["total"] > 0]
    return {
        "bars": shown,
        "types": [{"label": row["label"], "total": row["total"], "colour": colour(row["label"])}
                  for row in sorted(spent.rows, key=lambda row: -row["total"]) if row["total"] > 0],
        "tones": {label: colour(label) for label in present},
        "colours": [{"label": label, "colour": colour(label)} for label in COLOURED if label in present]
                   + ([{"label": "Everything else", "colour": "other"}] if set(present) - set(COLOURED) else []),
        "ticks": [{"y": round(i * step / scale * 100, 2), "label": dollars(i * step)}
                  for i in range(1, round(scale / step) + 1)],
        "line": None,
        "per_month": None,
        "dense": len(spent.years) > 12,
        "what": "Spending",
    }


def kinds(history: History) -> list[dict]:
    """Where the money went by kind of line (labor, parts, fees, other) and tax, the most first; what a printed
    total leaves over (supplies, a discount) goes under Other. Adds up to the report's total. Empty with fewer
    than two."""
    found: dict[str, int] = {}

    def add(label: str, cents: int) -> None:
        if cents:
            found[label] = found.get(label, 0) + cents

    for visit in history.visits:
        for line in visit["shown"]:
            add(KINDS.get(line["kind"], "Other"), line["amount_cents"] or 0)
        if history.by_service:
            continue
        tax = visit["tax_cents"] or 0
        add(TAX, tax)
        if visit["total_cents"] is not None:
            itemised = sum(line["amount_cents"] or 0 for line in visit["lines"])
            add("Other", visit["total_cents"] - itemised - tax)
    rows = [{"label": label, "cents": found[label]} for label in (*KINDS.values(), TAX) if found.get(label)]
    rows.sort(key=lambda row: -row["cents"])        # the biggest first, as its donut goes
    return _shares(rows) if len(rows) >= 2 else []


def shops(history: History, limit: int = 8) -> dict:
    """Who did the work: each shop (whatever its capitals), your own work, and work done with no receipt, with
    what it came to and how many visits, the most spent first, each with its share of them all. {"rows", "more",
    "rest"}: the first ``limit``, how many more there were, and what those came to."""
    found: dict[str, dict] = {}
    for visit in history.visits:              # newest first, so a shop is named as it was last spelled
        key = visit["who"].strip().lower()
        row = found.setdefault(key, {"shop": visit["shop"], "who": visit["who"], "diy": visit["source"] == "diy",
                                     "cents": 0, "visits": 0, "last": visit["performed_on"]})
        row["cents"] += _amount(visit, history)
        row["visits"] += 1
    rows = _shares(sorted(found.values(), key=lambda row: (-row["cents"], -row["visits"], row["who"].lower())))
    return {"rows": rows[:limit], "more": max(0, len(rows) - limit),
            "rest": sum(row["cents"] for row in rows[limit:])}


def by_car(history: History, miles: dict[int, float] | None = None) -> list[dict]:
    """A row a car, years across, adding up to the table's totals, the most spent first; each with its cost a
    mile when it went far enough. Empty with fewer than two cars."""
    miles = miles or {}
    found: dict[int, dict] = {}
    for visit in history.visits:
        row = found.setdefault(visit["vehicle_id"], {"id": visit["vehicle_id"], "label": visit["car_name"],
                                                     "cells": {}, "total": 0})
        year, cents = int(visit["performed_on"][:4]), _amount(visit, history)
        row["cells"][year] = row["cells"].get(year, 0) + cents
        row["total"] += cents
    if len(found) < 2:
        return []
    rows = sorted(found.values(), key=lambda row: (-row["total"], row["label"].lower()))
    for row in rows:
        row["miles"] = miles.get(row["id"], 0.0)
        row["per_mile"] = per_mile(row["total"], row["miles"])
    return rows


def per_mile(cents: int, miles: float) -> float | None:
    """Cents a mile, once there are enough miles behind it that one oil change doesn't swamp it."""
    return cents / miles if miles >= MIN_MILES else None


def miles(conn: sqlite3.Connection, cars: list, filters: Filters, today: date | None = None) -> dict[int, float]:
    """The miles each car went in the report's dates, by its odometer model, counted from when you got it to
    today (or, for a car you've archived, its last reading). A car the model can't tell is left out."""
    from ..web.running_cost import end_of, start_of   # imported here: the web layer imports this package
    from ..web.status import odometer_for
    today = today or date.today()
    found = {}
    for car in cars:
        if filters.car and car["id"] != filters.car:
            continue
        odometer = odometer_for(conn, car)
        begun = start_of(car, odometer)
        if not odometer or begun is None:
            continue
        first = max([begun[0]] + ([date.fromisoformat(filters.start)] if filters.start else []))
        last = min([end_of(car, odometer, today)] + ([date.fromisoformat(filters.end)] if filters.end else []))
        start, end = odometer.miles_on(first), odometer.miles_on(last)
        if first < last and start is not None and end is not None and end > start:
            found[car["id"]] = end - start
    return found


def _amount(visit: dict, history: History) -> int:
    """What a visit adds to the report: its matching lines when narrowed to a service, else what was paid."""
    return visit["matched_cents"] if history.by_service else visit["paid"] or 0


def _shares(rows: list[dict]) -> list[dict]:
    """Each row's share of the rows' whole (0–100, rounded) and its bar against the biggest (0–100)."""
    whole = sum(max(0, row["cents"]) for row in rows)
    top = max((row["cents"] for row in rows), default=0)
    for row in rows:
        row["share"] = round(max(0, row["cents"]) / whole * 100) if whole > 0 else 0
        row["bar"] = round(max(0, row["cents"]) / top * 100, 1) if top > 0 else 0
    return rows


# ---------- The donuts ----------

SLICES = 4                      # the most a donut has: past it, the three biggest and Everything else, since
                                # no more shades of one colour can be told apart
EVERYTHING_ELSE = "Everything else"
_OUTER, _INNER = 50.0, 31.0     # in a 100-square drawing, centred


def donut(parts: list[dict], rest: int = 0, tones: bool = False, key: str = "cents",
          name: str = "label") -> dict | None:
    """A donut for a breakdown, biggest first: each part its own slice up to four; past that, the three biggest
    and Everything else (with ``rest``, what parts not listed came to). Each part is marked with the slice it's
    in ("slice", None for one with nothing to draw) and that slice's tone: three shades of one colour, darkest
    first ("0"–"2"), then grey ("rest") for the fourth, Everything else or not; with ``tones``, the parts' own
    "tone", as the category donut keeps the page's colours ("c1"–"c3", "cother"). ``key`` and ``name`` say
    where a part keeps its amount and what it's called.

    A slice is never negative: a refund or a discount is in the total in the middle, but draws nothing. None
    with fewer than two slices. {"total", "slices": [{"label", "cents", "share", "tone", "path", "title"}],
    "words"}."""
    for part in parts:
        part["slice"], part["tone"] = None, part.get("tone") if tones else None
    drawn = [part for part in parts if part[key] > 0]
    rest = max(0, rest)
    fits = tones or len(drawn) + (1 if rest else 0) <= SLICES     # the page's colours each tell apart
    own = drawn if fits else drawn[:SLICES - 1]
    groups = [{"label": part[name], "cents": part[key], "parts": [part],
               "tone": part["tone"] if tones else str(n) if n < SLICES - 1 else "rest"}
              for n, part in enumerate(own)]
    others = drawn[len(own):]
    if others or rest:
        groups.append({"label": EVERYTHING_ELSE, "cents": sum(part[key] for part in others) + rest,
                       "parts": others, "tone": "cother" if tones else "rest"})
    if len(groups) < 2:
        return None
    whole = sum(group["cents"] for group in groups)
    slices, start = [], 0.0
    for n, group in enumerate(groups):
        end = 1.0 if n == len(groups) - 1 else start + group["cents"] / whole
        share = round(group["cents"] / whole * 100)
        slices.append({"label": group["label"], "cents": group["cents"], "share": share, "tone": group["tone"],
                       "path": _arc(start, end), "title": f"{group['label']}: {dollars(group['cents'])} · {share}%"})
        for part in group["parts"]:
            part["slice"], part["tone"] = n, group["tone"]
        start = end
    return {"total": sum(part[key] for part in parts) + rest, "slices": slices,
            "words": ", ".join(f"{s['label']} {s['share']}%" for s in slices)}


def categories(spent: Spending) -> dict | None:
    """The category donut, in the year bars' colours and grouped as their key is: each coloured category a slice
    (Engine, Brakes, Tires and wheels, Steering and suspension), and Everything else the rest, naming them, the
    most spent first."""
    coloured = [row for label in COLOURED for row in spent.rows if row["label"] == label]
    rest = sorted((row for row in spent.rows if row["label"] not in COLOURED), key=lambda row: -row["total"])
    parts = [{"label": row["label"], "cents": row["total"], "tone": f"c{row['tone']}"} for row in coloured]
    if rest:
        parts.append({"label": EVERYTHING_ELSE, "cents": sum(row["total"] for row in rest), "tone": "cother",
                      "names": [row["label"] for row in rest if row["total"] > 0]})
    chart = donut(parts, tones=True)
    if chart:
        chart["parts"] = _shares(parts)
    return chart


def _arc(start: float, end: float) -> str:
    """The ring between two fractions of the way round, clockwise from the top, as an SVG path."""
    def at(fraction: float, radius: float) -> str:
        angle = 2 * math.pi * fraction
        return f"{50 + radius * math.sin(angle):.3f} {50 - radius * math.cos(angle):.3f}"

    if end - start >= 0.9999:      # all the way round: two halves, as one arc can't end where it starts
        return _arc(start, start + 0.5) + " " + _arc(start + 0.5, end)
    big = 1 if end - start > 0.5 else 0
    return (f"M{at(start, _OUTER)} A{_OUTER} {_OUTER} 0 {big} 1 {at(end, _OUTER)} "
            f"L{at(end, _INNER)} A{_INNER} {_INNER} 0 {big} 0 {at(start, _INNER)} Z")
