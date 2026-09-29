"""The AMG web app.

    uvicorn amg.app:app --reload        # http://127.0.0.1:8000

Migrations run at startup, so a deploy that adds one needs nothing but a
restart. Every page sits behind the login guard (web/guard.py).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import PlainTextResponse, RedirectResponse

from . import db
from .web import guard, routes_auth, routes_design, routes_garage
from .web.templating import STATIC_DIR, asset


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
app.include_router(routes_design.router)


@app.get("/healthz", include_in_schema=False)
def healthz() -> PlainTextResponse:
    return PlainTextResponse("ok")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> RedirectResponse:
    # Browsers probe this path whatever the <link rel="icon"> says.
    return RedirectResponse(asset("favicon.svg"))
