"""Download your data: everything AMG holds about your cars, as spreadsheets and the files you uploaded.

A copy to read and keep, not a backup — nothing in it goes back into AMG (the
Back up page's zip does that). It holds:

    README.txt            what's here
    cars.csv              every car, archived ones included
    service-history.csv   the History report's CSV for every car: a row a line
    fuel.csv              every fill-up and charge
    odometer.csv          every reading, and where it came from
    schedules.csv         each car's maintenance schedule
    prices.csv            the prices the budget uses: yours, and Claude's estimates
    receipts/             every confirmed receipt as uploaded, named by date, shop and car
    manuals/              the files a schedule in use was read from

Receipts still waiting to be checked, and ones you discarded, aren't in it:
they're in nobody's history yet.
"""

from __future__ import annotations

import re
import sqlite3
import zipfile
from datetime import date
from pathlib import Path

from ..repo import documents, reports, schedules, services
from . import csvs, history
from .filters import Filters

POINT_SOURCES = {"manual": "Typed in", "service": "A service", "fill": "A fill-up", "charge": "A charge",
                 "acquired": "When you got it"}
APPLIES = {"always": "Normal and severe", "normal": "Normal only", "severe": "Severe only"}
ITEM_SOURCES = {"manual": "Owner's manual", "claude": "Claude's draft", "template": "AMG's template", "you": "You"}
PRICE_SOURCES = {"you": "You", "claude": "Claude's estimate"}
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def filename(today: date | None = None) -> str:
    return f"amg-your-data-{(today or date.today()).isoformat()}.zip"


def write(conn: sqlite3.Connection, path: Path, today: date | None = None) -> list[str]:
    """Write the zip to ``path``; returns the files the database lists that weren't on disk to put in it."""
    today = today or date.today()
    names = {row["code"]: row["name"] for row in services.list_types(conn)}
    sheets = {
        "cars.csv": _cars(conn),
        "service-history.csv": csvs.history_csv(history.load(conn, Filters()), Filters()),
        "fuel.csv": _fuel(conn),
        "odometer.csv": _odometer(conn),
        "schedules.csv": _schedules(conn),
        "prices.csv": _prices(conn, names),
    }
    missing: list[str] = []
    taken: set[str] = set()
    with zipfile.ZipFile(path, "w") as zf:
        for name, text in sheets.items():
            zf.writestr(name, text, compress_type=zipfile.ZIP_DEFLATED)
        receipts = reports.receipt_downloads(conn)
        manuals = reports.manuals(conn)
        for folder, rows, stem in (("receipts", receipts, _receipt_name), ("manuals", manuals, _manual_name)):
            for row in rows:
                source = documents.path(row)
                if not source.is_file():
                    missing.append(row["filename"])
                    continue
                # Scans are compressed already; storing them as-is is as small and much faster.
                zf.write(source, _unique(f"{folder}/{stem(row)}", source.suffix, taken), compress_type=zipfile.ZIP_STORED)
        zf.writestr("README.txt", _readme(conn, today, len(receipts), len(manuals), missing),
                    compress_type=zipfile.ZIP_DEFLATED)
    return missing


def safe(text: str) -> str:
    """Text a file name can hold on Windows, macOS and Linux alike."""
    return " ".join(_UNSAFE.sub(" ", text).split()).strip(" .")[:100]


# ---------- Sheets ----------


def _cars(conn: sqlite3.Connection) -> str:
    columns = ("Name", "Year", "Make", "Model", "Trim", "Engine", "Powertrain", "VIN", "Plate", "In service since",
               "Acquired", "Miles when acquired", "Severe service", "Alerts", "Archived", "Notes")
    rows = [[csvs.text(car["name"]), csvs.number(car["year"]), csvs.text(car["make"]), csvs.text(car["model"]),
             csvs.text(car["trim"]), csvs.text(car["engine"]), {"ev": "EV"}.get(car["powertrain"], car["powertrain"].title()),
             csvs.text(car["vin"]), csvs.text(car["plate"]), car["in_service_date"] or "", car["acquired_date"] or "",
             csvs.number(car["acquired_miles"]), _yes(car["severe_service"]), _yes(car["alerts"]),
             (car["archived_at"] or "")[:10], csvs.text(car["notes"])]
            for car in reports.cars(conn)]
    return csvs.sheet(columns, rows)


def _fuel(conn: sqlite3.Connection) -> str:
    columns = ("Car", "Date", "Odometer", "Energy", "Quantity", "Unit", "Cost", "Full", "Missed one before", "Place",
               "Note")
    rows = [[csvs.text(fill["car_name"]), fill["filled_on"], str(fill["odometer"]), fill["energy"].title(),
             csvs.number(fill["quantity"]), "kWh" if fill["energy"] == "electric" else "gal",
             csvs.amount(fill["cost_cents"]), _yes(fill["full"]), _yes(fill["missed_before"]),
             (fill["place"] or "").title(), csvs.text(fill["note"])]
            for fill in reports.fills(conn)]
    return csvs.sheet(columns, rows)


def _odometer(conn: sqlite3.Connection) -> str:
    rows = [[csvs.text(point["car_name"]), point["read_on"], str(point["miles"]),
             POINT_SOURCES.get(point["source"], point["source"])]
            for point in reports.odometer_points(conn)]
    return csvs.sheet(("Car", "Date", "Miles", "From"), rows)


def _schedules(conn: sqlite3.Connection) -> str:
    columns = ("Car", "Item", "Action", "Every miles", "Every months", "First at miles", "First at months", "Applies",
               "Services", "From", "Page", "Note")
    rows = []
    for car in reports.cars(conn):
        for item in schedules.items(conn, car["id"]):
            rows.append([csvs.text(car["name"]), csvs.text(item["name"]), item["action"].title(),
                         csvs.number(item["interval_miles"]), csvs.number(item["interval_months"]),
                         csvs.number(item["first_miles"]), csvs.number(item["first_months"]),
                         APPLIES.get(item["applies"], item["applies"]), "; ".join(item["type_names"]),
                         ITEM_SOURCES.get(item["source"], item["source"]), csvs.number(item["page"]),
                         csvs.text(item["note"])])
    return csvs.sheet(columns, rows)


def _prices(conn: sqlite3.Connection, names: dict[str, str]) -> str:
    columns = ("Car", "Job", "Services", "Action", "From", "Low", "High", "Note")
    rows = [[csvs.text(price["car_name"]), csvs.text(price["name"]),
             "; ".join(names.get(code, code) for code in price["codes"].split(",")), price["action"].title(),
             PRICE_SOURCES.get(price["source"], price["source"]), csvs.amount(price["low_cents"]),
             csvs.amount(price["high_cents"]), csvs.text(price["note"])]
            for price in reports.prices(conn)]
    return csvs.sheet(columns, rows)


# ---------- Files ----------


def _receipt_name(row) -> str:
    return safe(f"{row['performed_on']} {row['shop'] or 'Receipt'} - {row['car_name']}") or "receipt"


def _manual_name(row) -> str:
    return safe(Path(row["filename"]).stem) or "manual"


def _unique(stem: str, suffix: str, taken: set[str]) -> str:
    """The name, or the name with (2), (3) … when an earlier file has it. Case doesn't tell names apart on Windows."""
    name, n = f"{stem}{suffix}", 2
    while name.lower() in taken:
        name, n = f"{stem} ({n}){suffix}", n + 1
    taken.add(name.lower())
    return name


def _yes(value) -> str:
    return "Yes" if value else "No"


def _readme(conn: sqlite3.Connection, today: date, receipts: int, manuals: int, missing: list[str]) -> str:
    cars = len(reports.cars(conn))
    missing_note = (f"\n{len(missing)} file(s) the database lists weren't on the server when this was made, so\n"
                    "they aren't in here either.\n" if missing else "")
    return f"""Your data from AMG
==================

Made {today:%B} {today.day}, {today.year}: {cars} car(s), {receipts} receipt(s), {manuals} manual(s).

Spreadsheets (CSV, UTF-8; amounts in dollars, dates as YYYY-MM-DD):

  cars.csv              every car, archived ones included
  service-history.csv   every confirmed service, a row for each line on it;
                        Visit # tells the rows of one service apart
  fuel.csv              every fill-up and charge
  odometer.csv          every odometer reading, and where it came from
  schedules.csv         each car's maintenance schedule
  prices.csv            the prices the budget uses: yours, and Claude's estimates

Files, as you uploaded them:

  receipts/             every confirmed receipt, named by date, shop and car
  manuals/              the owner's manuals schedules were read from

Receipts still waiting to be checked, and ones you discarded, aren't here.
{missing_note}
This is a copy to read and keep. It can't be put back into AMG: for that,
use Back up, whose zip holds the database itself.
"""
