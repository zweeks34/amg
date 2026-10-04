"""The schedule as an iCalendar file (RFC 5545), to import into a calendar.

Pure: events in, text out. Each event is an all-day one on the day a job falls
due. Its UID names the job and which time round it is ("the next oil change on
the Outback"), not the date, so a later file describes the same event with a
new date rather than a second event.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

PRODID = "-//AMG//Automobile Maintenance Genie//EN"
NAME = "Car maintenance"
_LINE = 75   # octets, before a line is folded


@dataclass(frozen=True)
class Event:
    uid: str
    day: date
    summary: str
    description: str = ""
    url: str = ""


def calendar(events: Iterable[Event], stamp: datetime | None = None) -> str:
    """The whole file. ``stamp`` (UTC) marks when it was made; later files carry a higher SEQUENCE."""
    stamp = (stamp or datetime.now(timezone.utc)).astimezone(timezone.utc)
    made = f"{stamp:%Y%m%dT%H%M%SZ}"
    sequence = int(stamp.timestamp()) // 60   # rises with every file, so a re-import reads as a revision
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", f"PRODID:{PRODID}", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             f"X-WR-CALNAME:{escape(NAME)}"]
    for event in events:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{event.uid}",
            f"DTSTAMP:{made}",
            f"LAST-MODIFIED:{made}",
            f"SEQUENCE:{sequence}",
            f"DTSTART;VALUE=DATE:{event.day:%Y%m%d}",
            f"DTEND;VALUE=DATE:{event.day + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{escape(event.summary)}",
        ]
        if event.description:
            lines.append(f"DESCRIPTION:{escape(event.description)}")
        if event.url:
            lines.append(f"URL:{event.url}")
        lines += ["TRANSP:TRANSPARENT", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    return "".join(fold(line) + "\r\n" for line in lines)


def escape(text: str) -> str:
    """A TEXT value: backslashes, semicolons, commas and newlines escaped."""
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def fold(line: str) -> str:
    """Split a line longer than 75 octets; each continuation starts with a space.

    Counted in UTF-8 octets and never inside a character, so "·" and "—" survive.
    """
    parts: list[str] = []
    current, size = "", 0
    for char in line:
        width = len(char.encode("utf-8"))
        limit = _LINE if not parts else _LINE - 1   # a continuation's leading space counts
        if size + width > limit:
            parts.append(current)
            current, size = "", 0
        current += char
        size += width
    parts.append(current)
    return "\r\n ".join(parts)
