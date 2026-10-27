"""Logos: each website's icon, and Stations and shops, where you see and put right where each one's comes from."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from starlette.responses import RedirectResponse, Response

from ..ingest import site_icons
from ..repo import logos as repo
from . import logos
from .deps import get_conn
from .templating import render

router = APIRouter()


@router.get("/logos/{site}.png")
def site_icon(request: Request, site: str, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    """A site's icon; fetched the first time it's asked for. Only a recognised brand's site, or one you gave."""
    if not site_icons.SITE.fullmatch(site) or not logos.known(conn, site):
        return Response(status_code=404)
    row = logos.icon(conn, site)
    if row is None or row["png"] is None:
        return Response(status_code=404)
    # Asked again every time, answered "not changed" while it hasn't: Fetch again shows at once.
    tag = '"' + hashlib.sha256(row["png"]).hexdigest()[:16] + '"'
    headers = {"ETag": tag, "Cache-Control": "private, no-cache"}
    if request.headers.get("if-none-match") == tag:
        return Response(status_code=304, headers=headers)
    return Response(row["png"], media_type="image/png", headers=headers)


@router.get("/places")
def places_page(request: Request, saved: str = "", fetched: str = "",
                conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    return _page(request, conn, saved=saved, fetched=fetched)


@router.post("/places")
def save_place(request: Request, name: str = Form(...), website: str = Form(""), letter_only: str = Form(""),
               conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    name = " ".join(name.split())
    site = site_icons.site_of(website)
    if website.strip() and site is None:
        return _page(request, conn, errors={name.lower(): "Type its website as you'd find it, like joesgarage.com."},
                     typed={name.lower(): website}, status_code=422)
    repo.set_place(conn, name, site or "", letter_only == "1")
    if site and letter_only != "1":
        logos.icon(conn, site)
    return RedirectResponse(f"/places?saved={quote(name)}", status_code=303)


@router.post("/places/fetch")
def fetch_again(site: str = Form(...), conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    if site_icons.SITE.fullmatch(site) and logos.known(conn, site):
        logos.icon(conn, site, again=True)
    return RedirectResponse(f"/places?fetched={quote(site)}", status_code=303)


def _page(request: Request, conn: sqlite3.Connection, saved: str = "", fetched: str = "",
          errors: dict | None = None, typed: dict | None = None, status_code: int = 200) -> Response:
    stations, shops = repo.visited(conn)
    book = logos.Book(conn)
    kept = repo.icons(conn)
    found = kept.get(fetched) if fetched else None
    return render(
        request,
        "places.html",
        status_code=status_code,
        active="places",
        stations=[_row(book, kept, row, "station") for row in stations],
        shops=[_row(book, kept, row, "shop") for row in shops],
        saved=saved,
        fetched=fetched,
        fetched_found=bool(found and found["found"]),
        errors=errors or {},
        typed=typed or {},
    )


def _count(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def _visits(row: sqlite3.Row, kind: str) -> str:
    """'3 fill-ups', '2 charges', '3 fill-ups and 1 charge', '1 service'."""
    if kind == "shop":
        return _count(row["visits"], "service")
    fills, charges = row["visits"] - row["charges"], row["charges"]
    return " and ".join(_count(n, word) for n, word in ((fills, "fill-up"), (charges, "charge")) if n)


def _row(book: logos.Book, kept: dict, row: sqlite3.Row, kind: str) -> dict:
    logo = book(row["name"])
    place = book.places.get(logo.name.lower())
    icon = kept.get(logo.site) if logo.site else None
    return {
        "name": logo.name,
        "key": logo.name.lower(),
        "kind": kind,
        "visits": _visits(row, kind),
        "last": row["last"],
        "logo": logo,
        "website": place["website"] if place else "",
        "letter_only": bool(place and place["letter_only"]),
        "said": _said(logo, icon),
    }


def _said(logo: logos.Logo, icon: sqlite3.Row | None) -> str:
    """Where a logo comes from, in a sentence."""
    known = f"Recognised as {logo.brand}. " if logo.brand and not logo.yours else ""
    if logo.site is None:
        if logo.yours:
            return "Shows its letter, as you asked."
        return "Not recognised. Give its website to show its logo."
    if icon is None:
        return f"{known}Its logo comes from {logo.site}, fetched the first time it's shown."
    if icon["found"]:
        via = ", by way of DuckDuckGo's icon service" if logos.from_service(icon["source"]) else ""
        return f"{known}Logo from {logo.site}{via}."
    tried = datetime.strptime(icon["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone()
    return (f"{known}No icon found for {logo.site} on {tried:%Y-%m-%d}; its letter shows. "
            "It's tried again after 30 days.")
