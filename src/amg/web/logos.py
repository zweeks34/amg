"""Which logo a station or shop gets, and fetching it the first time it's shown.

A name's logo comes from, the first that applies:

1. its letter, if you said so on Stations and shops;
2. the logo you uploaded for it;
3. the website you gave it;
4. the brand recognised in it (``brands.py``): the logo you uploaded for the
   brand, else the brand's website;
5. its letter.

A page never waits on the internet for one: it draws the letter, with the
picture over it (your upload, or the icon from ``/logos/<site>.png``, which
fetches a site's icon the first time it's asked for).
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from .. import db
from ..ingest import site_icons
from ..repo import logos as repo
from . import brands


@dataclass(frozen=True)
class Logo:
    name: str
    site: str | None            # where its icon comes from; None: its letter, or your upload
    brand: str | None           # the brand recognised in its name
    yours: bool                 # what you said about this name decides it: its website, its letter, its logo
    upload: tuple[int, str] | None = None    # your logo: its document's id and sha256
    upload_for: str | None = None            # "name": this one; "brand": every station or shop of its brand
    own_site: bool = False      # the website is one you gave this name

    @property
    def uploads_to(self) -> str:
        """Where a logo uploaded from this name goes: to its brand, unless you've made it a place of its own by
        giving it a website."""
        return "brand" if self.brand and not self.own_site else "name"


class Book:
    """The logos on one page: what you've said about places and brands, read once, when the first logo is asked
    for."""

    def __init__(self, conn: sqlite3.Connection | None = None) -> None:
        self._conn = conn
        self._places: dict[str, sqlite3.Row] | None = None
        self._brands: dict[str, sqlite3.Row] = {}

    def _load(self, conn: sqlite3.Connection) -> None:
        self._places, self._brands = repo.places(conn), repo.brand_logos(conn)

    @property
    def places(self) -> dict[str, sqlite3.Row]:
        if self._places is None:
            if self._conn is not None:
                self._load(self._conn)
            else:
                conn = db.connect()
                try:
                    self._load(conn)
                finally:
                    conn.close()
        return self._places  # type: ignore[return-value]

    @property
    def brands(self) -> dict[str, sqlite3.Row]:
        """Your logo for each brand you gave one."""
        self.places  # noqa: B018 -- read with the places
        return self._brands

    def __call__(self, name: str | None) -> Logo | None:
        name = " ".join((name or "").split())
        if not name:
            return None
        brand = brands.recognise(name)
        known = brand.name if brand else None
        place = self.places.get(name.lower())
        if place is not None and place["letter_only"]:
            return Logo(name, None, known, yours=True)
        if place is not None and place["logo_document_id"] and place["logo_sha256"]:
            return Logo(name, None, known, yours=True, upload=(place["logo_document_id"], place["logo_sha256"]),
                        upload_for="name", own_site=bool(place["website"]))
        if place is not None and place["website"]:
            return Logo(name, place["website"], known, yours=True, own_site=True)
        if brand and (mine := self.brands.get(brand.name)):
            return Logo(name, None, known, yours=False, upload=(mine["document_id"], mine["logo_sha256"]),
                        upload_for="brand")
        return Logo(name, brand.site if brand else None, known, yours=False)


_page: ContextVar[Book | None] = ContextVar("logos", default=None)


@contextmanager
def page() -> Iterator[None]:
    """While a page renders: one Book for all its logos."""
    token = _page.set(Book())
    try:
        yield
    finally:
        _page.reset(token)


def logo_for(name: str | None) -> Logo | None:
    """A template's way to a name's logo; None for no name."""
    return (_page.get() or Book())(name)


def known(conn: sqlite3.Connection, site: str) -> bool:
    """Whether a site is one AMG fetches: a recognised brand's, or one you gave."""
    return site in brands.SITES or conn.execute(
        "SELECT 1 FROM places WHERE website = ? LIMIT 1", (site,)).fetchone() is not None


_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()


def _lock(site: str) -> threading.Lock:
    with _locks_lock:
        return _locks.setdefault(site, threading.Lock())


def icon(conn: sqlite3.Connection, site: str, again: bool = False) -> sqlite3.Row | None:
    """A site's kept icon, fetched first if it's due (or ``again``). One fetch at a time for a site: a page showing
    a logo twenty times asks once."""
    with _lock(site):
        row = repo.icon(conn, site)
        if again or repo.due(row):
            found = site_icons.fetch(site)
            repo.keep(conn, site, found.png, found.source)
            row = repo.icon(conn, site)
        return row


def from_service(source: str) -> bool:
    """Whether an icon came from the icon service rather than the site itself."""
    return source.startswith(site_icons.SERVICE.split("{")[0])
