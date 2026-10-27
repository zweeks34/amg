"""Logos: what you've said about each station and shop, and the website icons AMG has fetched.

A station or shop is known by its name, whatever its capitals. Most need
nothing here: the brand in the name says where the logo comes from
(``web/brands.py``). A row in ``places`` is you putting one right: its own
website, or its letter instead.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from ..db import now_iso

# A site where no icon was found is asked again after this long: sites change.
RETRY_AFTER = timedelta(days=30)


# ---------- What you've said ----------


def places(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    """Every station and shop you've put right, by its name in lowercase."""
    return {row["name"].lower(): row for row in conn.execute("SELECT * FROM places ORDER BY name COLLATE NOCASE")}


def set_place(conn: sqlite3.Connection, name: str, website: str = "", letter_only: bool = False) -> None:
    """A station's or shop's own website, or its letter instead. Neither puts it back as recognised."""
    if not website and not letter_only:
        conn.execute("DELETE FROM places WHERE name = ?", (name,))
        return
    conn.execute(
        "INSERT INTO places (name, website, letter_only, updated_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (name) DO UPDATE SET website = excluded.website, letter_only = excluded.letter_only,"
        " updated_at = excluded.updated_at",
        (name, website, int(letter_only), now_iso()),
    )


def visited(conn: sqlite3.Connection) -> tuple[list[sqlite3.Row], list[sqlite3.Row]]:
    """The stations on your fill-ups and charges and the shops on your confirmed services: each once whatever its
    capitals, as it was last written, with how many times (and of those, how many were charges) and when last; most
    visited first."""
    stations = conn.execute(
        "SELECT station AS name, count(*) AS visits, sum(energy = 'electric') AS charges, max(filled_on) AS last"
        " FROM fuel_logs WHERE station <> ''"
        " GROUP BY station COLLATE NOCASE ORDER BY visits DESC, last DESC"
    ).fetchall()
    shops = conn.execute(
        "SELECT trim(shop) AS name, count(*) AS visits, max(performed_on) AS last FROM service_events"
        " WHERE confirmed = 1 AND trim(shop) <> '' GROUP BY trim(shop) COLLATE NOCASE ORDER BY visits DESC, last DESC"
    ).fetchall()
    return stations, shops


# ---------- Fetched icons ----------


def icon(conn: sqlite3.Connection, site: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM site_icons WHERE site = ?", (site,)).fetchone()


def icons(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    """What's known of every site fetched, by site; without the pictures."""
    return {row["site"]: row for row in conn.execute(
        "SELECT site, png IS NOT NULL AS found, source, fetched_at FROM site_icons")}


def keep(conn: sqlite3.Connection, site: str, png: bytes | None, source: str = "") -> None:
    """What fetching a site's icon found, or that it found nothing."""
    conn.execute(
        "INSERT INTO site_icons (site, png, source, fetched_at) VALUES (?, ?, ?, ?)"
        " ON CONFLICT (site) DO UPDATE SET png = excluded.png, source = excluded.source,"
        " fetched_at = excluded.fetched_at",
        (site, png, source, now_iso()),
    )


def forget(conn: sqlite3.Connection, site: str) -> None:
    """So the next page that shows it fetches it again."""
    conn.execute("DELETE FROM site_icons WHERE site = ?", (site,))


def due(row: sqlite3.Row | None, now: datetime | None = None) -> bool:
    """Whether a site's icon should be fetched: never tried, or nothing found more than RETRY_AFTER ago."""
    if row is None:
        return True
    if row["png"] is not None:
        return False
    fetched = datetime.strptime(row["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - fetched > RETRY_AFTER
