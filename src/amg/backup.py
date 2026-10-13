"""Backups: all of AMG's data in one zip, and putting one back.

What AMG holds that nothing else can rebuild is its database and the files
people uploaded. Page previews are a cache and are left out; the code is in
git; the Anthropic key lives in .env, which is the owner's to keep. A backup is:

    amg.sqlite3          a consistent snapshot, taken with SQLite's online
                         backup while the app keeps running
    files/ab/<sha>.pdf   every stored receipt, manual and photo, as uploaded
    README.txt           what this is and how to put it back

The snapshot is taken first, and the files it lists are copied after it. Files
are only ever added, under a name that is their own hash, so every file the
snapshot refers to is already on disk by then.

Restoring is a command, not a web page (``amg restore``): it replaces
everything, so it is done on the server, on purpose, with the app stopped.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import config, db

DATABASE = "amg.sqlite3"
README = "README.txt"

# The only names a backup holds. Anything else — a path climbing out with "..",
# an absolute path, a file nobody expected — means the zip isn't one of ours,
# and nothing in it is unpacked.
_FILE_ENTRY = re.compile(r"files/[0-9a-f]{2}/[0-9a-f]{64}\.(?:pdf|png|jpg|gif)")
_DIRECTORY_ENTRY = re.compile(r"files/(?:[0-9a-f]{2}/)?")


class BackupError(Exception):
    """A backup that can't be written."""


class RestoreError(Exception):
    """A backup that can't be restored. Nothing has been changed when this is raised."""


@dataclass
class Summary:
    counts: dict[str, int]
    database_bytes: int
    files_bytes: int


@dataclass
class Written:
    path: Path
    counts: dict[str, int]
    files: int
    bytes: int
    missing: list[str] = field(default_factory=list)


@dataclass
class Restored:
    counts: dict[str, int]
    files_written: int
    migrated: list[int]
    replaced: Path | None
    missing: list[str] = field(default_factory=list)


def backups_dir() -> Path:
    return config.data_dir() / "backups"


def filename(include_files: bool = True, when: datetime | None = None) -> str:
    stamp = f"{when or datetime.now():%Y-%m-%d-%H%M}"
    return f"amg-backup-{stamp}.zip" if include_files else f"amg-backup-{stamp}-database-only.zip"


def size_label(count: int) -> str:
    """A byte count as people read one: 840 KB, 2.1 MB, 1.3 GB."""
    size, unit = float(count), "bytes"
    for bigger in ("KB", "MB", "GB"):
        if size < 1024:
            break
        size, unit = size / 1024, bigger
    if unit == "bytes":
        return f"{count} bytes"
    return f"{size:,.0f} {unit}" if size >= 100 else f"{size:,.1f} {unit}"


# A deploy backs up with the new code before the restart migrates, so these
# read databases older than the code: a table that isn't there yet counts nothing.


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def _counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = _tables(conn)

    def count(table: str) -> int:
        return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] if table in tables else 0

    return {"cars": count("vehicles"), "services": count("service_events"), "fills": count("fuel_logs"),
            "files": count("documents")}


def _stored(conn: sqlite3.Connection) -> list[str]:
    if "documents" not in _tables(conn):
        return []
    return [row[0] for row in conn.execute("SELECT stored_as FROM documents ORDER BY id")]


def summary(conn: sqlite3.Connection) -> Summary:
    """What a backup would hold right now, for the page that offers one."""
    data = config.data_dir()
    files = [data / name for name in _stored(conn)]
    database = config.db_path()
    wal = database.with_name(database.name + "-wal")
    return Summary(
        counts=_counts(conn),
        database_bytes=database.stat().st_size + (wal.stat().st_size if wal.exists() else 0),
        files_bytes=sum(path.stat().st_size for path in files if path.exists()),
    )


# ---------- Backing up ----------


def write(target: Path, include_files: bool = True) -> Written:
    """Write a backup zip to ``target``, replacing it only once the zip is complete."""
    if not config.db_path().exists():
        raise BackupError("There's no database yet, so there's nothing to back up.")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".partial")
    data = config.data_dir()

    with tempfile.TemporaryDirectory() as scratch:
        snapshot = Path(scratch) / DATABASE
        version = _snapshot(snapshot)
        conn = sqlite3.connect(snapshot)
        try:
            counts = _counts(conn)
            stored = _stored(conn)
        finally:
            conn.close()

        missing: list[str] = []
        copied = 0
        with zipfile.ZipFile(partial, "w") as zf:
            zf.write(snapshot, DATABASE, compress_type=zipfile.ZIP_DEFLATED)
            if include_files:
                # Scans are compressed already; storing them as-is is as small and much faster.
                for name in stored:
                    source = data / name
                    if source.exists():
                        zf.write(source, name, compress_type=zipfile.ZIP_STORED)
                        copied += 1
                    else:
                        missing.append(name)
            zf.writestr(README, _readme(target.name, counts, version, include_files, missing),
                        compress_type=zipfile.ZIP_DEFLATED)
    partial.replace(target)
    return Written(target, counts, copied, target.stat().st_size, missing)


def _snapshot(path: Path) -> int:
    """Copy the live database to ``path`` as one self-contained file; return its schema version."""
    source = db.connect()
    copy = sqlite3.connect(path)
    try:
        source.backup(copy)
        # The copy inherits WAL mode from the live file; a backup should be one file, not three.
        copy.execute("PRAGMA journal_mode = DELETE")
        return copy.execute("SELECT max(version) FROM schema_version").fetchone()[0]
    finally:
        copy.close()
        source.close()


def _readme(name: str, counts: dict[str, int], version: int, include_files: bool, missing: list[str]) -> str:
    files_line = (
        "files/        every receipt, manual and photo, as uploaded"
        if include_files
        else "files/        NOT INCLUDED — this backup is the database only. It\n"
             "              restores onto a server that still has its files, but\n"
             "              can't bring back the scans themselves."
    )
    missing_note = (
        f"\n{len(missing)} file(s) the database lists were already missing from the server\n"
        "when this was taken, so they aren't in it either.\n"
        if missing else ""
    )
    return f"""AMG backup
==========

Taken {datetime.now():%Y-%m-%d %H:%M} · database version {version}
{counts['cars']} car(s), {counts['services']} service(s), {counts['fills']} fill-up(s) and charge(s),
{counts['files']} stored file(s).

amg.sqlite3   the database: cars, services, receipts, schedules, fill-ups,
              prices, inspections and registration, recalls, specs,
              issues, warranties, settings and your login password
{files_line}
{missing_note}
Not in here: the server's .env, which holds your Anthropic key. Keep a
copy of that key somewhere safe yourself.

To restore, copy this zip to the server, then with the app stopped:

    systemctl stop amg
    amg restore /tmp/{name} --replace
    systemctl start amg

The database it replaces is moved aside, not deleted. docs/DEPLOY-proxmox.md
has the whole procedure, including rebuilding the server from nothing.
"""


# ---------- Restoring ----------


def restore(source: Path, replace: bool = False) -> Restored:
    """Put a backup's database and files in place, then bring the database up to date.

    Everything is checked before anything is touched: the zip holds only what a
    backup holds, its database passes SQLite's integrity check, and it isn't
    from a newer AMG than this one. The database it replaces is moved into
    ``replaced-<when>/`` in the data directory rather than deleted.
    """
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile) as err:
        raise RestoreError(f"{source} isn't a zip file AMG can open ({err}).") from err

    data = config.data_dir()
    current = config.db_path()
    with archive:
        names = archive.namelist()
        strangers = [n for n in names
                     if n not in (DATABASE, README) and not _FILE_ENTRY.fullmatch(n)
                     and not _DIRECTORY_ENTRY.fullmatch(n)]
        if strangers:
            shown = ", ".join(strangers[:3]) + (" …" if len(strangers) > 3 else "")
            raise RestoreError(f"{source.name} holds files an AMG backup never does ({shown}), so it wasn't restored.")
        if DATABASE not in names:
            raise RestoreError(f"{source.name} has no database in it, so it isn't an AMG backup.")
        if current.exists() and not replace:
            raise RestoreError(
                f"There's already a database at {current}. Stop the app, then run this again with "
                "--replace: the current database is moved aside, not deleted."
            )

        incoming = current.with_name(DATABASE + ".restoring")
        try:
            with archive.open(DATABASE) as packed, open(incoming, "wb") as unpacked:
                shutil.copyfileobj(packed, unpacked)
            _check(incoming)
        except BaseException:
            incoming.unlink(missing_ok=True)
            raise

        replaced = None
        if current.exists():
            replaced = data / f"replaced-{datetime.now():%Y-%m-%d-%H%M%S}"
            replaced.mkdir()
            for suffix in ("", "-wal", "-shm"):
                part = current.with_name(current.name + suffix)
                if part.exists():
                    part.replace(replaced / part.name)
        incoming.replace(current)

        written = 0
        for name in names:
            if not _FILE_ENTRY.fullmatch(name):
                continue
            target = data / name
            if target.exists():  # named by its own hash, so it's the same file
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            partial = target.with_name(target.name + ".partial")
            with archive.open(name) as packed, open(partial, "wb") as unpacked:
                shutil.copyfileobj(packed, unpacked)
            partial.replace(target)
            written += 1

    conn = db.connect()
    try:
        migrated = db.migrate(conn)
        counts = _counts(conn)
        missing = [name for name in _stored(conn) if not (data / name).exists()]
    finally:
        conn.close()
    return Restored(counts, written, migrated, replaced, missing)


def _check(path: Path) -> None:
    try:
        conn = sqlite3.connect(path)
        try:
            verdict = conn.execute("PRAGMA integrity_check").fetchone()[0]
            versioned = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_version'"
            ).fetchone()
            version = conn.execute("SELECT max(version) FROM schema_version").fetchone()[0] if versioned else None
        finally:
            conn.close()
    except sqlite3.DatabaseError as err:
        raise RestoreError(f"The database in this backup can't be read ({err}).") from err
    if verdict != "ok":
        raise RestoreError(f"The database in this backup is damaged: {verdict}")
    newest = db.migrations()[-1][0]
    if version is None:
        raise RestoreError("The database in this backup has no schema version, so it isn't an AMG backup.")
    if version > newest:
        raise RestoreError(
            f"This backup comes from a newer AMG (database version {version}; this code knows up to "
            f"{newest}). Deploy the newer code, then restore."
        )
