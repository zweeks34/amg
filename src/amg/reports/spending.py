"""The Spending report: what went on each category of work, year by year.

Each year's column adds up to what you actually paid. A line's amount goes
under its category (history.category says which); a visit's tax goes under
Tax; and whatever its printed total leaves over — shop supplies, a line nobody
tagged, a discount the invoice didn't itemise — goes under Other with the
untagged lines. A visit with no total counts its lines and tax.

Narrowed to a service, only the lines that did it count, so Tax and the
leftovers drop out.
"""

from __future__ import annotations

from dataclasses import dataclass

from .filters import Filters
from .history import OTHER, History, category

TAX = "Tax"


@dataclass
class Spending:
    years: list[int]        # oldest first, every year from the first visit to the last
    rows: list[dict]        # {"label", "cells": {year: cents}, "total"}, in catalogue order, then Other and Tax
    totals: dict[int, int]  # by year
    total: int


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
    rows = [{"label": label, "cells": cells[label], "total": sum(cells[label].values())} for label in labels]
    totals = {year: sum(row["cells"].get(year, 0) for row in rows) for year in span}
    return Spending(span, rows, totals, sum(totals.values()))
