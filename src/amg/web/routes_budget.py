"""The budget: what's coming and what it will cost, for one car and for the garage.

Prices are set here too. A price you type beats everything AMG works out;
removing it brings AMG's estimate back. Jobs nothing can price can be priced
by Claude, in the background, the page watching until it's done.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Request
from starlette.responses import RedirectResponse, Response

from ..ingest import background
from ..repo import prices, vehicles
from . import budget, forms
from .deps import get_conn
from .routes_vehicles import vehicle_or_404
from .templating import render

router = APIRouter()

MOST_CENTS = 5_000_000   # $50,000: more than any one maintenance job


@router.get("/budget")
def garage_budget(request: Request, months: int | None = None, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    count = budget.horizon(months)
    active, _ = vehicles.garage(conn)
    plans = budget.garage(conn, active, count)
    per_car = [
        {"car": plan.car, "maintenance": plan.maintenance, "fuel": plan.fuel, "per_month": plan.per_month,
         "unpriced": plan.unpriced, "fuel_word": plan.units.title}
        for plan in plans
    ]
    return render(
        request,
        "budget.html",
        active="garage",
        count=count,
        horizons=budget.HORIZONS,
        plans=plans,
        strip=budget.strip(plans),
        per_car=per_car,
        months=budget.combined(plans),
        chart=budget.chart(budget.combined_months(plans), sum(p.per_month for p in plans), count) if plans else None,
        fuel_word=budget.fuel_word([p.units for p in plans]),
    )


@router.get("/vehicles/{vehicle_id}/budget")
def car_budget(request: Request, vehicle_id: int, months: int | None = None,
               conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    return _page(request, conn, car, budget.horizon(months))


@router.post("/vehicles/{vehicle_id}/prices")
async def set_price(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    form = await request.form()
    raw = {key: forms.text(form.get(key)) for key in ("codes", "action", "name", "price", "months", "do")}
    count = budget.horizon(raw["months"])
    codes = [code for code in raw["codes"].split(",") if code]
    if raw["do"] == "remove":
        prices.remove_yours(conn, vehicle_id, codes, raw["action"])
        return _back(vehicle_id, count)
    key = f"{raw['codes']}|{raw['action']}"
    try:
        cents = forms.money(raw["price"])
    except ValueError as err:
        return _page(request, conn, car, count, errors={key: str(err)}, raw=raw, status_code=422)
    if cents is None:
        return _page(request, conn, car, count, errors={key: "Enter what one visit costs, like 89.99."}, raw=raw,
                     status_code=422)
    if cents < 0:
        return _page(request, conn, car, count, errors={key: "A price can't be below zero."}, raw=raw, status_code=422)
    if cents > MOST_CENTS:
        return _page(request, conn, car, count, errors={key: "That's more than any one job costs. Check for an extra digit."},
                     raw=raw, status_code=422)
    try:
        prices.set_yours(conn, vehicle_id, codes, raw["action"], raw["name"] or "This job", cents)
    except ValueError as err:
        return _page(request, conn, car, count, errors={key: str(err)}, raw=raw, status_code=422)
    return _back(vehicle_id, count)


@router.post("/vehicles/{vehicle_id}/prices/ask")
async def ask_claude(request: Request, vehicle_id: int, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    car = vehicle_or_404(conn, vehicle_id)
    form = await request.form()
    count = budget.horizon(form.get("months"))
    wanted = budget.load(conn, car, count).to_ask
    if wanted:
        background.price(conn, vehicle_id, [(job["codes"].split(","), job["action"], job["name"]) for job in wanted])
    return _back(vehicle_id, count)


# ---------- Helpers ----------


def _back(vehicle_id: int, count: int) -> Response:
    months = "" if count == 12 else f"?months={count}"
    return RedirectResponse(f"/vehicles/{vehicle_id}/budget{months}#prices", status_code=303)


def _page(request: Request, conn: sqlite3.Connection, car, count: int, errors: dict | None = None,
          raw: dict | None = None, status_code: int = 200) -> Response:
    plan = budget.load(conn, car, count)
    names = vehicles.names(conn)
    return render(
        request,
        "car_budget.html",
        status_code=status_code,
        active="garage",
        car=car,
        plan=plan,
        count=count,
        horizons=budget.HORIZONS,
        months=budget.month_rows(plan, names),
        prices=budget.price_rows(plan, names),
        chart=budget.chart(plan.months, plan.per_month, count),
        fuel_words=budget.fuel_words(plan),
        errors=errors or {},
        raw=raw or {},
    )
