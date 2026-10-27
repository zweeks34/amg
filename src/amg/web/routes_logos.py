"""Logos: each website's icon, and Stations and shops, where you see and put right where each one's comes from:
its website, its letter instead, or a logo you upload."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from starlette.datastructures import UploadFile
from starlette.responses import RedirectResponse, Response

from ..ingest import site_icons
from ..repo import documents
from ..repo import logos as repo
from . import forms, logos
from .deps import get_conn
from .issues import PHOTO_TYPES
from .templating import render

router = APIRouter()

ADD = "add"       # the Add a station or shop form's key, for its errors and what was typed


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
def places_page(request: Request, saved: str = "", added: str = "", fetched: str = "",
                conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    return _page(request, conn, saved=saved, added=added, fetched=fetched)


@router.post("/places")
async def save_place(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    """One station's or shop's Change: its website, its letter instead, a logo picked, or yours removed."""
    form = await request.form()
    name = " ".join(forms.text(form.get("name")).split())
    if not name:
        return RedirectResponse("/places", status_code=303)
    problem = await _save(conn, name, form)
    if problem:
        key = name.lower()
        return _page(request, conn, errors={key: problem}, typed={key: forms.text(form.get("website"))},
                     status_code=422)
    return RedirectResponse(f"/places?saved={quote(name)}", status_code=303)


@router.post("/places/add")
async def add_place(request: Request, conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    """A station or shop set up before your first visit: its name, and a logo or its website."""
    form = await request.form()
    name = " ".join(forms.text(form.get("name")).split())
    typed = {ADD: {"name": name, "website": forms.text(form.get("website"))}}
    if not name:
        problem = "Name the station or shop, as you'll write it on a fill-up or receipt."
    elif not forms.text(form.get("website")) and not _picked_file(form):
        problem = "Give it a logo, or its website."
    else:
        problem = await _save(conn, name, form)
    if problem:
        return _page(request, conn, errors={ADD: problem}, typed=typed, status_code=422)
    repo.add(conn, name)
    return RedirectResponse(f"/places?added={quote(name)}", status_code=303)


@router.post("/places/fetch")
def fetch_again(site: str = Form(...), conn: sqlite3.Connection = Depends(get_conn)) -> Response:
    if site_icons.SITE.fullmatch(site) and logos.known(conn, site):
        logos.icon(conn, site, again=True)
    return RedirectResponse(f"/places?fetched={quote(site)}", status_code=303)


# ---------- Saving ----------


def _picked_file(form) -> UploadFile | None:
    upload = form.get("logo_file")
    return upload if isinstance(upload, UploadFile) and upload.filename else None


async def _save(conn: sqlite3.Connection, name: str, form) -> str:
    """What a form says about one name, saved; or what's wrong, with nothing saved."""
    website = forms.text(form.get("website"))
    site = site_icons.site_of(website)
    if website and site is None:
        return "Type its website as you'd find it, like joesgarage.com."
    picked = None
    if upload := _picked_file(form):
        filename = Path(upload.filename).name
        if Path(filename).suffix.lower() not in PHOTO_TYPES:
            return f"{filename}: add the logo as PNG, JPG or GIF."
        try:
            picked, _ = documents.store(conn, await upload.read(), filename)
        except documents.UploadError as err:
            return str(err)
    before = logos.Book(conn)(name)
    letter_only = form.get("letter_only") == "1" and picked is None      # a logo just picked is to be seen
    repo.set_place(conn, name, site or "", letter_only)
    if form.get("remove_logo") == "1" and before.upload_for:
        _set_logo(conn, before, before.upload_for, None)
    if picked is not None:
        after = logos.Book(conn)(name)                                   # with the website just given, if any
        _set_logo(conn, after, after.uploads_to, picked["id"])
    elif site and not letter_only:
        logos.icon(conn, site)
    return ""


def _set_logo(conn: sqlite3.Connection, logo: logos.Logo, upload_for: str, document_id: int | None) -> None:
    if upload_for == "brand":
        repo.set_brand_logo(conn, logo.brand, document_id)  # type: ignore[arg-type]
    else:
        repo.set_logo(conn, logo.name, document_id)


# ---------- The page ----------


def _page(request: Request, conn: sqlite3.Connection, saved: str = "", added: str = "", fetched: str = "",
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
        stations=[_row(book, kept, row["name"], "station", _visits(row, "station"), row["last"]) for row in stations],
        shops=[_row(book, kept, row["name"], "shop", _visits(row, "shop"), row["last"]) for row in shops],
        not_visited=[_row(book, kept, row["name"], "new", "", None) for row in repo.not_visited(conn)],
        saved=saved,
        added=added,
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


def _row(book: logos.Book, kept: dict, name: str, kind: str, visits: str, last: str | None) -> dict:
    logo = book(name)
    place = book.places.get(logo.name.lower())
    icon = kept.get(logo.site) if logo.site else None
    return {
        "name": logo.name,
        "key": logo.name.lower(),
        "kind": kind,
        "visits": visits,
        "last": last,
        "logo": logo,
        "website": place["website"] if place else "",
        "letter_only": bool(place and place["letter_only"]),
        "said": _said(logo, icon),
        "upload_hint": f"For every {logo.brand} station or shop" if logo.uploads_to == "brand" else f"For {logo.name}",
    }


def _said(logo: logos.Logo, icon: sqlite3.Row | None) -> str:
    """Where a logo comes from, in a sentence."""
    known = f"Recognised as {logo.brand}. " if logo.brand and not logo.yours else ""
    if logo.upload_for == "brand":
        return f"{known}Your logo, for every {logo.brand}."
    if logo.upload_for == "name":
        return "Your logo."
    if logo.site is None:
        if logo.yours:
            return "Shows its letter, as you asked."
        return "Not recognised. Give it a logo or its website."
    if icon is None:
        return f"{known}Its logo comes from {logo.site}, fetched the first time it's shown."
    if icon["found"]:
        via = ", by way of DuckDuckGo's icon service" if logos.from_service(icon["source"]) else ""
        return f"{known}Logo from {logo.site}{via}."
    tried = datetime.strptime(icon["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).astimezone()
    return (f"{known}No icon found for {logo.site} on {tried:%Y-%m-%d}; its letter shows. "
            "Give it a logo, or it's tried again after 30 days.")
