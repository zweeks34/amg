"""The specs card's words: its groups and rows, the form's boxes and suggestions, and reading the form back."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import zip_longest

from ..engine import specs as catalogue
from ..engine.specs import CUSTOM, FIELDS, OTHER, Fitted
from ..repo import specs
from ..repo.specs import SpecInput
from . import forms
from .recalls import day_words
from .templating import page_url

MAX_LENGTH = 160
FIELD_PREFIX = "spec_"


def source_label(row: Mapping) -> str:
    """Where a value came from: 'outback-manual.pdf, p. 412', or 'Set by you'."""
    if row["source"] != "read":
        return "Set by you"
    if not row.get("filename"):
        return "Read by Claude"
    return f"{row['filename']}, p. {row['page']}" if row.get("page") else row["filename"]


def source_link(row: Mapping) -> str | None:
    """The page a value was read from, full size."""
    if row["source"] == "read" and row.get("sha256") and row.get("page"):
        return page_url(row["document_id"], row["sha256"], row["page"], full=True)
    return None


# ---------- The card ----------


@dataclass
class CardRow:
    label: str
    value: str
    source: str
    link: str | None


@dataclass
class CardGroup:
    name: str
    rows: list[CardRow]
    fitted: list[Fitted] = field(default_factory=list)


def fitted_words(fitted: Fitted) -> str:
    """'Aug 1, 2026 at Valley Honda'."""
    return day_words(fitted.day.isoformat()) + (f" at {fitted.shop}" if fitted.shop else "")


def _lines(conn: sqlite3.Connection, car: Mapping) -> list[dict]:
    codes = list(dict.fromkeys(code for f in FIELDS.values() for code in f.codes))
    return specs.fitted_lines(conn, car["id"], codes)


def card(conn: sqlite3.Connection, car: Mapping) -> list[CardGroup]:
    """The groups with a value or a last-fitted visit, in shopping order; your own lines last."""
    stored = specs.values(conn, car["id"])
    by_key = {row["key"]: row for row in stored if row["key"] != CUSTOM}
    lines = _lines(conn, car)
    groups: list[CardGroup] = []
    for name, fields in catalogue.for_car(car["powertrain"], by_key):
        rows = [CardRow(f.label, by_key[f.key]["value"], source_label(by_key[f.key]), source_link(by_key[f.key]))
                for f in fields if f.key in by_key]
        fitted = catalogue.last_fitted(lines, catalogue.group_codes(fields))
        if rows or fitted:
            groups.append(CardGroup(name, rows, fitted))
    custom = [CardRow(row["label"], row["value"], source_label(row), source_link(row))
              for row in stored if row["key"] == CUSTOM]
    if custom:
        groups.append(CardGroup(OTHER, custom))
    return groups


# ---------- The form ----------


@dataclass
class Box:
    key: str
    label: str
    example: str
    value: str
    suggestions: list[str]
    read: str | None = None    # on a review: what Claude read, for the dashed style
    page: int | None = None    # … and the page it read it on
    was: str = ""              # … and your value, where Claude read something else


def raw_from(stored: list[dict]) -> dict:
    """The form's values from what's saved."""
    raw: dict = {FIELD_PREFIX + row["key"]: row["value"] for row in stored if row["key"] != CUSTOM}
    raw["custom"] = [{"label": row["label"], "value": row["value"]} for row in stored if row["key"] == CUSTOM]
    return raw


def boxes(conn: sqlite3.Connection, car: Mapping, raw: Mapping, read: Mapping | None = None,
          stored: list[dict] | None = None) -> list[tuple[str, list[Box]]]:
    """The form's groups of boxes, each with its value and what your receipts suggest for it.

    ``read`` is a reading's values, {key: {"value", "page"}}, when the form is
    checking one: each box it fills starts from Claude's value, and says what
    yours was when they differ.
    """
    stored = specs.values(conn, car["id"]) if stored is None else stored
    by_key = {row["key"]: row["value"] for row in stored if row["key"] != CUSTOM}
    with_values = {key for key in FIELDS if raw.get(FIELD_PREFIX + key)} | set(by_key) | set(read or {})
    lines = _lines(conn, car)
    groups: list[tuple[str, list[Box]]] = []
    for name, fields in catalogue.for_car(car["powertrain"], with_values):
        group: list[Box] = []
        for f in fields:
            box = Box(f.key, f.label, f.example, raw.get(FIELD_PREFIX + f.key, ""), catalogue.candidates(f, lines))
            if read and f.key in read:
                box.read, box.page = read[f.key]["value"], read[f.key].get("page")
                mine = by_key.get(f.key, "")
                box.was = mine if mine and mine != box.read else ""
            group.append(box)
        groups.append((name, group))
    return groups


def custom_lines(raw: Mapping, errors: Mapping | None = None) -> list[dict]:
    """Your own lines for the form's list, each with an id to keep its place and any error."""
    errors = errors or {}
    return [{"id": n, "label": line["label"], "value": line["value"], "error": errors.get(f"custom_{n}", "")}
            for n, line in enumerate(raw.get("custom", []))]


def parse(form, stored: list[dict], read: Mapping | None = None,
          document_id: int | None = None) -> tuple[list[SpecInput], dict, dict]:
    """The specs a form gives, with the raw values and any errors.

    A value left as Claude read it keeps its file and page; one left as it was
    keeps where it came from; anything else is yours. An empty box drops it.
    """
    by_key = {row["key"]: row for row in stored if row["key"] != CUSTOM}
    inputs: list[SpecInput] = []
    raw: dict = {}
    errors: dict[str, str] = {}
    for key in FIELDS:
        name = FIELD_PREFIX + key
        if name in form:
            value = forms.text(form.get(name))
        else:   # not on the form: not this car's powertrain and never set
            value = by_key[key]["value"] if key in by_key else ""
        raw[name] = value
        if not value:
            continue
        if len(value) > MAX_LENGTH:
            errors[name] = f"Keep it under {MAX_LENGTH} characters."
        elif read and key in read and value == read[key]["value"]:
            inputs.append(SpecInput(key, value, source="read", document_id=document_id, page=read[key].get("page")))
        elif key in by_key and value == by_key[key]["value"]:
            row = by_key[key]
            inputs.append(SpecInput(key, value, source=row["source"], document_id=row["document_id"], page=row["page"]))
        else:
            inputs.append(SpecInput(key, value))
    raw["custom"] = []
    for label, value in zip_longest(form.getlist("custom_label"), form.getlist("custom_value"), fillvalue=""):
        label, value = forms.text(label), forms.text(value)
        if not label and not value:
            continue
        name = f"custom_{len(raw['custom'])}"
        raw["custom"].append({"label": label, "value": value})
        if not label:
            errors[name] = "Name this line, such as Trunk light."
        elif not value:
            errors[name] = "Add its value, or remove the line."
        elif len(label) > MAX_LENGTH or len(value) > MAX_LENGTH:
            errors[name] = f"Keep each part under {MAX_LENGTH} characters."
        else:
            inputs.append(SpecInput(CUSTOM, value, label=label))
    return inputs, raw, errors
