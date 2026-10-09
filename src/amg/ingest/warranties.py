"""Looking for warranties on a receipt read before AMG kept them.

One question about a confirmed receipt: what warranties does it give? Claude
sees its pages, as when it was first read, and the lines as you confirmed
them, so it names the services each covers from those. What comes back goes
into the receipt's draft for you to check (repo/warranty_looks.py), never
straight into the car's warranties.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from pydantic import BaseModel, Field

from . import claude
from .receipts import WARRANTY_RULES, ReceiptWarranty, catalogue, content_blocks, local_text

SYSTEM_PROMPT = """\
You read an automobile service receipt for a car owner's personal maintenance log, looking only for \
warranties. The owner has already checked the receipt's work; its lines are listed after the pages.

{warranty_rules}

Take service_codes from the codes the listed lines cover, and from the catalogue below and nowhere \
else. If the receipt gives no warranty with terms, return an empty list: most receipts don't.

Ignore the customer's personal details — name, address, phone, email. Do not include them anywhere.

Catalogue (code — name, category):
{catalogue}
"""


class WarrantyLook(BaseModel):
    warranties: list[ReceiptWarranty] = Field(description="Warranties the receipt gives on this visit's parts or work, with their terms.")


def system_prompt(types: Iterable[Mapping]) -> str:
    return SYSTEM_PROMPT.format(warranty_rules=WARRANTY_RULES, catalogue=catalogue(types))


def lines_text(lines: Iterable[Mapping]) -> str:
    """'- Interstate battery MT-35: battery_12v (replace)', a line each, as the owner confirmed them."""
    rows = []
    for line in lines:
        covers = ", ".join(f"{c['code']} ({c['action']})" for c in line.get("covers") or [])
        rows.append(f"- {line['description']}" + (f": {covers}" if covers else ""))
    return "\n".join(rows) or "(no lines)"


def look(path: Path | str, lines: Iterable[Mapping], types: list[Mapping]) -> tuple[list[ReceiptWarranty], claude.Usage]:
    """The warranties a receipt gives, with any codes outside the catalogue dropped."""
    path = Path(path)
    content = content_blocks(path, "vision", local_text(path, use_ocr=False))[:-1]   # all but "Read this receipt."
    content.append({"type": "text", "text": f"The receipt's lines, as the owner confirmed them:\n{lines_text(lines)}"
                                            "\n\nList the warranties this receipt gives."})
    found, usage = claude.parse(WarrantyLook, system=system_prompt(types), content=content, effort="low")
    known = {t["code"] for t in types}
    for warranty in found.warranties:
        warranty.service_codes = [code for code in warranty.service_codes if code in known]
    return found.warranties, usage
