"""Reading a maintenance schedule: from an owner's manual's pages, or drafted by Claude.

An owner's manual runs to hundreds of pages and its schedule fills two to
eight of them, so the pages are found locally first — from the file's text
layer, or Tesseract's reading of pages without one — and only those are sent.
A short document (a dealer's maintenance guide, a few photos of the schedule
pages) is sent whole. Typed page numbers skip the search.

Claude reads the pages as images, as receipts are read: a schedule is a table
whose meaning is in which column a mark sits under, which only the picture
keeps. Schedules come in two shapes and the reading carries both — intervals
written out ("every 30,000 miles or 24 months") and tables of marks per
mileage column, which ``schedule_drafts`` turns into intervals.

Whatever comes back is a *draft*: nothing here writes to the database.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from . import claude, ocr, pdf

SEND_WHOLE = 8        # documents this short are sent whole
MAX_PAGES = 12        # never send more pages than this
MAX_OCR_PAGES = 60    # pages without text that AMG will OCR to search; past this, ask for page numbers
MIN_TEXT_CHARS = 40   # a text layer shorter than this counts as none
MIN_SCORE = 6         # a page must score this to count as part of a schedule

EFFORT = "high"
MAX_TOKENS = 64_000   # streamed, so this is a ceiling rather than a wait


class ManualError(Exception):
    """The schedule pages couldn't be found or read; the message says what to do."""


# ---------- What Claude returns ----------


class TableColumn(BaseModel):
    miles: int | None = Field(description="This column's distance in miles, e.g. 30000 for a column headed 30 (× 1,000 mi).")
    months: int | None = Field(description="This column's time in months, if the heading gives one.")


class ScheduleRow(BaseModel):
    name: str = Field(description="The item as the schedule words it, e.g. 'Disc brake pad & disc, front & rear axle boots & joints'. Drop footnote marks and item numbers.")
    page: int | None = Field(description="The page it's printed on, as numbered in the label before each image. Null when drafting without pages.")
    service_codes: list[str] = Field(description="Codes from the catalogue this item covers. One item can cover several.")
    action: Literal["replace", "inspect", "perform"] = Field(description="replace: renew the part or fluid. inspect: check it (\"inspect, correct or replace if necessary\" is inspect). perform: a procedure, such as rotating tires.")
    every_miles: int | None = Field(description="For a written interval: how often, in miles. Null for a table of marks.")
    every_months: int | None = Field(description="For a written interval: how often, in months (years × 12). Null for a table of marks.")
    first_miles: int | None = Field(description="For a written interval whose first one falls at a different point ('first at 137,500 miles, then every 75,000'): the first, in miles. Otherwise null.")
    first_months: int | None = Field(description="The same, in months.")
    marked_at_miles: list[int] = Field(description="For a table of marks: the miles of every column where this item has this action's mark, in miles (30000, not 30). Empty for a written interval.")
    severe: bool = Field(description="True when this entry applies only under severe driving conditions.")
    note: str = Field(description="Anything a person needs to know about this item, briefly: conditions, footnotes that matter. Empty if none.")
    applies_to_vehicle: bool = Field(description="False when the schedule limits this item to something the owner's car is not: another model, engine or transmission.")
    why_not: str = Field(description="When applies_to_vehicle is false, why, briefly: 'WRX/WRX STI only'. Otherwise empty.")


class ScheduleExtraction(BaseModel):
    printed_for: str = Field(description="What the schedule says it covers, as printed: model years, models, markets. Empty if it doesn't say.")
    table_columns: list[TableColumn] = Field(description="For a table of marks, its columns in order, from the headings. Empty when the schedule is written out.")
    items: list[ScheduleRow] = Field(description="One entry per item and action. A table row with different marks in different columns (I in some, R in others) is one entry per action.")
    severe_conditions: str = Field(description="What the schedule counts as severe driving conditions, one per line, as listed. Empty if it lists none.")
    uncertain: str = Field(description="Anything illegible, ambiguous or guessed, in one or two short sentences. Empty if everything was clear.")


SYSTEM_PROMPT = """\
You read the manufacturer's maintenance schedule for a car owner's personal maintenance log. The \
owner's service history is checked against what you return, so an interval read wrongly means \
work flagged as missed, or missed work not flagged.

Two shapes of schedule. Written intervals: "Replace every 30,000 miles or 24 months, whichever \
comes first" is every_miles 30000 and every_months 24. "Replace first at 137,500 miles or 11 years, \
then every 75,000 miles or 6 years" is first_miles 137500, first_months 132, every_miles 75000 and \
every_months 72. Tables of marks: columns headed by mileage (and often months), with a letter \
under each column where an item is due. For a table, list its columns in table_columns, and for \
each entry list the miles of every column carrying its mark in marked_at_miles; leave the every \
and first fields null, the owner's app works the interval out. Read each mark against the heading \
of its own column. A row with different letters in different columns (I in some, R in others) \
becomes one entry per letter, each with its own columns. A row that writes its interval out in \
words, even inside a table, is a written interval.

Distances are in miles. If both kilometres and miles are printed, use the miles; if only \
kilometres, convert (1 km = 0.621371 mi) and round to a sensible figure, and say so in the note.

Severe service. Many schedules give other intervals for severe driving conditions — short trips, \
towing, dusty or rough roads, extreme heat or cold, road salt — often in footnotes. For each \
item a severe interval changes, add a separate entry with severe true, the same name and codes \
as the normal entry, and the severe interval. Keep the normal entry as printed. List what the \
schedule counts as severe conditions in severe_conditions. A footnote that only says to do \
something "more often" gives no interval: put it in the item's note.

Which car. The schedule may cover several models, engines or transmissions; the owner's car is \
named below. Set applies_to_vehicle false for entries the schedule limits to something this car \
isn't, and say why in why_not. If you can't tell, set it true and say what you're unsure of in \
the note.

Service codes come from the catalogue below and nowhere else. One item can cover several codes: \
"engine oil and filter" covers engine_oil and oil_filter; "brake pads, discs, axle boots and \
joints" covers brake_pads, brake_rotors and axle_boots. An item that fits no code gets `other`.

Report what the schedule says, not what is typical. Leave out general advice that has no \
interval, such as checking fluid levels at every fill-up.

Catalogue (code — name, category):
{catalogue}
"""

DRAFT_INSTRUCTIONS = """\
There are no pages this time. Draft the manufacturer's recommended maintenance schedule for \
this car from what you know of it: the items, actions and intervals the maker publishes for \
this model year, engine and transmission, normal and severe. Leave page null and marked_at_miles \
empty. Don't pad it out with generic advice. In uncertain, say plainly how sure you are and what \
the owner should check against the manual."""


def system_prompt(types: Iterable[Mapping]) -> str:
    catalogue = "\n".join(f"{t['code']} — {t['name']}, {t['category']}" for t in types)
    return SYSTEM_PROMPT.format(catalogue=catalogue)


POWERTRAIN_WORDS = {"gas": "gasoline", "hybrid": "hybrid", "ev": "electric"}


def describe_car(car: Mapping) -> str:
    """'2016 Subaru Outback 2.5i Limited, 2.5L 4-cyl, gasoline' — what Claude is told about the car."""
    name = " ".join(str(part) for part in (car["year"], car["make"], car["model"], car["trim"]) if part)
    details = [d for d in (car["engine"], POWERTRAIN_WORDS.get(car["powertrain"], "")) if d]
    return ", ".join([name or "an unnamed car", *details])


# ---------- Finding the pages ----------


_KEYWORDS = [
    (re.compile(r"maintenance\s+schedule|scheduled\s+maintenance|maintenance\s+(?:interval|plan|chart|log)", re.I), 5),
    (re.compile(r"whichever\s+(?:comes|occurs)\s+first", re.I), 4),
    (re.compile(r"severe\s+(?:driving|service|operating|conditions|usage)", re.I), 2),
    (re.compile(r"\breplace|\binspect|\brotat", re.I), 1),
]
_INTERVALS = re.compile(
    r"\b\d{1,3}(?:,\d{3})+\s*(?:mi|miles|km)\b|\b\d{1,3}\s*(?:months|mos?\.?)\b|x\s*1,?000", re.I
)


def score(text: str) -> int:
    """How much a page's text looks like part of a maintenance schedule."""
    points = sum(weight * min(len(pattern.findall(text)), 3) for pattern, weight in _KEYWORDS)
    return points + min(len(_INTERVALS.findall(text)), 10)


def choose(scores: dict[int, int], limit: int = MAX_PAGES) -> list[int]:
    """The schedule pages, from each page's score: the best pages and the pages beside them.

    Schedule tables run across pages, and a continuation page is often just a
    grid of marks with no words to score — so each chosen page brings its
    neighbours, best pages first, until the limit.
    """
    if not scores:
        return []
    best = max(scores.values())
    if best < MIN_SCORE:
        return []
    threshold = max(MIN_SCORE, best * 0.4)
    ranked = sorted((n for n, s in scores.items() if s >= threshold), key=lambda n: (-scores[n], n))
    chosen: list[int] = []
    for number in ranked:
        for page in (number, number + 1, number - 1):
            if page in scores and page not in chosen and len(chosen) < limit:
                chosen.append(page)
    return sorted(chosen)


def parse_pages(typed: str, page_count: int) -> list[int]:
    """'30-31, 45' → [30, 31, 45]; raises ValueError with a message for the form."""
    numbers: list[int] = []
    for part in re.split(r"[,\s]+", typed.strip()):
        if not part:
            continue
        match = re.fullmatch(r"(\d+)(?:[-–](\d+))?", part)
        if not match:
            raise ValueError("Enter page numbers like 30-31, 45.")
        start, end = int(match[1]), int(match[2] or match[1])
        if start > end:
            start, end = end, start
        if start < 1 or end > page_count:
            raise ValueError(f"This file has {page_count} page{'s' if page_count != 1 else ''}.")
        numbers.extend(n for n in range(start, end + 1) if n not in numbers)
    if len(numbers) > MAX_PAGES:
        raise ValueError(f"That's {len(numbers)} pages; AMG reads up to {MAX_PAGES} at a time. Choose the schedule pages.")
    return sorted(numbers)


def find_pages(path: Path, typed: str = "") -> list[int]:
    """The pages to send Claude: typed ones, the whole of a short document, or the schedule's pages."""
    count = pdf.page_count(path)
    if typed.strip():
        return parse_pages(typed, count)
    if count <= SEND_WHOLE:
        return list(range(1, count + 1))

    pages = pdf.pages(path)
    textless = [page.number for page in pages if len(page.text) < MIN_TEXT_CHARS]
    can_ocr = ocr.available() and len(textless) <= MAX_OCR_PAGES
    texts = {page.number: page.text for page in pages}
    if textless and can_ocr:
        for number in textless:
            texts[number] = ocr.read(pdf.render(path, number, pdf.OCR_LONG_EDGE, fmt="png")).text
    chosen = choose({number: score(text) for number, text in texts.items()})
    if chosen:
        return chosen
    if textless and not can_ocr:
        raise ManualError("This scan has no text AMG can search for the schedule. Type the page numbers that "
                          "hold it, such as 30-31, and read it again.")
    raise ManualError("AMG couldn't find a maintenance schedule in this document. Type the page numbers that "
                      "hold it, such as 30-31, and read it again.")


# ---------- Reading ----------


@dataclass
class ScheduleRead:
    pages: list[int]
    extraction: ScheduleExtraction
    usage: claude.Usage
    warnings: list[str] = field(default_factory=list)


def content_blocks(path: Path, pages: list[int], car: Mapping, page_count: int) -> list[dict]:
    blocks: list[dict] = [{"type": "text", "text": f"The owner's car: {describe_car(car)}."}]
    for number in pages:
        image = base64.standard_b64encode(pdf.render(path, number, pdf.VISION_LONG_EDGE)).decode()
        blocks.append({"type": "text", "text": f"Page {number} of {page_count}"})
        blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image}})
    blocks.append({"type": "text", "text": "Read the maintenance schedule on these pages."})
    return blocks


def read_manual(path: Path | str, car: Mapping, types: list[Mapping], pages: str = "") -> ScheduleRead:
    """Find the schedule pages in a manual and read them with Claude."""
    path = Path(path)
    if not pdf.is_supported(path):
        raise ManualError(f"{path.suffix} files aren't supported; use PDF, PNG, JPG or GIF.")
    try:
        chosen = find_pages(path, pages)
    except ValueError as err:
        raise ManualError(str(err)) from err
    extraction, usage = claude.parse(
        ScheduleExtraction,
        system=system_prompt(types),
        content=content_blocks(path, chosen, car, pdf.page_count(path)),
        effort=EFFORT,
        max_tokens=MAX_TOKENS,
        stream=True,
    )
    return ScheduleRead(chosen, extraction, usage)


def draft_schedule(car: Mapping, types: list[Mapping]) -> ScheduleRead:
    """Claude's draft of the car's schedule from what it knows — no pages to check it against."""
    extraction, usage = claude.parse(
        ScheduleExtraction,
        system=system_prompt(types),
        content=[
            {"type": "text", "text": f"The owner's car: {describe_car(car)}."},
            {"type": "text", "text": DRAFT_INSTRUCTIONS},
        ],
        effort=EFFORT,
        max_tokens=MAX_TOKENS,
        stream=True,
    )
    return ScheduleRead([], extraction, usage)
