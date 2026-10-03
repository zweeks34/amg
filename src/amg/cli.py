"""Command-line tasks that run on the box rather than in the browser.

    python -m amg.cli set-password       # prompts twice; or pipe one line on stdin
    python -m amg.cli migrate            # apply pending migrations (the app also does this at startup)
    python -m amg.cli backup             # database and stored files, zipped into data/backups/
    python -m amg.cli restore FILE.zip   # put a backup back (stop the app first)

On the server the ``amg`` command (deploy/amg) runs these as the app's user:
``amg backup``, ``amg set-password``.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path

from . import auth, backup, config, db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m amg.cli", description="AMG maintenance tasks")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("set-password", help="set the login password (signs out every session)")
    commands.add_parser("migrate", help="apply pending database migrations")
    backing_up = commands.add_parser("backup", help="zip the database and the stored receipts")
    backing_up.add_argument("--out", type=Path, help="the zip to write, or a folder to put it in (default: data/backups/)")
    backing_up.add_argument("--no-files", action="store_true",
                            help="the database only: small, but it can't bring back the scans")
    restoring = commands.add_parser("restore", help="put a backup back in place (stop the app first)")
    restoring.add_argument("zip", type=Path, help="a zip made by `backup` or the Back up page")
    restoring.add_argument("--replace", action="store_true",
                           help="move the current database aside and use the backup's")
    args = parser.parse_args(argv)

    if problem := _wrong_user():
        print(problem, file=sys.stderr)
        return 1
    if args.command == "backup":
        return _backup(args.out, include_files=not args.no_files)
    if args.command == "restore":
        return _restore(args.zip, args.replace)

    conn = db.connect()
    try:
        applied = db.migrate(conn)
        if args.command == "migrate":
            print(f"Applied migrations: {applied}" if applied else "Database is up to date.")
            print(f"Database: {config.db_path()}")
            return 0
        if args.command == "set-password":
            return _set_password(conn)
    finally:
        conn.close()
    return 1


def _wrong_user() -> str | None:
    """Refuse root on a data directory the app's user owns.

    A database file or backup that root creates there is one the app can't
    write, and SQLite's -wal and -shm files are created by whoever opens the
    database first.
    """
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None or geteuid() != 0:
        return None
    if config.data_dir().stat().st_uid == 0:
        return None
    return ("Run this as the app's user, not root: use the `amg` command, which does that for you "
            "(e.g. `amg backup`). Files root creates in the data directory are files the app can't write.")


def _set_password(conn) -> int:
    if sys.stdin.isatty():
        password = getpass.getpass("New password: ")
        if getpass.getpass("Repeat it: ") != password:
            print("The two entries don't match. Nothing was changed.", file=sys.stderr)
            return 1
    else:
        password = sys.stdin.readline().rstrip("\r\n")
    try:
        auth.set_password(conn, password)
    except ValueError as err:
        print(f"{err} Nothing was changed.", file=sys.stderr)
        return 1
    print("Password set. Any open sessions have been signed out.")
    return 0


def _backup(out: Path | None, include_files: bool) -> int:
    if out is None:
        target = backup.backups_dir() / backup.filename(include_files)
    elif out.is_dir():
        target = out / backup.filename(include_files)
    else:
        target = out
    try:
        written = backup.write(target, include_files=include_files)
    except backup.BackupError as err:
        print(err, file=sys.stderr)
        return 1
    counts = written.counts
    what = f"{written.files} stored file(s)" if include_files else "no stored files (database only)"
    print(f"Backed up {counts['cars']} car(s), {counts['services']} service(s), {counts['fills']} fill-up(s) "
          f"and {what}.")
    print(f"{written.path} ({backup.size_label(written.bytes)})")
    if written.missing:
        print(f"{len(written.missing)} stored file(s) were already missing from {config.data_dir()} "
              "and aren't in the backup.", file=sys.stderr)
    return 0


def _restore(source: Path, replace: bool) -> int:
    try:
        restored = backup.restore(source, replace=replace)
    except backup.RestoreError as err:
        print(f"{err}\nNothing was changed.", file=sys.stderr)
        return 1
    counts = restored.counts
    print(f"Restored {counts['cars']} car(s), {counts['services']} service(s), {counts['fills']} fill-up(s) "
          f"and {counts['files']} stored file(s) from {source.name}.")
    if restored.replaced:
        print(f"The database it replaced is in {restored.replaced}.")
    if restored.migrated:
        print(f"Brought the database up to date (migrations {', '.join(map(str, restored.migrated))}).")
    if restored.missing:
        print(f"{len(restored.missing)} stored file(s) are missing — the backup was the database only, "
              "or taken from a server that had lost them. Their receipts show without a scan.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
