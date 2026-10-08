"""The daily alerts run: push what's newly due, and send the weekly email when it's due.

    python -m amg.alerts.run             # what the systemd timer runs at 8:00
    python -m amg.alerts.run --dry-run   # print what would go out; send and record nothing

On the server, ``amg alerts`` (and ``amg alerts --dry-run``) runs it as the
app's user. Every alert is claimed in the log before it's sent, so a second
run — or two at once — never sends it twice. A send that fails is logged and
tried again next run, and the run exits 1 so systemd shows it failed.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from .. import config, db
from ..repo import alerts, receipts
from . import ics, mail, ntfy, watch

DIGEST_DAY = 0   # Monday: the week's email goes with the first run on or after it


@dataclass
class Result:
    pushes: int = 0
    email: str = ""                    # sent, not due, not set up, no cars, would send (a dry run)
    failures: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def summary(self) -> str:
        pushes = "nothing new to push" if not self.pushes else f"{self.pushes} push{'es' if self.pushes != 1 else ''}"
        words = {"sent": "weekly email sent", "not due": "no email due", "not set up": "email not set up",
                 "no cars": "no cars on", "would send": "weekly email would go"}
        parts = [pushes, words.get(self.email, self.email)] + [f"failed: {f}" for f in self.failures]
        return "; ".join(p for p in parts if p)


def week(today: date) -> str:
    iso = today.isocalendar()
    return f"digest:{iso.year}-W{iso.week:02d}"


def calendar(watches: list[watch.CarWatch], base_url: str) -> str:
    return ics.calendar(watch.events(watches, base_url))


def run(conn: sqlite3.Connection, today: date, dry_run: bool = False, say: Callable[[str], None] = print) -> Result:
    result = Result()
    base_url = config.base_url()
    cars = alerts.cars_watched(conn)
    if not cars:
        say("No car has alerts turned on, or an inspection or registration date. Turn alerts on from the Alerts "
            "page, or add the dates on a car's page.")
        result.email = "no cars"
        return _finish(conn, result, dry_run)
    watches = [watch.look(conn, car, today) for car in cars]

    # Pushes: one per car, for what's newly due soon or overdue.
    push_settings = config.ntfy()
    if push_settings is None:
        say("Pushes aren't set up (AMG_NTFY_TOPIC is empty)" + (": showing what they would say." if dry_run else "."))
    logged = alerts.logged(conn, watch.CHANNEL)
    for car_watch in watches:
        fresh = watch.news(car_watch.alerting, logged)
        if not fresh:
            continue
        if dry_run or push_settings is None:
            if dry_run:
                _say_push(say, watch.push(car_watch, fresh, base_url))
                result.pushes += 1   # would go
            continue
        claimed = [(job, alert_id) for job in fresh
                   if (alert_id := alerts.claim(conn, watch.CHANNEL, job.subject, job.level, job.vehicle_id,
                                                job.line)) is not None]
        if not claimed:
            continue   # another run has them
        message = watch.push(car_watch, [job for job, _ in claimed], base_url)
        try:
            ntfy.send(message, push_settings)
        except ntfy.SendError as err:
            for _, alert_id in claimed:
                alerts.mark(conn, alert_id, "failed", str(err))
            result.failures.append(str(err))
            say(f"Push for {car_watch.car['name']} failed: {err}")
            continue
        for _, alert_id in claimed:
            alerts.mark(conn, alert_id, "sent")
        result.pushes += 1
        say(f"Pushed: {message.title}")

    # The weekly email: the first run of the week on or after Monday.
    mail_settings = config.smtp()
    key = week(today)
    sent_this_week = (key, "digest") in alerts.logged(conn, "email")
    if today.weekday() < DIGEST_DAY or sent_this_week:
        result.email = "not due"
        if dry_run:
            say("This week's email has gone; the next goes on Monday.")
    elif dry_run:
        result.email = "would send"
        say(f"Would email {mail_settings.to if mail_settings else '(email not set up)'}:\n"
            + mail.text(watches, receipts.count_to_check(conn), base_url))
    elif mail_settings is None:
        result.email = "not set up"
        say("The weekly email isn't set up (AMG_SMTP_USER and AMG_SMTP_PASSWORD).")
    else:
        message = mail.digest(watches, receipts.count_to_check(conn), base_url, calendar(watches, base_url))
        alert_id = alerts.claim(conn, "email", key, "digest", None, str(message["Subject"]))
        if alert_id is None:
            result.email = "not due"
        else:
            try:
                mail.send(message, mail_settings)
            except mail.SendError as err:
                alerts.mark(conn, alert_id, "failed", str(err))
                result.failures.append(str(err))
                result.email = ""
                say(f"The weekly email failed: {err}")
            else:
                alerts.mark(conn, alert_id, "sent")
                result.email = "sent"
                say(f"Emailed {mail_settings.to}: {message['Subject']}")
    return _finish(conn, result, dry_run)


def _say_push(say: Callable[[str], None], push: ntfy.Push) -> None:
    say(f"Would push: {push.title}\n  " + push.message.replace("\n", "\n  "))


def _finish(conn: sqlite3.Connection, result: Result, dry_run: bool) -> Result:
    if not dry_run:
        alerts.set_last_run(conn, datetime.now(timezone.utc).astimezone().isoformat(timespec="minutes"),
                            result.summary(), result.ok)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m amg.alerts.run",
                                     description="Push what's newly due, and send the weekly email when it's due")
    parser.add_argument("--dry-run", action="store_true", help="print what would go out; send and record nothing")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")   # a console that can't show "→" shows "?" rather than stopping
    conn = db.connect()
    try:
        db.migrate(conn)
        result = run(conn, date.today(), dry_run=args.dry_run)
    finally:
        conn.close()
    print(("Dry run: " if args.dry_run else "") + result.summary())
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
