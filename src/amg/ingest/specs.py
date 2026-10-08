"""Reading a car's specs (oil, filters, tires, bulbs, fluids) from its owner's manual or photos.

The pages are found as the schedule's are (``manuals.find_pages``), with a
scorer of their own: spec pages are thick with oil grades, capacities, tire
sizes and pressures, DOT ratings and bulb numbers. A short document — photos
of the spec pages and the tire sticker in the door frame — is sent whole.

Claude reads the pages as images and gives a value for each field of the card
the pages print, and nothing for the rest: a value from memory would look the
same on the card as one from the page. Whatever comes back is checked on the
review screen before it counts; nothing here writes to the database.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from ..engine.specs import FIELDS
from . import claude, manuals, pdf

EFFORT = "medium"
MAX_TOKENS = 16_000   # streamed, so this is a ceiling rather than a wait


# ---------- Finding the pages ----------


_KEYWORDS = [
    (re.compile(r"\bspecifications?\b|\bcapacit(?:y|ies)\b|recommended\s+(?:fluids?|lubricants?|oil|fuel)"
                r"|fluids?\s+and\s+lubricants?", re.I), 4),
    (re.compile(r"\bSAE\b|(?<!\d)\d{1,2}W-?\d{2}(?!\d)", re.I), 3),
    (re.compile(r"(?<!\d)\d{3}/\d{2}\s?Z?R\s?\d{2}(?!\d)|\bkPa\b|\bpsi\b|(?:inflation|tire)\s+pressure", re.I), 2),
    (re.compile(r"\bDOT\s?[345]\b|\boctane\b|\bAKI\b|\bR-?1234yf\b|\bR-?134a\b|\bbulbs?\b|\bwattage\b", re.I), 2),
    (re.compile(r"\b(?:qt|quarts?|gal|gallons?|liters?|litres?)\b", re.I), 1),
]


def score(text: str) -> int:
    """How much a page's text looks like a page of specifications."""
    return sum(weight * min(len(pattern.findall(text)), 3) for pattern, weight in _KEYWORDS)


def find_pages(path: Path, typed: str = "") -> list[int]:
    return manuals.find_pages(path, typed, scorer=score, sought="the specifications")


# ---------- What Claude returns ----------


class SpecValue(BaseModel):
    key: str = Field(description="The field's key, from the list of fields.")
    value: str = Field(description="As a parts counter needs it, short: '0W-20', '4.4 US qt (4.2 L)', '225/65R17 102H'.")
    page: int | None = Field(description="The page it's printed on, as numbered in the label before each image.")
    note: str = Field(description="Only when it matters: what the value depends on, or the values printed for "
                                  "other engines, transmissions or trims. Empty otherwise.")


class SpecsExtraction(BaseModel):
    printed_for: str = Field(description="What the pages say they cover, as printed: model years, models, engines. "
                                         "Empty if they don't say.")
    specs: list[SpecValue] = Field(description="One entry for each field the pages give a value for. Leave out the "
                                               "fields they don't give.")
    uncertain: str = Field(description="Anything illegible, ambiguous or guessed, in one or two short sentences. "
                                       "Empty if everything was clear.")


SYSTEM_PROMPT = """\
You read a car's specifications from pages of its owner's manual, or from photos of them and of the \
tire sticker in the door frame, for the owner's quick-reference card: what to buy at the parts counter. \
A wrong value means the wrong oil or the wrong part, so give only what the pages print. Leave out any \
field the pages don't give; never fill one in from what you know about the car.

Write each value as a parts counter needs it, short: "0W-20", "4.4 US qt (4.2 L)", "225/65R17 102H", \
"35 psi front, 33 psi rear". Put US units first, with the metric figure in brackets when both are \
printed. Name a fluid as printed ("Subaru High Torque CVTF", "DOT 3 or DOT 4"). For a bulb, give its \
number ("H11", "7443"); its wattage only when no number is printed. For oil capacity, the amount with \
the filter changed.

Which car. The pages may give values for several engines, transmissions or trims; the owner's car is \
named below. Give the value for this car and put the others in note. If you can't tell which applies, \
give the likeliest and say so in note.

Fields (key — what it is, with an example value):
{fields}
"""


def system_prompt() -> str:
    fields = "\n".join(f"{f.key} — {f.label}, e.g. {f.example}" for f in FIELDS.values())
    return SYSTEM_PROMPT.format(fields=fields)


def content_blocks(path: Path, pages: list[int], car: Mapping, page_count: int) -> list[dict]:
    blocks = manuals.content_blocks(path, pages, car, page_count)
    blocks[-1] = {"type": "text", "text": "Read the specifications on these pages."}
    return blocks


@dataclass
class SpecsRead:
    pages: list[int]
    extraction: SpecsExtraction
    usage: claude.Usage


def read_specs(path: Path | str, car: Mapping, pages: str = "") -> SpecsRead:
    """Find the spec pages in a manual (or take a short document whole) and read them with Claude."""
    path = Path(path)
    if not pdf.is_supported(path):
        raise manuals.ManualError(f"{path.suffix} files aren't supported; use PDF, PNG, JPG or GIF.")
    try:
        chosen = find_pages(path, pages)
    except ValueError as err:
        raise manuals.ManualError(str(err)) from err
    extraction, usage = claude.parse(
        SpecsExtraction,
        system=system_prompt(),
        content=content_blocks(path, chosen, car, pdf.page_count(path)),
        effort=EFFORT,
        max_tokens=MAX_TOKENS,
        stream=True,
    )
    return SpecsRead(chosen, extraction, usage)


def to_draft(extraction: SpecsExtraction) -> tuple[dict[str, dict], list[str]]:
    """The boxes a reading fills, {key: {"value", "page"}}, and what's worth a look on the review."""
    values: dict[str, dict] = {}
    warnings: list[str] = []
    for spec in extraction.specs:
        value = " ".join(spec.value.split())
        field = FIELDS.get(spec.key)
        if not value:
            continue
        if field is None:
            warnings.append(f"Claude also read “{value}” as {spec.key.replace('_', ' ')}, which the card "
                            "has no box for. Add it under Other if you want it.")
            continue
        if spec.key in values:
            warnings.append(f"{field.label}: Claude read “{values[spec.key]['value']}” first, and also "
                            f"“{value}”. The first is filled in.")
            continue
        values[spec.key] = {"value": value, "page": spec.page}
        if spec.note.strip():
            warnings.append(f"{field.label}: {spec.note.strip()}")
    if extraction.uncertain.strip():
        warnings.append(extraction.uncertain.strip())
    return values, warnings
