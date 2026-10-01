"""How well receipts are read, measured against what you confirmed.

Every confirmed receipt is a labelled example: its draft is the truth you
checked, and its reading is what Claude said. Comparing the two field by field
says where reading goes wrong — and re-reading the same files after a model or
prompt change says whether the change helped.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .drafts import Draft

FIELDS = (
    "kind", "date", "odometer", "shop", "invoice", "tax", "total", "vin",
    "line count", "line amounts", "services", "recommendations",
)


def _plain(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def compare(read: Draft, truth: Draft) -> dict[str, bool]:
    """Which fields of a reading match the confirmed draft."""
    def codes(d: Draft) -> set[str]:
        return {c["code"] for line in d.lines for c in line["covers"]}

    def amounts(d: Draft) -> list[int]:
        return sorted(line.get("amount_cents") or 0 for line in d.lines)

    return {
        "kind": read.document_kind == truth.document_kind,
        "date": read.performed_on == truth.performed_on,
        "odometer": read.odometer == truth.odometer,
        "shop": _plain(read.shop) == _plain(truth.shop),
        "invoice": _plain(read.invoice_number) == _plain(truth.invoice_number),
        "tax": read.tax_cents == truth.tax_cents,
        "total": read.total_cents == truth.total_cents,
        "vin": read.printed_vin == truth.printed_vin,
        "line count": len(read.lines) == len(truth.lines),
        "line amounts": amounts(read) == amounts(truth),
        "services": codes(read) == codes(truth),
        "recommendations": len(read.recommendations) == len(truth.recommendations),
    }


@dataclass
class Score:
    right: int = 0
    total: int = 0

    @property
    def percent(self) -> float:
        return 100.0 * self.right / self.total if self.total else 0.0


def summarize(results: list[dict[str, bool]]) -> dict[str, Score]:
    scores = {field: Score() for field in FIELDS}
    for result in results:
        for field, right in result.items():
            scores[field].total += 1
            scores[field].right += int(right)
    return scores


def misses(results: list[tuple[str, dict[str, bool]]]) -> Counter:
    """How many receipts each field was wrong on, for the 'worst first' list."""
    return Counter(field for _, result in results for field, right in result.items() if not right)
