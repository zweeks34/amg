"""The weekly email: what each car has overdue, due soon and coming up, and the calendar file.

Sent through your own mail account (Gmail, with an app password) by SMTP. It
goes out every week, even with nothing due: an email that stops coming is how
you'd know the alerts have stopped working.
"""

from __future__ import annotations

import smtplib
import ssl
from datetime import date
from email.message import EmailMessage
from email.utils import formataddr

from ..config import Smtp
from ..web.templating import dollars, templates
from .watch import CarWatch

TIMEOUT = 30   # seconds
CALENDAR_FILE = "amg-maintenance.ics"
IMPORT_HOW = ("To add them to Google Calendar: Settings → Import & export → Import, into a calendar of their own "
              "(say \"Car maintenance\").")


class SendError(Exception):
    """An email didn't go; the message says why, in words for the Alerts page."""


def subject(watches: list[CarWatch]) -> str:
    overdue = sum(len(w.overdue) for w in watches)
    due = sum(len(w.due) for w in watches)
    parts = [f"{overdue} overdue"] * bool(overdue) + [f"{due} due soon"] * bool(due)
    return "AMG: " + (", ".join(parts) if parts else "nothing due this week")


def budget_line(watch: CarWatch) -> str | None:
    """The year ahead in a sentence, as the car's page says it."""
    plan = watch.plan
    if not (plan.maintenance or plan.unpriced):
        return None
    line = f"~{dollars(plan.maintenance)} of maintenance in the next 12 months"
    if plan.due_now:
        line += f", {dollars(plan.due_now)} of it overdue now"
    line += f": put aside {dollars(plan.per_month)} a month" + (" for the rest" if plan.due_now else "")
    if plan.unpriced:
        line += f" ({plan.unpriced} job{'s' if plan.unpriced != 1 else ''} not priced yet)"
    return line + "."


def _row(row: dict) -> str:
    return f"{row['name']}: {row['when']}" + (f" · ~{dollars(row['cost'])}" if row.get("cost") else "")


def text(watches: list[CarWatch], to_check: int, base_url: str) -> str:
    lines = [subject(watches)]
    for watch in watches:
        car = watch.car
        lines += ["", car["name"].upper()]
        if not watch.has_schedule:
            lines.append("No maintenance schedule yet, so there's nothing to watch.")
        else:
            for heading, jobs in (("Overdue", watch.overdue), ("Due soon", watch.due)):
                if jobs:
                    lines += [heading] + [f"  • {job.line}" for job in jobs]
            if not watch.jobs:
                lines.append("Nothing due or overdue.")
            if watch.state.missed:
                lines.append(f"Missed earlier: {watch.state.missed}. The car's page lists them.")
            if watch.coming_up:
                lines += ["Coming up"] + [f"  • {_row(row)}" for row in watch.coming_up]
            if budget := budget_line(watch):
                lines.append(budget)
        lines.append(f"{base_url}/vehicles/{car['id']}")
    if to_check:
        lines += ["", f"{to_check} receipt{'s' if to_check != 1 else ''} to check: {base_url}/receipts"]
    lines += ["", f"The attached {CALENDAR_FILE} has the next 12 months of jobs. {IMPORT_HOW}"]
    return "\n".join(lines) + "\n"


def digest(watches: list[CarWatch], to_check: int, base_url: str, calendar: str) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject(watches)
    message.set_content(text(watches, to_check, base_url))
    html = templates.env.get_template("email/digest.html").render(
        subject=subject(watches), watches=watches, to_check=to_check, base_url=base_url, budget_line=budget_line,
        row=_row, calendar_file=CALENDAR_FILE, import_how=IMPORT_HOW)
    message.add_alternative(html, subtype="html")
    message.add_attachment(calendar.encode("utf-8"), maintype="text", subtype="calendar", filename=CALENDAR_FILE)
    return message


def test_message(today: date) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = "AMG: test email"
    message.set_content(f"This is a test from AMG, sent {today:%b} {today.day}. If you're reading it, the weekly "
                        "email will reach you too. It goes out on Mondays.\n")
    return message


def send(message: EmailMessage, settings: Smtp) -> None:
    for header in ("From", "To"):
        del message[header]
    message["From"] = formataddr(("AMG", settings.user))
    message["To"] = settings.to
    context = ssl.create_default_context()
    try:
        if settings.port == 465:
            with smtplib.SMTP_SSL(settings.host, settings.port, timeout=TIMEOUT, context=context) as server:
                server.login(settings.user, settings.password)
                server.send_message(message)
        else:
            with smtplib.SMTP(settings.host, settings.port, timeout=TIMEOUT) as server:
                server.starttls(context=context)
                server.login(settings.user, settings.password)
                server.send_message(message)
    except smtplib.SMTPAuthenticationError as err:
        raise SendError(f"{settings.host} turned down the login for {settings.user}. For Gmail, AMG_SMTP_PASSWORD "
                        "must be an app password, not your Google password.") from err
    except (smtplib.SMTPException, OSError) as err:
        raise SendError(f"Couldn't send through {settings.host}:{settings.port} ({err}).") from err
