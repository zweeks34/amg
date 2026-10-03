"""The schedule editor's data: what the browser posts, and what the server keeps.

The editor (``scheduleEditor`` in app.js) posts its rows as JSON in
``items_json``, as the line editor does, and is used twice: to check a draft
before using it, and to edit a car's schedule afterwards. Rows arrive as the
strings people typed; parsing turns them into the draft's items, with one
error message per bad row.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from ..ingest.schedule_drafts import blank_item
from ..repo import services
from ..repo.schedules import APPLIES, SOURCES
from . import forms

_NUMBERS = ("interval_miles", "interval_months", "first_miles", "first_months")


def editor_row(item: Mapping) -> dict:
    """A draft item as the editor shows it: numbers as typed text, codes as chips."""
    def number(key):
        value = item.get(key)
        return "" if value is None else (f"{value:,}" if key.endswith("miles") else str(value))

    marked = item.get("marked_miles") or []
    shown = [f"{m / 1000:g}k" for m in marked]
    if len(shown) > 6:   # a mark every 6,000 mi is 22 of them; the ends and the count say it
        shown = [shown[0], shown[1], f"… {shown[-1]} ({len(shown)} marks)"]
    return {
        "id": item.get("id"),
        "name": item.get("name", ""),
        "covers": list(item.get("codes", [])),
        "action": item.get("action", "replace"),
        **{key: number(key) for key in _NUMBERS},
        "applies": item.get("applies", "always"),
        "note": item.get("note", ""),
        "source": item.get("source", "you"),
        "document_id": item.get("document_id"),
        "page": item.get("page"),
        "included": bool(item.get("included", True)),
        "why_not": item.get("why_not", ""),
        "marked": ", ".join(shown).replace(", …", " …"),
        "marked_miles": list(marked),
        "from_read": bool(item.get("from_read")),
        "show_first": item.get("first_miles") is not None or item.get("first_months") is not None,
    }


def blank_row() -> dict:
    return editor_row(blank_item())


def clean_items(posted: str | None) -> list[dict]:
    """Posted rows as plain strings, lists and flags, whatever the browser sent."""
    try:
        data = json.loads(posted or "[]")
    except ValueError:
        return []
    rows = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        rows.append({
            "id": item["id"] if isinstance(item.get("id"), int) else None,
            "name": forms.text(str(item.get("name", ""))),
            "covers": [str(c) for c in item.get("covers", []) if isinstance(c, str)],
            "action": item.get("action") if item.get("action") in services.ACTIONS else "replace",
            **{key: forms.text(str(item.get(key, ""))) for key in _NUMBERS},
            "applies": item.get("applies") if item.get("applies") in APPLIES else "always",
            "note": forms.text(str(item.get("note", ""))),
            "source": item.get("source") if item.get("source") in SOURCES else "you",
            "document_id": item["document_id"] if isinstance(item.get("document_id"), int) else None,
            "page": item["page"] if isinstance(item.get("page"), int) else None,
            "included": bool(item.get("included", True)),
            "why_not": forms.text(str(item.get("why_not", ""))),
            "marked": forms.text(str(item.get("marked", ""))),
            "marked_miles": [m for m in item.get("marked_miles", []) if isinstance(m, int)],
            "from_read": bool(item.get("from_read")),
            "show_first": bool(item.get("show_first")),
        })
    return rows


def parse_items(
    rows: list[dict],
    types: Mapping[str, Mapping],
    documents: set[int],
) -> tuple[list[dict], list[str | None]]:
    """(the draft's items, one error or None per posted row). Empty rows are dropped.

    ``documents`` are the files items may point at — the draft's own manual and
    whatever the car's items already cite — so a posted id can't point anywhere else.
    """
    items: list[dict] = []
    errors: list[str | None] = []
    for row in rows:
        if not (row["name"] or row["covers"] or any(row[key] for key in _NUMBERS)):
            errors.append(None)
            continue
        problems: list[str] = []
        values: dict = {}
        for key in _NUMBERS:
            parser = forms.miles if key.endswith("miles") else forms.months
            try:
                values[key] = parser(row[key])
            except ValueError as err:
                problems.append(str(err))
                values[key] = None
            if values[key] == 0:
                problems.append("Enter miles above zero.")
                values[key] = None
        codes = [code for code in dict.fromkeys(row["covers"]) if code in types]
        name = row["name"] or ", ".join(types[code]["name"] for code in codes)
        if row["included"]:
            if not codes:
                problems.append("Add the service it's for, so AMG can match it to your services.")
            if not problems and not any(values.values()):
                problems.append("Give it an interval: miles, months or both.")
        document_id = row["document_id"] if row["document_id"] in documents else None
        items.append(blank_item(
            id=row["id"],
            name=name or "Unnamed item",
            codes=codes,
            action=row["action"],
            **values,
            applies=row["applies"],
            note=row["note"],
            source=row["source"],
            document_id=document_id,
            page=row["page"] if document_id else None,
            included=row["included"],
            why_not=row["why_not"],
            marked_miles=row["marked_miles"],
            from_read=row["from_read"],
        ))
        errors.append(" ".join(dict.fromkeys(problems)) or None)
    return items, errors
