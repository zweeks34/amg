"""A car's warranties as its pages show them, and reading the warranty form back.

Each says what it covers, its terms, where it came from and when it ends.
The car's page lists the ones in force, those ending soon first, and folds
the ended ones away. When each ends, and which later visit it asks about,
is the engine's call (engine/warranties.py).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from ..engine import warranties as engine
from ..engine.odometer import Odometer
from ..engine.warranties import Standing, Visit
from ..repo import odometer as readings
from ..repo import services, warranties, warranty_looks
from ..repo.warranties import WarrantyInput
from . import forms
from .issues import visit_words
from .recalls import day_words

MAX_TITLE = 120
MAX_DETAILS = 2000
UNITS = ("years", "months")


@dataclass
class Use:
    event_id: int
    words: str                     # "Used Sep 20, 2026 at Valley Honda"


@dataclass
class Row:
    id: int
    title: str
    provider: str
    covers: str                    # "The whole car", "12-volt battery"
    codes: frozenset[str]
    whole_car: bool
    terms: str                     # "3 years or 36,000 mi, whichever comes first", "Lifetime"
    source: str                    # "From Costco on Mar 1, 2025"
    source_url: str                # the receipt or service it came with; '' for none
    edit_url: str                  # the form, or the receipt for one read from a receipt
    from_receipt: bool
    details: str
    standing: Standing
    term: engine.Warranty
    receipt_id: int | None = None
    answers: dict[int, str] = field(default_factory=dict)   # what you said about later visits, by visit
    until: str = ""                # "Until Mar 1, 2028 or about 72,500 mi"
    left: str = ""                 # "about 2 years 5 months left"
    ending: str = ""               # "Ends in 45 days, Nov 23"
    ended: str = ""                # "Ended Mar 1, 2028"
    used: list[Use] = field(default_factory=list)
    ask: Visit | None = None       # the later visit to ask about
    question: str = ""
    paid: int | None = None        # the visit you paid for, which ended it

    @property
    def state(self) -> str:
        return self.standing.state

    @property
    def note(self) -> str:
        """'Under warranty: Costco, until Mar 1, 2028', for a recommendation or a job that touches what it covers."""
        return f"Under warranty: {self.provider or self.title}, {covered(self)}"


@dataclass
class Section:
    in_force: list[Row] = field(default_factory=list)    # ending soon first
    ended: list[Row] = field(default_factory=list)       # latest ended first
    found: list[dict] = field(default_factory=list)      # receipts with warranties found, not yet checked

    @property
    def ending(self) -> list[Row]:
        return [row for row in self.in_force if row.state == "ending"]

    def covering(self, codes: Iterable[str]) -> Row | None:
        """The warranty in force on a part these services touch; whole-car ones list no parts, and oil, filters and
        fluids are never a claim."""
        wanted = set(codes) - engine.ROUTINE
        return next((row for row in self.in_force if not row.whole_car and row.codes & wanted), None)


# ---------- Words ----------


def length_words(months: int | None) -> str:
    if months is None:
        return ""
    if months % 12 == 0:
        years = months // 12
        return f"{years} year{'s' if years != 1 else ''}"
    return f"{months} month{'s' if months != 1 else ''}"


def terms(months: int | None, miles: int | None) -> str:
    """'3 years or 36,000 mi, whichever comes first', '36 months', '50,000 mi', 'Lifetime'."""
    if months is None and miles is None:
        return "Lifetime"
    parts = [part for part in (length_words(months), f"{miles:,} mi" if miles else "") if part]
    return " or ".join(parts) + (", whichever comes first" if len(parts) == 2 else "")


def names(codes: Iterable[str], type_names: Mapping[str, str]) -> str:
    """'12-volt battery'; 'Brake pads and brake rotors'."""
    listed = [type_names.get(code, code) for code in codes]
    listed = listed[:1] + [_lower(name) for name in listed[1:]]
    if len(listed) <= 1:
        return "".join(listed)
    return ", ".join(listed[:-1]) + " and " + listed[-1]


def _ordered(codes: Iterable[str], type_names: Mapping[str, str]) -> list[str]:
    """Codes in the catalogue's order, as ``type_names`` lists them."""
    order = {code: i for i, code in enumerate(type_names)}
    return sorted(codes, key=lambda code: (order.get(code, len(order)), code))


def used_words(visit: Visit) -> str:
    """'Used Sep 20, 2026 at Valley Honda'."""
    day = day_words(visit.day.isoformat())
    return f"Used {day} at {visit.shop}" if visit.shop else f"Used {day}, on your own work"


def _lower(text: str) -> str:
    return text[:1].lower() + text[1:] if text[1:2].islower() else text


def _short(day: date, today: date) -> str:
    return f"{day:%b} {day.day}" + (f", {day.year}" if day.year != today.year else "")


def _span(today: date, end: date) -> str:
    """'45 days', 'about 5 months', 'about 2 years 5 months'."""
    months = (end.year - today.year) * 12 + end.month - today.month - (end.day < today.day)
    if months < 2:
        days = (end - today).days
        return f"{days} day{'s' if days != 1 else ''}"
    if months < 12:
        return f"about {months} months"
    years, rest = divmod(months, 12)
    return f"about {years} year{'s' if years != 1 else ''}" + (f" {rest} month{'s' if rest != 1 else ''}" if rest else "")


def until(warranty: Mapping, standing: Standing, estimated: bool) -> str:
    """'Until Mar 1, 2028 or about 72,500 mi'; 'For as long as you own the car'."""
    if warranty["months"] is None and warranty["miles"] is None:
        return "For as long as you own the car"
    parts = []
    if standing.ends_on:
        parts.append(day_words(standing.ends_on.isoformat()))
    if standing.end_miles is not None:
        parts.append(f"about {round(standing.end_miles, -2):,} mi" if estimated else f"{standing.end_miles:,} mi")
    elif warranty["miles"]:
        parts.append(f"{warranty['miles']:,} mi after it started")
    return "Until " + " or ".join(parts)


def covered(row: Row) -> str:
    """How far it covered a part, for the question: 'until Mar 1, 2028', 'for life'."""
    return "for life" if row.until.startswith("For as long") else _lower(row.until)


def question(row: Row, visit: Visit, type_names: Mapping[str, str]) -> str:
    """'Valley Honda replaced the 12-volt battery on Sep 20, 2026. Costco's warranty covered it until Mar 1, 2028.'"""
    replaced = _ordered(visit.replaced & row.codes, type_names)
    who = visit.shop or "You"
    whose = f"{row.provider}'s warranty" if row.provider else "This warranty"
    return (f"{who} replaced the {_lower(names(replaced, type_names))} on {day_words(visit.day.isoformat())}. "
            f"{whose} covered {_it(replaced)} {covered(row)}.")


def _it(parts: Sequence[str]) -> str:
    return "them" if len(parts) > 1 else "it"


def _ended(standing: Standing, codes: frozenset[str], type_names: Mapping[str, str]) -> str:
    day = standing.end_day
    if day is None:
        return ""
    if standing.by == "miles":
        return f"Ended at {standing.end_miles:,} mi, around {day:%b} {day.year}"
    if standing.by == "paid" and standing.paid is not None:
        part = _lower(names(_ordered(standing.paid.replaced & codes, type_names), type_names))
        if standing.paid.shop:
            return f"Ended {day_words(day.isoformat())}: you paid to replace the {part} at {standing.paid.shop}"
        return f"Ended {day_words(day.isoformat())}: you replaced the {part} yourself"
    return f"Ended {day_words(day.isoformat())}"


def _ending(standing: Standing, today: date, miles_left: float | None) -> str:
    day = standing.end_day
    if day is None:
        return ""
    if standing.by == "miles" and miles_left is not None:
        return f"Ends in about {round(max(miles_left, 0), -2):,.0f} mi, around {_short(day, today)}"
    days = (day - today).days
    if days <= 0:
        return "Ends today"
    if days == 1:
        return "Ends tomorrow"
    return f"Ends in {days} days, {_short(day, today)}"


def _left(standing: Standing, today: date, miles_left: float | None) -> str:
    if standing.end_day is None:
        return ""
    if standing.by == "miles" and miles_left is not None:
        return f"about {round(miles_left, -2):,.0f} mi left"
    return f"{_span(today, standing.end_day)} left"


# ---------- Rows ----------


def warranty(row: Mapping) -> engine.Warranty:
    return engine.Warranty(row["id"], date.fromisoformat(row["starts_on"]), row["start_miles"], row["months"],
                           row["miles"], frozenset(row["codes"]), bool(row["whole_car"]), row["service_event_id"])


def row(found: Mapping, visits: Sequence[Visit], odometer: Odometer | None, today: date,
        type_names: Mapping[str, str]) -> Row:
    term = warranty(found)
    standing = engine.standing(term, today, odometer, visits, found["answers"])
    from_receipt = found["receipt_id"] is not None
    if found["service_event_id"]:
        visit = {"performed_on": found["event_on"], "shop": found["event_shop"]}
        source = f"From {visit_words(visit)}"
        source_url = f"/receipts/{found['receipt_id']}" if from_receipt else f"/services/{found['service_event_id']}"
    else:
        source, source_url = "", ""
    result = Row(
        id=found["id"],
        title=found["title"],
        provider=found["provider"],
        covers="The whole car" if term.whole_car else names(_ordered(found["codes"], type_names), type_names),
        codes=term.codes,
        whole_car=term.whole_car,
        terms=terms(found["months"], found["miles"]),
        source=source,
        source_url=source_url,
        edit_url=f"/receipts/{found['receipt_id']}#warranties" if from_receipt else f"/warranties/{found['id']}/edit",
        from_receipt=from_receipt,
        details=found["details"],
        standing=standing,
        term=term,
        receipt_id=found["receipt_id"],
        answers=dict(found["answers"]),
    )
    result.until = until(found, standing, estimated=found["start_miles"] is None)
    today_miles = odometer.miles_on(today) if odometer is not None else None
    miles_left = None if (standing.end_miles is None or today_miles is None) else standing.end_miles - today_miles
    if standing.state == "ended":
        result.ended = _ended(standing, term.codes, type_names)
        result.paid = standing.paid.id if standing.paid else None
    else:
        result.left = _left(standing, today, miles_left)
        result.ending = _ending(standing, today, miles_left) if standing.state == "ending" else ""
        result.ask = engine.to_ask(term, visits, found["answers"], odometer)
        result.question = question(result, result.ask, type_names) if result.ask else ""
    by_id = {v.id: v for v in visits}
    result.used = [
        Use(event_id, used_words(by_id[event_id]))
        for event_id, answer in sorted(found["answers"].items(),
                                       key=lambda pair: (by_id[pair[0]].day, pair[0]) if pair[0] in by_id else
                                       (date.min, pair[0]))
        if answer == "claimed" and event_id in by_id
    ]
    return result


def odometer_for(conn: sqlite3.Connection, car: Mapping) -> Odometer:
    """The car's odometer model, as status.load builds it, for a page that has no CarStatus to hand."""
    in_service = date.fromisoformat(car["in_service_date"]) if car["in_service_date"] else None
    return Odometer(((date.fromisoformat(p["read_on"]), p["miles"]) for p in readings.points(conn, car["id"])),
                    in_service=in_service)


def load(conn: sqlite3.Connection, car: Mapping, odometer: Odometer | None = None,
         today: date | None = None) -> Section:
    today = today or date.today()
    odometer = odometer if odometer is not None else odometer_for(conn, car)
    visits = warranties.visits(conn, car["id"])
    type_names = {t["code"]: t["name"] for t in services.list_types(conn)}
    rows = [row(found, visits, odometer, today, type_names) for found in warranties.for_car(conn, car["id"])]
    live = [r for r in rows if r.state != "ended"]
    live.sort(key=lambda r: (r.state != "ending", not r.whole_car, r.standing.end_day or date.max, r.title.lower()))
    ended = sorted((r for r in rows if r.state == "ended"), key=lambda r: r.standing.end_day or date.min, reverse=True)
    return Section(live, ended, warranty_looks.to_check(conn, car["id"]))


# ---------- Elsewhere: a service's page, a receipt's review ----------


@dataclass
class Answered:
    row: Row
    answer: str                    # claimed or paid
    words: str                     # "Done under this warranty"


@dataclass
class ServiceBlock:
    """A service's page: the warranties that came with it, the ones asking about it, and what you said."""
    came_with: list[Row] = field(default_factory=list)
    asked: list[tuple[Row, str]] = field(default_factory=list)    # each with "It covered the 12-volt battery …"
    answered: list[Answered] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)                # procedures done under one, such as rotations

    def __bool__(self) -> bool:
        return bool(self.came_with or self.asked or self.answered or self.notes)


ANSWER_WORDS = {"claimed": "Done under this warranty", "paid": "You paid for it, so this warranty ended"}


def under(row: Row, codes: Iterable[str], type_names: Mapping[str, str]) -> str:
    """'The 12-volt battery was under warranty (36-month free replacement, Costco) until Mar 1, 2028.'"""
    parts = _ordered(set(codes) & row.codes, type_names)
    name = ", ".join(part for part in (row.title, row.provider) if part)
    were = "were" if len(parts) > 1 else "was"
    return f"The {_lower(names(parts, type_names))} {were} under warranty ({name}) {covered(row)}."


def for_service(conn: sqlite3.Connection, event: Mapping, car: Mapping) -> ServiceBlock:
    section = load(conn, car)
    rows = section.in_force + section.ended
    type_names = {t["code"]: t["name"] for t in services.list_types(conn)}
    visit = next((v for v in warranties.visits(conn, car["id"]) if v.id == event["id"]), None)
    block = ServiceBlock(came_with=[row for row in rows if row.term.event_id == event["id"]])
    for found in rows:
        if found.ask and found.ask.id == event["id"]:
            parts = _ordered(found.ask.replaced & found.codes, type_names)
            block.asked.append((found, f"It covered the {_lower(names(parts, type_names))} {covered(found)}."))
        elif event["id"] in found.answers:
            answer = found.answers[event["id"]]
            block.answered.append(Answered(found, answer, ANSWER_WORDS[answer]))
    performed = {cover["code"] for line in event["lines"] for cover in line["covers"] if cover["action"] == "perform"}
    if visit is not None and performed:
        day, odometer = visit.day, odometer_for(conn, car)
        miles = visit.odometer if visit.odometer is not None else odometer.miles_on(day)
        block.notes = [
            f"{names(_ordered(found.codes & performed, type_names), type_names)}: under warranty "
            f"({', '.join(part for part in (found.title, found.provider) if part)}) {covered(found)}."
            for found in rows
            if not found.whole_car and found.codes & performed and found.term.event_id != event["id"]
            and engine.in_force_on(found.term, day, miles, odometer)
        ]
    return block


def review_notes(conn: sqlite3.Connection, car: Mapping, day: str, odometer_miles: int | None,
                 replaced: Iterable[str], receipt_id: int | None) -> list[str]:
    """A receipt's review: each part its lines replace that a warranty (not its own) covered on that day."""
    replaced = set(replaced) - engine.NEVER_ASKS
    if not (day and replaced):
        return []
    odometer = odometer_for(conn, car)
    section = load(conn, car, odometer)
    type_names = {t["code"]: t["name"] for t in services.list_types(conn)}
    when = date.fromisoformat(day)
    miles = odometer_miles if odometer_miles is not None else odometer.miles_on(when)
    return [
        under(found, replaced, type_names)
        for found in section.in_force + section.ended
        if not found.whole_car and found.codes & replaced and found.receipt_id != receipt_id
        and when > found.term.starts_on and engine.in_force_on(found.term, when, miles, odometer)
        and not (found.standing.paid and found.standing.paid.day < when)
    ]


# ---------- The form ----------


def blank(car: Mapping, today: date) -> dict:
    return {"title": "", "provider": "", "covers": "parts", "codes": [], "starts_on": today.isoformat(),
            "start_miles": "", "length": "", "unit": "years", "miles": "", "lifetime": "", "details": "",
            "event_id": ""}


def from_visit(visit: Visit) -> dict:
    """A new warranty filled in from the visit it came with: its day, miles, shop and the parts it replaced."""
    return {"title": "", "provider": visit.shop, "covers": "parts", "codes": sorted(visit.replaced),
            "starts_on": visit.day.isoformat(), "start_miles": "" if visit.odometer is None else f"{visit.odometer:,}",
            "length": "", "unit": "years", "miles": "", "lifetime": "", "details": "", "event_id": str(visit.id)}


def raw_from(found: Mapping) -> dict:
    months = found["months"]
    in_years = months is not None and months % 12 == 0
    return {
        "title": found["title"], "provider": found["provider"],
        "covers": "whole" if found["whole_car"] else "parts", "codes": list(found["codes"]),
        "starts_on": found["starts_on"],
        "start_miles": "" if found["start_miles"] is None else f"{found['start_miles']:,}",
        "length": "" if months is None else str(months // 12 if in_years else months),
        "unit": "years" if in_years or months is None else "months",
        "miles": "" if found["miles"] is None else f"{found['miles']:,}",
        "lifetime": "1" if months is None and found["miles"] is None else "",
        "details": found["details"],
        "event_id": "" if found["service_event_id"] is None else str(found["service_event_id"]),
    }


def parse(form, types: Mapping[str, Mapping], visits: Sequence[Visit]) -> tuple[WarrantyInput, dict, dict]:
    """The warranty a form gives, with the raw values and any errors."""
    keys = ("title", "provider", "covers", "starts_on", "start_miles", "length", "unit", "miles", "lifetime", "details",
            "event_id")
    raw: dict = {key: forms.text(form.get(key)) for key in keys}
    raw["codes"] = [code for code in dict.fromkeys(forms.text(c) for c in form.getlist("code")) if code in types]
    raw["unit"] = raw["unit"] if raw["unit"] in UNITS else "years"
    raw["covers"] = "whole" if raw["covers"] == "whole" else "parts"
    errors: dict[str, str] = {}

    if not raw["title"]:
        errors["title"] = "Name it, such as Powertrain or Battery free replacement."
    elif len(raw["title"]) > MAX_TITLE:
        errors["title"] = f"Keep it under {MAX_TITLE} characters. The details can say more."
    if len(raw["provider"]) > MAX_TITLE:
        errors["provider"] = f"Keep it under {MAX_TITLE} characters."
    if len(raw["details"]) > MAX_DETAILS:
        errors["details"] = f"Keep the details under {MAX_DETAILS:,} characters."
    if raw["covers"] == "parts" and not raw["codes"]:
        errors["codes"] = "Choose what it covers, such as 12-volt battery, or choose The whole car."

    starts_on = _parse(forms.day, raw["starts_on"], "starts_on", errors, "Enter the day it started.")
    start_miles = _parse(forms.miles, raw["start_miles"], "start_miles", errors)
    months = miles = None
    if not raw["lifetime"]:
        length = _parse(_length, raw["length"], "length", errors)
        months = None if length is None else length * (12 if raw["unit"] == "years" else 1)
        if months is not None and months > 600:
            errors["length"] = "That's more than 50 years. Check for an extra digit."
        miles = _parse(forms.miles, raw["miles"], "miles", errors)
        if months is None and miles is None and "length" not in errors and "miles" not in errors:
            errors["length"] = "Say how long it lasts: years or months, miles, or lifetime."

    event_id = next((v.id for v in visits if str(v.id) == raw["event_id"]), None)
    return WarrantyInput(
        title=raw["title"], starts_on=starts_on or "", provider=raw["provider"], start_miles=start_miles,
        months=months, miles=miles, whole_car=raw["covers"] == "whole", codes=raw["codes"],
        details=raw["details"], event_id=event_id,
    ), raw, errors


def _length(value: str | None) -> int | None:
    raw = forms.text(value)
    if not raw:
        return None
    if not raw.isdigit() or int(raw) == 0:
        raise ValueError("Enter a whole number, like 3.")
    return int(raw)


def _parse(parser, value, key: str, errors: dict, required: str | None = None):
    try:
        parsed = parser(value)
    except ValueError as err:
        errors[key] = str(err)
        return None
    if parsed is None and required:
        errors[key] = required
    return parsed
