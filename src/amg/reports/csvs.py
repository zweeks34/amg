"""Reports as CSV: what each view shows, for a spreadsheet.

UTF-8 with a byte-order mark, so Excel reads "°" and "é" as written (Google
Sheets doesn't mind it). Amounts are plain numbers — 1234.50, -12.00 — so a
spreadsheet adds them up; dates are ISO. A text cell that starts with = + - @
gets a leading apostrophe: a spreadsheet would otherwise take a line read as
"-Oil filter" for a formula and show #NAME?.
"""

from __future__ import annotations

import csv
import io

from .filters import Filters
from .fuel import Section
from .history import History, category
from .spending import Spending

BOM = "﻿"
SOURCES = {"shop": "Shop", "receipt": "Receipt", "diy": "Your own work", "attested": "Done, no receipt"}
HISTORY_COLUMNS = ("Car", "Date", "Odometer", "Where", "Invoice", "Source", "Line", "Kind", "Part number", "Quantity",
                   "Amount", "Services", "Category", "Visit total", "Visit tax", "Notes", "Visit #")
FUEL_COLUMNS = ("Car", "Month", "Fill-ups", "Miles", "Quantity", "Unit", "Economy", "Economy unit", "Cents a mile",
                "Spent", "Price per unit")
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


def text(value) -> str:
    value = "" if value is None else str(value)
    return "'" + value if value.startswith(_FORMULA) else value


def amount(cents: int | None) -> str:
    """Cents as dollars, exactly: 123450 → 1234.50, -1200 → -12.00."""
    if cents is None:
        return ""
    whole, part = divmod(abs(cents), 100)
    return f"{'-' if cents < 0 else ''}{whole}.{part:02d}"


def number(value: float | int | None, places: int | None = None) -> str:
    if value is None:
        return ""
    if places is not None:
        return f"{value:.{places}f}"
    return f"{value:f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)


def services(line: dict) -> str:
    return "; ".join(cover["name"] + (" (inspected)" if cover["action"] == "inspect" else "") for cover in line["covers"])


def history_csv(history: History, filters: Filters) -> str:
    """One row a line, with its visit's columns on every row; a visit with no lines gets a row of its own."""
    rows = []
    for visit in history.visits:
        head = [text(visit["car_name"]), visit["performed_on"], number(visit["odometer"]), text(visit["who"]),
                text(visit["invoice_number"]), SOURCES.get(visit["source"], visit["source"])]
        tail = [amount(visit["total_cents"]), amount(visit["tax_cents"]), text(visit["notes"]), str(visit["id"])]
        if not visit["shown"]:
            rows.append(head + [""] * 7 + tail)
        for line in visit["shown"]:
            rows.append(head + [
                text(line["description"]), line["kind"].capitalize(), text(line["part_number"]),
                number(line["quantity"]), amount(line["amount_cents"]), text(services(line)),
                category(line, filters) if line["covers"] else "",
            ] + tail)
    return sheet(HISTORY_COLUMNS, rows)


def spending_csv(spending: Spending | None) -> str:
    """The table as shown: categories down, years across, totals last."""
    if spending is None:
        return sheet(("Category", "Total"), [])
    rows = [[text(row["label"])] + [amount(row["cells"].get(year)) for year in spending.years] + [amount(row["total"])]
            for row in spending.rows]
    rows.append(["Total"] + [amount(spending.totals[year]) for year in spending.years] + [amount(spending.total)])
    return sheet(["Category"] + [str(year) for year in spending.years] + ["Total"], rows)


def fuel_csv(sections: list[Section]) -> str:
    """Each car's months, newest first. Price per unit is dollars a gallon or kWh."""
    rows = []
    for section in sections:
        units = section.units
        places = 1 if units.quantity == "gal" else 2
        for month in section.months:
            rows.append([
                text(section.car["name"]), month.month, str(month.fills), number(month.miles or None),
                number(month.quantity or None, 3), units.quantity, number(month.economy, places), units.economy,
                number(month.cost_per_mile, 1), amount(month.spent),
                number(month.unit_price / 100 if month.unit_price is not None else None, 3),
            ])
    return sheet(FUEL_COLUMNS, rows)


def sheet(header, rows) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(header)
    writer.writerows(rows)
    return BOM + out.getvalue()
