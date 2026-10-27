"""Logos: what you've said about each station and shop, and the website icons AMG has fetched.

A station or shop is known by its name, whatever its capitals. Most need
nothing here: the brand in the name says where the logo comes from
(``web/brands.py``). A row in ``places`` is you putting one right: its own
website, its letter instead, or a logo you uploaded; or one you added before
visiting it. A logo you uploaded for a brand is in ``brand_logos``.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from ..db import now_iso

# A site where no icon was found is asked again after this long: sites change.
RETRY_AFTER = timedelta(days=30)


# ---------- What you've said ----------


def places(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    """Every station and shop you've put right or added, by its name in lowercase; with its logo's fingerprint."""
    return {row["name"].lower(): row for row in conn.execute(
        "SELECT p.*, d.sha256 AS logo_sha256 FROM places p LEFT JOIN documents d ON d.id = p.logo_document_id"
        " ORDER BY p.name COLLATE NOCASE")}


def _tidy(conn: sqlite3.Connection, name: str) -> None:
    """A place with nothing said about it is as good as none: it goes back to as recognised."""
    conn.execute("DELETE FROM places WHERE name = ? AND website = '' AND letter_only = 0"
                 " AND logo_document_id IS NULL AND added = 0", (name,))


def _ensure(conn: sqlite3.Connection, name: str) -> None:
    conn.execute("INSERT INTO places (name, updated_at) VALUES (?, ?) ON CONFLICT (name) DO NOTHING",
                 (name, now_iso()))


def set_place(conn: sqlite3.Connection, name: str, website: str = "", letter_only: bool = False) -> None:
    """A station's or shop's own website, or its letter instead. Neither, and no logo of yours, puts it back as
    recognised."""
    _ensure(conn, name)
    conn.execute("UPDATE places SET website = ?, letter_only = ?, updated_at = ? WHERE name = ?",
                 (website, int(letter_only), now_iso(), name))
    _tidy(conn, name)


def add(conn: sqlite3.Connection, name: str) -> None:
    """A station or shop set up before you've been: listed on Stations and shops until you have."""
    _ensure(conn, name)
    conn.execute("UPDATE places SET added = 1, updated_at = ? WHERE name = ?", (now_iso(), name))


def set_logo(conn: sqlite3.Connection, name: str, document_id: int | None) -> None:
    """Your logo for one station or shop; None takes it away."""
    _ensure(conn, name)
    conn.execute("UPDATE places SET logo_document_id = ?, updated_at = ? WHERE name = ?",
                 (document_id, now_iso(), name))
    _tidy(conn, name)


def brand_logos(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    """Your logo for each brand you gave one, by the brand's name; with its fingerprint."""
    return {row["brand"]: row for row in conn.execute(
        "SELECT b.*, d.sha256 AS logo_sha256 FROM brand_logos b JOIN documents d ON d.id = b.document_id")}


def set_brand_logo(conn: sqlite3.Connection, brand: str, document_id: int | None) -> None:
    """Your logo for every station or shop recognised as a brand; None takes it away."""
    if document_id is None:
        conn.execute("DELETE FROM brand_logos WHERE brand = ?", (brand,))
        return
    conn.execute(
        "INSERT INTO brand_logos (brand, document_id, updated_at) VALUES (?, ?, ?)"
        " ON CONFLICT (brand) DO UPDATE SET document_id = excluded.document_id, updated_at = excluded.updated_at",
        (brand, document_id, now_iso()),
    )


def uploads(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every logo you uploaded, for a station or shop ("name") or a brand ("brand"), with its stored file."""
    return conn.execute(
        "SELECT 'name' AS kind, p.name AS owner, d.* FROM places p JOIN documents d ON d.id = p.logo_document_id"
        " UNION ALL"
        " SELECT 'brand' AS kind, b.brand AS owner, d.* FROM brand_logos b JOIN documents d ON d.id = b.document_id"
        " ORDER BY owner COLLATE NOCASE"
    ).fetchall()


def not_visited(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """The stations and shops you've set up that no fill-up or confirmed service names yet."""
    return conn.execute(
        "SELECT p.* FROM places p"
        " WHERE NOT EXISTS (SELECT 1 FROM fuel_logs f WHERE f.station = p.name COLLATE NOCASE)"
        "   AND NOT EXISTS (SELECT 1 FROM service_events e WHERE e.confirmed = 1 AND trim(e.shop) = p.name COLLATE NOCASE)"
        " ORDER BY p.name COLLATE NOCASE"
    ).fetchall()


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
