"""A schedule draft: your editable copy of a schedule before you use it.

Pure functions only — no database. A draft starts from Claude's reading of a
manual (or its draft from what it knows), a generic template, or another car's
schedule, and becomes whatever you correct it to. Using it writes the car's
schedule items *from* the draft.

A table of marks becomes intervals here, by arithmetic rather than by asking
Claude to do it: marks at 30, 60, 90 and 120 thousand miles are every 30,000;
marks at 30 and 90 are first at 30,000, then every 60,000. A mark repeated at
uneven steps is flagged rather than guessed at silently.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from ..engine.schedule import in_effect  # noqa: F401  (pages ask a draft's items the same question)
from ..repo.schedules import APPLIES, ItemInput
from .manuals import ScheduleExtraction, TableColumn

ORIGINS = ("manual", "claude", "template", "copy")


@dataclass
class ScheduleDraft:
    origin: str
    printed_for: str = ""        # what the schedule says it covers; shown, not edited
    severe_conditions: str = ""  # what the schedule counts as severe service
    read_note: str = ""          # what Claude was unsure of; shown, not edited
    # {id, name, codes: [code], action, interval_miles, interval_months, first_miles, first_months,
    #  applies, note, source, document_id, page, included, why_not, marked_miles: [miles], from_read}
    items: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ScheduleDraft:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in known})

    def included(self) -> list[dict]:
        return [item for item in self.items if item["included"]]


def blank_item(**values) -> dict:
    item = {
        "id": None, "name": "", "codes": [], "action": "replace", "interval_miles": None, "interval_months": None,
        "first_miles": None, "first_months": None, "applies": "always", "note": "", "source": "you",
        "document_id": None, "page": None, "included": True, "why_not": "", "marked_miles": [], "from_read": False,
    }
    item.update(values)
    return item


# ---------- Marks to intervals ----------


@dataclass
class Intervals:
    every_miles: int | None = None
    every_months: int | None = None
    first_miles: int | None = None
    first_months: int | None = None
    uneven: bool = False

    def any(self) -> bool:
        return any(v is not None for v in (self.every_miles, self.every_months, self.first_miles, self.first_months))


def _series(values: Iterable[int | None]) -> tuple[int | None, int | None, bool]:
    """(every, first, uneven) for the points at which something falls due.

    Evenly spaced from the first step: every step, no separate first. Starting
    elsewhere: first at the start, then every step. One point: every that far,
    on the assumption the pattern carries on past the table. Uneven: the most
    common step, flagged.
    """
    points = sorted({v for v in values if v and v > 0})
    if not points:
        return None, None, False
    if len(points) == 1:
        return points[0], None, False
    steps = [b - a for a, b in zip(points, points[1:])]
    every = Counter(steps).most_common(1)[0][0]
    uneven = any(step != every for step in steps)
    first = points[0] if points[0] != every else None
    return every, first, uneven


def intervals_from_marks(marked_miles: Iterable[int], columns: Iterable[TableColumn]) -> Intervals:
    """The intervals a table row's marks add up to, in miles and in months (from the column headings)."""
    months_at = {c.miles: c.months for c in columns if c.miles}
    miles = sorted({m for m in marked_miles if m and m > 0})
    every_miles, first_miles, uneven_miles = _series(miles)
    every_months, first_months, uneven_months = _series(months_at.get(m) for m in miles)
    return Intervals(every_miles, every_months, first_miles, first_months, uneven_miles or uneven_months)


def _tidy(found: Intervals) -> Intervals:
    """Nonsense out: non-positive values gone, a 'first' that's just the first interval dropped."""
    def positive(value):
        return value if value and value > 0 else None

    every_miles, every_months = positive(found.every_miles), positive(found.every_months)
    first_miles, first_months = positive(found.first_miles), positive(found.first_months)
    if (first_miles, first_months) == (every_miles, every_months):
        first_miles = first_months = None
    return Intervals(every_miles, every_months, first_miles, first_months, found.uneven)


# ---------- From a reading ----------


def from_extraction(
    extraction: ScheduleExtraction,
    types: Mapping[str, Mapping],
    origin: str,
    document_id: int | None = None,
    pages: list[int] | None = None,
) -> tuple[ScheduleDraft, list[str]]:
    """The first draft of a schedule from Claude's reading, and what to look at before using it."""
    warnings: list[str] = []
    source = "manual" if origin == "manual" else "claude"
    items: list[dict] = []
    for row in extraction.items:
        name = row.name.strip()
        codes = [code for code in dict.fromkeys(row.service_codes) if code in types]
        unknown = [code for code in row.service_codes if code not in types]
        if unknown:
            warnings.append(f"Dropped unknown service codes {unknown} from “{name}”.")
        name = name or ", ".join(types[code]["name"] for code in codes) or "Unnamed item"

        if row.marked_at_miles:
            found = intervals_from_marks(row.marked_at_miles, extraction.table_columns)
            if found.uneven:
                marks = ", ".join(f"{m:,}" for m in sorted(set(row.marked_at_miles)))
                warnings.append(f"“{name}” is marked at uneven steps ({marks} mi); AMG took every "
                                f"{found.every_miles:,} mi. Check it against the page.")
        else:
            found = Intervals(row.every_miles, row.every_months, row.first_miles, row.first_months)
        found = _tidy(found)
        if not found.any():
            warnings.append(f"No interval was read for “{name}”. Add one, or leave it out.")

        page = row.page if source == "manual" and (pages is None or row.page in pages) else None
        items.append(blank_item(
            name=name,
            codes=codes,
            action=row.action,
            interval_miles=found.every_miles,
            interval_months=found.every_months,
            first_miles=found.first_miles,
            first_months=found.first_months,
            applies="severe" if row.severe else "always",
            note=row.note.strip(),
            source=source,
            document_id=document_id if source == "manual" else None,
            page=page,
            included=row.applies_to_vehicle,
            why_not=row.why_not.strip(),
            marked_miles=sorted({m for m in row.marked_at_miles if m and m > 0}),
            from_read=True,
        ))
    pair_severe(items)
    if extraction.uncertain.strip():
        warnings.append(f"Claude noted: {extraction.uncertain.strip()}")
    draft = ScheduleDraft(
        origin=origin,
        printed_for=extraction.printed_for.strip(),
        severe_conditions=extraction.severe_conditions.strip(),
        read_note=extraction.uncertain.strip(),
        items=items,
    )
    return draft, warnings


def pair_severe(items: list[dict]) -> None:
    """A severe-service entry stands in for the normal entry it covers.

    Oil every 6,000 mi normally and every 3,000 under severe service are two
    entries; the 6,000 one becomes normal-only, or severe service would carry
    both. A severe entry with nothing to stand in for (gear oil replaced where
    normal service only inspects it) is simply severe-only.
    """
    for severe in items:
        if severe["applies"] != "severe" or not severe["included"] or not severe["codes"]:
            continue
        for item in items:
            if (item["applies"] == "always" and item["included"] and item["codes"]
                    and item["action"] == severe["action"] and set(item["codes"]) <= set(severe["codes"])):
                item["applies"] = "normal"


# ---------- To and from schedule items ----------


def to_items(draft: ScheduleDraft) -> list[ItemInput]:
    return [
        ItemInput(
            id=item.get("id"),
            name=item["name"],
            action=item["action"],
            codes=list(item["codes"]),
            interval_miles=item["interval_miles"],
            interval_months=item["interval_months"],
            first_miles=item["first_miles"],
            first_months=item["first_months"],
            applies=item["applies"],
            note=item["note"],
            source=item["source"],
            document_id=item["document_id"],
            page=item["page"],
        )
        for item in draft.included()
    ]


def from_items(items: Iterable[Mapping], origin: str = "copy", keep_ids: bool = False) -> ScheduleDraft:
    """A draft from schedule items — another car's, to copy, or this car's, to edit."""
    return ScheduleDraft(origin=origin, items=[
        blank_item(
            id=item["id"] if keep_ids else None,
            name=item["name"],
            codes=list(item["codes"]),
            action=item["action"],
            interval_miles=item["interval_miles"],
            interval_months=item["interval_months"],
            first_miles=item["first_miles"],
            first_months=item["first_months"],
            applies=item["applies"],
            note=item["note"],
            source=item["source"],
            document_id=item["document_id"],
            page=item["page"],
        )
        for item in items
    ])


# ---------- Reading an item ----------


def _months(months: int) -> str:
    if months >= 12 and months % 12 == 0:
        years = months // 12
        return f"{years} year{'s' if years != 1 else ''}"
    return f"{months} month{'s' if months != 1 else ''}"


def _distance(miles: int | None, months: int | None) -> str:
    parts = ([f"{miles:,} mi"] if miles else []) + ([_months(months)] if months else [])
    return " or ".join(parts)


def interval_words(item: Mapping) -> str:
    """'every 6,000 mi or 6 months'; 'first at 137,500 mi or 11 years, then every 75,000 mi or 6 years'."""
    every = _distance(item["interval_miles"], item["interval_months"])
    first = _distance(item["first_miles"], item["first_months"])
    if first and every:
        return f"first at {first}, then every {every}"
    if first:
        return f"once, at {first}"
    return f"every {every}" if every else "no interval"
