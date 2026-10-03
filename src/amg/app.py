"""The AMG web app.

    uvicorn amg.app:app --reload        # http://127.0.0.1:8000

Migrations run at startup, so a deploy that adds one needs nothing but a
restart. Every page sits behind the login guard (web/guard.py).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import PlainTextResponse, RedirectResponse, Response

from . import db
from .web import (guard, routes_auth, routes_backup, routes_design, routes_garage, routes_receipts, routes_schedules,
                  routes_services, routes_vehicles)
from .web.templating import STATIC_DIR, asset, render


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    conn = db.connect()
    try:
        db.migrate(conn)
    finally:
        conn.close()
    yield


app = FastAPI(title="AMG — Automobile Maintenance Genie", lifespan=lifespan, docs_url=None, redoc_url=None)
app.middleware("http")(guard.require_login)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.include_router(routes_auth.router)
app.include_router(routes_garage.router)
app.include_router(routes_vehicles.router)
app.include_router(routes_services.router)
app.include_router(routes_receipts.router)
app.include_router(routes_schedules.router)
app.include_router(routes_backup.router)
app.include_router(routes_design.router)


@app.exception_handler(StarletteHTTPException)
async def not_found(request: Request, exc: StarletteHTTPException) -> Response:
    if exc.status_code == 404 and not request.url.path.startswith("/static/"):
        return render(request, "not_found.html", status_code=404)
    return await http_exception_handler(request, exc)


@app.get("/healthz", include_in_schema=False)
def healthz() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> RedirectResponse:
    # Browsers probe this path whatever the <link rel="icon"> says.
    return RedirectResponse(asset("favicon.svg"))
