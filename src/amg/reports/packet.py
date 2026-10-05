"""The sale packet: a car's history and every receipt behind it, as one PDF to hand a buyer.

The front pages are HTML laid out on Letter paper by PyMuPDF's Story: the car,
what's on file, and every confirmed service, oldest first, the way a car's
life is told. Then each confirmed receipt, as stored — a PDF page for page, a
photo as a page of its own — with a bookmark each. The history table says
which page each receipt starts on, so the front pages are laid out once to
count them, then again with the numbers in.

Left out on purpose: your notes, which are yours, not a buyer's; and receipts
still waiting to be checked. Scans go in as they are — a name and address on
a receipt are on the page.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path

import pymupdf

from ..repo import documents, reports, vehicles
from ..web.templating import miles, money, templates
from .filters import lower_first
from .history import paid

PAPER = pymupdf.paper_rect("letter")
MARGIN = 54                         # three-quarters of an inch
CSS = """
* { font-family: sans-serif; }
body { font-size: 9.5pt; color: #16202b; }
h1 { font-size: 20pt; font-weight: bold; margin: 0 0 3pt 0; }
p { margin: 0 0 8pt 0; }
.sub { font-size: 10pt; color: #3a4654; margin-bottom: 14pt; }
.facts { width: 100%; margin-bottom: 14pt; }
.facts td { padding: 1pt 12pt 1pt 0; }
.label { font-size: 8pt; font-weight: bold; color: #3a4654; }
.history { width: 100%; border-collapse: collapse; }
.history th { font-size: 8pt; font-weight: bold; color: #3a4654; text-align: left; padding: 3pt 4pt;
              border-bottom: 1px solid #16202b; }
.history td { padding: 4pt; vertical-align: top; border-bottom: 1px solid #c9cfd5; }
.num { text-align: right; }
.mono { font-family: monospace; font-size: 9pt; }
.muted { color: #5a6672; }
"""
DONE_BY = {"diy": "Owner's own work", "attested": "Done, no receipt"}


@dataclass
class Entry:
    visit: dict
    file: sqlite3.Row | None        # the stored receipt, when the service came from one
    pages: pymupdf.Document | None  # it, as PDF pages; None when there's none or it couldn't be read
    start: int | None = None        # the packet page it starts on, 1-based

    @property
    def missing(self) -> bool:
        return self.file is not None and self.pages is None


def write(conn: sqlite3.Connection, car, path: Path, today: date | None = None) -> int:
    """Write the packet for a car to ``path``; returns its page count."""
    today = today or date.today()
    visits = list(reversed(reports.visits(conn, car["id"])))        # oldest first
    files = reports.receipt_files(conn, car["id"])
    entries = [Entry(visit, files.get(visit["id"]), _open(files.get(visit["id"]))) for visit in visits]
    try:
        front = _front(conn, car, entries, today)
        out = pymupdf.open()
        out.insert_pdf(front)
        toc = [[1, "Service history", 1]]
        for entry in entries:
            if entry.pages is not None:
                out.insert_pdf(entry.pages)
                toc.append([1, _bookmark(entry.visit), entry.start])
        _number(out, front.page_count, title(car))
        out.set_toc(toc)
        out.save(path, garbage=3, deflate=True)
        count = out.page_count
        out.close()
        front.close()
    finally:
        for entry in entries:
            if entry.pages is not None:
                entry.pages.close()
    return count


def title(car) -> str:
    """The car as a buyer knows it: "2016 Subaru Outback 2.5i Premium", or its name when that's all there is."""
    words = " ".join(str(part) for part in (car["year"], car["make"], car["model"], car["trim"]) if part)
    return words or car["name"]


def done_by(visit: dict) -> str:
    return visit["shop"] or DONE_BY.get(visit["source"], "Owner's own work")


def work(visit: dict) -> str:
    """What was done, in service-type names, plus any labor or part line nobody tagged; fees and credits aren't work."""
    said: list[str] = []
    for line in visit["lines"]:
        names = [cover["name"] for cover in line["covers"]] if line["covers"] else (
            [line["description"]] if line["kind"] in ("labor", "part") and line["description"] else [])
        said += [name for name in names if name not in said]
    return ", ".join(said[:1] + [lower_first(name) for name in said[1:]])


# ---------- Helpers ----------


def _open(file) -> pymupdf.Document | None:
    """A stored receipt as PDF pages; None when there's no file or it can't be read."""
    if file is None:
        return None
    try:
        source = pymupdf.open(documents.path(file))
        if source.is_pdf:
            return source
        converted = pymupdf.open("pdf", source.convert_to_pdf())
        source.close()
        return converted
    except Exception:
        return None


def _front(conn: sqlite3.Connection, car, entries: list[Entry], today: date) -> pymupdf.Document:
    """The front pages, laid out until the receipts' page numbers settle (twice, nearly always)."""
    pages = 0
    for _ in range(4):
        start = pages + 1
        for entry in entries:
            entry.start = None
            if entry.pages is not None:
                entry.start, start = start, start + entry.pages.page_count
        front = _layout(_html(conn, car, entries, today))
        if front.page_count == pages:
            return front
        pages = front.page_count
        front.close()
    raise RuntimeError("The packet's front pages didn't settle.")    # pragma: no cover


def _html(conn: sqlite3.Connection, car, entries: list[Entry], today: date) -> str:
    rows = [{
        "date": entry.visit["performed_on"],
        "miles": miles(entry.visit["odometer"]) if entry.visit["odometer"] is not None else "",
        "done_by": done_by(entry.visit),
        "work": work(entry.visit),
        "paid": money(cents) if (cents := paid(entry.visit)) is not None else "",
        "receipt": "file missing" if entry.missing else (f"p. {entry.start}" if entry.file else ""),
    } for entry in entries]
    return templates.env.get_template("pdf/packet.html").render(
        title=title(car),
        car=car,
        odometer=vehicles.latest_odometer(conn, car["id"]),
        rows=rows,
        attached=sum(1 for entry in entries if entry.pages is not None),
        first=entries[0].visit["performed_on"] if entries else None,
        last=entries[-1].visit["performed_on"] if entries else None,
        today=f"{today:%B} {today.day}, {today.year}",
        month=lambda day: f"{date.fromisoformat(day):%b %Y}",
    )


def _layout(html: str) -> pymupdf.Document:
    buffer = BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    story = pymupdf.Story(html=html, user_css=CSS)
    where = PAPER + (MARGIN, MARGIN, -MARGIN, -MARGIN - 18)          # room at the foot for the page number
    more = True
    while more:
        device = writer.begin_page(PAPER)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()
    return pymupdf.open("pdf", buffer.getvalue())


def _number(out: pymupdf.Document, front_pages: int, name: str) -> None:
    """A line at the foot of each front page: what this is, and which page of how many."""
    for n in range(front_pages):
        page = out[n]
        page.insert_text((MARGIN, PAPER.height - MARGIN + 6), f"{name} · service history · page {n + 1} of "
                         f"{out.page_count}", fontsize=8, fontname="helv", color=(0.35, 0.4, 0.45))


def _bookmark(visit: dict) -> str:
    parts = [visit["performed_on"], done_by(visit)]
    if visit["odometer"] is not None:
        parts.append(miles(visit["odometer"]))
    return " · ".join(parts)
