"""The calendar file: that it parses, and that it describes the right days."""

from __future__ import annotations

from datetime import date, datetime, timezone

import alert_fixtures as af  # tests/ is on pytest's path

from amg.alerts import ics, watch
from amg.repo import vehicles

STAMP = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)


def parse(text: str) -> list[dict]:
    """A small RFC 5545 reader: every line CRLF-ended and at most 75 octets, unfolded, BEGIN/END balanced."""
    assert text.endswith("\r\n") and "\n" not in text.replace("\r\n", "")
    raw = text[:-2].split("\r\n")
    assert all(len(line.encode("utf-8")) <= 75 for line in raw)
    lines: list[str] = []
    for line in raw:
        if line.startswith(" "):
            lines[-1] += line[1:]
        else:
            lines.append(line)
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-1] == "END:VCALENDAR"
    events, current, depth = [], None, 0
    for line in lines:
        name, _, value = line.partition(":")
        if name == "BEGIN":
            depth += 1
            if value == "VEVENT":
                current = {}
        elif name == "END":
            depth -= 1
            if value == "VEVENT":
                events.append(current)
                current = None
        elif current is not None:
            current[name] = value
    assert depth == 0
    return events


def unescape(value: str) -> str:
    return value.replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def test_a_file_parses_and_its_text_survives():
    tricky = "Brakes, front; rear\\left\nand a long line " + "·" * 60
    text = ics.calendar([ics.Event("amg-1@amg", date(2026, 7, 1), "Oil and filter · Outback", tricky,
                                   "http://amg.home.arpa/vehicles/1")], STAMP)
    (event,) = parse(text)
    assert event["UID"] == "amg-1@amg"
    assert event["DTSTART;VALUE=DATE"] == "20260701" and event["DTEND;VALUE=DATE"] == "20260702"
    assert unescape(event["SUMMARY"]) == "Oil and filter · Outback"
    assert unescape(event["DESCRIPTION"]) == tricky
    assert event["DTSTAMP"] == "20260610T120000Z" and event["URL"] == "http://amg.home.arpa/vehicles/1"


def test_folding_never_splits_a_character():
    line = "SUMMARY:" + "—" * 40
    folded = ics.fold(line)
    assert all(len(part.encode("utf-8")) <= 75 for part in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == line


def test_the_cars_next_twelve_months_are_events(conn, car):
    watched = watch.look(conn, vehicles.get(conn, car), af.JUNE_10)
    found = watch.events([watched], "http://amg.home.arpa")
    assert [(e.day, e.summary) for e in found] == [
        (date(2026, 7, 1), "REPLACE Oil and filter · Outback"),     # what to do, first
        (date(2026, 9, 1), "REPLACE Wiper blades · Outback"),
        (date(2027, 1, 1), "REPLACE Oil and filter · Outback"),
        (date(2027, 3, 1), "REPLACE Wiper blades · Outback"),
    ]                                                     # the cabin filter (2028) is past the 12 months
    assert parse(ics.calendar(found, STAMP))[0]["UID"] == f"amg-{car}-engine_oil+oil_filter-replace-1@amg"


def test_an_event_keeps_its_uid_as_dates_pass_and_the_job_is_done(conn, car):
    def uids(day):
        return {e.day: e.uid for e in watch.events([watch.look(conn, vehicles.get(conn, car), day)], "")}

    june = uids(af.JUNE_10)
    july = uids(af.JULY_2)                                # July's oil change is overdue now: left out
    assert date(2026, 7, 1) not in july and july[date(2027, 1, 1)] == june[date(2027, 1, 1)]
    af.oil_change(conn, car, date(2026, 7, 5))
    moved = uids(date(2026, 7, 6))                        # done: the next one moves to Jan 5
    assert moved[date(2027, 1, 5)] == june[date(2027, 1, 1)]
