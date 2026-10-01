"""The line editor's data: what the browser posts, and what the server keeps.

The editor (``lineEditor`` in app.js) posts its rows as JSON — ``lines_json``
for work done and, on the receipt review, ``recs_json`` for recommendations.
Rows arrive as the strings people typed; parsing turns them into cents,
known service codes and actions, with one error message per bad row so the
editor can show it beside that row.
"""

from __future__ import annotations

import json
from collections.abc import Mapping

from ..repo import services
from . import forms


def blank_line() -> dict:
    return {"description": "", "kind": "other", "amount": "", "covers": [], "inspect_only": False,
            "part_number": "", "quantity": "", "covers_source": "you", "from_read": False}


def blank_rec() -> dict:
    return {"description": "", "covers": [], "amount": ""}


def clean_lines(posted: str | None) -> list[dict]:
    """Posted line rows as plain strings and lists, whatever the browser sent."""
    rows = []
    for item in _json_list(posted):
        rows.append({
            "description": forms.text(str(item.get("description", ""))),
            "kind": str(item.get("kind", "other")),
            "amount": forms.text(str(item.get("amount", ""))),
            "covers": [str(c) for c in item.get("covers", []) if isinstance(c, str)],
            "inspect_only": bool(item.get("inspect_only")),
            "part_number": forms.text(str(item.get("part_number", ""))),
            "quantity": forms.text(str(item.get("quantity", ""))),
            "covers_source": item.get("covers_source") if item.get("covers_source") in ("claude", "learned", "you") else "you",
            "from_read": bool(item.get("from_read")),
        })
    return rows


def clean_recs(posted: str | None) -> list[dict]:
    return [
        {
            "description": forms.text(str(item.get("description", ""))),
            "covers": [str(c) for c in item.get("covers", []) if isinstance(c, str)],
            "amount": forms.text(str(item.get("amount", ""))),
        }
        for item in _json_list(posted)
    ]


def parse_lines(rows: list[dict], types: Mapping[str, Mapping]) -> tuple[list[services.LineInput], list[str | None], list[dict]]:
    """(lines, one error or None per row, the same lines as draft dicts).

    Empty rows are dropped. A line with no description is named after the
    services it covers.
    """
    lines: list[services.LineInput] = []
    drafts: list[dict] = []
    errors: list[str | None] = []
    for row in rows:
        covers = [code for code in dict.fromkeys(row["covers"]) if code in types]
        try:
            amount = forms.money(row["amount"])
            quantity = forms.quantity(row["quantity"])
        except ValueError as err:
            errors.append(str(err))
            continue
        errors.append(None)
        if not row["description"] and not covers and amount is None:
            continue
        coverage = [
            services.Coverage(code, "inspect" if row["inspect_only"] else types[code]["default_action"])
            for code in covers
        ]
        line = services.LineInput(
            description=row["description"] or ", ".join(types[c]["name"] for c in covers) or "Unnamed item",
            kind=row["kind"] if row["kind"] in services.KINDS else "other",
            part_number=row["part_number"],
            quantity=quantity,
            amount_cents=amount,
            covers=coverage,
        )
        lines.append(line)
        drafts.append({
            "description": line.description,
            "kind": line.kind,
            "part_number": line.part_number,
            "quantity": line.quantity,
            "amount_cents": line.amount_cents,
            "covers": [{"code": c.code, "action": c.action} for c in coverage],
            "covers_source": row.get("covers_source", "you"),
        })
    return lines, errors, drafts


def parse_recs(rows: list[dict], types: Mapping[str, Mapping]) -> tuple[list[dict], list[str | None]]:
    recs: list[dict] = []
    errors: list[str | None] = []
    for row in rows:
        try:
            quoted = forms.money(row["amount"])
        except ValueError as err:
            errors.append(str(err))
            continue
        errors.append(None)
        codes = [code for code in dict.fromkeys(row["covers"]) if code in types]
        if not row["description"] and not codes and quoted is None:
            continue
        recs.append({
            "description": row["description"] or ", ".join(types[c]["name"] for c in codes) or "Unnamed item",
            "codes": codes,
            "quoted_cents": quoted,
        })
    return recs, errors


def rows_from_draft(lines: list[dict], read: list[dict] | None = None) -> list[dict]:
    """Draft lines as editor rows; ``from_read`` marks lines still exactly as Claude read them."""
    read = read or []
    rows = []
    for i, line in enumerate(lines):
        covers = [c["code"] for c in line["covers"]]
        rows.append({
            "description": line["description"],
            "kind": line["kind"],
            "amount": dollars(line.get("amount_cents")),
            "covers": covers,
            "inspect_only": bool(covers) and all(c["action"] == "inspect" for c in line["covers"]),
            "part_number": line.get("part_number") or "",
            "quantity": "" if line.get("quantity") is None else f"{line['quantity']:g}",
            "covers_source": line.get("covers_source", "you"),
            "from_read": i < len(read) and _same_line(line, read[i]),
        })
    return rows


def recs_from_draft(recs: list[dict]) -> list[dict]:
    return [{"description": r["description"], "covers": list(r["codes"]), "amount": dollars(r.get("quoted_cents"))}
            for r in recs]


def dollars(cents: int | None) -> str:
    return "" if cents is None else f"{cents / 100:.2f}"


def _same_line(a: dict, b: dict) -> bool:
    return (a["description"] == b["description"] and a.get("amount_cents") == b.get("amount_cents")
            and [c["code"] for c in a["covers"]] == [c["code"] for c in b["covers"]])


def _json_list(posted: str | None) -> list[dict]:
    try:
        value = json.loads(posted or "[]")
    except ValueError:
        return []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
