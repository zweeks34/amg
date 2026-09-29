"""Command-line tasks that run on the box rather than in the browser.

    python -m amg.cli set-password    # prompts twice; or pipe one line on stdin
    python -m amg.cli migrate         # apply pending migrations (the app also does this at startup)
"""

from __future__ import annotations

import argparse
import getpass
import sys

from . import auth, config, db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m amg.cli", description="AMG maintenance tasks")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("set-password", help="set the login password (signs out every session)")
    commands.add_parser("migrate", help="apply pending database migrations")
    args = parser.parse_args(argv)

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


if __name__ == "__main__":
    sys.exit(main())
