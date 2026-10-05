"""Reports: the History, Spending and Fuel views, each one as a CSV, a car's sale packet, and your data.

Every report is a GET with its filters in the address bar (reports/filters.py),
so a report is a link you can keep, print, or download as it stands.
"""

from __future__ import annotations

import os
import re
import sqlite3
import tempfile
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.background import BackgroundTask
from starlette.responses import FileResponse, Response

from ..reports import csvs, export, fuel, history, packet, spending
from ..reports.filters import VIEWS, Filters, service_label, service_options, span_words
from ..repo import reports
from . import fuel_status
from .deps import get_conn
from .routes_vehicles import vehicle_or_404
from .templating import render

router = APIRouter()

TITLES = {"history": "Service history", "spending": "Spending by year", "fuel": "Fuel economy"}


@router.get("/reports")
def page(request: Request, view: str = "", car: str = "", start: str = Query("", alias="from"),
         end: str = Query("", alias="to"), service: str = "", shop: str = "",
         conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    filters, options = _filters(conn, view, car, start, end, service, shop)
    context: dict = {}
    if filters.view == "fuel":
        context["sections"] = fuel.load(conn, _cars_for(options["cars"], filters), filters)
        context["anything"] = reports.has_fills(conn)
        context.update(economy_words=fuel_status.economy_words, cents_a_mile=fuel_status.cents_a_mile,
                       price_words=fuel_status.price_words)
    else:
        found = history.load(conn, filters)
        context["history"] = found
        context["anything"] = reports.has_services(conn)
        if filters.view == "spending":
            context["spending"] = spending.table(found, filters, reports.categories(conn))
    return render(
        request,
        "reports.html",
        active="reports",
        filters=filters,
        options=options,
        views={**VIEWS, "fuel": _fuel_word(options["cars"])},
        title=TITLES[filters.view] if filters.view != "fuel" else f"{_fuel_word(options['cars'])} economy",
        heading=_heading(filters, options, date.today()),
        car=next((c for c in options["cars"] if c["id"] == filters.car), None),
        service_words=service_label(filters.service, _names(options)) if filters.service else "",
        span_words=span_words,
        **context,
    )


@router.get("/reports/{view}.csv")
def download(view: str, car: str = "", start: str = Query("", alias="from"), end: str = Query("", alias="to"),
             service: str = "", shop: str = "", conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    if view not in VIEWS:
        raise HTTPException(status_code=404)
    filters, options = _filters(conn, view, car, start, end, service, shop)
    if view == "fuel":
        text = csvs.fuel_csv(fuel.load(conn, _cars_for(options["cars"], filters), filters))
    else:
        found = history.load(conn, filters)
        text = (csvs.history_csv(found, filters) if view == "history"
                else csvs.spending_csv(spending.table(found, filters, reports.categories(conn))))
    car_name = next((c["name"] for c in options["cars"] if c["id"] == filters.car), "all cars")
    name = f"amg-{view}-{slug(car_name)}-{date.today().isoformat()}.csv"
    return Response(text, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/vehicles/{vehicle_id}/sale-packet.pdf")
def sale_packet(vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    """A car's whole history and every confirmed receipt, as one PDF. Built in the system temp directory and
    deleted once sent, like a backup download: it's the size of the car's scans."""
    car = vehicle_or_404(conn, vehicle_id)
    handle, name = tempfile.mkstemp(prefix="amg-packet-", suffix=".pdf")
    os.close(handle)
    path = Path(name)
    try:
        packet.write(conn, car, path)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return FileResponse(path, media_type="application/pdf",
                        filename=f"{slug(packet.title(car))}-service-history-{date.today().isoformat()}.pdf",
                        background=BackgroundTask(path.unlink, missing_ok=True))


@router.get("/reports/your-data.zip")
def your_data(conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    """Everything, as spreadsheets and the uploaded files. Temp file, deleted once sent, like the packet."""
    handle, name = tempfile.mkstemp(prefix="amg-data-", suffix=".zip")
    os.close(handle)
    path = Path(name)
    try:
        export.write(conn, path)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return FileResponse(path, media_type="application/zip", filename=export.filename(),
                        background=BackgroundTask(path.unlink, missing_ok=True))


def slug(text: str) -> str:
    """A name for a file name: "Mom's Outback" → "mom-s-outback"."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "car"


# ---------- Helpers ----------


def _filters(conn: sqlite3.Connection, view: str, car: str, start: str, end: str, service: str,
             shop: str) -> tuple[Filters, dict]:
    cars = [{**c, "label": c["name"] + (" (archived)" if c["archived_at"] else "")} for c in reports.cars(conn)]
    groups = service_options(reports.used_types(conn), reports.categories(conn))
    options = {"cars": cars, "services": groups, "shops": reports.shops(conn)}
    offered = [option["value"] for group in groups for option in group["options"]]
    filters = Filters.read(view, car, start, end, service, shop).within([c["id"] for c in cars], offered)
    return filters, options


def _names(options: dict) -> dict[str, str]:
    """Each service on offer by its value: a type's code → its name."""
    return {o["value"]: o["label"] for group in options["services"] for o in group["options"]}


def _cars_for(cars: list[dict], filters: Filters) -> list[dict]:
    return [c for c in cars if c["id"] == filters.car] if filters.car else cars


def _fuel_word(cars: list[dict]) -> str:
    """Charging when every car is electric; otherwise Fuel."""
    return "Charging" if cars and all(c["powertrain"] == "ev" for c in cars) else "Fuel"


def _heading(filters: Filters, options: dict, today: date) -> str:
    """What a printed report is, at its top: "Service history · Outback · Brakes · Jan 2019 – Oct 2026 · …"."""
    view = TITLES[filters.view] if filters.view != "fuel" else f"{_fuel_word(options['cars'])} economy"
    car = next((c["name"] for c in options["cars"] if c["id"] == filters.car), "All cars")
    parts = [view, car]
    if filters.uses_service and filters.service:
        parts.append(filters.category or _names(options)[filters.service])
    if filters.uses_service and filters.shop:
        parts.append(f"at “{filters.shop}”")
    if span := span_words(filters.start, filters.end):
        parts.append(span)
    parts.append(f"printed {today:%b} {today.day}, {today.year}")
    return " · ".join(parts)
